"""Environment and secret management.

Two jobs: know which variables the code actually needs, and make sure a real
value never lands in a file that gets committed. Values are read from the
environment at use time and are never written anywhere by NEXUS.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .symbols import iter_text_files

PLACEHOLDER = "<set-me>"

# How each ecosystem asks for a variable.
USAGE_PATTERNS = [
    re.compile(r"""os\.environ(?:\.get)?\[?\(?\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""),
    re.compile(r"""os\.getenv\(\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""),
    re.compile(r"""process\.env\.([A-Z][A-Z0-9_]{2,})"""),
    re.compile(r"""process\.env\[\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""),
    re.compile(r"""System\.getenv\(\s*"([A-Z][A-Z0-9_]{2,})"""),
    re.compile(r"""ENV\[\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""),
    re.compile(r"""getenv\(\s*['"]([A-Z][A-Z0-9_]{2,})['"]"""),
    re.compile(r"""\$\{([A-Z][A-Z0-9_]{2,})\}"""),          # compose / shell
]

# A variable declared for production is not declared for development. Unioning
# every .env* file reports a clean bill of health for an environment that would
# actually fail at boot — a false pass, which is the one answer worth preventing.
ENVIRONMENTS: dict[str, tuple[str, ...]] = {
    "dev": (".env", ".env.local", ".env.development"),
    "staging": (".env", ".env.local", ".env.staging"),
    "prod": (".env", ".env.local", ".env.production"),
}
DEFAULT_ENVIRONMENT = "dev"
ENV_FILE_GLOBS = tuple(dict.fromkeys(f for files in ENVIRONMENTS.values() for f in files))
KEY_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=")


@dataclass
class EnvReport:
    used_in_code: dict[str, list[str]]     # var -> files that read it
    declared: set[str]                     # keys present in THIS environment's files
    in_example: set[str]                   # keys present in .env.example
    present_in_process: set[str]
    environment: str = DEFAULT_ENVIRONMENT
    declared_elsewhere: set[str] = field(default_factory=set)  # defined, but for another env

    @property
    def missing_from_example(self) -> set[str]:
        return (set(self.used_in_code) | self.declared) - self.in_example

    @property
    def undeclared(self) -> set[str]:
        """Read by the code but defined nowhere, for any environment. A variable
        declared only for production is not 'declared nowhere' — it has its own
        bucket, so each name is reported once, under the heading that is true."""
        return (set(self.used_in_code) - self.declared
                - self.declared_elsewhere - self.in_example)

    @property
    def missing_for_this_environment(self) -> set[str]:
        """Declared for some other environment, not for this one. Reported separately
        because 'it works on staging' is the symptom this catches."""
        return (set(self.used_in_code) & self.declared_elsewhere) - self.declared

    @property
    def unused(self) -> set[str]:
        return (self.declared | self.in_example) - set(self.used_in_code)

    @property
    def missing_at_runtime(self) -> set[str]:
        return set(self.used_in_code) - self.present_in_process


def scan_usage(root: Path) -> dict[str, list[str]]:
    root = Path(root)
    found: dict[str, list[str]] = {}
    for p in iter_text_files(root):
        if p.name.startswith(".env"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(root))
        for rx in USAGE_PATTERNS:
            for var in rx.findall(text):
                found.setdefault(var, [])
                if rel not in found[var]:
                    found[var].append(rel)
    return dict(sorted(found.items()))


def keys_in_env_files(root: Path, environment: str = DEFAULT_ENVIRONMENT) -> set[str]:
    """Key names only, for one environment's file cascade. Values are never read."""
    keys: set[str] = set()
    root = Path(root)
    for name in ENVIRONMENTS.get(environment, ENVIRONMENTS[DEFAULT_ENVIRONMENT]):
        f = root / name
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = KEY_LINE.match(line)
            if m:
                keys.add(m.group(1))
    return keys


def keys_in_example(root: Path) -> set[str]:
    f = Path(root) / ".env.example"
    if not f.is_file():
        return set()
    return {m.group(1) for line in f.read_text(encoding="utf-8", errors="replace").splitlines()
            if (m := KEY_LINE.match(line))}


def report(root: Path, environ: dict | None = None,
           environment: str = DEFAULT_ENVIRONMENT) -> EnvReport:
    if environment not in ENVIRONMENTS:
        raise ValueError(f"unknown environment {environment!r}: "
                         f"expected one of {', '.join(sorted(ENVIRONMENTS))}")
    env = environ if environ is not None else os.environ
    used = scan_usage(root)
    here = keys_in_env_files(root, environment)
    everywhere: set[str] = set()
    for name in ENVIRONMENTS:
        everywhere |= keys_in_env_files(root, name)
    return EnvReport(used_in_code=used, declared=here,
                     in_example=keys_in_example(root),
                     present_in_process={k for k in used if k in env},
                     environment=environment, declared_elsewhere=everywhere - here)


def render_example(rep: EnvReport) -> str:
    """Keys and placeholders. By construction this function has no access to a value."""
    keys = sorted(set(rep.used_in_code) | rep.declared | rep.declared_elsewhere
                  | rep.in_example)
    lines = [
        "# Generated by `nexus env --write`. Keys only — never real values.",
        "# Copy to .env and fill in. .env must stay out of version control.",
        "",
    ]
    for k in keys:
        where = rep.used_in_code.get(k)
        if where:
            lines.append(f"# used in: {', '.join(where[:3])}" + (" …" if len(where) > 3 else ""))
        lines.append(f"{k}={PLACEHOLDER}")
        lines.append("")
    return "\n".join(lines)


def write_example(root: Path, rep: EnvReport) -> Path:
    """The only file this module writes, in any environment. There is no code path
    here that writes a real .env — production config is not NEXUS's to touch."""
    path = Path(root) / ".env.example"
    path.write_text(render_example(rep), encoding="utf-8")
    return path


def gitignore_protects_env(root: Path) -> bool:
    f = Path(root) / ".gitignore"
    if not f.is_file():
        return False
    lines = {line.strip() for line in f.read_text(encoding="utf-8", errors="replace").splitlines()}
    return bool(lines & {".env", ".env*", "*.env", ".env.local"})
