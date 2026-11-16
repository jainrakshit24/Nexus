"""Secret and PII scanning, run before anything is written to disk.

Pattern corpus adapted from the ECC `opensource-sanitizer` agent
(~/.claude/plugins/marketplaces/ecc/agents/opensource-sanitizer.md).
Severity split follows that agent: the secrets group hard-fails, the
heuristic/PII group warns.
"""
from __future__ import annotations

import re
from typing import NamedTuple

# Any match here blocks the write. Nothing in this group has a legitimate
# reason to live in project memory.
SECRET_PATTERNS: list[tuple[str, str]] = [
    ("api-key-assignment", r"""[A-Za-z0-9_]*(api[_-]?key|apikey|api[_-]?secret)[A-Za-z0-9_]*\s*[=:]\s*['"]?[A-Za-z0-9+/=_-]{16,}"""),
    ("aws-access-key-id", r"AKIA[0-9A-Z]{16}"),
    ("aws-secret-access-key", r"(?i)(aws_secret_access_key|aws_secret)\s*[=:]\s*['\"]?[A-Za-z0-9+/=]{20,}"),
    ("database-url-with-credentials", r"(postgres|postgresql|mysql|mongodb|redis)://[^:\s]+:[^@\s]+@[^\s'\"]+"),
    ("jwt", r"eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+"),
    ("private-key-block", r"-----BEGIN\s+(RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE KEY-----"),
    ("github-token", r"gh[pousr]_[A-Za-z0-9_]{36,}"),
    ("github-pat", r"github_pat_[A-Za-z0-9_]{22,}"),
    ("google-oauth-secret", r"GOCSPX-[A-Za-z0-9_-]+"),
    ("slack-webhook", r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"),
    ("sendgrid-key", r"SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}"),
    ("mailgun-key", r"key-[A-Za-z0-9]{32}"),
    ("slack-bot-token", r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("generic-password-assignment", r"(?i)\b(password|passwd|secret|token)\s*[=:]\s*['\"][^'\"\s]{8,}['\"]"),
]

# These are reported but do not block: a project memory may legitimately
# mention an internal host or a contact address.
WARN_PATTERNS: list[tuple[str, str]] = [
    ("personal-email", r"[a-zA-Z0-9._%+-]+@(gmail|yahoo|hotmail|outlook|protonmail|icloud)\.(com|net|org)"),
    ("private-ip", r"\b(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)\b"),
    ("ssh-connection-string", r"ssh\s+[a-z][a-z0-9._-]*@[0-9.]+"),
    ("high-entropy-env-line", r"(?m)^[A-Z_]{3,}=[A-Za-z0-9+/=_-]{32,}$"),
]

_SECRETS = [(n, re.compile(p)) for n, p in SECRET_PATTERNS]
_WARNS = [(n, re.compile(p)) for n, p in WARN_PATTERNS]


class Finding(NamedTuple):
    pattern: str
    severity: str  # "secret" | "warning"
    excerpt: str


class SecretFound(Exception):
    """Raised instead of writing a record that carries a credential."""

    def __init__(self, findings: list[Finding]):
        self.findings = findings
        names = ", ".join(sorted({f.pattern for f in findings}))
        super().__init__(f"refusing to store: matched {names}")


def _excerpt(text: str, match: re.Match) -> str:
    """Show enough to identify the line, never the whole secret."""
    raw = match.group(0)
    head = raw[:6]
    return f"{head}…({len(raw)} chars)"


def scan(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for name, rx in _SECRETS:
        for m in rx.finditer(text):
            findings.append(Finding(name, "secret", _excerpt(text, m)))
    for name, rx in _WARNS:
        for m in rx.finditer(text):
            findings.append(Finding(name, "warning", _excerpt(text, m)))
    return findings


def enforce(text: str) -> list[Finding]:
    """Block on secrets, return the warnings for the caller to display."""
    findings = scan(text)
    secrets = [f for f in findings if f.severity == "secret"]
    if secrets:
        raise SecretFound(secrets)
    return [f for f in findings if f.severity == "warning"]
