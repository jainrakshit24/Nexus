"""Engineering gates: what must be true before an edit, and after it.

The one rule this module exists to enforce: **a test is never reported as
passing unless its output was captured.** `TestRun` cannot be constructed
claiming success with an empty log, so no code path — not even a careless
one added later — can fabricate a green run.
"""
from __future__ import annotations

import fnmatch
import json
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from . import discover, roles, scrub
from .impact import Impact, analyze
from .store import Store

PLANS_DIR = "plans"


# --------------------------------------------------------------------------
# test execution
# --------------------------------------------------------------------------

@dataclass
class TestRun:
    __test__ = False  # it is a result record, not a pytest test class

    command: str
    exit_code: int | None     # None means: never ran
    log: str
    duration_s: float = 0.0

    def __post_init__(self):
        # The honesty invariant. A zero exit with nothing captured is not
        # evidence of anything, so it cannot be represented at all.
        if self.exit_code == 0 and not self.log.strip():
            raise ValueError(
                "refusing to record a passing test run with no captured output — "
                "a pass without evidence is not a pass"
            )

    @classmethod
    def not_run(cls, command: str, reason: str) -> "TestRun":
        return cls(command=command, exit_code=None, log=reason)

    @property
    def ran(self) -> bool:
        return self.exit_code is not None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and bool(self.log.strip())

    def summary(self) -> str:
        if not self.ran:
            return f"tests NOT RUN — {self.log}"
        state = "PASSED" if self.passed else f"FAILED (exit {self.exit_code})"
        return f"`{self.command}` {state} in {self.duration_s:.1f}s"

    def tail(self, lines: int = 25) -> str:
        return "\n".join(self.log.strip().splitlines()[-lines:])


def run_tests(root: Path, command: str | None = None, timeout: int = 900) -> TestRun:
    cmd = command or discover.profile(root).get("test_command") or ""
    if not cmd:
        return TestRun.not_run("", "no test command detected for this project")
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=root, shell=True, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return TestRun(cmd, exit_code=124, log=f"timed out after {timeout}s",
                       duration_s=time.perf_counter() - t0)
    except OSError as e:
        return TestRun.not_run(cmd, f"could not start the test command: {e}")
    log = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0 and not log.strip():
        # A silent success is indistinguishable from a command that did nothing.
        return TestRun(cmd, exit_code=proc.returncode,
                       log="(command exited 0 but produced no output — treated as no evidence)",
                       duration_s=time.perf_counter() - t0)
    return TestRun(cmd, proc.returncode, log, time.perf_counter() - t0)


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def _git(root: Path, *args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def changed_files(root: Path) -> list[str]:
    """Files different from HEAD, staged or not, plus untracked ones."""
    code, out = _git(root, "status", "--porcelain")
    if code != 0:
        return []
    files = []
    for line in out.splitlines():
        if len(line) > 3:
            path = line[3:].strip().strip('"')
            if " -> " in path:          # rename
                path = path.split(" -> ")[-1]
            files.append(path)
    return sorted(set(files))


def diff_text(root: Path) -> str:
    code, out = _git(root, "diff", "HEAD")
    return out if code == 0 else ""


def untracked_files(root: Path) -> list[str]:
    code, out = _git(root, "ls-files", "--others", "--exclude-standard")
    return sorted(l.strip() for l in out.splitlines() if l.strip()) if code == 0 else []


def added_lines_by_file(diff: str) -> dict[str, str]:
    """Only the lines this change *adds*, grouped by file.

    Scanning the whole diff flags credentials that were already there, or
    that are being deleted. Neither is this change's doing.
    """
    out: dict[str, list[str]] = {}
    current = ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" b/", 1)
            current = parts[1].strip() if len(parts) == 2 else ""
        elif line.startswith("+++ b/"):
            current = line[6:].strip()
        elif line.startswith("+") and not line.startswith("+++") and current:
            out.setdefault(current, []).append(line[1:])
    return {f: "\n".join(lines) for f, lines in out.items()}


ALLOWLIST_FILE = "secret-allowlist"


def load_allowlist(root: Path) -> list[tuple[str, str]]:
    """`<pattern-name> <path-glob>` per line. Known-benign matches, e.g. test fixtures.

    Entries never hide a finding — they move it from blocking to a note, so a
    reviewer still sees it and can see why it was allowed.
    """
    f = Path(root) / ".nexus" / ALLOWLIST_FILE
    if not f.is_file():
        return []
    rules = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            rules.append((parts[0], parts[1]))
    return rules


