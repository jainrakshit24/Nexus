## NEXUS

This project has a NEXUS memory and code-intelligence server. Prefer it over
re-deriving what the project already knows.

- **Before answering a question about this codebase**, call `nexus_recall`.
  It is far cheaper than reading files and often sufficient.
- **Before editing any file**, call `nexus_impact` on it. Depth 2 finds
  dependents that never mention the file by name.
- **For a non-trivial change**, call `nexus_gate` with `stage: "pre"` first.
  It returns the dependents that must keep working, which specialists the
  change earns, and whether an ADR is required. If it reports BLOCKED, write
  the ADR before editing.
- **After editing**, call `nexus_gate` with `stage: "post"`. It runs the real
  test suite and captures the output. A pass is never reported without one.
- **When you have proved something** — a test went green, a schema changed, a
  decision was made — call `nexus_remember` with `confidence: "verified"` and
  a source. Do not record guesses as facts, and never store a credential.
- `nexus_context` assembles memory, impact and file outlines inside a token
  budget when you are starting a task from cold.
