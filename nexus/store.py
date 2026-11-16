"""Memory store: Markdown is the truth, SQLite FTS5 is a rebuildable index."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path

from . import scrub
from .record import CONFIDENCE_WEIGHT, Record, read as read_record

NEXUS_DIR = ".nexus"
GLOBAL_DIR = Path.home() / ".nexus" / "global"

TIER_DIR = {
    "project": "project",
    "semantic": "semantic",
    "procedural": "procedures",
    "episodic": "episodes",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY, name TEXT, type TEXT, confidence TEXT, source TEXT,
    created_at TEXT, verified_at TEXT, supersedes TEXT, superseded_by TEXT,
    graph_refs TEXT, tags TEXT, path TEXT, hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_name_type ON records(name, type);
CREATE INDEX IF NOT EXISTS idx_live ON records(superseded_by);
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
    USING fts5(id UNINDEXED, name, body, tags, source);
"""


class NotInitialized(Exception):
    pass


def find_root(start: Path | None = None) -> Path:
    """Nearest ancestor holding a .nexus directory."""
    p = (start or Path.cwd()).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / NEXUS_DIR).is_dir():
            return candidate
    raise NotInitialized(f"no {NEXUS_DIR}/ found at or above {p} — run `nexus init` first")


def git_root(start: Path | None = None) -> Path | None:
    p = (start or Path.cwd()).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.dir = self.root / NEXUS_DIR
        self.db_path = self.dir / "index.db"
        self._db: sqlite3.Connection | None = None

    # ---------- setup ----------

    @classmethod
    def init(cls, root: Path) -> "Store":
        root = Path(root).resolve()
        store = cls(root)
        for d in TIER_DIR.values():
            (store.dir / d).mkdir(parents=True, exist_ok=True)
        (store.dir / "superseded").mkdir(parents=True, exist_ok=True)
        GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
        gitignore = store.dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("index.db\nindex.db-*\n", encoding="utf-8")
        store.db.executescript(SCHEMA)
        store.db.commit()
        return store

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.db_path)
            self._db.row_factory = sqlite3.Row
            self._db.executescript(SCHEMA)
        return self._db

    # ---------- paths ----------

    def path_for(self, rec: Record) -> Path:
        if rec.type == "global":
            return GLOBAL_DIR / f"{rec.name}.md"
        if rec.type == "episodic":
            month = (rec.created_at or "0000-00")[:7]
            return self.dir / TIER_DIR["episodic"] / month / f"{rec.name}.md"
        return self.dir / TIER_DIR[rec.type] / f"{rec.name}.md"

    def all_files(self) -> list[Path]:
        files = sorted(GLOBAL_DIR.glob("*.md")) if GLOBAL_DIR.is_dir() else []
        for d in TIER_DIR.values():
            files += sorted((self.dir / d).rglob("*.md"))
        files += sorted((self.dir / "superseded").glob("*.md"))
        return files

    # ---------- write ----------

    def find_live(self, name: str, type_: str) -> tuple[Record, Path] | None:
        row = self.db.execute(
            "SELECT path FROM records WHERE name=? AND type=? AND superseded_by='' LIMIT 1",
            (name, type_),
        ).fetchone()
        if row and Path(row["path"]).exists():
            return read_record(Path(row["path"])), Path(row["path"])
        # Index may be cold or stale; fall back to the filesystem, which is the truth.
        probe = self.path_for(Record(name=name, type=type_, body="x"))
        if probe.exists():
            return read_record(probe), probe
        if type_ == "episodic":
            for p in (self.dir / TIER_DIR["episodic"]).rglob(f"{name}.md"):
                return read_record(p), p
        return None

    def write(self, rec: Record) -> tuple[str, Record, list[scrub.Finding]]:
        """Returns (action, record, warnings). Raises scrub.SecretFound."""
        warnings = scrub.enforce("\n".join([rec.name, rec.source, " ".join(rec.tags), rec.body]))

        existing = self.find_live(rec.name, rec.type)
        action = "created"
        if existing:
            old, old_path = existing
            if old.hash == rec.hash and old.confidence == rec.confidence:
                return "unchanged", old, warnings
            # Conflict: supersede, never overwrite. The old record stays readable.
            old.superseded_by = rec.id
            rec.supersedes = old.id
            archived = self.dir / "superseded" / f"{old.name}.{old.id}.md"
            old.write(archived)
            old_path.unlink(missing_ok=True)
            self._index(old, archived)
            action = "superseded"

        path = self.path_for(rec)
        rec.write(path)
        self._index(rec, path)
        self.db.commit()
        return action, rec, warnings

    def _index(self, rec: Record, path: Path) -> None:
        d = asdict(rec)
        self.db.execute("DELETE FROM records WHERE id=?", (rec.id,))
        self.db.execute("DELETE FROM records_fts WHERE id=?", (rec.id,))
        self.db.execute(
            """INSERT INTO records (id,name,type,confidence,source,created_at,verified_at,
                   supersedes,superseded_by,graph_refs,tags,path,hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec.id, rec.name, rec.type, rec.confidence, rec.source, rec.created_at,
             rec.verified_at, rec.supersedes, rec.superseded_by,
             json.dumps(d["graph_refs"]), json.dumps(d["tags"]), str(path), rec.hash),
        )
        self.db.execute(
            "INSERT INTO records_fts (id,name,body,tags,source) VALUES (?,?,?,?,?)",
            (rec.id, rec.name.replace("-", " "), rec.body, " ".join(rec.tags), rec.source),
        )

    def reindex(self) -> int:
        self.db.executescript("DROP TABLE IF EXISTS records; DROP TABLE IF EXISTS records_fts;")
        self.db.executescript(SCHEMA)
        n = 0
        for path in self.all_files():
            try:
                rec = read_record(path)
            except ValueError:
                continue  # not a NEXUS record; leave it alone
            self._index(rec, path)
            n += 1
        self.db.commit()
        return n

    # ---------- read ----------

    @staticmethod
    def _fts_query(text: str, joiner: str) -> str | None:
        tokens = re.findall(r"[A-Za-z0-9_]{2,}", text)
        if not tokens:
            return None
        return f" {joiner} ".join(f'"{t}"' for t in tokens)

    def recall(self, query: str, type_: str | None = None, limit: int = 10,
               include_superseded: bool = False) -> list[dict]:
        where = [] if include_superseded else ["r.superseded_by=''"]
        params: list = []
        if type_:
            where.append("r.type=?")
            params.append(type_)

        for joiner in ("AND", "OR"):  # precision first, then widen
            fts = self._fts_query(query, joiner)
            if fts is None:
                break
            clause = " AND ".join(["records_fts MATCH ?", *where]) if where else "records_fts MATCH ?"
            sql = f"""
                SELECT r.*, bm25(records_fts) AS bm25
                FROM records_fts JOIN records r ON r.id = records_fts.id
                WHERE {clause}
            """
            rows = self.db.execute(sql, [fts, *params]).fetchall()
            if rows:
                break
        else:
            rows = []

        if not rows and self._fts_query(query, "AND") is None:
            # Empty query: most recent live records.
            clause = " AND ".join(where) if where else "1=1"
            rows = self.db.execute(
                f"SELECT *, 0.0 AS bm25 FROM records r WHERE {clause} ORDER BY created_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            d["graph_refs"] = json.loads(d.get("graph_refs") or "[]")
            d["tags"] = json.loads(d.get("tags") or "[]")
            # bm25 is negative-better; flip so higher = better, then weight by confidence.
            d["score"] = -float(d.pop("bm25")) * CONFIDENCE_WEIGHT.get(d["confidence"], 0.7)
            results.append(d)
        # id is the tiebreaker so equal-scoring hits keep a stable order across reindexes.
        results.sort(key=lambda r: (-r["score"], r["id"]))
        results = results[:limit]
        # bm25 magnitudes depend on corpus size and are meaningless on their own,
        # so expose a 0-100 figure relative to the best hit in this result set.
        best = results[0]["score"] if results and results[0]["score"] > 0 else 0
        for d in results:
            d["relevance"] = round(100 * d["score"] / best, 1) if best else 0.0
        return results

    def get(self, ident: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM records WHERE id=? OR name=? ORDER BY superseded_by='' DESC LIMIT 1",
            (ident, ident),
        ).fetchone()
        return dict(row) if row else None

    def chain(self, ident: str) -> list[dict]:
        """A record and everything it superseded, newest first."""
        out: list[dict] = []
        cur = self.get(ident)
        seen = set()
        while cur and cur["id"] not in seen:
            seen.add(cur["id"])
            out.append(cur)
            cur = self.get(cur["supersedes"]) if cur["supersedes"] else None
        return out

    def forget(self, ident: str, hard: bool = False) -> str | None:
        rec = self.get(ident)
        if not rec:
            return None
        path = Path(rec["path"])
        if hard:
            path.unlink(missing_ok=True)
            self.db.execute("DELETE FROM records WHERE id=?", (rec["id"],))
            self.db.execute("DELETE FROM records_fts WHERE id=?", (rec["id"],))
            self.db.commit()
            return "deleted"
        if rec["superseded_by"]:
            return "already-superseded"
        obj = read_record(path)
        obj.superseded_by = "forgotten"
        archived = self.dir / "superseded" / f"{obj.name}.{obj.id}.md"
        obj.write(archived)
        path.unlink(missing_ok=True)
        self._index(obj, archived)
        self.db.commit()
        return "forgotten"

    def stats(self) -> dict:
        rows = self.db.execute(
            "SELECT type, COUNT(*) n FROM records WHERE superseded_by='' GROUP BY type"
        ).fetchall()
        superseded = self.db.execute(
            "SELECT COUNT(*) n FROM records WHERE superseded_by!=''"
        ).fetchone()["n"]
        return {
            "root": str(self.root),
            "by_type": {r["type"]: r["n"] for r in rows},
            "live": sum(r["n"] for r in rows),
            "superseded": superseded,
            "index": str(self.db_path),
        }
