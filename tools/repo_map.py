#!/usr/bin/env python3
"""Repo Map Generator — creates a concise structural map of a GitHub repository.

Inspired by Aider's repo map approach: parse source files into AST and extract
only class names, function signatures, and model definitions. No implementation
bodies. This gives an LLM a complete structural understanding of the codebase
in ~2K tokens instead of ~150K tokens from reading full files.

Usage:
    python tools/repo_map.py --repo owner/name
    python tools/repo_map.py --repo owner/name --branch main
    python tools/repo_map.py --local /path/to/repo

Output:
    A text-based structural map printed to stdout.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# File patterns to skip entirely
SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "coverage", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "egg-info",
}

SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock",
    "poetry.lock", "Pipfile.lock",
}

SKIP_EXTENSIONS = {
    ".min.js", ".min.css", ".map", ".wasm", ".pyc", ".pyo",
    ".ico", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip", ".tar",
    ".gz", ".bz2",
}


def should_skip(path: Path) -> bool:
    """Check if a file/directory should be skipped."""
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    if path.name in SKIP_FILES:
        return True
    if any(path.name.endswith(ext) for ext in SKIP_EXTENSIONS):
        return True
    return False


# ---------------------------------------------------------------------------
# Python AST Extraction
# ---------------------------------------------------------------------------


def extract_python_symbols(filepath: Path) -> list[str]:
    """Extract class/function signatures from a Python file using AST."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return []

    lines: list[str] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            # Class with bases
            bases = [_name(b) for b in node.bases if _name(b)]
            base_str = f"({', '.join(bases)})" if bases else ""
            lines.append(f"  class {node.name}{base_str}:")
            doc = _first_sentence_docstring(node)
            if doc:
                lines.append(f"    # {doc}")

            for item in ast.iter_child_nodes(node):
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    sig = _func_signature(item)
                    prefix = "async " if isinstance(item, ast.AsyncFunctionDef) else ""
                    lines.append(f"    {prefix}def {sig}")
                    doc = _first_sentence_docstring(item)
                    if doc:
                        lines.append(f"      # {doc}")

                # Pydantic/dataclass field definitions
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    ann = _annotation_str(item.annotation)
                    lines.append(f"    {item.target.id}: {ann}")

        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            sig = _func_signature(node)
            prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            lines.append(f"  {prefix}def {sig}")
            doc = _first_sentence_docstring(node)
            if doc:
                lines.append(f"    # {doc}")

    return lines


def _first_sentence_docstring(node: ast.AST) -> str:
    """Extract the first sentence of a docstring, if present."""
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    # Take first sentence (up to first period, newline, or 120 chars)
    first_line = doc.strip().split("\n")[0].strip()
    # Trim to first sentence ending with a period
    dot_idx = first_line.find(".")
    if 0 < dot_idx < 120:
        return first_line[: dot_idx + 1]
    return first_line[:120]


def _func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a function signature string from an AST node."""
    args_list = []
    all_args = node.args

    # Positional args
    defaults_offset = len(all_args.args) - len(all_args.defaults)
    for i, arg in enumerate(all_args.args):
        ann = f": {_annotation_str(arg.annotation)}" if arg.annotation else ""
        default_idx = i - defaults_offset
        default = f" = ..." if default_idx >= 0 else ""
        args_list.append(f"{arg.arg}{ann}{default}")

    # *args
    if all_args.vararg:
        ann = f": {_annotation_str(all_args.vararg.annotation)}" if all_args.vararg.annotation else ""
        args_list.append(f"*{all_args.vararg.arg}{ann}")

    # **kwargs
    if all_args.kwarg:
        ann = f": {_annotation_str(all_args.kwarg.annotation)}" if all_args.kwarg.annotation else ""
        args_list.append(f"**{all_args.kwarg.arg}{ann}")

    ret = f" -> {_annotation_str(node.returns)}" if node.returns else ""
    return f"{node.name}({', '.join(args_list)}){ret}"


def _annotation_str(node) -> str:
    """Convert an annotation AST node to a readable string."""
    if node is None:
        return ""
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_annotation_str(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return f"{_annotation_str(node.value)}[{_annotation_str(node.slice)}]"
    if isinstance(node, ast.Tuple):
        return ", ".join(_annotation_str(e) for e in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return f"{_annotation_str(node.left)} | {_annotation_str(node.right)}"
    return "..."


def _name(node) -> str:
    """Get name from a base class node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    return ""


# ---------------------------------------------------------------------------
# TypeScript / JavaScript Extraction (regex-based)
# ---------------------------------------------------------------------------

# Patterns for TS/JS symbol extraction
TS_CLASS_RE = re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?", re.MULTILINE)
TS_FUNCTION_RE = re.compile(
    r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)(?:\s*:\s*([^\s{]+))?",
    re.MULTILINE,
)
TS_METHOD_RE = re.compile(
    r"^\s+(?:async\s+)?(\w+)\s*\(([^)]*)\)(?:\s*:\s*([^\s{]+))?",
    re.MULTILINE,
)
TS_INTERFACE_RE = re.compile(r"^(?:export\s+)?interface\s+(\w+)(?:\s+extends\s+(\w+))?", re.MULTILINE)
TS_TYPE_RE = re.compile(r"^(?:export\s+)?type\s+(\w+)\s*=", re.MULTILINE)
TS_CONST_EXPORT_RE = re.compile(r"^export\s+const\s+(\w+)", re.MULTILINE)


