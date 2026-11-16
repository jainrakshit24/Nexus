# Phase 3 — Discipline & Security · COMPLETE (2026-11-16)

Phases 1–2 made NEXUS *know* things. Phase 3 makes it refuse careless work.

## What shipped

| Module | Does |
|---|---|
| `nexus/roles.py` | Routes specialists by blast radius and file shape — never by keywords in a task description. |
| `nexus/gate.py` | Pre-edit plan, post-edit verdict, test execution with a captured log, per-file diff scanning, confirmed reverts. |
| `nexus/adr.py` | ADRs in `docs/adr/`, numbered, templated, and indexed into memory so `recall` finds them. |
| `nexus/envman.py` | Which variables the code reads, which are declared, which are missing; `.env.example` from keys alone. |

New commands: `nexus plan · verify · adr · env · debt`.
The technical-debt registry is not a new store — it is memory records tagged `debt`.

## The invariant this phase exists for

```python
if self.exit_code == 0 and not self.log.strip():
    raise ValueError("a pass without evidence is not a pass")
```

`TestRun` cannot be *constructed* claiming success with an empty log. No code
path — including one added carelessly later — can report a green run that never
produced output. A command that exits 0 silently is recorded as
`(exited 0 but produced no output — treated as no evidence)`.

## Acceptance criteria — results

| # | Criterion | Result |
|---|---|---|
| 1 | A breaking edit is caught, with the failing output quoted; a "pass" with no log fails hard | **PASS** — `test_a_passing_run_with_no_log_cannot_be_constructed` and the whitespace variant both expect `ValueError`. `test_post_edit_fails_and_quotes_the_failing_output` asserts the failure text appears in the verdict. |
| 2 | A 1-file, 0-dependent change runs light gear and invokes **no** specialist | **PASS** — `route(["utils/format.py"], 0, True, "light") == ["developer"]`, asserted exactly. |
| 3 | A schema change runs full gear and requires an ADR before EXECUTE | **PASS** — plan is `blocked`, CLI exits `7` and prints the exact `nexus adr new` command. An ADR naming the target lifts the block; an unrelated ADR does not. |
| 4 | `.env.example` has every required key and zero real values | **PASS** — every non-comment line's value is exactly `<set-me>`, and NEXUS's own secret scanner finds nothing in the generated file, even when the source `.env` held a real DSN and an API key. |
| 5 | No destructive action without explicit confirmation | **PASS** — `revert_unintended` takes an injected `confirm`; declined leaves files untouched, and with nothing to revert it never prompts (the test's confirm raises if called). |

**137 tests, 3.5 s.** Phases 1 and 2 still green.

## Dogfooding result

`nexus verify` run against this repository, with its real 137-test suite:

```
# Post-edit gate: REVIEW
## Changed but not in the plan (8) …
## Credential-shaped strings allowed by `.nexus/secret-allowlist` …
## Tests
`pytest` PASSED in 3.8s
```

## Defects found and fixed

1. **QA was skipped exactly when it mattered most.** Routing required
   `has_tests and blast_radius > 0`. A change with three dependents and *no*
   test coverage got no QA — the absence of tests is the strongest reason to
   involve QA, not a reason to skip it. Now routed either way, with the reason
   saying which case it is.

2. **The scanner flagged what the change did not do.** Scanning the whole
   `git diff` matched credentials on *removed* lines and in surrounding
   context. Now only added lines are scanned, grouped per file.

3. **A brand-new file was never scanned at all.** `git diff HEAD` does not show
   untracked files, and a new file is the likeliest place for a hardcoded
   credential. Found while writing the allowlist test, which failed because the
   fixture file it created was invisible to the gate. Untracked files are now
   read whole.

4. **A scanner that cries wolf gets switched off.** Dogfooding blocked on this
   repo's own deliberate test fixtures. Rather than loosen the patterns, there
   is an auditable `.nexus/secret-allowlist` of `<pattern> <path-glob>` lines.
   Allowed findings are still printed, in their own section, with the file that
   produced them — moved out of blocking, never hidden.

5. **The allowlist would not survive a clone.** `.nexus/` was fully gitignored,
   so project *policy* was being treated as working data. Now `.nexus/*` with
   `!.nexus/secret-allowlist`.

## Known limits (carried into Phase 4)

- **Local embeddings are still the open decision from Phase 2.** recall@5 sits
  at 0.70, exactly on the trigger. Not addressed here; it is a storage change,
  not a discipline one, and deserves its own decision.
- The gate reports; it does not block a commit. A pre-commit hook would, and
  belongs with the Phase 4 adapters.
- `find_adr` matches an ADR by filename stem. An ADR about `store.py` would
  satisfy a change to any file whose stem appears in its text.
- Role routing is path-pattern based and tuned for common layouts; an unusual
  repository will need its patterns adjusted.
- `nexus verify` compares against the *latest* plan only; concurrent work on two
  plans is not modelled.
