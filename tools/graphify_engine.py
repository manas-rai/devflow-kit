"""Thin wrapper around the Graphify CLI.

Graphify (https://graphify.net) parses a repo into a knowledge graph and writes
``GRAPH_REPORT.md``, ``graph.html``, and a ``graphify-out/`` per-file cache into
the working directory. We run it inside a checked-out repo and collect those
artifacts.

NOTE: Graphify's exact CLI flags and model-config env vars should be verified
against the installed ``graphifyy`` version. This wrapper invokes the documented
bare ``graphify`` command (overridable via ``GRAPHIFY_CMD``) and locates outputs
by their documented filenames, so adjusting the invocation is a one-line change.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPORT_FILENAME = "GRAPH_REPORT.md"
CACHE_DIRNAME = "graphify-out"


@dataclass
class GraphifyResult:
    """Artifacts produced by a Graphify run."""

    report_path: Path
    cache_dir: Path
    stdout: str


def count_source_files(repo_path: Path) -> int:
    """Count non-skipped files in a repo — a proxy for Graphify's workload.

    Reuses repo_map's skip rules (node_modules, lockfiles, binaries, etc.) so
    the count reflects roughly what Graphify will process, for cost guarding.
    """
    from tools.repo_map import should_skip

    repo_path = Path(repo_path)
    count = 0
    for f in repo_path.rglob("*"):
        if f.is_file() and not should_skip(f.relative_to(repo_path)):
            count += 1
    return count


def run_graphify(
    repo_path: Path,
    restore_cache_from: Path | None = None,
    timeout: int = 3600,
) -> GraphifyResult:
    """Run Graphify in ``repo_path`` and return the produced artifacts.

    Args:
        repo_path: A checked-out repo to analyze.
        restore_cache_from: A prior ``graphify-out/`` cache to seed the run with,
            so only changed files are re-processed (incremental updates).
        timeout: Hard cap on the Graphify process, in seconds.
    """
    repo_path = Path(repo_path)
    cache_dir = repo_path / CACHE_DIRNAME

    if restore_cache_from and Path(restore_cache_from).exists():
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        shutil.copytree(restore_cache_from, cache_dir)

    cmd = os.environ.get("GRAPHIFY_CMD", "graphify").split()
    print(f"graphify: running {' '.join(cmd)} in {repo_path}", file=sys.stderr, flush=True)

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"graphify command not found ({cmd[0]!r}). "
            "Install it with: pip install 'devflow-kit[graphify]' or set GRAPHIFY_CMD."
        ) from exc

    if proc.returncode != 0:
        raise RuntimeError(
            f"graphify failed (exit {proc.returncode}): {proc.stderr[:500] or proc.stdout[:500]}"
        )

    report_path = repo_path / REPORT_FILENAME
    if not report_path.exists():
        raise FileNotFoundError(
            f"graphify did not produce {REPORT_FILENAME} in {repo_path}"
        )

    print(
        f"graphify: produced {report_path.name} ({report_path.stat().st_size} bytes)",
        file=sys.stderr,
        flush=True,
    )
    return GraphifyResult(report_path=report_path, cache_dir=cache_dir, stdout=proc.stdout)