def extract_ts_symbols(filepath: Path) -> list[str]:
    """Extract class/function/interface signatures from TypeScript/JavaScript."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except (UnicodeDecodeError, OSError):
        return []

    lines: list[str] = []

    # Classes
    for match in TS_CLASS_RE.finditer(source):
        name = match.group(1)
        extends = f"(extends {match.group(2)})" if match.group(2) else ""
        lines.append(f"  class {name} {extends}".rstrip())

        # Find methods inside this class (simple heuristic: indented methods after class line)
        class_start = match.end()
        # Find the next class/function/interface or end of file
        next_top = len(source)
        for pattern in [TS_CLASS_RE, TS_FUNCTION_RE, TS_INTERFACE_RE]:
            m = pattern.search(source, class_start + 1)
            if m and m.start() < next_top:
                next_top = m.start()

        class_body = source[class_start:next_top]
        for method_match in TS_METHOD_RE.finditer(class_body):
            method_name = method_match.group(1)
            params = method_match.group(2).strip()[:80]  # Keep params concise
            ret = f": {method_match.group(3)}" if method_match.group(3) else ""
            if method_name not in ("if", "for", "while", "switch", "catch", "return"):
                lines.append(f"    {method_name}({params}){ret}")

    # Top-level functions
    for match in TS_FUNCTION_RE.finditer(source):
        name = match.group(1)
        params = match.group(2).strip()[:80]
        ret = f": {match.group(3)}" if match.group(3) else ""
        lines.append(f"  function {name}({params}){ret}")

    # Interfaces
    for match in TS_INTERFACE_RE.finditer(source):
        name = match.group(1)
        extends = f" extends {match.group(2)}" if match.group(2) else ""
        lines.append(f"  interface {name}{extends}")

    # Type aliases
    for match in TS_TYPE_RE.finditer(source):
        lines.append(f"  type {match.group(1)}")

    # Exported constants (API endpoints, configs)
    for match in TS_CONST_EXPORT_RE.finditer(source):
        lines.append(f"  export const {match.group(1)}")

    return lines


# ---------------------------------------------------------------------------
# Main Logic
# ---------------------------------------------------------------------------

EXTRACTORS = {
    ".py": extract_python_symbols,
    ".ts": extract_ts_symbols,
    ".tsx": extract_ts_symbols,
    ".js": extract_ts_symbols,
    ".jsx": extract_ts_symbols,
}


def generate_repo_map(repo_path: Path) -> str:
    """Walk a local repo and generate a structural map."""
    output_blocks: list[str] = []

    # Collect and sort all source files
    source_files: list[Path] = []
    for ext in EXTRACTORS:
        source_files.extend(repo_path.rglob(f"*{ext}"))

    source_files = [f for f in source_files if not should_skip(f.relative_to(repo_path))]
    source_files.sort(key=lambda f: str(f.relative_to(repo_path)))

    for filepath in source_files:
        rel_path = filepath.relative_to(repo_path)
        extractor = EXTRACTORS.get(filepath.suffix)
        if not extractor:
            continue

        symbols = extractor(filepath)
        if symbols:
            output_blocks.append(f"{rel_path}:")
            output_blocks.extend(symbols)
            output_blocks.append("")  # blank line separator

    if not output_blocks:
        return "No source files found in the repository."

    return "\n".join(output_blocks)


def clone_repo(owner_name: str, branch: str = "main") -> Path:
    """Shallow-clone a GitHub repo into a temp directory."""
    tmp_dir = tempfile.mkdtemp(prefix="devflow-repomap-")
    url = f"https://github.com/{owner_name}.git"

    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")
    if token:
        url = f"https://x-access-token:{token}@github.com/{owner_name}.git"

    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", branch, url, tmp_dir],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(tmp_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a structural repo map")
    parser.add_argument("--repo", help="GitHub repo (owner/name)")
    parser.add_argument("--branch", default="main", help="Branch to clone (default: main)")
    parser.add_argument("--local", help="Path to a local repo (skip cloning)")
    args = parser.parse_args()

    if args.local:
        repo_path = Path(args.local)
        if not repo_path.exists():
            print(f"Error: {args.local} does not exist", file=sys.stderr)
            sys.exit(1)
        repo_map = generate_repo_map(repo_path)
        print(repo_map)

    elif args.repo:
        tmp_path = None
        try:
            tmp_path = clone_repo(args.repo, args.branch)
            repo_map = generate_repo_map(tmp_path)
            print(repo_map)
        finally:
            if tmp_path and tmp_path.exists():
                shutil.rmtree(tmp_path, ignore_errors=True)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
