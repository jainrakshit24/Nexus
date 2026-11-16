"""Secret values: read at the moment of use, never stored.

NEXUS holds variable *names*. Values live in the operating system's own store
and are fetched when something actually needs one. Nothing here writes a
secret anywhere, and nothing here returns one to a caller that is going to put
it in a memory record — `envman` and `store` deal only in names.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass

from .evidence import execute

# Each backend: the binary, and the argv that prints one secret to stdout.
BACKENDS = [
    ("secret-tool", lambda key: ["secret-tool", "lookup", "service", "nexus", "key", key]),
    ("pass", lambda key: ["pass", "show", key]),
    ("security", lambda key: ["security", "find-generic-password", "-s", key, "-w"]),
]


@dataclass
class Backend:
    name: str
    available: bool
    note: str


def backends() -> list[Backend]:
    out = []
    for name, _argv in BACKENDS:
        found = shutil.which(name)
        out.append(Backend(name, found is not None,
                           found or "not installed"))
    return out


def available() -> list[str]:
    return [b.name for b in backends() if b.available]


def get(key: str, backend: str | None = None, cwd: str = ".") -> tuple[str | None, str]:
    """Fetch one secret. Returns (value, source). Never caches, never logs it.

    The value is returned to the caller and nowhere else. If no backend holds
    it, the answer is None and the reason — never a placeholder that a caller
    might mistake for a real credential.
    """
    for name, argv in BACKENDS:
        if backend and name != backend:
            continue
        if not shutil.which(name):
            continue
        run = execute(f"secret:{name}", argv(key), cwd, timeout=20)
        if run.exit_code == 0 and run.log.strip():
            return run.log.strip().splitlines()[0], name
    if not available():
        return None, "no secret store found (looked for secret-tool, pass, security)"
    return None, f"{key} is not in {', '.join(available())}"
