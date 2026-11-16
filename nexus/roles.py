"""Role routing: which specialists a change actually earns.

Routing is by blast radius and by what the files *are*, never by keywords in
the task description. A one-file change with no dependents gets the developer
and nobody else — the brief's warning about excessive delegation is enforced
here, mechanically, not by good intentions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Path shapes that pull in a specialist regardless of blast radius.
SECURITY_PATHS = re.compile(
    r"(auth|login|session|token|password|crypto|secret|permission|role|acl|cors|csrf|sanitiz)", re.I)
DEVOPS_PATHS = re.compile(
    r"(dockerfile|docker-compose|\.github/workflows|\.gitlab-ci|jenkinsfile|terraform|\.tf$|"
    r"helm|k8s|kubernetes|deploy|procfile|nginx|supervisor)", re.I)
ARCHITECTURE_PATHS = re.compile(
    r"(migration|schema|models?\.py|entities|__init__\.py|api/|routes?|interface|contract|proto)", re.I)
DATA_PATHS = re.compile(r"(migration|schema|\.sql$|models?\.py|repository|dao)", re.I)

ARCHITECT_BLAST_THRESHOLD = 5


BRIEFS = {
    "developer": "Follow the conventions already in the files you touch. Reuse what "
                 "exists before adding anything. Keep the change as small as the task allows.",
    "architect": "Compare this against the existing architecture before accepting it. "
                 "If it introduces a new pattern, say why the existing one does not fit, "
                 "and record it as an ADR.",
    "data": "Check the migration is reversible or deliberately not, that it is safe on a "
            "non-empty table, and that old and new code can both run during the deploy.",
    "security": "Check authentication and authorisation on every path this touches, "
                "validate input at the boundary, and confirm no secret is read from or "
                "written to the repository.",
    "devops": "Confirm the build still produces the same artefact, the deployment is "
              "reversible with one command, and no environment variable was added "
              "without a placeholder in .env.example.",
    "qa": "Name the edge cases before reading the implementation. Check the dependents "
          "listed in this plan actually still work, and that a test fails without the fix.",
    "tpm": "Confirm the scope matches what was asked, the acceptance criteria are "
           "testable, and anything deferred is written down rather than forgotten.",
}


@dataclass(frozen=True)
class Role:
    name: str
    why: str

    @property
    def brief(self) -> str:
        """What this role must actually do on this change.

        NEXUS cannot spawn a host's subagents, so it does the next honest thing:
        it says precisely what the role is responsible for, in the plan the
        agent is already reading."""
        return BRIEFS.get(self.name, "")


def route(targets: list[str], blast_radius: int, has_tests: bool,
          gear: str, new_files: list[str] | None = None) -> list[Role]:
    """The smallest set of specialists this change needs."""
    roles = [Role("developer", "every change needs one")]
    new_files = new_files or []
    joined = " ".join(targets)

    if gear == "light" and blast_radius == 0 and not SECURITY_PATHS.search(joined) \
            and not DEVOPS_PATHS.search(joined) and not ARCHITECTURE_PATHS.search(joined):
        return roles  # isolated change: no specialist, by design

    if blast_radius > 0:
        # No test coverage is the strongest reason to involve QA, not a reason to skip it.
        roles.append(Role("qa", f"{blast_radius} dependent(s) can break"
                                + ("" if has_tests else " and nothing covers them")))
    if SECURITY_PATHS.search(joined):
        roles.append(Role("security", "touches authentication, secrets or input handling"))
    if DEVOPS_PATHS.search(joined):
        roles.append(Role("devops", "touches build, deployment or infrastructure config"))
    if DATA_PATHS.search(joined):
        roles.append(Role("data", "touches schema, migrations or persistence"))
    if ARCHITECTURE_PATHS.search(joined) or blast_radius >= ARCHITECT_BLAST_THRESHOLD or len(new_files) > 2:
        reason = ("introduces a module boundary" if new_files and len(new_files) > 2
                  else f"blast radius {blast_radius}" if blast_radius >= ARCHITECT_BLAST_THRESHOLD
                  else "touches an architectural surface")
        roles.append(Role("architect", reason))
    if len(targets) > 3 and gear == "full":
        roles.append(Role("tpm", f"{len(targets)} files in one change"))

    # Stable order, no duplicates.
    order = {"developer": 0, "architect": 1, "data": 2, "security": 3, "devops": 4, "qa": 5, "tpm": 6}
    seen: dict[str, Role] = {}
    for r in roles:
        seen.setdefault(r.name, r)
    return sorted(seen.values(), key=lambda r: order.get(r.name, 99))


def needs_adr(targets: list[str], new_files: list[str] | None = None) -> tuple[bool, str]:
    """Whether this change must be justified in an ADR before it is executed."""
    joined = " ".join(targets)
    if ARCHITECTURE_PATHS.search(joined):
        return True, "changes an architectural surface (schema, API, module boundary or contract)"
    if new_files and len(new_files) > 2:
        return True, f"introduces {len(new_files)} new modules at once"
    return False, ""
