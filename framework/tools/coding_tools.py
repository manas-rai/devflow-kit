"""Coding tools — filesystem + bash + git for the implementation agent."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

REPO_ROOT: Path | None = None


def set_repo_root(path: Path) -> None:
    global REPO_ROOT
    REPO_ROOT = path


def _validate_path(file_path: str) -> Path:
    if REPO_ROOT is None:
        raise ValueError("REPO_ROOT is not set. Call set_repo_root() before using coding tools.")
    full = (REPO_ROOT / file_path).resolve()
    if not str(full).startswith(str(REPO_ROOT.resolve())):
        raise ValueError(f"Path {file_path} is outside repo root")
    return full


async def read_file(path: str) -> str:
    """Read a file from the repo and return its contents."""
    try:
        full = _validate_path(path)
        return await asyncio.to_thread(full.read_text)
    except Exception as e:
        return f"Error reading {path}: {e}"


async def write_file(path: str, content: str) -> str:
    """Write content to a file in the repo, creating parent dirs as needed."""
    try:
        full = _validate_path(path)

        def _write():
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)

        await asyncio.to_thread(_write)
        return f"Successfully wrote {len(content)} bytes to {path}."
    except Exception as e:
        return f"Error writing {path}: {e}"


async def list_files(directory: str = ".") -> str:
    """List files in a directory within the repo."""
    try:
        full = _validate_path(directory)

        def _list():
            entries = sorted(full.iterdir())
            lines = []
            for entry in entries:
                prefix = "[dir]  " if entry.is_dir() else "[file] "
                lines.append(f"{prefix}{entry.name}")
            return "\n".join(lines) if lines else "(empty directory)"

        return await asyncio.to_thread(_list)
    except Exception as e:
        return f"Error listing {directory}: {e}"


async def search_in_repo(pattern: str, file_glob: str = "**/*.py") -> str:
    """Search for a pattern in repo files matching the glob."""
    try:
        if REPO_ROOT is None:
            return "REPO_ROOT is not set."

        def _search():
            matches = []
            for file_path in REPO_ROOT.glob(file_glob):
                try:
                    text = file_path.read_text(errors="replace")
                    for i, line in enumerate(text.splitlines(), 1):
                        if pattern.lower() in line.lower():
                            rel = file_path.relative_to(REPO_ROOT)
                            matches.append(f"{rel}:{i}: {line.rstrip()}")
                            if len(matches) >= 50:
                                return matches
                except Exception:
                    pass
            return matches

        results = await asyncio.to_thread(_search)
        if not results:
            return f"No matches found for '{pattern}' in {file_glob}."
        return "\n".join(results[:50])
    except Exception as e:
        return f"Error searching repo: {e}"


async def run_bash(command: str, timeout: int = 60) -> str:
    """Run a bash command in the repo root."""
    try:
        cwd = str(REPO_ROOT) if REPO_ROOT else None

        def _run():
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output or "(no output)"

        return await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    except Exception as e:
        return f"Error running command: {e}"


async def git_status() -> str:
    """Return git status of the repo."""
    return await run_bash("git status --short")


async def git_diff() -> str:
    """Return git diff of staged and unstaged changes."""
    return await run_bash("git diff HEAD")


async def git_add_and_commit(message: str) -> str:
    """Stage all changes and create a commit."""
    add_result = await run_bash("git add -A")
    commit_result = await run_bash(f'git commit -m {message!r}')
    return f"git add:\n{add_result}\ngit commit:\n{commit_result}"


async def git_push(branch: str) -> str:
    """Push the current branch to origin."""
    return await run_bash(f"git push origin {branch}")
