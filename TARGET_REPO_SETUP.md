# Target Repository Setup Guide

To connect a new repository to **DevFlow Kit** and enable the Claude Code automatic implementation flow, follow these onboarding steps.

## Prerequisites
1. **Claude Code GitHub App Installed:** Ensure the [Claude Code GitHub App](https://github.com/apps/claude) is installed on the target repository.

## 1. Add Repository Secrets

The target repository executes the Claude Code CLI via GitHub Actions. Since GitHub securely isolates secrets between repositories, these must be explicitly added to the target repository.

Go to **Settings > Secrets and variables > Actions > New repository secret** and add:

| Secret Name | Purpose |
| ----------- | ------- |
| `CLAUDE_CODE_OAUTH_TOKEN` | Authenticates the `claude-code-action` to generate code via Anthropic's API. |
| `GH_PAT` | A GitHub Personal Access Token. Allows Claude Code to bypass default restrictions and create pull requests natively. |

## 2. Enable Pull Request Creation for Actions

By default, GitHub prevents automated actions from opening Pull Requests. You must explicitly allow this:

1. Go to **Settings > Actions > General**
2. Scroll down to **Workflow permissions**
3. Select **Read and write permissions**
4. Check the box for **Allow GitHub Actions to create and approve pull requests**
5. Click **Save**

## 3. Add the Claude Code Workflow

The GitHub App triggers a workflow in the target repository whenever someone mentions `@claude`. You must add the workflow file to define what happens.

Create a new file at `.github/workflows/claude.yml` in the target repository with this exact content:

```yaml
name: Claude Code

on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]
  issues:
    types: [opened, assigned]
  pull_request_review:
    types: [submitted]

jobs:
  claude:
    if: |
      (github.event_name == 'issue_comment' && contains(github.event.comment.body, '@claude')) ||
      (github.event_name == 'pull_request_review_comment' && contains(github.event.comment.body, '@claude')) ||
      (github.event_name == 'pull_request_review' && contains(github.event.review.body, '@claude')) ||
      (github.event_name == 'issues' && (contains(github.event.issue.body, '@claude') || contains(github.event.issue.title, '@claude')))
    runs-on: ubuntu-latest
    permissions:
      contents: write       # Required to create branches and push code
      pull-requests: write  # Required to open PRs
      issues: write         # Required to comment on the issue
      id-token: write
      actions: read
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 1

      - name: Run Claude Code
        id: claude
        uses: anthropics/claude-code-action@v1
        env:
          GH_TOKEN: ${{ secrets.GH_PAT }}
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          additional_permissions: |
            actions: read
```

## Summary
Once these 3 steps are complete, DevFlow Kit's automated flow will successfully end with the Claude Code GitHub App picking up the `@claude` trigger and pushing a PR!
