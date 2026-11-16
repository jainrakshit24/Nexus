# NEXUS — measurements

Every number here came from a command in this repo. Reproduce with the command shown.
Nothing is projected, and nothing labelled *estimated* is presented as measured.

Measured 2026-11-16 on Python 3.10.12, Linux 6.8, this repository (17 code files, 2.8k lines).

---

## 1. Memory retrieval quality

`python3 bench/run_recall.py` — 50 project facts, 50 questions that deliberately
**paraphrase** them rather than reuse their wording ("what algorithm protects stored
credentials" against a fact that says "passwords are hashed with Argon2id").

| k | recall@k | hits |
|---|---|---|
| 1 | 0.54 | 27/50 |
| 3 | 0.62 | 31/50 |
| **5** | **0.70** | **35/50** |
| 10 | 0.76 | 38/50 |

Latency: p50 **0.2 ms**, max 0.6 ms.

**Read this honestly.** This is a deliberately hard slice: questions share almost no
vocabulary with the facts. Real queries mix paraphrase with the project's own terms,
so day-to-day recall is better than 0.70 — but how much better is not measured, so no
number is claimed for it.

**What moved it:** switching the FTS5 tokenizer to `porter unicode61` — one line — took
recall@5 from **0.64 to 0.70** and recall@1 from 0.44 to 0.54.

**The upgrade trigger.** The blueprint pre-committed to adding local embeddings if
recall@5 fell below 0.70. It now sits **exactly on the line**. That is not a pass; it is
a tie. The remaining 15 misses are pure vocabulary gaps ("pictures"/"images",
"credentials"/"passwords") that no keyword trick fixes. **Recommendation: add local
embeddings (`sqlite-vec` + a small local model) as the first Phase 3 item**, keeping
keyword search as the other half of a hybrid, and re-run this benchmark to prove it.

## 2. Context packing

`nexus context "<task>" --budget 4000`, measured with `tiktoken/cl100k_base`.

| Task | actual (measured) | baseline (measured) | saved (*estimated*) | ratio |
|---|---|---|---|---|
| refactor `nexus/record.py` to support tags | 916 | 9,122 | 8,206 | 0.100 |
| add a flag to `nexus/cli.py` | 506 | 4,747 | 4,241 | 0.107 |
| speed up `nexus/store.py` recall | 940 | 10,024 | 9,084 | 0.094 |

**Baseline** = what reading those same files whole would have cost. **Saved** is
*estimated* because the baseline is a counterfactual — nobody ran it.

**Where it does not pay off:** on files of a few dozen tokens the pack costs more than
the files, because it also carries memory and impact that a plain read would not give
you. The accounting reports zero saved in that case rather than a negative number
(`test_tiny_files_report_no_saving_rather_than_a_negative_one`).

**Tokenizer caveat:** `cl100k_base` is a real tokenizer but not Claude's. Counts are
close for English and code, not exact. Every report names the tokenizer that produced it.

## 3. Impact analysis vs. a manual grep

Target `nexus/record.py`, compared against
`grep -rln -e "from \.record" -e "record\.py" -e "import record" --include="*.py"`.

| | files found |
|---|---|
| manual grep | 4 |
| `nexus impact --depth 2` | 7 |

- **Superset of grep:** yes — every grep hit is reported.
- **Found what grep could not:** `nexus/context.py`, `tests/conftest.py`, `tests/test_cli.py`
  — transitive dependents that never contain the string `record` at all.
- **grep's false positive:** `nexus/graph.py` matched only inside a code comment. NEXUS
  does not report it as a dependent, because no parser links them.

## 4. Graph freshness

`nexus graph` — compares graphify's `manifest.json` mtimes against the filesystem.
Detecting staleness takes a filesystem walk, **no rebuild**:

```
size      : 235 nodes, 567 links (directed=True)
freshness : STALE: 4 changed, 6 never indexed of 17 indexed files
```

Limitation: comparison is by **mtime**, not content hash — graphify records an AST hash
NEXUS cannot recompute without re-parsing. A touched-but-unchanged file reads as stale.
False-stale is the safe direction; false-fresh would not be.

## 5. Language server (Serena), opt-in

`nexus impact <file> --serena`

| | |
|---|---|
| cold start + session + 1 query | **4.7 s** (4.9 s on a second run — no warm cache) |
| files returned for `Record` | 7 |

Four to five seconds per invocation is why this is behind a flag and not the default.
The graph answers the same question in milliseconds; Serena is for when precision
matters more than latency, or for languages graphify's extractor does not parse.

## 6. Test suite

`python3 -m pytest tests -q` — **83 tests, 2.7 s**, across 9 modules.
MCP client tests run against a fake stdio server, so they need no network and no `uvx`.
