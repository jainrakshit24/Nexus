"""Symbol and reference search — the non-graph half of impact analysis.

The graph knows what the parser understood. This module catches what the
parser never saw: a module named in a config file, a table name in SQL, a
route string in a template. Deliberately dumber than the graph, and
deliberately wider.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".next", ".nexus", "graphify-out", "target", ".mypy_cache", ".pytest_cache", "vendor"}

TEXT_SUFFIXES = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb",
                 ".php", ".sql", ".sh", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".json",
                 ".md", ".txt", ".html", ".css", ".env.example", ".tf", ".proto"}

TEST_HINT = re.compile(r"(^|[/_.])(tests?|spec|__tests__)([/_.]|$)")

# Names too generic to be evidence of anything. `parse` appears in every file
# that calls ast.parse; matching on it says nothing about who depends on whom.
GENERIC_NAMES = {
    "read", "write", "parse", "load", "save", "get", "set", "put", "run", "main",
    "init", "update", "delete", "remove", "add", "list", "find", "make", "build",
    "open", "close", "start", "stop", "send", "data", "text", "path", "file",
    "name", "type", "value", "key", "id", "item", "node", "root", "store", "index",
    "record", "result", "config", "status", "query", "source", "target", "format",
}


def is_test_file(rel: str) -> bool:
    return bool(TEST_HINT.search(rel.lower()))


def iter_text_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def exported_names(path: Path) -> set[str]:
    """Top-level names a Python module offers to importers."""
    if path.suffix != ".py" or not path.exists():
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError):
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    names.add(t.id)
    return names


def needles_for(root: Path, target: str) -> set[str]:
    """Search terms that would appear in a file referencing this target."""
    p = root / target
    needles = {Path(target).stem}
    if p.is_file():
        needles |= exported_names(p)
    # A dotted module path, as it appears in imports and config.
    if target.endswith(".py"):
        needles.add(target[:-3].replace("/", "."))
    return {n for n in needles if len(n) > 2 and n not in GENERIC_NAMES}


def references(root: Path, needles: set[str], exclude: set[str] | None = None) -> dict[str, list[str]]:
    """Files mentioning any needle, mapped to the needles they matched.

    Word-boundary matching, so `store` does not match `restore`.
    """
    exclude = exclude or set()
    if not needles:
        return {}
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(needles)) + r")\b")
    hits: dict[str, list[str]] = {}
    for p in iter_text_files(root):
        rel = str(p.relative_to(root))
        if rel in exclude:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = sorted(set(pattern.findall(text)))
        if found:
            hits[rel] = found
    return hits


def outline(path: Path, max_lines: int = 120) -> str:
    """A file's shape without its body: the cheap substitute for reading it.

    Python gets a real AST outline. Everything else falls back to the lines
    that look like declarations, which is crude but still far cheaper than
    the whole file.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if Path(path).suffix == ".py":
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            tree = None
        if tree is not None:
            out: list[str] = []
            doc = ast.get_docstring(tree)
            if doc:
                out.append(f'"""{doc.strip().splitlines()[0]}"""')
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = ", ".join(a.arg for a in node.args.args)
                    out.append(f"L{node.lineno}: def {node.name}({args})")
                elif isinstance(node, ast.ClassDef):
                    bases = ", ".join(getattr(b, "id", "...") for b in node.bases)
                    out.append(f"L{node.lineno}: class {node.name}({bases})" if bases
                               else f"L{node.lineno}: class {node.name}")
            return "\n".join(out[:max_lines])

    decl = re.compile(r"^\s*(export\s+)?(async\s+)?(function|class|def|type|interface|struct|"
                      r"impl|fn|func|const|var|let|CREATE TABLE|CREATE INDEX)\b", re.I)
    lines = [f"L{i}: {l.strip()}" for i, l in enumerate(text.splitlines(), 1) if decl.match(l)]
    return "\n".join(lines[:max_lines])
