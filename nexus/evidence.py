"""The shared rule for anything that claims a check succeeded.

Phase 3 established it for test runs: a zero exit with nothing captured is not
evidence, so it cannot be represented at all. Phase 6 adds linters, type
checkers, vulnerability scanners and API diffs — every one of which could
otherwise invent a green result. They all build on this.

A fourth state matters as much as pass/fail: **not configured**. A project with
no type checker has not passed type checking, and saying so is the difference
between a useful gate and a decorative one.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass


@dataclass
class Run:
    """One check, with the evidence it produced."""

    __test__ = False  # a result record, not a pytest test class

    command: str
    exit_code: int | None      # None means: it never ran
    log: str
    duration_s: float = 0.0
    name: str = "check"
    reason: str = ""           # why it did not run, when it did not

    def __post_init__(self):
        if self.exit_code == 0 and not self.log.strip():
            raise ValueError(
                f"refusing to record a passing {self.name} with no captured output — "
                "a pass without evidence is not a pass"
            )

    @classmethod
    def not_run(cls, command: str, reason: str, name: str = "check") -> Run:
        return cls(command=command, exit_code=None, log=reason, name=name, reason=reason)

    @property
    def ran(self) -> bool:
        return self.exit_code is not None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and bool(self.log.strip())

    @property
    def status(self) -> str:
        if not self.ran:
            return "not-run"
        return "pass" if self.passed else "fail"

    def summary(self) -> str:
        if not self.ran:
            return f"{self.name}: NOT RUN — {self.log}"
        state = "PASSED" if self.passed else f"FAILED (exit {self.exit_code})"
        return f"{self.name}: `{self.command}` {state} in {self.duration_s:.1f}s"

    def tail(self, lines: int = 25) -> str:
        return "\n".join(self.log.strip().splitlines()[-lines:])


def execute(name: str, command: str | list[str], cwd, timeout: int = 600,
            shell: bool = False) -> Run:
    """Run a command and capture everything it said.

    **No shell by default.** Commands reach this function from repository
    contents — a detected test command, a configured linter — and a directory
    named `a$(id -u)` is enough to turn `shell=True` into arbitrary code
    execution. Callers pass an argv list; `shell=True` is reserved for a
    command a human typed, and the caller must ask for it explicitly.
    """
    argv = command if isinstance(command, list) else (command if shell else shlex.split(command))
    display = command if isinstance(command, str) else shlex.join(command)
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(argv, cwd=cwd, shell=shell, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Run(display, 124, f"timed out after {timeout}s", time.perf_counter() - t0, name)
    except (OSError, ValueError) as e:
        return Run.not_run(display, f"could not start: {e}", name)
    log = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0 and not log.strip():
        # A silent success is indistinguishable from a command that did nothing.
        log = "(exited 0 but produced no output — treated as no evidence)"
    return Run(display, proc.returncode, log, time.perf_counter() - t0, name)
