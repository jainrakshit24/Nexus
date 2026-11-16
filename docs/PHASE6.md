# Phase 6 — Deeper Verification & Enforcement · COMPLETE (2026-11-17)

Phase 3 built a gate that ran tests and scanned for credentials, and could only
advise. This phase gives it the rest of the checks the brief asked for, and the
ability to say no.

It also began with a self-audit that found a **security defect NEXUS had
introduced itself**. That is fixed here, first.

## The security defect

```
repo directory named:  skills/a$(id -u)/tests
detected test command: pytest skills/a$(id -u)/tests
passed to:             subprocess.run(..., shell=True)
```

`discover.test_command()` built a command out of repository **directory names**,
and `gate.run_tests()` handed it to a shell. Running `nexus verify` on a repo
you did not write was arbitrary code execution — and it was agent-reachable,
because the `nexus_gate` MCP tool runs tests by default.

Three changes close it:

1. `evidence.execute()` no longer uses a shell. Commands are argv lists;
   `shell=True` exists only as an explicit opt-in for a command a human typed.
2. Discovered paths are allowlisted (`^[A-Za-z0-9._/-]+$`). A path carrying
   anything a shell could interpret produces **no command at all**, rather than
   a sanitised one.
3. A detected command is never run through a shell even when `--shell` is
   passed. The flag applies only to `--test-command`.

**15 regression tests** pin this, including six hostile directory names and an
assertion that no module passes `shell=True`.

## What else shipped

| Module | Does |
|---|---|
| `nexus/evidence.py` | The shared no-pass-without-evidence primitive, now used by every checker. Adds a fourth state: **not configured**. |
| `nexus/checks.py` | Lint, type and vulnerability checks run from the project's **own** configuration. NEXUS never installs a tool. Advisory ids extracted from scanner output. |
| `nexus/apishape.py` | Public API shape before and after, and the rules for what actually breaks a caller. |
| `nexus/migrations.py` | Destructive statements and branched history, without a database. Advisory. |
| `nexus/secrets.py` | Read-at-use from `secret-tool`, `pass` or `security`. Writes nothing, anywhere. |
| gate | Dead-code detection, pre-commit enforcement, staged-diff mode, role briefs. |

New: `nexus plan --list`, `verify --plan/--ref/--no-checks/--shell`,
`impact <many targets>`, `env --get/--backends`, `dashboard --trend`,
`install git-hooks`, `hook pre-commit`.

## Acceptance criteria — results

| # | Criterion | Result |
|---|---|---|
| 1 | The gate runs the project's own linter and type checker, and reports "not configured" rather than silently passing | **PASS** — three states, not two. "Configured but not installed" is reported as a broken setup, never as a pass. NEXUS now configures ruff for itself and its own gate reports `lint pass`. |
| 2 | A removed public function is reported as breaking, naming its callers | **PASS** — with the distinction that an optional parameter added is *not* breaking, which is what keeps the check worth reading. |
| 3 | The pre-commit hook blocks FAIL/BLOCKED and can only be bypassed explicitly | **PASS** — four tests: blocks a staged credential, allows a clean change, ignores unstaged work, and never wedges a repo it cannot read. Bypass is `NEXUS_SKIP_GATE=1`. |
| 4 | A vulnerable dependency is reported with its advisory id | **PARTIAL, stated honestly** — extraction of CVE/GHSA/PYSEC/RUSTSEC/OSV ids is implemented and tested. No scanner is installed on this machine, so the **live** path is untested, exactly as `COMPATIBILITY.md` treats untested hosts. |
| 5 | An ADR must name the path, not merely contain the word | **PASS** — "How we think about the store" no longer satisfies a change to `store.py`. |
| 6 | No check reports success without captured evidence | **PASS** — the invariant moved into `evidence.Run`, so every checker added later inherits it. |
| 7 | Everything green | **PASS** — **291 tests**, and `ruff check` clean. |

## Defects found and fixed in this phase

1. **Command injection** (above). Found by auditing, not by a test.
2. **An untracked directory hid every file inside it.** `git status --porcelain`
   reports a wholly-new directory as the directory; the gate never looked
   inside. A new `migrations/` folder was invisible to secret scanning and to
   every other per-file check.
3. **Dead-code detection asked the wrong oracle.** It consulted the graph — but
   a symbol added in this change cannot be in a graph built from committed
   code, so the answer was always "unknown". Rewritten to count occurrences in
   text, which is the one question a plain search answers better than a parser.
   On this repo it went from **17 false positives to 1 true positive**: a
   `list_plans` function that had been written and never wired to a command.
4. **`scrub._excerpt(text, match)` had a dead parameter**, found by the linter
   the moment NEXUS started linting itself.
5. **Staleness fired on `touch`.** It compared mtime, so a checkout, a rebuild
   or a formatter run marked verified facts stale. Now it compares a content
   digest recorded at verification. (Phase 5 carryover, fixed here.)
6. **`graph.resolve` silently merged files with the same basename.** In a
   monorepo `utils.py` matched several modules and their dependents were pooled.
   It now returns `ambiguous` and impact withholds graph evidence rather than
   guessing.

## What this phase deliberately did not claim

- **Role "invocation" is role *briefing*.** NEXUS cannot spawn a host's
  subagents. It states precisely what each role is responsible for, in the plan
  the agent is already reading. Calling that "invocation" would be inventing a
  capability.
- **Migration validation does not run migrations**, and says so in its output.
- **Vulnerability scanning is untested live** — see AC4.

## Known limits

- Dead-code detection is blind to dynamic access (`getattr`, plugin registries,
  template lookups). Marked in the code as a shortcut with its upgrade trigger.
- Breaking-change detection is Python-only. Other languages report nothing,
  which is correct; claiming nothing changed would not be.
- The pre-commit hook does not run tests by default. A slow hook is a bypassed
  hook. `NEXUS_GATE_TESTS=1` opts in.
- Six broad `except Exception` handlers remain in `hooks.py` and `server.py`.
  Those are deliberate: a hook that raises would break the user's session, and a
  tool that raises would break the MCP connection rather than return an error.
