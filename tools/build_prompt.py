#!/usr/bin/env python3
"""Fill the refinement prompt template with environment variables.

This is pure plumbing — no decisions, no branching, no logic.
It reads the template, replaces placeholders, and prints to stdout.
The workflow captures the output and passes it to Claude Code Action.

Usage:
    python tools/build_prompt.py

Requires env vars:
    ISSUE_KEY, PROJECT_KEY, COMPONENT, SUMMARY, DESCRIPTION,
    JIRA_BASE_URL, TARGET_REPO, TARGET_BRANCH
"""

import os
import sys
from pathlib import Path


def main() -> None:
    template_path = Path(__file__).parent.parent / "prompts" / "refine.md"
    template = template_path.read_text()

    replacements = {
        "{{issue_key}}": os.environ.get("ISSUE_KEY", ""),
        "{{project_key}}": os.environ.get("PROJECT_KEY", ""),
        "{{component}}": os.environ.get("COMPONENT", ""),
        "{{summary}}": os.environ.get("SUMMARY", ""),
        "{{description}}": os.environ.get("DESCRIPTION", "No description provided."),
        "{{jira_base_url}}": os.environ.get("JIRA_BASE_URL", "").rstrip("/"),
        "{{target_repo}}": os.environ.get("TARGET_REPO", ""),
        "{{target_branch}}": os.environ.get("TARGET_BRANCH", "main"),
    }

    prompt = template
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)

    # Sanity check — make sure no placeholders remain
    if "{{" in prompt:
        import re

        remaining = re.findall(r"\{\{.*?\}\}", prompt)
        print(f"WARNING: unfilled placeholders: {remaining}", file=sys.stderr)

    print(prompt)


if __name__ == "__main__":
    main()
