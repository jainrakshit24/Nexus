"""Static checks run from the project's own configuration.

Two rules:

1. **NEXUS never installs a tool.** If a project has no type checker, the gate
   says "not configured" — it does not go and fetch one, and it certainly does
   not report a pass.
2. **Configured but missing is its own answer.** A `[tool.mypy]` section with no
   mypy on PATH is a broken setup, not a clean bill of health. That case is
   reported as `not-run`, with the reason.

Everything here returns `evidence.Run`, so the Phase 3 invariant — no pass
without captured output — covers every checker automatically.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .evidence import Run, execute

KINDS = ("lint", "types", "vulnerabilities")

# Advisory identifiers every ecosystem's scanner prints somewhere in its output.
ADVISORY_RE = re.compile(r"\b(CVE-\d{4}-\d{4,}|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}|"
                         r"PYSEC-\d{4}-\d+|RUSTSEC-\d{4}-\d+|OSV-\d{4}-\d+)\b", re.I)


def advisories(log: str) -> list[str]:
    """Advisory ids named in a scanner's output. A vulnerability report that
    does not name what it found is not actionable."""
    return sorted({m.group(0).upper() for m in ADVISORY_RE.finditer(log or "")})


@dataclass
class Candidate:
    kind: str
    tool: str
    command: str
    evidence: str          # the file or key that says this project uses it
    binary: str = ""       # what must exist to run it; defaults to `tool`

    def resolved_binary(self, root: Path) -> str | None:
        name = self.binary or self.tool
        local = root / "node_modules" / ".bin" / name
        if local.exists():
            return str(local)
        return shutil.which(name)


def _has_section(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _pkg_json(root: Path) -> dict:
    f = root / "package.json"
    if not f.is_file():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def candidates(root: Path) -> list[Candidate]:
    """Everything this project appears to have configured. Order matters:
    the first match per kind wins, so a project with both ruff and flake8
    is checked with ruff."""
    root = Path(root)
    pp = root / "pyproject.toml"
    setup_cfg = root / "setup.cfg"
    tox = root / "tox.ini"
    pkg = _pkg_json(root)
    out: list[Candidate] = []

    # ---- python lint ----
    if (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file() or \
            (pp.is_file() and _has_section(pp, "[tool.ruff")):
        out.append(Candidate("lint", "ruff", "ruff check .", "ruff config"))
    if (root / ".flake8").is_file() or _has_section(setup_cfg, "[flake8]") or _has_section(tox, "[flake8]"):
        out.append(Candidate("lint", "flake8", "flake8", "flake8 config"))
    if (root / ".pylintrc").is_file() or (pp.is_file() and _has_section(pp, "[tool.pylint")):
        out.append(Candidate("lint", "pylint", "pylint .", "pylint config"))

    # ---- python types ----
    if (root / "mypy.ini").is_file() or _has_section(setup_cfg, "[mypy]") or \
            (pp.is_file() and _has_section(pp, "[tool.mypy")):
        out.append(Candidate("types", "mypy", "mypy .", "mypy config"))
    if (root / "pyrightconfig.json").is_file() or (pp.is_file() and _has_section(pp, "[tool.pyright")):
        out.append(Candidate("types", "pyright", "pyright", "pyright config"))

    # ---- node ----
    eslint_cfg = any((root / n).is_file() for n in
                     (".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
                      "eslint.config.js", "eslint.config.mjs", "eslint.config.ts"))
    if eslint_cfg or "eslintConfig" in pkg:
        out.append(Candidate("lint", "eslint", "npx --no-install eslint .", "eslint config", "eslint"))
    if (root / "tsconfig.json").is_file():
        out.append(Candidate("types", "tsc", "npx --no-install tsc --noEmit", "tsconfig.json", "tsc"))

    # ---- go / rust ----
    if (root / "go.mod").is_file():
        out.append(Candidate("lint", "go vet", "go vet ./...", "go.mod", "go"))
        out.append(Candidate("vulnerabilities", "govulncheck", "govulncheck ./...", "go.mod"))
    if (root / "Cargo.toml").is_file():
        out.append(Candidate("lint", "clippy", "cargo clippy -- -D warnings", "Cargo.toml", "cargo"))
        out.append(Candidate("vulnerabilities", "cargo-audit", "cargo audit", "Cargo.toml", "cargo-audit"))

    # ---- dependency vulnerabilities ----
    if (root / "package-lock.json").is_file() or (root / "pnpm-lock.yaml").is_file():
        out.append(Candidate("vulnerabilities", "npm audit", "npm audit --audit-level=high",
                             "lockfile", "npm"))
    if any((root / n).is_file() for n in ("requirements.txt", "poetry.lock", "uv.lock")) or \
            (pp.is_file() and _has_section(pp, "dependencies")):
        out.append(Candidate("vulnerabilities", "pip-audit", "pip-audit", "python dependencies"))
    return out


def plan(root: Path, kinds: tuple[str, ...] = KINDS) -> dict[str, Candidate | None]:
    """The first configured candidate per kind, or None if nothing is configured."""
    chosen: dict[str, Candidate | None] = dict.fromkeys(kinds)
    for c in candidates(root):
        if c.kind in chosen and chosen[c.kind] is None:
            chosen[c.kind] = c
    return chosen


def run(root: Path, kinds: tuple[str, ...] = KINDS, timeout: int = 600) -> list[Run]:
    root = Path(root).resolve()
    out: list[Run] = []
    for kind, candidate in plan(root, kinds).items():
        if candidate is None:
            out.append(Run.not_run("", f"no {kind} tool is configured for this project", kind))
            continue
        binary = candidate.resolved_binary(root)
        if binary is None:
            out.append(Run.not_run(
                candidate.command,
                f"{candidate.tool} is configured ({candidate.evidence}) but is not installed — "
                f"this is a broken setup, not a pass",
                kind))
            continue
        run_result = execute(kind, candidate.command, root, timeout=timeout)
        run_result.name = kind
        out.append(run_result)
    return out
