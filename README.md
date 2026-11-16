<div align="center">

# NEXUS

**Engineering Intelligence & Memory System**

Your codebase remembers. Your agent stops re-learning it every session.

[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-black.svg)](pyproject.toml)
[![Local-first](https://img.shields.io/badge/local--first-no%20model%20calls-black.svg)](#privacy)
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-black.svg)](#use-it-from-your-agent)

</div>

---

## The problem

Every coding session starts from zero. The agent re-reads the same files, re-derives the same constraints, and re-makes a decision the team already made six months ago — because nothing carried over. Meanwhile it edits a file without knowing that four other modules depend on it, and reports "tests pass" without having run them.

NEXUS fixes the three gaps underneath that:

| Gap | What NEXUS adds |
|---|---|
| The session forgets | Durable, confidence-graded project memory in Markdown, retrieved by keyword **and** by graph traversal |
| The agent edits blind | Blast-radius analysis across parsed imports, text, tests and (optionally) a language server |
| Claims are not evidence | A gate that runs the checks and **cannot record a pass it did not observe** |

It is local-first. No model is called, no network is touched, nothing leaves the machine.

## Install

**As an agent skill** (skills.sh — works in Claude Code, Cursor, Codex and ~60 other agent dirs):

```bash
npx skills add jainrakshit24/Nexus
```

**As a Claude Code plugin:**

```
/plugin marketplace add jainrakshit24/Nexus
/plugin install nexus@nexus
```

**As a CLI** (the skill bootstraps this for you, or do it yourself):

```bash
pip install "nexus-eims @ git+https://github.com/jainrakshit24/Nexus.git"
```

## Quick start

```bash
cd <your repo>
nexus init .                      # detect stack + test command, create .nexus/

nexus recall "auth token"         # what do we already know?
nexus plan src/billing.py         # before editing: dependents, risks, owning role, missing ADR
nexus verify                      # after editing: diff, secrets, lint, types, vulns, API breaks, tests
nexus remember "webhooks are idempotent via event.id" \
  --confidence verified --source src/billing/webhooks.py:88
```

That loop — *recall → plan → edit → verify → remember* — is the whole product. Everything else is support.

<details>
<summary><b>Full command surface</b></summary>

```bash
# memory
nexus remember "..." --confidence verified --source file.py:12
nexus recall <query> --limit 5     nexus show <name>      nexus forget <name>
nexus consolidate                  # fold old episodes into monthly summaries
nexus reindex                      # rebuild the index from Markdown (truth is on disk)
nexus status

# understanding
nexus impact src/billing.py --depth 2       # transitive dependents
nexus impact src/billing.py --serena        # language-server precision, ~4.7s
nexus context "add proration" --budget 4000 # a packed brief, under a hard token budget
nexus tokens                                # measured actual / measured baseline / estimated saved
nexus graph                                 # graph size and staleness, no rebuild

# discipline
nexus plan <file>        nexus verify [--staged]
nexus adr new "Title" --affects src/billing.py      nexus adr list
nexus debt add "..." --where src/billing.py:40      nexus debt list
nexus env --write                           # .env.example from key names only, never values

# surfaces
nexus serve              # MCP server over stdio
nexus install claude-code | codex | cursor | vscode | all [--dry-run]
nexus dashboard [--compact]
```

</details>

## How it works

```
   Markdown in .nexus/          <- the truth. Git-friendly, human-readable, diffable.
          |
          v
   SQLite FTS5 index            <- a cache. Delete it, run `nexus reindex`, lose nothing.
          |
          +-- keyword recall (porter unicode61, confidence-weighted)
          +-- graph expansion  <- the join nobody else builds
                   |
                   v
          graphify code graph   <- NEXUS reads graphs. It does not build them.
```

**The join is the point.** Keyword search answers "what did we say about auth". Graph expansion answers "what do we know about the code this file depends on" — a question with no shared vocabulary at all. A fact anchored with `--source` becomes reachable through the import graph, and goes stale automatically when that file's content changes.

NEXUS is deliberately **wiring, not engine-building**. The code graph, the language server and the host orchestration already exist as mature tools. NEXUS adds the thin layer they were all missing. See [`docs/adr/0001-reuse-over-build.md`](docs/adr/0001-reuse-over-build.md).

## Measured

Every number below came from a command in this repository. Full method and caveats in [`docs/BENCHMARK.md`](docs/BENCHMARK.md).

**Context packing** — `nexus context`, counted with `cl100k_base`:

| Task | packed | reading those files whole | ratio |
|---|---|---|---|
| refactor a record module | 916 | 9,122 | **0.10** |
| add a CLI flag | 506 | 4,747 | **0.11** |
| speed up retrieval | 940 | 10,024 | **0.09** |

**Retrieval** — 50 questions that deliberately paraphrase their facts instead of quoting them:

| | recall@1 | recall@5 |
|---|---|---|
| keyword only | 0.54 | 0.70 |

And on questions only the graph can answer (asked by naming a *caller*, a symbol present in no fact):

| | recall@5 |
|---|---|
| keyword only | 0.00 |
| keyword **+ graph expansion** | **1.00** |

**Impact vs. grep**, same target: grep found 4 files, `nexus impact --depth 2` found 7 — including three transitive dependents that never contain the string at all — and correctly dropped grep's one false positive, a match inside a comment.

**Cold start on 10,101 files:** discovery 101 ms, MCP launch→initialize 44 ms, impact without a graph 318 ms.

## Use it from your agent

```bash
nexus install claude-code     # or codex / cursor / vscode / all
```

Points the host at `nexus serve`, an MCP server exposing five tools:

`nexus_recall` · `nexus_remember` · `nexus_impact` · `nexus_context` · `nexus_gate`

Host support — tested and untested, stated separately — is in [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

The dashboard (`nexus dashboard`, bound to 127.0.0.1) is deliberately **not** reachable from the MCP server, so watching NEXUS costs the agent zero context tokens. That is enforced by a test, not by a promise.

## The honesty invariant

One rule runs through the whole gate: **a pass with no captured evidence is not a pass.**

```python
if self.exit_code == 0 and not self.log.strip():
    raise ValueError("refusing to record a passing check with no captured output")
```

It is impossible to construct a passing result without the output that proves it. "Configured but not installed" is reported as a broken setup, never silently as a pass. NEXUS reads the project's own lint, type and audit configuration and never installs a tool behind your back.

## Privacy

- No model calls, no telemetry, no network.
- Secrets are read at point of use from the OS keychain (`secret-tool` / `pass` / `security`). An AST-level test asserts NEXUS calls no writer, so it cannot persist a credential even by accident.
- `nexus env --write` emits key *names* only — never values.
- The diff scanner reads untracked files whole, because `git diff` does not show a brand-new file containing a hardcoded key.
- Findings allowed by `.nexus/secret-allowlist` are still printed, never hidden. A scanner that silently suppresses is a scanner nobody trusts.

## Known limits

Stated up front, because a tool that hides these is worse than one that has them.

- **Breaking-change detection parses Python only.** Other languages get the diff and the tests, not an API shape diff.
- **Graph staleness is by mtime, not content hash** — a touched-but-unchanged file reads as stale. False-stale is the safe direction.
- **Dead-code detection counts text occurrences**, so it is blind to dynamic access (`getattr`, registries, string dispatch). Treat a hit as a question, not a verdict.
- **Every benchmark here is synthetic and self-authored.** The same author wrote the corpus, the questions and the scoring. That is weak evidence by construction — treat the numbers as a floor and a direction.
- **NEXUS has not been run against a large third-party codebase**, only against itself and against fixtures.
- **Local embeddings were considered and declined** at recall@5 = 0.70 against a pre-registered trigger of "below 0.70". The threshold was set before the data and was not moved afterwards. Reopening conditions are in [`docs/adr/0002`](docs/adr/).

## Documentation

| | |
|---|---|
| [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) | Architecture, memory lifecycle, storage, security, token strategy |
| [`docs/BENCHMARK.md`](docs/BENCHMARK.md) | Every measurement, with the command that produced it |
| [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md) | Host support, tested vs. untested |
| [`docs/RESEARCH.md`](docs/RESEARCH.md) | What already existed, licenses, reuse-vs-build |
| [`docs/PHASES.md`](docs/PHASES.md) | The build plan and its acceptance criteria |
| [`docs/PHASE1.md`](docs/PHASE1.md) … [`PHASE6.md`](docs/PHASE6.md) | What each phase shipped, and what it failed at first |
| [`docs/adr/`](docs/adr/) | Architecture decision records |

## Development

```bash
pip install -e ".[dev]" --no-build-isolation
python3 -m pytest tests -q      # 291 tests
ruff check .
nexus verify                    # NEXUS gates itself
```

## License

MIT — see [LICENSE](LICENSE).
