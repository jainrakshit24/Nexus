"""Context packing: assemble what the agent needs, under a token budget.

Priority order, highest first. Sections are added while they fit; anything
that does not fit is dropped and named, never silently truncated mid-thought.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import symbols, tokens
from .impact import Impact, analyze
from .store import Store

PATH_LIKE = re.compile(r"[\w./-]+\.(?:py|js|jsx|ts|tsx|go|rs|java|rb|php|sql|yml|yaml|toml|md)")


@dataclass
class Section:
    name: str
    body: str
    priority: int
    cost: int = 0


@dataclass
class Pack:
    task: str
    sections: list[Section]
    dropped: list[str]
    budget: int
    baseline: int
    files_considered: list[str] = field(default_factory=list)

    @property
    def actual(self) -> int:
        return sum(s.cost for s in self.sections)

    def render(self) -> str:
        parts = [f"# NEXUS context for: {self.task}\n"]
        for s in self.sections:
            parts.append(f"## {s.name}\n{s.body.strip()}\n")
        if self.dropped:
            parts.append("## Omitted (budget)\n" + "\n".join(f"- {d}" for d in self.dropped) + "\n")
        return "\n".join(parts)

    def accounting(self) -> tokens.Accounting:
        return tokens.Accounting(task=self.task, actual=self.actual, baseline=self.baseline)


def targets_in(task: str, root: Path) -> list[str]:
    """File paths named in the task that actually exist."""
    out = []
    for m in PATH_LIKE.findall(task):
        rel = m.lstrip("./")
        if (root / rel).is_file():
            out.append(rel)
    return sorted(set(out))


def build(root: Path, task: str, budget: int = 4000, memory_limit: int = 6) -> Pack:
    root = Path(root).resolve()
    store = Store(root)
    candidates: list[Section] = []

    # 1. The project overview: cheap, and orients everything else.
    overview = store.recall("project overview stack test command", type_="project", limit=1)
    if overview:
        body = Path(overview[0]["path"]).read_text(encoding="utf-8").split("---", 2)[-1].strip()
        candidates.append(Section("Project", body, priority=1))

    # 2. Memories relevant to this task.
    mems = [m for m in store.recall(task, limit=memory_limit) if m["name"] != "project-overview"]
    if mems:
        lines = []
        for m in mems:
            text = Path(m["path"]).read_text(encoding="utf-8").split("---", 2)[-1].strip()
            src = f" (source: {m['source']})" if m["source"] else ""
            lines.append(f"- **{m['name']}** [{m['confidence']}]{src}\n  {text}")
        candidates.append(Section(f"Relevant memory ({len(mems)})", "\n".join(lines), priority=2))

    # 3. Impact of the files this task names.
    files = targets_in(task, root)
    impacts: list[Impact] = []
    for f in files:
        imp = analyze(root, f)
        impacts.append(imp)
        rows = [f"- {d.file} [{d.strength}] via {', '.join(sorted(d.sources))}" for d in imp.dependents[:15]]
        stale = f"\nGraph: {imp.staleness.summary()}" if imp.staleness else "\nGraph: unavailable"
        candidates.append(Section(
            f"Impact of {f} (blast radius {imp.blast_radius}, workflow: {imp.gear})",
            f"Reason: {imp.reason()}{stale}\n" + ("\n".join(rows) or "- no dependents found"),
            priority=3,
        ))

    # 4. Outlines of the target files and their strong dependents — shape, not body.
    outline_files: list[str] = list(files)
    for imp in impacts:
        outline_files += imp.strong_files
    seen: set[str] = set()
    for f in outline_files:
        if f in seen or not (root / f).is_file():
            continue
        seen.add(f)
        body = symbols.outline(root / f)
        if body:
            candidates.append(Section(f"Outline: {f}", f"```\n{body}\n```", priority=4))

    # Baseline: what reading every one of those files whole would have cost.
    baseline = sum(tokens.count_file(root / f) for f in seen)

    # Fit to budget, highest priority first, dropping whole sections only.
    chosen: list[Section] = []
    dropped: list[str] = []
    used = 0
    for s in sorted(candidates, key=lambda s: s.priority):
        s.cost = tokens.count(f"## {s.name}\n{s.body}\n")
        if used + s.cost <= budget:
            chosen.append(s)
            used += s.cost
        else:
            dropped.append(f"{s.name} ({s.cost:,} tokens, would exceed budget)")

    return Pack(task=task, sections=chosen, dropped=dropped, budget=budget,
                baseline=baseline, files_considered=sorted(seen))
