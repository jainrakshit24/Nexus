"""Token counting and accounting.

Three numbers, never conflated:

  actual     measured  — tokens in the context NEXUS actually produced
  baseline   measured  — tokens the naive alternative would have cost
                         (reading those same files whole)
  saved      ESTIMATED — baseline minus actual

`saved` is an estimate even though both inputs are measured, because the
baseline is a counterfactual: nobody ran it. It is always rendered with
the word "estimated". A fourth number, the host's own reported usage, is
reported only when the host actually exposes it, and says `unavailable`
otherwise rather than guessing.

The tokenizer is tiktoken's `cl100k_base`. That is a real tokenizer but
not Claude's; counts are within a few percent for English and code, and
every report says which tokenizer produced them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

TOKENIZER_NAME = "tiktoken/cl100k_base"

_encoder = None


def _enc():
    global _encoder
    if _encoder is None:
        import tiktoken  # imported lazily: counting is optional to the rest of NEXUS
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count(text: str) -> int:
    if not text:
        return 0
    return len(_enc().encode(text, disallowed_special=()))


def count_file(path: Path) -> int:
    try:
        return count(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


@dataclass
class Accounting:
    task: str
    actual: int           # measured
    baseline: int         # measured counterfactual
    tokenizer: str = TOKENIZER_NAME
    at: str = ""

    def __post_init__(self):
        if not self.at:
            self.at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    @property
    def saved_estimated(self) -> int:
        return max(0, self.baseline - self.actual)

    @property
    def compression(self) -> float:
        return round(self.actual / self.baseline, 3) if self.baseline else 1.0

    def lines(self) -> list[str]:
        """Rendered exactly as the honesty rule requires: label every number."""
        return [
            f"actual   (measured)  : {self.actual:>8,} tokens   [{self.tokenizer}]",
            f"baseline (measured)  : {self.baseline:>8,} tokens   [full-file reads of the same files]",
            f"saved    (estimated) : {self.saved_estimated:>8,} tokens   [baseline - actual; the baseline was never run]",
            f"compression ratio    : {self.compression:>8}          [actual / baseline]",
        ]


def log_path(root: Path) -> Path:
    return Path(root) / ".nexus" / "tokens.jsonl"


def record(root: Path, acc: Accounting) -> None:
    p = log_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = asdict(acc) | {"saved_estimated": acc.saved_estimated, "compression": acc.compression}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def history(root: Path) -> list[dict]:
    p = log_path(root)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def totals(root: Path) -> dict:
    rows = history(root)
    actual = sum(r.get("actual", 0) for r in rows)
    baseline = sum(r.get("baseline", 0) for r in rows)
    return {
        "packs": len(rows),
        "actual_measured": actual,
        "baseline_measured": baseline,
        "saved_estimated": max(0, baseline - actual),
        "tokenizer": TOKENIZER_NAME,
    }


def platform_usage(project_root: Path) -> dict:
    """The host's own reported usage, when the host writes it down.

    Claude Code keeps per-project JSONL transcripts with usage records.
    If none are found we say so — we never substitute an estimate here.
    """
    slug = "-" + str(Path(project_root).resolve()).strip("/").replace("/", "-")
    d = Path.home() / ".claude" / "projects" / slug
    if not d.is_dir():
        return {"available": False, "reason": f"no host usage records at {d}"}
    inp = out = 0
    files = 0
    for f in d.glob("*.jsonl"):
        files += 1
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    usage = (json.loads(line).get("message") or {}).get("usage") or {}
                except (json.JSONDecodeError, AttributeError):
                    continue
                inp += usage.get("input_tokens", 0) or 0
                out += usage.get("output_tokens", 0) or 0
        except OSError:
            continue
    if not files:
        return {"available": False, "reason": f"no transcripts in {d}"}
    return {"available": True, "source": str(d), "transcripts": files,
            "input_tokens": inp, "output_tokens": out}
