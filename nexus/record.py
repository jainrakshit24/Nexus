"""The memory record: one fact, one file, Markdown with YAML frontmatter."""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path

import yaml

TIERS = ("global", "project", "episodic", "semantic", "procedural")
CONFIDENCE = ("verified", "observed", "assumed")

# Retrieval weight by confidence. An assumption must never outrank a
# verified fact on an equal keyword match.
CONFIDENCE_WEIGHT = {"verified": 1.0, "observed": 0.85, "assumed": 0.7}

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford, no I/L/O/U


def new_id() -> str:
    """Sortable, collision-safe id. ULID-shaped without the dependency."""
    ms = int(time.time() * 1000)
    head = ""
    for _ in range(10):
        ms, rem = divmod(ms, 32)
        head = _B32[rem] + head
    tail = "".join(_B32[b % 32] for b in os.urandom(10))
    return f"mem_{head}{tail}"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return s[:72] or "untitled"


def body_hash(body: str) -> str:
    normalized = "\n".join(line.rstrip() for line in body.strip().splitlines())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


@dataclass
class Record:
    name: str
    type: str
    body: str
    id: str = field(default_factory=new_id)
    confidence: str = "assumed"
    source: str = ""
    created_at: str = field(default_factory=lambda: date.today().isoformat())
    verified_at: str = ""
    supersedes: str = ""
    superseded_by: str = ""
    graph_refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.type not in TIERS:
            raise ValueError(f"type must be one of {TIERS}, got {self.type!r}")
        if self.confidence not in CONFIDENCE:
            raise ValueError(f"confidence must be one of {CONFIDENCE}, got {self.confidence!r}")
        # A record cannot claim verification without saying what verified it.
        if self.confidence == "verified" and not self.source:
            raise ValueError("confidence=verified requires --source (file:line, commit, or test)")
        if self.confidence == "verified" and not self.verified_at:
            self.verified_at = date.today().isoformat()
        self.name = slugify(self.name)

    @property
    def hash(self) -> str:
        return body_hash(self.body)

    def to_markdown(self) -> str:
        meta = {k: v for k, v in asdict(self).items() if k != "body" and v not in ("", [], None)}
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
        return f"---\n{front}---\n\n{self.body.strip()}\n"

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown(), encoding="utf-8")
        return path


_FRONT = re.compile(r"\A---\n(.*?)\n---\s*\n?(.*)\Z", re.S)


def parse(text: str) -> Record:
    m = _FRONT.match(text)
    if not m:
        raise ValueError("record has no YAML frontmatter")
    meta = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    known = {f for f in Record.__dataclass_fields__ if f != "body"}
    unknown = set(meta) - known
    if unknown:
        # Forward compatibility: a newer NEXUS may add fields. Don't crash.
        for k in unknown:
            meta.pop(k)
    return Record(body=body, **meta)


def read(path: Path) -> Record:
    try:
        return parse(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"{path}: {e}") from e
