# DevFlow Kit

AI agents that turn Jira tickets into pull requests — zero infrastructure needed.

Fork once into your org, connect to Jira, and the agents refine specs, decompose complex tickets into parallel subtasks, and create GitHub issues that the [Claude Code App](https://github.com/apps/claude) implements automatically. One repo. One setup. Target repos stay untouched.

## How it works

```
Jira ticket created
       ↓
  Jira Automation webhook → this repo
       ↓
  Refinement Agent
  ├── Simple ticket → creates 1 GitHub issue with @claude
  └── Complex ticket → decomposes into N subtasks
      ├── Creates Jira subtasks
      └── Creates N GitHub issues with @claude (parallel)
       ↓
  Claude Code GitHub App picks up each @claude issue
  → reads the repo → implements → opens PR
       ↓
  Sync Agent watches PRs → updates Jira status
  → when all subtasks merge → parent ticket → Done
```

**Target repos need nothing installed.** No workflows, no secrets, no config. The Claude Code App (installed at org level) runs directly in target repos. This hub is the only thing you set up.

## Quick start

### Prerequisites

- GitHub org (or personal account)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed: `npm install -g @anthropic-ai/claude-code`
- Claude Pro or Max subscription
- Jira Cloud project

### Setup (one time, ~15 minutes)

**1. Install Claude Code GitHub App**

Go to [github.com/apps/claude](https://github.com/apps/claude) → Install on your org → select the repos you want DevFlow Kit to work with.

**2. Use this template**

Click **"Use this template"** above to create your own copy (e.g., `your-org/devflow-kit`).

**3. Generate credentials**

```bash
# Claude OAuth token (valid ~1 year)
claude setup-token
# → Copy: sk-ant-oat01-xxxxx...
```

Create a [fine-grained GitHub PAT](https://github.com/settings/personal-access-tokens/new):
- Repository access: select your target repos
- Permissions: Contents (R/W), Issues (R/W), Pull requests (R/W), Metadata (R)

Get a [Jira API token](https://id.atlassian.com/manage-profile/security/api-tokens).

**4. Add secrets to this repo**

Go to Settings → Secrets and variables → Actions:

| Secret | Value |
|--------|-------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Token from `claude setup-token` |
| `GITHUB_PAT` | Fine-grained PAT |
| `JIRA_BASE_URL` | `https://your-domain.atlassian.net` |
| `JIRA_USER_EMAIL` | Bot account email |
| `JIRA_API_TOKEN` | Jira API token |

**5. Configure repo-map.json**

Edit `repo-map.json` to map your Jira components to GitHub repos:

```json
{
  "version": "1",
  "routes": [
    {
      "jira_project": "MYPROJ",
      "component": "backend",
      "github_repo": "your-org/backend-api"
    },
    {
      "jira_project": "MYPROJ",
      "component": "frontend",
      "github_repo": "your-org/web-app"
    }
  ],
  "defaults": {
    "github_repo": "your-org/backend-api"
  }
}
```

**6. Create Jira Automation rule**

In Jira → Project Settings → Automation → Create Rule:

- **When:** Issue transitioned to "To Refine"
- **Then:** Send web request
  - URL: `https://api.github.com/repos/YOUR-ORG/devflow-kit/dispatches`
  - Method: POST
  - Headers: `Authorization: Bearer YOUR_PAT`, `Accept: application/vnd.github+json`
  - Body:
    ```json
    {
      "event_type": "devflow-refine",
      "client_payload": {
        "issue_key": "{{issue.key}}",
        "project_key": "{{project.key}}",
        "component": "{{issue.components.name}}",
        "summary": "{{issue.summary}}",
        "description": "{{issue.description}}"
      }
    }
    ```

**Done.** Move a Jira ticket to "To Refine" and watch it flow through to a PR.

## Adding a new repo

1. Add the repo to the Claude Code App's access list
2. Add the repo to your PAT's scope
3. Add one entry to `repo-map.json`

No changes to the target repo.

## How the refinement agent thinks

The agent doesn't always decompose tickets. It makes a smart decision:

| Ticket type | Decision | What happens |
|-------------|----------|-------------|
| Small bug fix | **Direct** | Creates 1 issue with @claude, minimal spec |
| Clear feature | **Refine** | Writes a full spec, creates 1 issue with @claude |
| Multi-concern feature | **Decompose** | Breaks into N subtasks, creates N issues, Claude runs in parallel |
| Large refactor | **Refine** | Keeps as 1 issue (atomic change, splitting would break things) |

Decomposition only happens when subtasks can genuinely run in parallel with non-overlapping file scopes.

## Parallel execution

When decomposing, independent subtasks trigger simultaneously:

```
Refinement creates 3 issues at t=0

  Claude instance A → PR #44 (avatar endpoint)     ← parallel
  Claude instance B → PR #45 (storage service)     ← parallel
  Claude instance C → PR #46 (profile UI)          ← waits for A & B
```

The Sync Agent tracks progress and transitions the parent ticket when all subtasks merge.

## Project structure

```
devflow-kit/
├── .github/workflows/
│   ├── refine.yml              ← Refinement Agent workflow
│   ├── sync.yml                ← Sync Agent (polls PRs every 15min)
│   └── dependency-chain.yml    ← Sequential subtask dispatch
├── agents/
│   ├── refine.py               ← Refinement Agent logic
│   ├── sync.py                 ← Sync Agent logic
│   ├── sync_poll.py            ← PR polling for sync
│   ├── dependency_chain.py     ← Sequential dependency handler
│   └── utils/
│       ├── config.py           ← Config + repo routing
│       ├── jira.py             ← Jira API client
│       ├── github.py           ← GitHub API client
│       └── claude.py           ← Claude Code CLI wrapper
├── prompts/
│   ├── refine.md               ← Refinement prompt template
│   └── issue-body.md           ← GitHub issue template
├── schemas/
│   └── refinement-output.json  ← Output validation schema
├── repo-map.json               ← Route config (edit this)
├── pyproject.toml
└── tests/
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check .
ruff format .
```

## Improving output quality

Add a `CLAUDE.md` file to your target repos. This is optional but significantly improves Claude's implementation quality. It should describe:

- Tech stack and versions
- Project structure
- Coding conventions
- Testing approach
- Key patterns to follow

The refinement agent reads this file (via the GitHub API) when analyzing tickets.

## License

MIT — see [LICENSE](LICENSE).
