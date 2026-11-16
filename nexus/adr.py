"""Architecture Decision Records.

ADRs live in `docs/adr/` as ordinary Markdown, because that is where a
reviewer expects to find them and because they belong in the repository, not
in a tool's private directory. NEXUS also indexes each one into memory, so
`nexus recall` surfaces a decision without anyone remembering it exists.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .record import Record, slugify
from .store import Store

ADR_DIR = Path("docs") / "adr"
NUM_RE = re.compile(r"^(\d{4})-")

TEMPLATE = """# ADR {number} — {title}

**Date:** {today} · **Status:** proposed

## Context
{context}

## Decision
{decision}

## Alternatives considered
{alternatives}

## Consequences
{consequences}

## Affects
{affects}
"""


def directory(root: Path) -> Path:
    return Path(root) / ADR_DIR


def existing(root: Path) -> list[dict]:
    d = directory(root)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.md")):
        m = NUM_RE.match(f.name)
        text = f.read_text(encoding="utf-8", errors="replace")
        title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), f.stem)
        status = "unknown"
        sm = re.search(r"\*\*Status:\*\*\s*([A-Za-z-]+)", text)
        if sm:
            status = sm.group(1).lower()
        out.append({"number": m.group(1) if m else "----", "title": title,
                    "status": status, "path": str(f.relative_to(root))})
    return out


def next_number(root: Path) -> str:
    nums = [int(a["number"]) for a in existing(root) if a["number"].isdigit()]
    return f"{max(nums) + 1 if nums else 1:04d}"


def create(root: Path, title: str, context: str = "", decision: str = "",
           alternatives: str = "", consequences: str = "",
           affects: list[str] | None = None, index: bool = True) -> Path:
    root = Path(root).resolve()
    d = directory(root)
    d.mkdir(parents=True, exist_ok=True)
    number = next_number(root)
    path = d / f"{number}-{slugify(title)}.md"
    body = TEMPLATE.format(
        number=number, title=title, today=date.today().isoformat(),
        context=context or "_TODO: what forces this decision?_",
        decision=decision or "_TODO: what are we doing?_",
        alternatives=alternatives or "_TODO: what else was on the table, and why not?_",
        consequences=consequences or "_TODO: what gets better, what gets worse?_",
        affects="\n".join(f"- `{a}`" for a in (affects or [])) or "_TODO: which files or modules?_",
    )
    path.write_text(body, encoding="utf-8")

    if index:
        store = Store(root)
        if store.dir.is_dir():
            store.write(Record(
                name=f"adr-{number}-{slugify(title)}", type="semantic",
                body=f"ADR {number}: {title}\n\n{decision or '(decision not yet written)'}",
                confidence="verified", source=str(path.relative_to(root)),
                tags=["adr", "architecture"], graph_refs=list(affects or []),
            ))
    return path
