"""Engineering gates: what must be true before an edit, and after it.

The one rule this module exists to enforce: **a test is never reported as
passing unless its output was captured.** `TestRun` cannot be constructed
claiming success with an empty log, so no code path — not even a careless
one added later — can fabricate a green run.
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from . import apishape, checks as checks_mod, discover, migrations, roles, scrub
from .evidence import Run, execute
from .impact import Impact, analyze
from .store import Store

PLANS_DIR = "plans"


# --------------------------------------------------------------------------
# test execution
# --------------------------------------------------------------------------

@dataclass
class TestRun(Run):
    """A test run. The honesty invariant lives in `evidence.Run`."""

    name: str = "tests"

    @classmethod
    def not_run(cls, command: str, reason: str, name: str = "tests") -> TestRun:
        return cls(command=command, exit_code=None, log=reason, name=name, reason=reason)

    def summary(self) -> str:
        if not self.ran:
            return f"tests NOT RUN — {self.log}"
        state = "PASSED" if self.passed else f"FAILED (exit {self.exit_code})"
        return f"`{self.command}` {state} in {self.duration_s:.1f}s"


def run_tests(root: Path, command: str | None = None, timeout: int = 900,
              shell: bool = False) -> TestRun:
    """Run the project's tests.

    `shell` is opt-in and exists only for a command a human typed with a pipe
    or `&&` in it. The *detected* command is never run through a shell: it is
    built from repository contents, and that is an injection vector.
    """
    cmd = command or discover.profile(root).get("test_command") or ""
    if not cmd:
        return TestRun.not_run("", "no test command detected for this project")
    run = execute("tests", cmd, root, timeout=timeout, shell=shell and command is not None)
    return TestRun(run.command, run.exit_code, run.log, run.duration_s, "tests", run.reason)


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
        if len(line) <= 3:
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:          # rename
            path = path.split(" -> ")[-1]
        # git reports a wholly-untracked directory as the directory itself.
        # Left unexpanded, every file inside it is invisible to the gate.
        full = Path(root) / path
        if path.endswith("/") or full.is_dir():
            files += [str(f.relative_to(root)) for f in sorted(full.rglob("*"))
                      if f.is_file() and ".git" not in f.parts]
        else:
            files.append(path)
    return sorted(set(files))


def diff_text(root: Path, staged: bool = False) -> str:
    code, out = _git(root, "diff", "--cached") if staged else _git(root, "diff", "HEAD")
    return out if code == 0 else ""


def staged_files(root: Path) -> list[str]:
    code, out = _git(root, "diff", "--cached", "--name-only")
    return sorted(line.strip() for line in out.splitlines() if line.strip()) if code == 0 else []


def untracked_files(root: Path) -> list[str]:
    code, out = _git(root, "ls-files", "--others", "--exclude-standard")
    return sorted(line.strip() for line in out.splitlines() if line.strip()) if code == 0 else []


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


def scan_diff(root: Path, staged: bool = False) -> tuple[list[dict], list[dict]]:
    """Returns (blocking, allowed) credential findings in everything this change adds."""
    rules = load_allowlist(root)
    blocking, allowed = [], []

    added_by_file = added_lines_by_file(diff_text(root, staged=staged))
    # A brand-new file never appears in a diff, and a new file is the likeliest
    # place for a hardcoded credential. Treat all of it as added.
    staged_set = set(staged_files(root)) if staged else None
    for rel in untracked_files(root):
        if staged_set is not None and rel not in staged_set:
            continue
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
        for r in self.roles:
            lines.append(f"- **{r['name']}** — {r['why']}")
            if r.get("brief"):
                lines.append(f"  {r['brief']}")
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


def load_plan(root: Path, plan_id: str | None = None) -> Plan | None:
    """A named plan, or the most recent one."""
    p = plans_dir(root) / (f"{plan_id}.json" if plan_id else "latest.json")
    if not p.exists():
        return None
    try:
        return Plan(**json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError):
        return None


def list_plans(root: Path) -> list[dict]:
    out = []
    for f in sorted(plans_dir(root).glob("*.json")):
        if f.stem == "latest":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({"id": data.get("id", f.stem), "created_at": data.get("created_at", ""),
                    "targets": data.get("targets", []), "gear": data.get("gear", "")})
    return sorted(out, key=lambda d: d["created_at"], reverse=True)


def load_latest_plan(root: Path) -> Plan | None:
    return load_plan(root)


def find_adr(root: Path, targets: list[str]) -> str | None:
    """An ADR counts only if it names a target as a *path*.

    Matching on the bare stem was far too loose: an ADR discussing "the store"
    satisfied any change to `store.py`. A decision record that does not name
    the file it governs is not a decision record for that file.
    """
    adr_dir = Path(root) / "docs" / "adr"
    if not adr_dir.is_dir():
        return None
    wanted = set()
    for t in targets:
        wanted.add(t)                       # src/db/schema.sql
        wanted.add(Path(t).name)            # schema.sql — still has the extension
    wanted.discard("")
    for f in sorted(adr_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if any(w in text for w in wanted):
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

    role_list = [{"name": r.name, "why": r.why, "brief": r.brief}
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
    checks: list[Run] = field(default_factory=list)
    breaking: list[dict] = field(default_factory=list)
    dead_code: list[dict] = field(default_factory=list)
    migrations: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def failed_checks(self) -> list[Run]:
        return [c for c in self.checks if c.ran and not c.passed]

    @property
    def unhandled_breaks(self) -> list[dict]:
        """Breaking changes whose callers were not touched in this change."""
        touched = set(self.changed)
        return [b for b in self.breaking if set(b.get("callers") or []) - touched]

    @property
    def status(self) -> str:
        if self.secrets:
            return "BLOCKED"
        if (self.tests.ran and not self.tests.passed) or self.failed_checks:
            return "FAIL"
        if not self.tests.ran:
            return "UNVERIFIED"
        if self.unintended or self.breaking:
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
        if self.breaking:
            lines += ["", f"## Breaking API changes ({len(self.breaking)})"]
            for b in self.breaking:
                callers = b.get("callers") or []
                untouched = sorted(set(callers) - set(self.changed))
                lines.append(f"- **{b['symbol']}** — {b['change']}: {b['why']}")
                lines.append(f"  before: `{b['before']}`" + (f"  after: `{b['after']}`" if b["after"] else ""))
                if callers:
                    lines.append(f"  callers: {', '.join(callers)}"
                                 + (f"  — **{len(untouched)} not updated here**" if untouched else
                                    " — all updated in this change"))
                else:
                    lines.append("  callers: none found (graph may be stale)")

        lines += ["", "## Tests", f"{self.tests.summary()}"]
        if self.tests.ran and not self.tests.passed:
            lines += ["", "```", self.tests.tail(), "```"]

        if self.checks:
            lines += ["", "## Static checks"]
            for c in self.checks:
                lines.append(f"- {c.summary()}")
                if c.ran and not c.passed:
                    lines += ["", "  ```", *(f"  {ln}" for ln in c.tail(15).splitlines()), "  ```"]
        if self.dead_code:
            lines += ["", f"## Added but unreferenced ({len(self.dead_code)})"]
            lines += [f"- `{d['symbol']}` in {d['file']} — {d['why']}" for d in self.dead_code]

        m = self.migrations or {}
        if m.get("destructive") or m.get("history"):
            lines += ["", "## Migrations"]
            for h in m.get("history", []):
                lines.append(f"- **history**: {h}")
            for d in m.get("destructive", []):
                lines.append(f"- **{d['rule']}** in {d['file']} — {d['why']}")
            lines.append("  (advisory — NEXUS does not run migrations)")

        if self.notes:
            lines += ["", "## Notes"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines) + "\n"


def detect_breaking(root: Path, changed: list[str], ref: str = "HEAD") -> list[dict]:
    """Breaking API changes in this diff, with the callers that would feel them."""
    from .impact import analyze
    out: list[dict] = []
    for rel in changed:
        for item in apishape.breaking_changes(root, rel, ref=ref):
            item["file"] = rel
            symbol = item["symbol"].split(".")[0]
            try:
                imp = analyze(root, symbol if item["kind"] != "module" else rel, depth=2)
                item["callers"] = sorted({d.file for d in imp.dependents if d.strength == "strong"})
            except Exception:
                item["callers"] = []
            out.append(item)
    return out


ENTRY_POINT_NAMES = {"main", "run", "app", "handler", "setup", "cli", "__init__"}


def _occurrences(root: Path, name: str) -> int:
    from . import symbols
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    total = 0
    for f in symbols.iter_text_files(Path(root)):
        try:
            total += len(pattern.findall(f.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
        if total > 1:
            return total
    return total


def detect_dead_code(root: Path, changed: list[str], ref: str = "HEAD") -> list[dict]:
    """Public symbols this change *adds* that nothing anywhere mentions.

    Text evidence, deliberately, not the graph. A symbol added in this change
    cannot be in a graph built from committed code, so asking the graph would
    answer "unknown" every time. A name that appears nowhere else in the
    repository is genuinely unreferenced — the one question a plain text search
    answers more reliably than a parser.

    Narrowed to newly added symbols, because flagging every unreferenced public
    name produces a wall of noise, and a wall of noise is ignored.

    shortcut: blind to dynamic access (getattr, plugin registries, template
    lookups); upgrade when a project is found that relies on those.
    """
    out: list[dict] = []
    for rel in changed:
        if Path(rel).suffix not in apishape.PARSEABLE:
            continue
        path = root / rel
        if not path.exists():
            continue
        before = set(apishape.shape(apishape.committed_source(root, rel, ref) or ""))
        after = apishape.shape(path.read_text(encoding="utf-8", errors="replace"))
        for name in sorted(set(after) - before):
            short = name.split(".")[-1]
            if short in ENTRY_POINT_NAMES or short.startswith("test_") or short.startswith("__"):
                continue
            # Count every occurrence, including inside the defining file: a
            # symbol used by its own module is used. The definition itself is
            # one occurrence, so anything above one is a real reference.
            if _occurrences(root, short) <= 1:
                out.append({"file": rel, "symbol": name,
                            "why": "added by this change and referenced nowhere in the repository"})
    return out


def post_edit(root: Path, plan: Plan | None = None, test_command: str | None = None,
              run: bool = True, run_checks: bool = True, ref: str = "HEAD",
              plan_id: str | None = None, staged: bool = False,
              shell: bool = False) -> Verdict:
    root = Path(root).resolve()
    plan = plan or load_plan(root, plan_id)
    changed = staged_files(root) if staged else changed_files(root)
    expected = set(plan.targets) if plan else set()
    # Files NEXUS wrote itself are not the author's unintended changes.
    unintended = sorted(f for f in changed
                        if f not in expected and not f.startswith(".nexus/"))

    findings, allowed = scan_diff(root, staged=staged)

    tests = (run_tests(root, test_command, shell=shell) if run
             else TestRun.not_run(test_command or "", "test execution was skipped (--no-tests)"))

    static = checks_mod.run(root) if run_checks else []
    breaking = detect_breaking(root, changed, ref=ref)
    dead = detect_dead_code(root, changed, ref=ref) if run_checks else []
    migration_report = migrations.validate(root, only=changed)

    notes: list[str] = []
    if plan and plan.blocked:
        notes.append(f"the plan was blocked on a missing ADR ({plan.adr_reason})")
    missing = sorted(set(expected) - set(changed))
    if missing:
        notes.append(f"planned but not changed: {', '.join(missing)}")

    if allowed:
        notes.append(f"{len(allowed)} credential-shaped string(s) allowed by .nexus/secret-allowlist")

    verdict = Verdict(plan_id=plan.id if plan else None, changed=changed,
                      unintended=unintended, secrets=findings, tests=tests,
                      allowed_secrets=allowed, checks=static, breaking=breaking,
                      dead_code=dead, migrations=migration_report, notes=notes)
    unhandled = verdict.unhandled_breaks
    if unhandled:
        notes.append(f"{len(unhandled)} breaking change(s) have callers that were not "
                     f"updated in this change")
    return verdict


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
