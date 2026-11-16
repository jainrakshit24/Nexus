"""Project discovery: read the repo, report what it actually is."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".next", ".nexus", "target", ".mypy_cache", ".pytest_cache", "vendor"}

# Ordered: the first marker that matches wins, because a repo with both a
# package.json and a stray Makefile is a Node repo.
MARKERS = [
    ("node", "package.json"),
    ("python", "pyproject.toml"),
    ("python", "setup.py"),
    ("python", "requirements.txt"),
    ("rust", "Cargo.toml"),
    ("go", "go.mod"),
    ("java", "pom.xml"),
    ("java", "build.gradle"),
    ("ruby", "Gemfile"),
    ("php", "composer.json"),
]


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def git_info(root: Path) -> dict:
    if not (root / ".git").exists() or not shutil.which("git"):
        return {"repo": False}
    status = _run(["git", "status", "--porcelain"], root)
    return {
        "repo": True,
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root) or "unknown",
        "head": _run(["git", "rev-parse", "--short", "HEAD"], root) or "unknown",
        "dirty_files": len([ln for ln in status.splitlines() if ln.strip()]),
    }


def _makefile_has_test(root: Path) -> bool:
    mk = root / "Makefile"
    return mk.exists() and bool(re.search(r"(?m)^test\s*:", mk.read_text(errors="ignore")))


EXT_STACK = {".py": "python", ".ts": "node", ".tsx": "node", ".js": "node",
             ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby", ".php": "php"}


SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")


def _nested_pytest_target(root: Path, max_depth: int = 3) -> str:
    """Repos often keep tests below the root (monorepos, skill bundles)."""
    best = None
    for d in root.rglob("tests"):
        if not d.is_dir() or any(part in SKIP_DIRS for part in d.parts):
            continue
        depth = len(d.relative_to(root).parts)
        if depth > max_depth or not any(d.glob("test_*.py")):
            continue
        if best is None or depth < best[0]:
            best = (depth, d)
    if best is None:
        return ""
    rel = str(best[1].relative_to(root))
    # A path is repository-controlled input. If it carries anything a shell
    # could interpret, do not put it in a command at all.
    return rel if SAFE_PATH.match(rel) else ""


def test_command(root: Path, stack: str) -> str:
    """Best guess at the command that runs this project's tests, or ''."""
    if stack == "node":
        try:
            pkg = json.loads((root / "package.json").read_text())
        except (OSError, json.JSONDecodeError):
            pkg = {}
        if "test" in pkg.get("scripts", {}):
            mgr = ("pnpm" if (root / "pnpm-lock.yaml").exists()
                   else "yarn" if (root / "yarn.lock").exists()
                   else "bun" if (root / "bun.lockb").exists() else "npm")
            return f"{mgr} test" if mgr != "npm" else "npm test"
    if stack == "python":
        has_tests = any((root / d).is_dir() for d in ("tests", "test")) or \
            any(root.glob("test_*.py")) or any(root.glob("*_test.py"))
        if has_tests:
            return "pytest"
        nested = _nested_pytest_target(root)
        if nested:
            return f"pytest {nested}"
    if stack == "rust":
        return "cargo test"
    if stack == "go":
        return "go test ./..."
    if stack == "java":
        return "mvn test" if (root / "pom.xml").exists() else "./gradlew test"
    if stack == "ruby":
        return "bundle exec rspec" if (root / "spec").is_dir() else "bundle exec rake test"
    if stack == "php":
        return "./vendor/bin/phpunit"
    if _makefile_has_test(root):
        return "make test"
    return ""


def file_census(root: Path, cap: int = 20000) -> tuple[Counter, int]:
    counts: Counter = Counter()
    total = 0
    for p in root.rglob("*"):
        if total >= cap:
            break
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        total += 1
        if p.suffix:
            counts[p.suffix.lower()] += 1
    return counts, total


def entrypoints(root: Path) -> list[str]:
    names = ["main.py", "app.py", "manage.py", "index.js", "index.ts", "main.go",
             "main.rs", "src/main.rs", "src/index.ts", "src/index.js", "cli.py",
             "Dockerfile", "docker-compose.yml"]
    return [n for n in names if (root / n).exists()]


def profile(root: Path) -> dict:
    root = Path(root).resolve()
    stack = next((s for s, marker in MARKERS if (root / marker).exists()), "")
    markers = [m for _, m in MARKERS if (root / m).exists()]
    counts, total = file_census(root)
    if not stack:
        # No marker file (monorepo root, docs-first repo): fall back to what the
        # code actually is. Flagged as inferred so nobody mistakes it for a fact.
        for ext, _n in counts.most_common():
            if ext in EXT_STACK:
                stack = EXT_STACK[ext] + " (inferred from file types)"
                break
        else:
            stack = "unknown"
    return {
        "name": root.name,
        "path": str(root),
        "stack": stack,
        "markers": markers,
        "test_command": test_command(root, stack.split(" ")[0]),
        "entrypoints": entrypoints(root),
        "file_count": total,
        "top_extensions": counts.most_common(8),
        "git": git_info(root),
    }


def to_markdown(p: dict) -> str:
    git = p["git"]
    if not git.get("repo"):
        git_line = "not a git repository"
    else:
        dirty = git.get("dirty_files", 0)
        state = f"{dirty} uncommitted file(s)" if dirty else "clean"
        git_line = f"`{git['branch']}` @ `{git['head']}` — {state}"
    exts = ", ".join(f"`{e}` {n}" for e, n in p["top_extensions"]) or "none"
    eps = ", ".join(f"`{e}`" for e in p["entrypoints"]) or "none detected"
    return f"""Project **{p['name']}** at `{p['path']}`.

- **Stack:** {p['stack']} (markers: {', '.join(f'`{m}`' for m in p['markers']) or 'none'})
- **Test command:** {f"`{p['test_command']}`" if p['test_command'] else "not detected — set it manually"}
- **Entrypoints:** {eps}
- **Files:** {p['file_count']} (excluding vendor/build dirs)
- **Top extensions:** {exts}
- **Git:** {git_line}

Discovered by `nexus init`. Confidence is `observed`: these are facts read off the
filesystem, not verified by running anything. Run the test command once and
re-record it as `verified` with the run as its source.
"""
