"""Public API shape, before and after, for breaking-change detection.

"Before" is the committed version; "after" is what is on disk now. Only
changes that would break a caller are reported — adding an optional parameter
is not a breaking change, and a gate that says it is gets ignored.

Python only for now. Reporting nothing for a language it cannot parse is
correct; claiming nothing changed would not be.
"""
from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path

PARSEABLE = {".py", ".pyi"}


@dataclass
class Signature:
    name: str
    kind: str                 # "function" | "class" | "method"
    positional: list[str]
    defaults: int             # how many trailing positionals have defaults
    kwonly_required: list[str]
    varargs: bool
    varkw: bool

    @property
    def required_positional(self) -> list[str]:
        return self.positional[: len(self.positional) - self.defaults]

    def render(self) -> str:
        parts = list(self.positional)
        for i in range(len(self.positional) - self.defaults, len(self.positional)):
            if 0 <= i < len(parts):
                parts[i] += "=..."
        if self.varargs:
            parts.append("*args")
        parts += [f"{k}=..." if k not in self.kwonly_required else k for k in self.kwonly_required]
        if self.varkw:
            parts.append("**kwargs")
        return f"{self.name}({', '.join(parts)})"


def _signature(node, name: str, kind: str) -> Signature:
    args = node.args
    positional = [a.arg for a in (list(args.posonlyargs) + list(args.args))]
    return Signature(
        name=name, kind=kind, positional=positional,
        defaults=len(args.defaults), varargs=args.vararg is not None,
        kwonly_required=[a.arg for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d is None],
        varkw=args.kwarg is not None,
    )


def shape(source: str) -> dict[str, Signature]:
    """Every public, top-level name a caller could depend on."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    out: dict[str, Signature] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                out[node.name] = _signature(node, node.name, "function")
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            out[node.name] = Signature(node.name, "class", [], 0, [], False, False)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                        (not sub.name.startswith("_") or sub.name == "__init__"):
                    full = f"{node.name}.{sub.name}"
                    out[full] = _signature(sub, full, "method")
    return out


def committed_source(root: Path, rel: str, ref: str = "HEAD") -> str | None:
    try:
        p = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=root,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def compare(before: dict[str, Signature], after: dict[str, Signature]) -> list[dict]:
    """Only what would break a caller."""
    out: list[dict] = []
    for name, old in before.items():
        new = after.get(name)
        if new is None:
            out.append({"symbol": name, "kind": old.kind, "change": "removed",
                        "before": old.render(), "after": None,
                        "why": "callers referencing this will fail"})
            continue
        if old.kind != new.kind:
            out.append({"symbol": name, "kind": old.kind, "change": "kind changed",
                        "before": f"{old.kind} {old.render()}", "after": f"{new.kind} {new.render()}",
                        "why": f"was a {old.kind}, now a {new.kind}"})
            continue
        if old.kind == "class":
            continue

        old_req, new_req = old.required_positional, new.required_positional
        if len(new_req) > len(old_req) and not old.varargs:
            added = new_req[len(old_req):]
            out.append({"symbol": name, "kind": old.kind, "change": "required parameter added",
                        "before": old.render(), "after": new.render(),
                        "why": f"existing calls omit {', '.join(added)}"})
            continue
        dropped = [a for a in old_req if a not in new.positional] if not new.varkw else []
        if dropped:
            out.append({"symbol": name, "kind": old.kind, "change": "parameter removed or renamed",
                        "before": old.render(), "after": new.render(),
                        "why": f"callers passing {', '.join(dropped)} will fail"})
            continue
        gone_kw = [k for k in old.kwonly_required if k not in new.kwonly_required
                   and k not in new.positional and not new.varkw]
        if gone_kw:
            out.append({"symbol": name, "kind": old.kind, "change": "keyword argument removed",
                        "before": old.render(), "after": new.render(),
                        "why": f"callers passing {', '.join(gone_kw)} will fail"})
    return out


def breaking_changes(root: Path, rel: str, ref: str = "HEAD") -> list[dict]:
    """Breaking changes between the committed version of a file and the one on disk."""
    root = Path(root)
    if Path(rel).suffix not in PARSEABLE:
        return []
    before_src = committed_source(root, rel, ref)
    if before_src is None:
        return []                      # new file: nothing to break
    path = root / rel
    after_src = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if not after_src:
        return [{"symbol": rel, "kind": "module", "change": "file deleted",
                 "before": rel, "after": None, "why": "every importer breaks"}]
    return compare(shape(before_src), shape(after_src))