def scan_diff(root: Path) -> tuple[list[dict], list[dict]]:
    """Returns (blocking, allowed) credential findings in everything this change adds."""
    rules = load_allowlist(root)
    blocking, allowed = [], []

    added_by_file = added_lines_by_file(diff_text(root))
    # A brand-new file never appears in `git diff HEAD`, and a new file is the
    # likeliest place for a hardcoded credential. Treat all of it as added.
    for rel in untracked_files(root):
        if rel.startswith(".nexus/"):
            continue
        f = Path(root) / rel
        try:
            if f.is_file() and f.stat().st_size < 2_000_000:
                added_by_file[rel] = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

    for file, added in added_by_file.items():
        for f in scrub.scan(added):
            if f.severity != "secret":
                continue
            item = {"pattern": f.pattern, "excerpt": f.excerpt, "file": file}
            if any(f.pattern == name and fnmatch.fnmatch(file, glob) for name, glob in rules):
                allowed.append(item)
            else:
                blocking.append(item)
    return blocking, allowed


# --------------------------------------------------------------------------
# pre-edit gate
# --------------------------------------------------------------------------

@dataclass
class Plan:
    targets: list[str]
    gear: str
    reasons: list[str]
    roles: list[dict]
    blast_radius: int
    dependents: list[str]
    tests_to_run: list[str]
    memories: list[dict]
    adr_required: bool
    adr_reason: str
    adr_found: str | None
    risks: list[str]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = self.created_at.replace(":", "").replace("-", "")[:15]

    @property
    def blocked(self) -> bool:
        return self.adr_required and not self.adr_found

    def render(self) -> str:
        lines = [f"# Plan {self.id}", "",
                 f"**Targets:** {', '.join(self.targets)}",
                 f"**Workflow:** {self.gear}  ({'; '.join(self.reasons)})",
                 f"**Blast radius:** {self.blast_radius}", "",
                 "## Roles"]
        lines += [f"- **{r['name']}** — {r['why']}" for r in self.roles]
        lines += ["", "## Dependents that must keep working"]
        lines += [f"- {d}" for d in self.dependents] or ["- none found"]
        lines += ["", "## Tests covering this change"]
        lines += [f"- {t}" for t in self.tests_to_run] or ["- none found — write one before editing"]
        if self.memories:
            lines += ["", "## What we already know"]
            lines += [f"- **{m['name']}** [{m['confidence']}]: {m['body']}" for m in self.memories]
        if self.risks:
            lines += ["", "## Risks"] + [f"- {r}" for r in self.risks]
        lines += ["", "## Architecture decision record"]
        if not self.adr_required:
            lines.append("- not required for this change")
        elif self.adr_found:
            lines.append(f"- satisfied by `{self.adr_found}`")
        else:
            lines.append(f"- **REQUIRED and MISSING** — {self.adr_reason}")
            lines.append("- run `nexus adr new \"<title>\"` before editing")
        return "\n".join(lines) + "\n"


def plans_dir(root: Path) -> Path:
    return Path(root) / ".nexus" / PLANS_DIR


def save_plan(root: Path, plan: Plan) -> Path:
    d = plans_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{plan.id}.json").write_text(json.dumps(asdict(plan), indent=2), encoding="utf-8")
    path = d / f"{plan.id}.md"
    path.write_text(plan.render(), encoding="utf-8")
    (d / "latest.json").write_text(json.dumps(asdict(plan), indent=2), encoding="utf-8")
    return path


def load_latest_plan(root: Path) -> Plan | None:
    p = plans_dir(root) / "latest.json"
    if not p.exists():
        return None
    try:
        return Plan(**json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError):
        return None


