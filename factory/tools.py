"""The tools the agents can call. Each call runs as a durable activity.

The agents only ever touch a checkout under WORK_ROOT. They cannot run git,
push, or see the GitHub token: the workflow does those steps itself, after it
has checked the agent's work. That is the line between what the model may do
and what the system does.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from dapr_agents import tool

MAX_READ = 40_000
MAX_OUTPUT = 12_000
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}

_work_root: Path | None = None
_scope = ""
_test_command = ""


def configure(work_root: Path, scope: str, test_command: str) -> None:
    global _work_root, _scope, _test_command
    _work_root, _scope, _test_command = work_root.resolve(), scope, test_command


def _workspace(workspace: str) -> Path:
    if _work_root is None:
        raise RuntimeError("tools.configure() was not called")
    path = Path(workspace).resolve()
    if path.parent != _work_root or not (path / ".git").exists():
        raise ValueError(f"{workspace} is not an agent workspace")
    return path


def _inside(base: Path, rel: str) -> Path:
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"{rel} is outside the workspace")
    return target


@tool
def list_files(workspace: str, directory: str = ".") -> str:
    """List the files under a directory of the workspace (recursive, at most 300 entries).

    Args:
        workspace: Absolute path of the workspace, exactly as given in the task.
        directory: Directory relative to the workspace root.
    """
    base = _workspace(workspace)
    root = _inside(base, directory)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            found.append(str(Path(dirpath, name).relative_to(base)))
            if len(found) >= 300:
                return "\n".join(found + ["... (truncated)"])
    return "\n".join(found) or "(empty)"


@tool
def read_file(workspace: str, path: str) -> str:
    """Read a text file from the workspace.

    Args:
        workspace: Absolute path of the workspace, exactly as given in the task.
        path: File path relative to the workspace root.
    """
    text = _inside(_workspace(workspace), path).read_text(errors="replace")
    return text if len(text) <= MAX_READ else text[:MAX_READ] + "\n... (truncated)"


@tool
def write_file(workspace: str, path: str, content: str) -> str:
    """Create or overwrite a file. Only files inside the task's scope directory may be written.

    Args:
        workspace: Absolute path of the workspace, exactly as given in the task.
        path: File path relative to the workspace root.
        content: The complete new content of the file.
    """
    base = _workspace(workspace)
    target = _inside(base, path)
    scope = _inside(base, _scope) if _scope else base
    if target != scope and scope not in target.parents:
        raise ValueError(f"only files under {_scope}/ may be changed")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"wrote {path} ({len(content)} bytes)"


@tool
def search_code(workspace: str, text: str) -> str:
    """Find lines containing some text (case-sensitive) across the workspace.

    Args:
        workspace: Absolute path of the workspace, exactly as given in the task.
        text: The text to look for.
    """
    base = _workspace(workspace)
    hits = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            file = Path(dirpath, name)
            try:
                lines = file.read_text().splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(lines, 1):
                if text in line:
                    hits.append(f"{file.relative_to(base)}:{n}: {line.strip()[:200]}")
                    if len(hits) >= 100:
                        return "\n".join(hits + ["... (truncated)"])
    return "\n".join(hits) or "no matches"


def run_test_command(base: Path) -> tuple[bool, str]:
    """Run the configured test command in a checkout, with no tokens in its environment."""
    env = {k: v for k, v in os.environ.items() if "TOKEN" not in k and "KEY" not in k}
    try:
        out = subprocess.run(
            shlex.split(_test_command),
            cwd=base,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, "tests timed out after 180s"
    text = (out.stdout + out.stderr).strip()
    if len(text) > MAX_OUTPUT:
        text = "... (truncated)\n" + text[-MAX_OUTPUT:]
    return out.returncode == 0, text


@tool
def run_tests(workspace: str) -> str:
    """Run the project's test suite in the workspace and return the result.

    Args:
        workspace: Absolute path of the workspace, exactly as given in the task.
    """
    passed, output = run_test_command(_workspace(workspace))
    return ("PASSED\n" if passed else "FAILED\n") + output


ALL = {t.name: t for t in (list_files, read_file, write_file, search_code, run_tests)}
