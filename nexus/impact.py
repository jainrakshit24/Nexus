"""Impact analysis: what else moves when this moves.

Three sources, unioned, because each is blind where the others see:
  graph  — graphify's parsed call/import edges. Precise, but only as good
           as the last build, and silent about anything it cannot parse.
  text   — word-boundary search for the target's exported names. Catches
           config files, SQL, docs, templates. Noisier.
  tests  — any of the above that looks like a test file.

Each dependent carries the sources that found it, so a caller can tell
parsed evidence from a textual coincidence instead of being handed one
undifferentiated list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import serena as serena_mod
from . import symbols
from .graph import Graph, GraphMissing, Staleness, load as load_graph

# A change crossing one of these is never "light", whatever the file count.
RISKY_PATH_HINTS = ("migration", "schema", "models.py", "api/", "routes", "auth",
                    "security", "settings", "config/", "__init__.py", "Dockerfile")


@dataclass
class Dependent:
    file: str
    sources: set[str] = field(default_factory=set)
    symbols_hit: list[str] = field(default_factory=list)
    relations: set[str] = field(default_factory=set)
    hops: int = 0  # 0 = text only, 1 = direct graph dependent, 2+ = transitive

    @property
    def strength(self) -> str:
        """Parsed evidence outranks a word match."""
        if "graph" in self.sources or "lsp" in self.sources:
            return "strong"
        if "test" in self.sources:
            return "medium"
        return "weak"


@dataclass
class Impact:
    target: str
    kind: str
    dependents: list[Dependent]
    staleness: Staleness | None
    graph_available: bool
    notes: list[str] = field(default_factory=list)

    @property
    def strong_files(self) -> list[str]:
        return [d.file for d in self.dependents if d.strength == "strong"]

    @property
    def test_files(self) -> list[str]:
        return [d.file for d in self.dependents if "test" in d.sources]

    @property
    def code_dependents(self) -> list[Dependent]:
        """Code dependents that count toward blast radius.

        Prose and tests are excluded: docs do not break, and a test breaking
        is the point of running them. Text-only hits are excluded too when
        the graph answered, because a word match cannot tell a reference from
        a name collision — two modules may both define `to_markdown`. Without
        a graph they are all we have, so they count and the reason says so.
        """
        trusted = self.graph_available and self.kind != "none"
        return [d for d in self.dependents
                if not d.file.endswith((".md", ".txt"))
                and "test" not in d.sources
                and (d.strength == "strong" or not trusted)]

    @property
    def blast_radius(self) -> int:
        return len(self.code_dependents)

    @property
    def risky(self) -> bool:
        return any(h in self.target for h in RISKY_PATH_HINTS)

    @property
    def gear(self) -> str:
        """Which workflow this change earns. Phase 3 enforces it; Phase 2 reports it."""
        if self.risky:
            return "full"
        if self.staleness and self.staleness.is_stale:
            return "full"
        return "light" if self.blast_radius < 3 else "full"

    def reason(self) -> str:
        if self.risky:
            return f"target path matches a risky pattern ({self.target})"
        if self.staleness and self.staleness.is_stale:
            return "graph is stale, so dependents cannot be trusted"
        qualifier = "" if (self.graph_available and self.kind != "none") else " (text-only evidence, no graph)"
        if self.blast_radius < 3:
            return f"only {self.blast_radius} code dependent(s){qualifier}"
        return f"{self.blast_radius} code dependents{qualifier}"


def analyze(root: Path, target: str, use_graph: bool = True, depth: int = 1,
            use_serena: bool = False, serena_timeout: float = 120.0) -> Impact:
    root = Path(root).resolve()
    found: dict[str, Dependent] = {}
    notes: list[str] = []
    graph: Graph | None = None
    staleness: Staleness | None = None
    kind = "file"

    def record(file: str, source: str, syms: list[str] | None = None,
               rel: str | None = None, hops: int = 0):
        if not file or file == target:
            return
        d = found.setdefault(file, Dependent(file=file))
        d.sources.add(source)
        if syms:
            d.symbols_hit = sorted(set(d.symbols_hit) | set(syms))
        if rel:
            d.relations.add(rel)
        if hops and (d.hops == 0 or hops < d.hops):
            d.hops = hops

    # --- source 1: the graph ---
    if use_graph:
        try:
            graph = load_graph(root)
        except GraphMissing as e:
            notes.append(str(e))
        else:
            staleness = graph.staleness(root, extensions={".py", ".js", ".ts", ".go", ".rs"})
            kind, node_ids = graph.resolve(target)
            if kind == "none":
                notes.append(f"'{target}' is not in the graph — graph evidence unavailable")
            else:
                for dep in graph.dependents(node_ids, depth=depth):
                    record(dep["file"], "graph", [dep["label"]], dep["relation"], dep["hops"])

    # --- source 2: text references ---
    needles = symbols.needles_for(root, target)
    if not needles:
        notes.append(f"no distinctive exported names found for {target}; text search skipped")
    for file, hits in symbols.references(root, needles, exclude={target}).items():
        record(file, "text", hits)

    # --- source 3: the language server, when asked for ---
    if use_serena:
        syms = sorted(symbols.exported_names(root / target))[:6]
        if not syms:
            notes.append("serena skipped: no exported symbols to ask about")
        else:
            hits, err = serena_mod.referencing_files(root, syms, target, timeout=serena_timeout)
            if err:
                notes.append(err)
            for file, matched in hits.items():
                record(file, "lsp", matched, hops=1)

    # --- source 4: tests ---
    for file in list(found):
        if symbols.is_test_file(file):
            found[file].sources.add("test")

    dependents = sorted(found.values(),
                        key=lambda d: ({"strong": 0, "medium": 1, "weak": 2}[d.strength], d.hops or 99, d.file))
    return Impact(target=target, kind=kind, dependents=dependents, staleness=staleness,
                  graph_available=graph is not None, notes=notes)