def find_adr(root: Path, targets: list[str]) -> str | None:
    """An ADR counts only if it names one of the targets."""
    adr_dir = Path(root) / "docs" / "adr"
    if not adr_dir.is_dir():
        return None
    stems = {Path(t).stem for t in targets} | {t for t in targets}
    for f in sorted(adr_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if any(s and s in text for s in stems):
            return str(f.relative_to(root))
    return None


def pre_edit(root: Path, targets: list[str], depth: int = 2) -> Plan:
    root = Path(root).resolve()
    store = Store(root)
    impacts: list[Impact] = [analyze(root, t, depth=depth) for t in targets]

    gear = "full" if any(i.gear == "full" for i in impacts) else "light"
    reasons = [f"{i.target}: {i.reason()}" for i in impacts]
    blast = max((i.blast_radius for i in impacts), default=0)
    dependents = sorted({d.file for i in impacts for d in i.dependents if d.strength != "weak"})
    tests = sorted({f for i in impacts for f in i.test_files})

    risks: list[str] = []
    for i in impacts:
        if i.staleness and i.staleness.is_stale:
            risks.append(f"knowledge graph is stale ({i.staleness.summary()}) — dependents may be incomplete")
            break
    if not tests:
        risks.append("no test covers these files; a regression here is invisible")
    for t in targets:
        if not (root / t).exists():
            risks.append(f"{t} does not exist yet — this is a new file")

    new_files = [t for t in targets if not (root / t).exists()]
    required, adr_reason = roles.needs_adr(targets, new_files)
    adr_found = find_adr(root, targets) if required else None

    mems = []
    for m in store.recall(" ".join(targets) + " " + " ".join(Path(t).stem for t in targets), limit=5):
        body = Path(m["path"]).read_text(encoding="utf-8").split("---", 2)[-1].strip()
        mems.append({"name": m["name"], "confidence": m["confidence"], "body": body[:400]})

    role_list = [{"name": r.name, "why": r.why}
                 for r in roles.route(targets, blast, bool(tests), gear, new_files)]

    return Plan(targets=targets, gear=gear, reasons=reasons, roles=role_list,
                blast_radius=blast, dependents=dependents, tests_to_run=tests,
                memories=mems, adr_required=required, adr_reason=adr_reason,
                adr_found=adr_found, risks=risks)


# --------------------------------------------------------------------------
# post-edit gate
# --------------------------------------------------------------------------

@dataclass
class Verdict:
    plan_id: str | None
    changed: list[str]
    unintended: list[str]
    secrets: list[dict]
    tests: TestRun
    allowed_secrets: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.secrets:
            return "BLOCKED"
        if self.tests.ran and not self.tests.passed:
            return "FAIL"
        if not self.tests.ran:
            return "UNVERIFIED"
        if self.unintended:
            return "REVIEW"
        return "PASS"

    def render(self) -> str:
        lines = [f"# Post-edit gate: {self.status}", ""]
        if self.plan_id:
            lines.append(f"Checked against plan `{self.plan_id}`.")
        else:
            lines.append("No plan on record — every changed file counts as unintended.")
        lines += ["", f"## Changed files ({len(self.changed)})"] + [f"- {f}" for f in self.changed]
        if self.unintended:
            lines += ["", f"## Changed but not in the plan ({len(self.unintended)})"]
            lines += [f"- {f}" for f in self.unintended]
        if self.secrets:
            lines += ["", "## Credentials added by this change — this blocks it"]
            lines += [f"- {s['file']}: {s['pattern']} ({s['excerpt']})" for s in self.secrets]
        if self.allowed_secrets:
            lines += ["", "## Credential-shaped strings allowed by `.nexus/secret-allowlist`"]
            lines += [f"- {s['file']}: {s['pattern']} ({s['excerpt']})" for s in self.allowed_secrets]
        lines += ["", "## Tests", f"{self.tests.summary()}"]
        if self.tests.ran and not self.tests.passed:
            lines += ["", "```", self.tests.tail(), "```"]
        if self.notes:
            lines += ["", "## Notes"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines) + "\n"


def post_edit(root: Path, plan: Plan | None = None, test_command: str | None = None,
              run: bool = True) -> Verdict:
    root = Path(root).resolve()
    plan = plan or load_latest_plan(root)
    changed = changed_files(root)
    expected = set(plan.targets) if plan else set()
    # Files NEXUS wrote itself are not the author's unintended changes.
    unintended = sorted(f for f in changed
                        if f not in expected and not f.startswith(".nexus/"))

    findings, allowed = scan_diff(root)

    tests = (run_tests(root, test_command) if run
             else TestRun.not_run(test_command or "", "test execution was skipped (--no-tests)"))

    notes: list[str] = []
    if plan and plan.blocked:
        notes.append(f"the plan was blocked on a missing ADR ({plan.adr_reason})")
    missing = sorted(set(expected) - set(changed))
    if missing:
        notes.append(f"planned but not changed: {', '.join(missing)}")

    if allowed:
        notes.append(f"{len(allowed)} credential-shaped string(s) allowed by .nexus/secret-allowlist")

    return Verdict(plan_id=plan.id if plan else None, changed=changed,
                   unintended=unintended, secrets=findings, tests=tests,
                   allowed_secrets=allowed, notes=notes)


def revert_unintended(root: Path, files: list[str], confirm) -> list[str]:
    """Discard changes to files the plan did not name. Destructive — always asks.

    `confirm` is injected so this is testable and so no caller can skip it.
    """
    if not files:
        return []
    if not confirm(files):
        return []
    reverted = []
    for f in files:
        code, _ = _git(root, "checkout", "--", f)
        if code == 0:
            reverted.append(f)
    return reverted
