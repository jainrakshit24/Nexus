"""graphify adapter.

graphify owns extraction. This module owns what graphify does not do:
locating its output, reading it, telling you when it has gone stale, and
answering "what depends on this".

Note on building: the graph is produced by the `/graphify` skill running
inside an agent (AST for code, an LLM pass for prose). The `graphify`
binary on PATH exposes query helpers but no build command, so NEXUS reads
graphs and reports staleness — it never claims to build one itself.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# Edge relations that mean "the source depends on the target".
# `contains` is structural (file holds symbol), not a dependency.
DEPENDENCY_RELATIONS = {
    "calls", "imports", "imports_from", "references", "implements",
    "inherits", "method", "indirect_call", "uses", "extends",
}

CANDIDATE_DIRS = ("graphify-out", "docs/graphify-out", ".nexus/graphify-out")


class GraphMissing(Exception):
    pass


def find_graph_dir(root: Path) -> Path | None:
    env = os.environ.get("NEXUS_GRAPH_DIR")
    if env and (Path(env) / "graph.json").exists():
        return Path(env)
    for rel in CANDIDATE_DIRS:
        d = root / rel
        if (d / "graph.json").exists():
            return d
    return None


@dataclass
class Staleness:
    changed: list[str]
    deleted: list[str]
    unindexed: list[str]
    indexed: int

    @property
    def is_stale(self) -> bool:
        return bool(self.changed or self.deleted or self.unindexed)

    def summary(self) -> str:
        if not self.indexed:
            return "no manifest — staleness unknown"
        if not self.is_stale:
            return f"fresh ({self.indexed} files indexed)"
        bits = []
        if self.changed:
            bits.append(f"{len(self.changed)} changed")
        if self.deleted:
            bits.append(f"{len(self.deleted)} deleted")
        if self.unindexed:
            bits.append(f"{len(self.unindexed)} never indexed")
        return f"STALE: {', '.join(bits)} of {self.indexed} indexed files"


class Graph:
    """A loaded graphify graph, indexed for reverse lookup."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        data = json.loads((self.dir / "graph.json").read_text(encoding="utf-8"))
        self.directed: bool = bool(data.get("directed"))
        self.nodes: dict[str, dict] = {n["id"]: n for n in data.get("nodes", [])}
        self.links: list[dict] = data.get("links", [])

        # The directory the graph was built against; paths in the graph are
        # relative to it, which is not always the repo root.
        marker = self.dir / ".graphify_root"
        self.graph_root = Path(marker.read_text().strip()) if marker.exists() else self.dir.parent

        manifest_path = self.dir / "manifest.json"
        self.manifest: dict = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

        self.by_file: dict[str, list[str]] = defaultdict(list)
        for nid, n in self.nodes.items():
            src = n.get("source_file")
            if src:
                self.by_file[src].append(nid)

        self.incoming: dict[str, list[dict]] = defaultdict(list)
        self.outgoing: dict[str, list[dict]] = defaultdict(list)
        for link in self.links:
            self.outgoing[link["source"]].append(link)
            self.incoming[link["target"]].append(link)

    # ---------- lookup ----------

    def resolve(self, target: str) -> tuple[str, list[str]]:
        """Map a user-supplied path or symbol to node ids.

        Returns (kind, node_ids) where kind is 'file' or 'symbol'.
        """
        if target in self.nodes:
            return "symbol", [target]

        # File path, possibly relative to the repo rather than the graph root.
        candidates = {target, target.lstrip("./")}
        p = Path(target)
        if p.is_absolute():
            try:
                candidates.add(str(p.resolve().relative_to(self.graph_root.resolve())))
            except (ValueError, OSError):
                pass
        for c in candidates:
            if c in self.by_file:
                return "file", list(self.by_file[c])
        # Suffix match: "store.py" should find "nexus/store.py". But a monorepo
        # has many `utils.py`, and silently merging them produces dependents that
        # belong to a different module. Say so instead.
        suffix_hits = sorted(f for f in self.by_file if f.endswith("/" + target) or f == target)
        if len(suffix_hits) > 1:
            return "ambiguous", suffix_hits
        if suffix_hits:
            return "file", list(self.by_file[suffix_hits[0]])

        label = target.lower()
        sym_hits = [nid for nid, n in self.nodes.items()
                    if n.get("norm_label") == label or (n.get("label") or "").lower() == label]
        if sym_hits:
            return "symbol", sym_hits
        return "none", []

    def dependents(self, node_ids: list[str], relations: set[str] | None = None,
                   depth: int = 1) -> list[dict]:
        """Nodes that depend on these, following reverse edges up to `depth` hops.

        Depth 1 is "who calls this". Depth 2 adds "who calls them" — the
        second-order breakage a text search cannot reach, because those
        files never mention the target at all.
        """
        relations = relations or DEPENDENCY_RELATIONS
        seen: dict[str, dict] = {}
        targets = set(node_ids)
        frontier = list(node_ids)
        for hop in range(1, max(1, depth) + 1):
            next_frontier: list[str] = []
            for nid in frontier:
                for link in self.incoming[nid]:
                    if link.get("relation") not in relations:
                        continue
                    src = link["source"]
                    if src in targets or src in seen:
                        continue
                    node = self.nodes.get(src)
                    if not node:
                        continue
                    seen[src] = {
                        "node": src,
                        "label": node.get("label", src),
                        "file": node.get("source_file", ""),
                        "location": node.get("source_location", ""),
                        "relation": link.get("relation"),
                        "confidence": link.get("confidence", "UNKNOWN"),
                        "origin": link.get("_origin", ""),
                        "hops": hop,
                    }
                    next_frontier.append(src)
            frontier = next_frontier
            if not frontier:
                break
        return sorted(seen.values(), key=lambda d: (d["hops"], d["file"], d["label"]))

    def files_of(self, node_ids: list[str]) -> set[str]:
        return {self.nodes[n].get("source_file", "") for n in node_ids if n in self.nodes} - {""}

    # ---------- staleness ----------

    def staleness(self, repo_root: Path | None = None, extensions: set[str] | None = None) -> Staleness:
        """Compare the manifest against the filesystem. No rebuild required."""
        base = Path(repo_root) if repo_root else self.graph_root
        changed, deleted = [], []
        for rel, meta in self.manifest.items():
            f = base / rel
            if not f.exists():
                deleted.append(rel)
                continue
            recorded = meta.get("mtime")
            # mtime, not content hash: graphify records an AST hash we cannot
            # recompute without re-parsing. Coarser, but honest and cheap.
            if recorded and f.stat().st_mtime > float(recorded) + 1:
                changed.append(rel)

        unindexed: list[str] = []
        if extensions and self.manifest:
            known = set(self.manifest)
            skip = {".git", "node_modules", "__pycache__", ".nexus", ".venv", "dist", "build"}
            for f in base.rglob("*"):
                if not f.is_file() or f.suffix not in extensions:
                    continue
                if any(part in skip for part in f.parts):
                    continue
                rel = str(f.relative_to(base))
                if rel not in known:
                    unindexed.append(rel)

        return Staleness(sorted(changed), sorted(deleted), sorted(unindexed), len(self.manifest))


def load(root: Path) -> Graph:
    d = find_graph_dir(Path(root))
    if d is None:
        raise GraphMissing(
            f"no graphify-out/ found under {root}. Build one by running `/graphify` "
            f"in your agent (NEXUS reads graphs, it does not build them)."
        )
    return Graph(d)


def explain(node: str, graph_dir: Path) -> str:
    """Delegate to the graphify CLI when it is on PATH."""
    exe = shutil.which("graphify")
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "explain", node, "--graph", str(Path(graph_dir) / "graph.json")],
                             capture_output=True, text=True, timeout=30)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""
