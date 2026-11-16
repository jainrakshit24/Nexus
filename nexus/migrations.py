"""Migration validation without a database.

A migration cannot be fully validated without running it, and NEXUS will not
run one. What it *can* do without a connection is catch the two failures that
cost the most and need no database to spot: a branched history, and a
destructive statement nobody flagged.

Everything here is advisory. It reports; it does not block.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

DESTRUCTIVE = [
    ("drop-table", re.compile(r"\bDROP\s+TABLE\b", re.I),
     "drops a table - data is unrecoverable once this runs"),
    ("drop-column", re.compile(r"\bDROP\s+(COLUMN|CONSTRAINT)\b", re.I),
     "drops a column or constraint - existing data in it is lost"),
    ("not-null-without-default",
     re.compile(r"\bADD\s+COLUMN\b(?:(?!DEFAULT).)*\bNOT\s+NULL\b", re.I | re.S),
     "adds NOT NULL with no default - fails on a non-empty table"),
    ("truncate", re.compile(r"\bTRUNCATE\b", re.I), "empties a table"),
    ("rename", re.compile(r"\bRENAME\s+(TO|COLUMN)\b", re.I),
     "renames - old and new code cannot both work during a rolling deploy"),
    ("django-delete-model", re.compile(r"migrations\.(DeleteModel|RemoveField)\b"),
     "removes a model or field"),
    ("alembic-drop", re.compile(r"op\.drop_(table|column|constraint)\b"),
     "drops a table, column or constraint"),
]

MIGRATION_DIRS = ("migrations", "migration", "versions", "migrate")
ALEMBIC_DOWN = re.compile(r"down_revision[^=]*=\s*['\"]([^'\"]+)['\"]")
ALEMBIC_REV = re.compile(r"\brevision[^=]*=\s*['\"]([^'\"]+)['\"]")
SEQ_NUM = re.compile(r"^(\d{3,4})[_-]")
SKIP = {".git", ".nexus", "node_modules", "__pycache__", ".venv", "graphify-out"}


def migration_files(root: Path) -> list[Path]:
    root = Path(root)
    out: list[Path] = []
    for d in root.rglob("*"):
        if not d.is_dir() or d.name not in MIGRATION_DIRS:
            continue
        if any(part in SKIP for part in d.parts):
            continue
        out += [f for f in sorted(d.glob("*.py")) + sorted(d.glob("*.sql"))
                if f.name != "__init__.py"]
    return out


def destructive_statements(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [{"rule": name, "why": why} for name, rx, why in DESTRUCTIVE if rx.search(text)]


def branched_history(files: list[Path]) -> list[str]:
    """Two migrations claiming the same parent, or the same sequence number."""
    problems: list[str] = []

    parents: Counter = Counter()
    for f in files:
        if f.suffix != ".py":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        down = ALEMBIC_DOWN.search(text)
        if down:
            parents[down.group(1)] += 1
    for parent, count in parents.items():
        if count > 1:
            problems.append(
                f"{count} migrations declare down_revision = {parent!r} - branched history")

    numbers: dict[str, list[str]] = {}
    for f in files:
        m = SEQ_NUM.match(f.name)
        if m:
            numbers.setdefault(f"{f.parent}/{m.group(1)}", []).append(f.name)
    for names in numbers.values():
        if len(names) > 1:
            problems.append(f"duplicate migration number: {', '.join(sorted(names))}")
    return problems


def validate(root: Path, only: list[str] | None = None) -> dict:
    """Structural review of this project's migrations. Advisory, never blocking."""
    root = Path(root)
    everything = migration_files(root)
    files = everything
    if only is not None:
        wanted = {str(Path(o)) for o in only}
        files = [f for f in everything if str(f.relative_to(root)) in wanted]
    report: dict = {"checked": [str(f.relative_to(root)) for f in files],
                    "destructive": [], "history": branched_history(everything)}
    for f in files:
        for item in destructive_statements(f):
            report["destructive"].append({"file": str(f.relative_to(root)), **item})
    return report
