"""Memory store: Markdown is the truth, SQLite FTS5 is a rebuildable index."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
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

# Bump when the index schema or the FTS tokenizer changes: a stale index is
# silently wrong (an old tokenizer keeps ranking by the old rules), so the
# store rebuilds itself from Markdown instead of trusting it.
SCHEMA_VERSION = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY, name TEXT, type TEXT, confidence TEXT, source TEXT,
    created_at TEXT, verified_at TEXT, supersedes TEXT, superseded_by TEXT,
    graph_refs TEXT, tags TEXT, path TEXT, hash TEXT, ref_files TEXT,
    consolidated_into TEXT DEFAULT '', anchor_hash TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_name_type ON records(name, type);
CREATE INDEX IF NOT EXISTS idx_live ON records(superseded_by, consolidated_into);
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
    USING fts5(id UNINDEXED, name, body, tags, source, tokenize='porter unicode61');
"""


# `src/auth.py:40` or `tests/test_x.py` inside a free-text source field.
SOURCE_PATH = re.compile(r"([\w./-]+\.[A-Za-z0-9]{1,6})(?::\d+)?")


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
        self._stale_schema: int | None = None
        self._graph_cache: object | None = None
        self._graph_tried = False
        self._global_sig: tuple | None = None

    # ---------- setup ----------

    @classmethod
    def init(cls, root: Path) -> Store:
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
            fresh = not self.db_path.exists()
            self._db = sqlite3.connect(self.db_path)
            self._db.row_factory = sqlite3.Row
            self._db.executescript(SCHEMA)
            found = self._db.execute("PRAGMA user_version").fetchone()[0]
            if fresh or found == 0:
                self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self._db.commit()
            elif found != SCHEMA_VERSION:
                self._stale_schema = found
        return self._db

    def _global_signature(self) -> tuple:
        """Cheap: names and mtimes, no parsing. Used only to decide whether to look."""
        try:
            return tuple(sorted((f.name, f.stat().st_mtime_ns)
                                for f in GLOBAL_DIR.glob("*.md")))
        except OSError:
            return ()

    def sync_global(self) -> int:
        """Pull `~/.nexus/global/` into this project's index. Returns rows changed.

        Global records belong to every project, but every project keeps its own
        index. Without this, a convention written in one repository stays
        invisible in all the others until somebody runs `nexus reindex` there by
        hand — and nothing anywhere tells them to. The tier looked implemented
        and silently was not.
        """
        sig = self._global_signature()
        if sig == self._global_sig:
            return 0
        self._global_sig = sig
        indexed = {r["id"]: r["hash"] for r in
                   self.db.execute("SELECT id, hash FROM records WHERE type='global'")}
        seen: set[str] = set()
        changed = 0
        for f in sorted(GLOBAL_DIR.glob("*.md")) if GLOBAL_DIR.is_dir() else []:
            try:
                rec = read_record(f)
            except (ValueError, OSError):
                continue          # not a NEXUS record; leave it alone
            seen.add(rec.id)
            if indexed.get(rec.id) != rec.hash:
                self._index(rec, f)
                changed += 1
        for gone in set(indexed) - seen:   # removed on another machine
            self.db.execute("DELETE FROM records WHERE id=?", (gone,))
            self.db.execute("DELETE FROM records_fts WHERE id=?", (gone,))
            changed += 1
        if changed:
            self.db.commit()
        return changed

    def ensure_current_schema(self) -> int | None:
        """Rebuild the index if it was written by an older schema. Returns rows rebuilt."""
        self.db  # noqa: B018 - opening the db is what detects the mismatch
        if getattr(self, "_stale_schema", None) is None:
            return None
        n = self.reindex()
        return n

    # ---------- the graph join ----------

    def graph(self):
        """The project's knowledge graph, loaded once per Store, or None.

        Imported here rather than at module scope: the memory engine must keep
        working in a project that has no graph at all.
        """
        if not self._graph_tried:
            self._graph_tried = True
            try:
                from .graph import GraphMissing, load as load_graph
                self._graph_cache = load_graph(self.root)
            except (GraphMissing, OSError, json.JSONDecodeError, KeyError, ValueError):
                # A project may have no graph, or a corrupt one. Neither is a
                # reason for the memory engine to stop working.
                self._graph_cache = None
        return self._graph_cache

    def source_path(self, source: str) -> str | None:
        """The file a record's `source` field points at, if any."""
        for candidate in SOURCE_PATH.findall(source or ""):
            if (self.root / candidate).is_file():
                return candidate
            g = self.graph()
            if g and g.resolve(candidate)[0] == "file":
                return candidate
        return None

    def resolve_graph_refs(self, rec: Record) -> list[str]:
        """Node ids for a record's source file. Empty when nothing resolves —
        a link is never invented."""
        g = self.graph()
        if g is None:
            return []
        path = self.source_path(rec.source)
        if not path:
            return []
        kind, ids = g.resolve(path)
        return ids if kind == "file" else []

    def anchor_digest(self, rec: Record) -> str:
        """Digest of the file a record was verified against, at the time of writing."""
        path = self.source_path(rec.source)
        if not path:
            return ""
        f = self.root / path
        try:
            return hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        except OSError:
            return ""

    def ref_files(self, rec: Record) -> list[str]:
        """Every file this record is anchored to: its source, plus the files of
        any graph nodes it references."""
        files: set[str] = set()
        path = self.source_path(rec.source)
        if path:
            files.add(path)
        g = self.graph()
        if g and rec.graph_refs:
            files |= g.files_of(list(rec.graph_refs))
        return sorted(files)

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
            "SELECT path FROM records WHERE name=? AND type=? AND superseded_by='' "
            "AND consolidated_into='' LIMIT 1",
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

        if not rec.graph_refs:
            rec.graph_refs = self.resolve_graph_refs(rec)
        if rec.confidence == "verified" and not rec.anchor_hash:
            rec.anchor_hash = self.anchor_digest(rec)

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
                   supersedes,superseded_by,graph_refs,tags,path,hash,ref_files,
                   consolidated_into,anchor_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec.id, rec.name, rec.type, rec.confidence, rec.source, rec.created_at,
             rec.verified_at, rec.supersedes, rec.superseded_by,
             json.dumps(d["graph_refs"]), json.dumps(d["tags"]), str(path), rec.hash,
             json.dumps(self.ref_files(rec)), rec.consolidated_into, rec.anchor_hash),
        )
        self.db.execute(
            "INSERT INTO records_fts (id,name,body,tags,source) VALUES (?,?,?,?,?)",
            (rec.id, rec.name.replace("-", " "), rec.body, " ".join(rec.tags), rec.source),
        )

    def reindex(self) -> int:
        self.db.executescript("DROP TABLE IF EXISTS records; DROP TABLE IF EXISTS records_fts;")
        self.db.executescript(SCHEMA)
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._stale_schema = None
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

    # ---------- staleness of a record ----------

    def record_staleness(self, row: dict) -> str | None:
        """Why this verified fact can no longer be trusted, or None.

        `verified_at` was written from Phase 1 and never read again. A fact
        proved against `src/auth.py:40` is only as true as that file's last
        edit, so retrieval has to say when the ground has moved.
        """
        if (row.get("confidence") or "") != "verified":
            return None          # observed and assumed never claimed currency
        stamp = row.get("verified_at") or ""
        if not stamp:
            return None
        try:
            verified_ts = datetime.fromisoformat(stamp).timestamp()
        except ValueError:
            return None
        try:
            files = json.loads(row.get("ref_files") or "[]")
        except json.JSONDecodeError:
            return None
        anchor = row.get("anchor_hash") or ""
        for rel in files:
            p = self.root / rel
            if not p.exists():
                return f"{rel} no longer exists (verified {stamp})"
            if anchor:
                # Content, not mtime. A rebuild, a checkout or a formatter run
                # touches a file without changing it, and a staleness warning
                # that fires on those gets ignored like any other false alarm.
                try:
                    current = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                except OSError:
                    continue
                if current != anchor:
                    return f"{rel} changed after this was verified ({stamp})"
            elif p.stat().st_mtime > verified_ts:
                return f"{rel} changed after this was verified ({stamp}, mtime only)"
        return None

    def stale_records(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM records WHERE superseded_by='' "
                               "AND consolidated_into='' AND confidence='verified'").fetchall()
        out = []
        for row in rows:
            why = self.record_staleness(dict(row))
            if why:
                d = dict(row)
                d["stale"] = why
                out.append(d)
        return out

    # ---------- read ----------

    @staticmethod
    def _fts_query(text: str, joiner: str) -> str | None:
        tokens = re.findall(r"[A-Za-z0-9_]{2,}", text)
        if not tokens:
            return None
        return f" {joiner} ".join(f'"{t}"' for t in tokens)

    def graph_neighbour_files(self, query: str, hops: int = 1) -> set[str]:
        """Files reachable from whatever the query names, through the graph.

        This is the half of `BLUEPRINT.md §5` that keyword search cannot do: a
        question about `beta` should surface what is known about `alpha`, because
        beta calls it — even though the two share no words.
        """
        g = self.graph()
        if g is None:
            return set()
        seeds: list[str] = []
        for token in re.findall(r"[\w./-]{3,}", query):
            kind, ids = g.resolve(token)
            if kind != "none":
                seeds.extend(ids)
        if not seeds:
            return set()

        files = set(g.files_of(seeds))
        frontier = list(dict.fromkeys(seeds))
        seen = set(frontier)
        for _ in range(max(1, hops)):
            nxt = []
            for nid in frontier:
                for link in self.graph().outgoing[nid] + self.graph().incoming[nid]:
                    other = link["target"] if link["source"] == nid else link["source"]
                    if other in seen:
                        continue
                    seen.add(other)
                    nxt.append(other)
                    node = g.nodes.get(other) or {}
                    if node.get("source_file"):
                        files.add(node["source_file"])
            frontier = nxt
            if not frontier:
                break
        return files

    def records_anchored_to(self, files: set[str], exclude: set[str]) -> list[dict]:
        """Live records whose source or graph refs point at any of these files.

        shortcut: scans one column for every live record. Fine to five figures;
        add an index on ref_files if a project ever outgrows that.
        """
        if not files:
            return []
        rows = self.db.execute(
            "SELECT * FROM records WHERE superseded_by='' AND consolidated_into='' "
            "AND ref_files NOT IN ('', '[]')"
        ).fetchall()
        out = []
        for row in rows:
            if row["id"] in exclude:
                continue
            try:
                refs = set(json.loads(row["ref_files"] or "[]"))
            except json.JSONDecodeError:
                continue
            if refs & files:
                d = dict(row)
                d["matched_files"] = sorted(refs & files)
                out.append(d)
        return out

    def recall(self, query: str, type_: str | None = None, limit: int = 10,
               include_superseded: bool = False, expand: bool = True) -> list[dict]:
        self.sync_global()
        where = [] if include_superseded else ["r.superseded_by=''", "r.consolidated_into=''"]
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
            d["via"] = "keyword"
            d["graph_refs"] = json.loads(d.get("graph_refs") or "[]")
            d["tags"] = json.loads(d.get("tags") or "[]")
            # bm25 is negative-better; flip so higher = better, then weight by confidence.
            d["score"] = -float(d.pop("bm25")) * CONFIDENCE_WEIGHT.get(d["confidence"], 0.7)
            d["stale"] = self.record_staleness(d)
            results.append(d)
        if expand and not include_superseded:
            # Graph-linked records the keyword pass could not see. They rank below
            # every keyword hit, because a structural link is weaker evidence than
            # the question's own words.
            found = {r["id"] for r in results}
            neighbours = self.graph_neighbour_files(query)
            floor = min((r["score"] for r in results), default=1.0)
            for row in self.records_anchored_to(neighbours, exclude=found):
                if type_ and row["type"] != type_:
                    continue
                d = dict(row)
                d["via"] = "graph"
                d["graph_refs"] = json.loads(d.get("graph_refs") or "[]")
                d["tags"] = json.loads(d.get("tags") or "[]")
                d.pop("bm25", None)
                d["score"] = floor * 0.5 * CONFIDENCE_WEIGHT.get(d["confidence"], 0.7)
                d["stale"] = self.record_staleness(d)
                results.append(d)

        # id is the tiebreaker so equal-scoring hits keep a stable order across reindexes.
        results.sort(key=lambda r: (0 if r.get("via") == "keyword" else 1, -r["score"], r["id"]))
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

    def consolidate_episodes(self, older_than_days: int = 30, dry_run: bool = False) -> list[dict]:
        """Fold old episodic records into one summary per month.

        `BLUEPRINT.md §3` says episodic memory decays and is summarised. Nothing
        is deleted: the originals stay on disk and `recall --all` still finds
        them. They simply stop competing with current facts for attention.
        """
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=older_than_days)).date().isoformat()
        rows = self.db.execute(
            "SELECT * FROM records WHERE type='episodic' AND superseded_by='' "
            "AND consolidated_into='' AND created_at < ? ORDER BY created_at",
            (cutoff,)).fetchall()

        by_month: dict[str, list[dict]] = {}
        for row in rows:
            d = dict(row)
            if "summary" in json.loads(d.get("tags") or "[]"):
                continue          # never fold a summary into another summary
            by_month.setdefault((d["created_at"] or "0000-00")[:7], []).append(d)

        results = []
        for month, group in sorted(by_month.items()):
            if len(group) < 2:
                continue          # one record is already its own summary
            lines = []
            for d in group:
                try:
                    body = Path(d["path"]).read_text(encoding="utf-8").split("---", 2)[-1].strip()
                except OSError:
                    body = ""
                first = body.splitlines()[0] if body else "(unreadable)"
                lines.append(f"- {d['created_at']} **{d['name']}**: {first}")

            summary = Record(
                name=f"episodes-{month}", type="episodic",
                body=(f"{len(group)} episodes from {month}, folded into one record. "
                      f"The originals are still on disk and `recall --all` finds them.\n\n"
                      + "\n".join(lines)),
                confidence="observed",
                source=f"consolidated {len(group)} episodic record(s)",
                tags=["summary", "consolidated"],
            )
            results.append({"month": month, "folded": len(group), "summary": summary.name})
            if dry_run:
                continue

            self.write(summary)
            for d in group:
                obj = read_record(Path(d["path"]))
                obj.consolidated_into = summary.id
                obj.write(Path(d["path"]))
                self._index(obj, Path(d["path"]))
            self.db.commit()
        return results

    def stats(self) -> dict:
        rows = self.db.execute(
            "SELECT type, COUNT(*) n FROM records WHERE superseded_by='' "
            "AND consolidated_into='' GROUP BY type"
        ).fetchall()
        superseded = self.db.execute(
            "SELECT COUNT(*) n FROM records WHERE superseded_by!=''"
        ).fetchone()["n"]
        consolidated = self.db.execute(
            "SELECT COUNT(*) n FROM records WHERE consolidated_into!=''"
        ).fetchone()["n"]
        stale = self.stale_records()
        return {
            "root": str(self.root),
            "by_type": {r["type"]: r["n"] for r in rows},
            "live": sum(r["n"] for r in rows),
            "superseded": superseded,
            "consolidated": consolidated,
            "stale": len(stale),
            "stale_records": [{"name": r["name"], "why": r["stale"]} for r in stale[:10]],
            "index": str(self.db_path),
        }
