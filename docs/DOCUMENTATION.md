# DevFlow Kit

**AI-powered SDLC agents that turn Jira tickets into production-ready pull requests — with zero infrastructure to deploy.**

DevFlow Kit is a single GitHub repository that an organisation forks once. It receives Jira webhooks, intelligently refines and (when necessary) decomposes tickets, creates GitHub issues tagged with `@claude` in the correct target repositories, and syncs PR status back to Jira. The Claude Code GitHub App — installed once at the org level — handles all implementation. Target repositories need nothing installed, configured, or maintained.

> **Design philosophy:** One repo. One setup. Zero touch on target repos. The hub thinks, the Claude Code App builds.

---

## Table of contents

1. [Naming rationale](#1-naming-rationale)
2. [Architecture overview](#2-architecture-overview)
3. [Core concepts](#3-core-concepts)
4. [Org setup (one time)](#4-org-setup-one-time)
5. [Agent system design](#5-agent-system-design)
6. [Agent catalog](#6-agent-catalog)
7. [Smart decomposition](#7-smart-decomposition)
8. [Parallel execution](#8-parallel-execution)
9. [Jira integration](#9-jira-integration)
10. [Multi-repo routing](#10-multi-repo-routing)
11. [Authentication and secrets](#11-authentication-and-secrets)
12. [Configuration reference](#12-configuration-reference)
13. [Error handling and observability](#13-error-handling-and-observability)
14. [Cost model](#14-cost-model)
15. [Security model](#15-security-model)
16. [Extending DevFlow Kit](#16-extending-devflow-kit)
17. [Roadmap](#17-roadmap)
18. [Glossary](#18-glossary)

---

## 1. Naming rationale

**DevFlow Kit** was chosen for specific reasons:

- **Dev** — anchored in software development, not generic automation
- **Flow** — implies movement through stages (ticket → spec → code → PR → done), extensible to any workflow phase
- **Kit** — a toolkit of composable parts, not a monolithic framework

**Why this name scales:** Adding a QA agent means adding a new "flow stage," not renaming the project. `devflow-kit/agents/qa-agent` reads naturally. So does `devflow-kit/agents/security-scan-agent` or `devflow-kit/agents/release-notes-agent`.

**Alternative names considered:**

| Name | Why considered | Why not chosen |
|------|---------------|----------------|
| `sprint-agents` | Clear connection to agile | Too Jira-specific; breaks if someone uses Linear |
| `agentflow` | Clean, short | Too generic; could be any agent framework |
| `sdlc-pilot` | Descriptive | "Pilot" implies single driver, not a kit of tools |
| `spec-to-pr` | Exactly describes v1 | Doesn't scale to QA, testing, decomposition |

---

## 2. Architecture overview

### 2.1 The two components

DevFlow Kit has exactly two moving parts:

| Component | What it is | Who sets it up |
|-----------|-----------|----------------|
| **Hub repo** | A GitHub repo forked into the org. Contains all workflows, all agent logic, all configuration. | Org admin, once. |
| **Claude Code GitHub App** | Anthropic's official GitHub App. Installed on the org. Responds to `@claude` on issues. | Org admin, once. |

Target repositories need nothing — no workflow files, no secrets, no config, no CLAUDE.md (though having one improves quality). They are completely passive. The hub creates issues in them; the Claude Code App does the work.

### 2.2 End-to-end flow

```
1. PM creates Jira ticket: "Add user avatar feature"
       │
2. Jira Automation fires webhook → Hub repo
       │
3. Hub: Refinement Agent runs
       │  Reads the ticket
       │  Clones the target repo (read-only, to understand codebase)
       │  Decides: is this a single task or does it need decomposition?
       │
       ├── SIMPLE TICKET (no decomposition needed)
       │   │
       │   ▼
       │   Hub creates 1 GitHub issue in target repo
       │   with full spec + @claude tag
       │   │
       │   ▼
       │   Claude Code App picks it up → implements → opens PR
       │
       └── COMPLEX TICKET (decomposition needed)
           │
           ▼
           Hub creates N Jira subtasks under the parent
           Hub creates N GitHub issues (one per subtask) in target repo(s)
           each with scoped spec + @claude tag
           │
           ▼
           N Claude Code instances spin up simultaneously
           Each works on its own branch, touching only its scoped files
           Each opens its own PR
           │
           ▼
           Hub tracks all PRs → when all merge → parent Jira ticket → Done
```

### 2.3 What runs where

| What happens | Where it runs | Triggered by |
|-------------|--------------|-------------|
| Route Jira event to correct agent | Hub repo (GitHub Actions runner) | Jira webhook |
| Refinement / decomposition | Hub repo (GitHub Actions runner) | Jira webhook |
| Code implementation | Target repo (Claude Code GitHub App) | `@claude` mention on issue |
| PR → Jira sync | Hub repo (GitHub Actions runner) | GitHub webhook on PR events |

**There is no deployed application.** The hub repo is YAML files and a JSON config. GitHub Actions is the serverless runtime. The Claude Code App is hosted by Anthropic.

### 2.4 What target repos DON'T need

- No workflow files (`.github/workflows/`)
- No secrets configured
- No `.devflow/` config folder
- No CLAUDE.md (optional — improves output quality)
- No DevFlow Kit awareness of any kind
- No setup, no onboarding, no maintenance

The only requirement is that the Claude Code GitHub App has access to the repo (configured once at the org level).

---

## 3. Core concepts

### 3.1 Hub repo

The single repo that the org forks from DevFlow Kit. It contains:

- **Workflows** — GitHub Actions YAML files that run the agents
- **Agent logic** — prompt templates, output schemas, Jira/GitHub API calls
- **Routing config** — `repo-map.json` mapping Jira projects/components to GitHub repos
- **Secrets** — Claude OAuth token, GitHub PAT, Jira credentials (stored as GitHub secrets)

### 3.2 Agents

An agent is a unit of automation that handles one phase of the SDLC. All agents run in the hub repo's GitHub Actions. They read from and write to external systems (Jira, GitHub) via APIs.

### 3.3 Target repo

Any GitHub repository where code lives. It is passive — the hub creates issues in it, the Claude Code App implements code in it. From the target repo's perspective, it just sees issues being created and PRs being opened by bots.

### 3.4 `@claude` trigger

The Claude Code GitHub App responds to `@claude` mentions on GitHub issues. When it sees a mention, it reads the repo, understands the codebase, implements the requested changes, and opens a PR. This is the mechanism that lets the hub "send work" to any repo without installing anything there.

### 3.5 Agent chain

Agents chain naturally through Jira status transitions:

```
Ticket Created → [RefinementAgent] → Refined / Decomposed
    ↓ (for each subtask or for the original ticket)
Ready for Dev → [Hub creates @claude issue] → [Claude Code App implements]
    ↓
PR Opened → [SyncAgent] → Jira updated
    ↓
PR Merged → [SyncAgent] → Jira → Done
```

---

## 4. Org setup (one time)

### 4.1 Prerequisites

- A GitHub org (or personal account)
- A Jira Cloud project
- Claude Code CLI installed locally (`npm install -g @anthropic-ai/claude-code`)
- Claude Pro or Max subscription (for OAuth token)

### 4.2 Setup steps

**Step 1: Install Claude Code GitHub App on your org**

Go to [github.com/apps/claude](https://github.com/apps/claude) and install it on your organisation. When prompted for repository access, select the repos you want DevFlow Kit to work with (your 100 out of 1000). This can be changed later.

**Step 2: Fork DevFlow Kit**

Click "Use this template" on the DevFlow Kit repo. This creates `your-org/devflow-hub`. This is the only repo you create.

**Step 3: Generate credentials**

```bash
# Generate Claude OAuth token (valid ~1 year)
claude setup-token
# Copy the token: sk-ant-oat01-xxxxx...

# Create a fine-grained GitHub PAT:
# → github.com/settings/personal-access-tokens/new
# → Repository access: select your target repos
# → Permissions: Contents (R/W), Issues (R/W), Pull requests (R/W), Metadata (R)
# → Generate and copy
```

**Step 4: Add secrets to the hub repo**

Go to `your-org/devflow-hub` → Settings → Secrets and variables → Actions:

| Secret | Value |
|--------|-------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Token from `claude setup-token` |
| `GITHUB_PAT` | Fine-grained PAT from Step 3 |
| `JIRA_BASE_URL` | `https://your-domain.atlassian.net` |
| `JIRA_USER_EMAIL` | Bot account email |
| `JIRA_API_TOKEN` | Jira API token |

**Step 5: Configure repo-map.json**

Edit `repo-map.json` in the hub repo to map your Jira projects/components to GitHub repos:

```json
{
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

**Step 6: Create Jira Automation rules**

Create one Jira Automation rule:

```
WHEN: Issue transitioned to "To Refine"
THEN: Send web request
  URL:     https://api.github.com/repos/your-org/devflow-hub/dispatches
  Method:  POST
  Headers:
    Authorization: Bearer {GITHUB_PAT}
    Accept: application/vnd.github+json
  Body:
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

### 4.3 Enrolling a new repo

When you want DevFlow Kit to work on a new repo:

1. Add the repo to the Claude Code GitHub App's access list (org settings)
2. Add the repo to your GitHub PAT's repository scope
3. Add one entry to `repo-map.json`

No changes to the target repo. No PRs. No files.

### 4.4 Removing a repo

Delete its entry from `repo-map.json`. Optionally remove it from the Claude Code App's access list and the PAT scope.

---

## 5. Agent system design

### 5.1 All agents run in the hub

Every agent runs as a GitHub Actions workflow inside the hub repo. No agent logic exists in target repos. The hub is the brain; target repos are just codebases that receive work.

### 5.2 Agent interface

Every agent receives the same inputs and produces outputs that feed into the next stage:

**Inputs** (from Jira webhook payload):
- `issue_key` — Jira ticket key (e.g., PROJ-100)
- `project_key` — Jira project (e.g., MYPROJ)
- `component` — Jira component (maps to target repo)
- `summary` — ticket title
- `description` — ticket body

**Outputs** (vary by agent):
- Jira comments and status transitions
- GitHub issues (with `@claude` tags)
- Jira subtask creation
- PR tracking and sync

### 5.3 Agent lifecycle

```
Hub receives Jira webhook
    → Determine which agent to run (from event_type)
    → Agent reads ticket details
    → Agent resolves target repo from repo-map.json
    → Agent does its work (refine, create issues, sync)
    → Agent updates Jira (comment, transition, subtask creation)
    → Done — runner torn down
```

---

## 6. Agent catalog

### 6.1 RefinementAgent

**Purpose:** The single entry point for all tickets. Analyzes the ticket, refines it into a technical spec, decides whether decomposition is needed, and creates the appropriate GitHub issues.

**Trigger:** `repository_dispatch` event `devflow-refine` (from Jira Automation)

**What it does:**

1. Reads the Jira ticket summary and description
2. Resolves the target repo from `repo-map.json`
3. Clones the target repo (read-only) to understand the codebase
4. Analyzes the ticket and makes a decision:

   **Decision A — Simple ticket (no decomposition):**
   - Generates a technical spec (approach, files to change, acceptance criteria)
   - Creates one GitHub issue in the target repo with the spec + `@claude`
   - Creates one Jira subtask (if desired) or updates the original ticket
   - Posts spec as Jira comment, transitions to "In Progress"

   **Decision B — Complex ticket (decomposition needed):**
   - Breaks the ticket into N subtasks with non-overlapping file scopes
   - Creates N Jira subtasks under the parent
   - Creates N GitHub issues (one per subtask) with scoped specs + `@claude`
   - Posts decomposition summary to parent Jira ticket
   - Transitions parent to "Decomposed"

   **Decision C — Ticket is already clear and small enough:**
   - Creates one GitHub issue directly with `@claude` — no additional refinement
   - Not every ticket needs a rewrite

5. The Claude Code GitHub App picks up every `@claude` issue independently

**When it does NOT decompose:**

The refinement agent is conservative about decomposition. It only breaks a ticket down when there is a clear benefit. Specifically, it decomposes when:

- The ticket explicitly spans multiple concerns that would produce a messy single PR (e.g., "Add avatar feature" = API endpoint + storage service + UI component)
- The estimated change set touches more than 5-7 files across different modules
- The ticket spans multiple repositories

It does NOT decompose when:

- The ticket is already small and focused ("Fix the 500 error on /api/users")
- The ticket is one logical unit even if it touches several files ("Add pagination to the list endpoint" — touches route, service, model, test, but they're all one coherent change)
- Decomposition would create subtasks that depend on each other so heavily they can't be done in parallel anyway
- The ticket is a refactor or cleanup that should be atomic

The goal is not to always break things down. The goal is to break things down only when doing so enables parallel work or produces cleaner PRs.

**Structured output schema:**

```json
{
  "decision": "direct | refine | decompose",
  "reasoning": "string — why this decision was made",

  "spec": {
    "overview": "string",
    "technical_approach": "string",
    "acceptance_criteria": ["string"],
    "files_to_modify": ["string"],
    "files_to_create": ["string"],
    "complexity": "S|M|L"
  },

  "subtasks": [
    {
      "summary": "string",
      "description": "string — full spec for this subtask",
      "scope": ["file paths this subtask should touch"],
      "acceptance_criteria": ["string"],
      "target_repo": "org/repo — if different from parent",
      "depends_on": [],
      "can_parallelize": true
    }
  ]
}
```

When `decision` is `direct` or `refine`, `subtasks` is empty — one issue is created. When `decision` is `decompose`, `subtasks` contains the breakdown.

**How the `@claude` issue is constructed:**

The hub creates a GitHub issue in the target repo with this structure:

```markdown
## Jira Ticket
[PROJ-100](https://your-domain.atlassian.net/browse/PROJ-100)

## Summary
Add user avatar upload endpoint

## Technical Spec
### Overview
Create a new POST endpoint for avatar uploads with S3 storage.

### Files to modify
- `app/api/routes/users.py` — add upload route
- `app/models/user.py` — add avatar_url field

### Files to create
- `app/services/avatar.py` — upload logic
- `tests/test_avatar.py` — tests

### Acceptance Criteria
- Given a valid PNG/JPG under 5MB, upload succeeds and returns URL
- Given an oversized file, returns 413
- Given an invalid format, returns 422

## Scope
Only modify the files listed above. Do not change other files.

@claude implement this following the spec above.
Commit messages should be prefixed with PROJ-100.
```

---

### 6.2 SyncAgent

**Purpose:** Keep Jira in sync with GitHub PR lifecycle events.

**Trigger:** GitHub webhook on PR events in target repos. The hub repo receives these webhooks via a workflow triggered by `repository_dispatch` (the Claude Code App or GitHub can be configured to notify the hub), or via a scheduled polling workflow that checks for PR activity on tracked issues.

**What it does:**

1. Detects PR events (opened, merged, closed) related to tracked Jira tickets
2. Extracts Jira issue key from PR title, branch name, or body
3. Updates Jira:
   - **PR opened:** Comments with PR link, transitions to "In Review"
   - **PR merged:** Comments confirmation, transitions to "Done"
   - **PR closed without merge:** Comments warning
4. For decomposed tickets: tracks progress across all subtasks
   - When a subtask PR merges → transitions that subtask to "Done"
   - Checks if all sibling subtasks are done
   - When all done → transitions parent ticket to "Done"

**Parent ticket tracking:**

The SyncAgent maintains awareness of parent-subtask relationships. When it processes a merged PR for a subtask, it:

1. Queries Jira for the parent ticket
2. Queries all sibling subtasks
3. If all are "Done," transitions the parent
4. If not, posts a progress update:

```
🔄 Subtask progress: 2/3 complete

✅ PROJ-101: Avatar upload endpoint — PR #44 merged
✅ PROJ-102: S3 storage service — PR #45 merged
⏳ PROJ-103: Profile UI component — PR #46 in review
```

---

### 6.3 QAAgent (future — v2)

**Purpose:** Validate PRs against acceptance criteria before human review.

**Trigger:** PR opened by Claude Code App

**Planned capabilities:**
- Read acceptance criteria from the GitHub issue that spawned the PR
- Review the diff against those criteria
- Run test suite and verify coverage
- Post a QA review comment on the PR (approve or request changes)

Implementation: The hub creates a review comment via the GitHub API, or posts a new `@claude` comment on the PR with QA instructions. The Claude Code App can respond to PR comments too, so it would run a second pass focused on validation.

---

### 6.4 SecurityAgent (future — v3)

**Purpose:** Scan PRs for vulnerabilities and credential leaks.

---

### 6.5 ReleaseNotesAgent (future — v3)

**Purpose:** Auto-generate release notes from merged PRs.

---

## 7. Smart decomposition

### 7.1 Decision framework

The refinement agent uses a structured decision process:

```
Read ticket → Understand codebase
    │
    ├── Is the ticket already a clear, small task?
    │   YES → decision: "direct"
    │         Create 1 GitHub issue with @claude, minimal refinement
    │
    ├── Is the ticket clear but needs technical detailing?
    │   YES → decision: "refine"
    │         Write a full spec, create 1 GitHub issue with @claude
    │
    └── Is the ticket large, multi-concern, or multi-repo?
        YES → Does decomposition enable parallel work?
              YES → decision: "decompose"
              NO  → decision: "refine" (keep it as one coherent change)
```

### 7.2 Decomposition rules

When the agent decides to decompose, it follows these rules:

**Rule 1: Non-overlapping file scopes.**
Each subtask must touch a distinct set of files. If two subtasks need to modify the same file, they cannot run in parallel. The agent either merges them into one subtask or structures the work so the shared file is only modified by one subtask.

**Rule 2: Interface-first for dependencies.**
When subtask B depends on subtask A's output (e.g., frontend needs an API that backend is building), the agent defines the interface contract in subtask B's spec. This way Claude can code against the interface without waiting for subtask A's PR to merge.

Example:
```
Subtask A (backend): "Create POST /api/avatar → returns {url: string}"
Subtask B (frontend): "Call POST /api/avatar. API contract: POST /api/avatar,
                       body: multipart/form-data, response: {url: string}.
                       Implement against this contract."
```

**Rule 3: Minimal subtask count.**
Fewer subtasks = less coordination overhead. The agent prefers 2-3 subtasks over 5-6. If a ticket can be done in 2 subtasks covering 80% of the parallelism benefit, that's better than 5 subtasks with diminishing returns.

**Rule 4: Each subtask produces a mergeable PR.**
Every subtask must result in a PR that can be merged independently without breaking the codebase. No subtask should leave the codebase in a broken state if merged alone. This means each subtask includes its own tests.

**Rule 5: Same-repo subtasks share a branch naming convention.**
Branch names follow `claude/{subtask-key}` (e.g., `claude/PROJ-101`, `claude/PROJ-102`). Since file scopes don't overlap, merge conflicts are avoided.

### 7.3 Examples

**Example 1: Simple bug fix — NO decomposition**

```
Ticket: "Fix 500 error when user has no email"
Decision: direct
Reasoning: Single file fix, clear problem, no benefit to decomposition.
→ Creates 1 GitHub issue with @claude
```

**Example 2: Feature with clear scope — Refine only, NO decomposition**

```
Ticket: "Add pagination to /api/users endpoint"
Decision: refine
Reasoning: Touches route, service, model, and tests — but it's one coherent
           change. Splitting it would create dependencies between subtasks
           with no parallelism benefit.
→ Creates 1 GitHub issue with full spec + @claude
```

**Example 3: Multi-concern feature — Decomposition**

```
Ticket: "Add user avatar feature"
Decision: decompose
Reasoning: Three independent concerns — storage backend, API endpoint,
           frontend display. Each can be built and tested independently.
           Frontend can code against the API contract without waiting.

Subtasks:
  1. "Avatar storage service" → app/services/storage.py, app/core/s3.py
  2. "Avatar upload endpoint" → app/api/avatar.py, app/models/user.py
  3. "Avatar display in profile" → src/components/Profile.tsx (different repo)

→ Creates 3 GitHub issues across 2 repos, each with @claude
→ Claude Code App spawns 3 instances simultaneously
```

**Example 4: Cross-repo feature — Decomposition**

```
Ticket: "Add real-time notifications"
Decision: decompose
Reasoning: Requires backend WebSocket service, frontend notification component,
           and mobile push notification handler. Three different repos.

Subtasks:
  1. "WebSocket notification service" → your-org/backend-api
  2. "Notification bell component" → your-org/web-app
  3. "Push notification handler" → your-org/mobile-app

→ Creates 3 GitHub issues in 3 different repos, each with @claude
→ 3 independent Claude Code instances across 3 repos
```

**Example 5: Large refactor — NO decomposition despite size**

```
Ticket: "Migrate from SQLAlchemy to SQLModel across all models"
Decision: refine
Reasoning: Even though this touches 20+ files, it's one atomic change.
           Splitting it would leave the codebase in an inconsistent state
           where some models use SQLAlchemy and others use SQLModel.
           Must be one PR.
→ Creates 1 GitHub issue with comprehensive spec + @claude
```

---

## 8. Parallel execution

### 8.1 How it works

The Claude Code GitHub App automatically spawns a separate instance for each `@claude` issue. When the refinement agent creates 3 issues simultaneously, 3 Claude instances spin up on 3 separate GitHub Actions runners. They run in parallel with no awareness of each other.

```
RefinementAgent creates 3 issues at t=0

  t=0   Issue #31 @claude → Claude instance A starts
  t=0   Issue #32 @claude → Claude instance B starts
  t=0   Issue #33 @claude → Claude instance C starts

  t=5m  Instance A finishes → PR #44 opened
  t=8m  Instance B finishes → PR #45 opened
  t=12m Instance C finishes → PR #46 opened

  All 3 ran simultaneously. Total wall time: 12 minutes.
  Sequential would have been: 25 minutes.
```

### 8.2 Branch isolation

Each Claude instance creates its own branch:
- `claude/PROJ-101` (subtask 1)
- `claude/PROJ-102` (subtask 2)
- `claude/PROJ-103` (subtask 3)

Because the refinement agent enforces non-overlapping file scopes, these branches modify different files. When merged to `main`, there are no conflicts.

### 8.3 What if there ARE dependencies?

When subtask B depends on subtask A, the refinement agent handles it by:

1. Marking `"can_parallelize": false` on subtask B
2. Including the interface contract in subtask B's spec
3. NOT creating subtask B's GitHub issue immediately

Instead, the hub monitors subtask A's PR. When it merges, the hub then creates subtask B's issue. This creates a sequential chain for dependent work while keeping independent work parallel.

```
Parallel group 1 (independent):
  Issue #31: Avatar storage service     → Claude instance A → PR #44
  Issue #32: Avatar upload endpoint     → Claude instance B → PR #45

Sequential (depends on group 1):
  [Wait for PR #44 and #45 to merge]
  Issue #33: Avatar display in profile  → Claude instance C → PR #46
```

### 8.4 Concurrency limits

GitHub Actions concurrency limits per plan:

| Plan | Concurrent jobs |
|------|----------------|
| Free | 20 |
| Pro/Team | 40 |
| Enterprise | 180 |

The Claude Code GitHub App runs on GitHub's infrastructure, so it counts against the target repo's org limits. For most use cases (3-5 parallel subtasks), this is well within bounds.

---

## 9. Jira integration

### 9.1 Required Jira workflow statuses

Minimal set (you can rename these to match your existing workflow):

| Status | Purpose | Set by |
|--------|---------|--------|
| To Refine | Ticket ready for AI analysis | Human (transitions ticket) |
| In Progress | Claude is working on it | RefinementAgent |
| In Review | PR opened | SyncAgent |
| Done | PR merged | SyncAgent |

Extended set (for decomposition):

| Status | Purpose | Set by |
|--------|---------|--------|
| Decomposed | Parent broken into subtasks | RefinementAgent |
| Blocked | Subtask waiting on dependency | RefinementAgent |

### 9.2 Jira Automation rules

Only ONE rule is required:

**Rule: Trigger refinement**
```
WHEN:  Issue transitioned to "To Refine"
THEN:  Send web request
       URL:    https://api.github.com/repos/{ORG}/{HUB_REPO}/dispatches
       Method: POST
       Headers:
         Authorization: Bearer {GITHUB_PAT}
         Accept: application/vnd.github+json
       Body:
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

That's it. One rule. The refinement agent handles everything downstream — decomposition, issue creation, and chaining.

### 9.3 Jira API operations

| Operation | Used by | Purpose |
|-----------|---------|---------|
| Add comment | RefinementAgent, SyncAgent | Post specs, status updates, PR links |
| Transition issue | RefinementAgent, SyncAgent | Move ticket through statuses |
| Create subtask | RefinementAgent | Create child tickets for decomposition |
| Get issue | RefinementAgent | Read full ticket details |
| Get subtasks | SyncAgent | Check if all subtasks are done |
| Update description | RefinementAgent | Replace rough description with refined spec |

---

## 10. Multi-repo routing

### 10.1 How routing works

The hub reads `repo-map.json` and matches the Jira ticket's `project_key` + `component` to a GitHub repo:

1. **Exact match**: project + component found → use that route
2. **Project default**: project matches, no component match → use defaults
3. **Global default**: nothing matches → use global default repo

### 10.2 repo-map.json (full schema)

```json
{
  "$schema": "https://devflow-kit.dev/schemas/repo-map.v1.json",
  "version": "1",

  "routes": [
    {
      "jira_project": "MYPROJ",
      "component": "backend",
      "github_repo": "your-org/backend-api",
      "default_branch": "main"
    },
    {
      "jira_project": "MYPROJ",
      "component": "frontend",
      "github_repo": "your-org/web-app",
      "default_branch": "main"
    },
    {
      "jira_project": "MYPROJ",
      "component": "mobile",
      "github_repo": "your-org/mobile-app",
      "default_branch": "develop"
    },
    {
      "jira_project": "PLATFORM",
      "component": "infra",
      "github_repo": "your-org/infrastructure",
      "default_branch": "main"
    }
  ],

  "defaults": {
    "github_repo": "your-org/backend-api",
    "default_branch": "main"
  }
}
```

### 10.3 Cross-repo tickets

When the refinement agent decomposes a ticket into subtasks that span multiple repos, it creates issues in different repos:

```
Parent ticket: PROJ-100 "Add notification system"
  Component: not specified (spans multiple)

RefinementAgent reads the ticket, understands it needs:
  → Subtask 1: WebSocket server      → creates issue in your-org/backend-api
  → Subtask 2: Notification UI       → creates issue in your-org/web-app
  → Subtask 3: Push notifications    → creates issue in your-org/mobile-app
```

Each issue is created via the GitHub API using the PAT, which has access to all enrolled repos. The Claude Code App, installed at the org level, picks up `@claude` in all three repos.

### 10.4 Enrolling repos

Adding a new repo to DevFlow Kit:

1. Add the repo to the Claude Code GitHub App's access list (org settings → installed apps → Claude → configure → repository access)
2. Add the repo to your PAT's scope (Settings → Developer → PATs → edit → add repo)
3. Add an entry to `repo-map.json` in the hub repo

Three clicks and one line of JSON. No changes to the target repo.

---

## 11. Authentication and secrets

### 11.1 Credentials needed

| Credential | Purpose | How to get it | Stored in |
|------------|---------|---------------|-----------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Hub's refinement agent uses Claude Code | `claude setup-token` | Hub repo secrets |
| `GITHUB_PAT` | Create issues and read repos across the org | GitHub fine-grained PAT | Hub repo secrets |
| `JIRA_BASE_URL` | Jira Cloud URL | Your Atlassian URL | Hub repo secrets |
| `JIRA_USER_EMAIL` | Jira API auth | Bot account email | Hub repo secrets |
| `JIRA_API_TOKEN` | Jira API auth | id.atlassian.com/manage-profile/security/api-tokens | Hub repo secrets |

**All secrets live in one place: the hub repo.** Target repos have no secrets.

### 11.2 Claude Code GitHub App auth

The Claude Code GitHub App authenticates separately — it's installed at the org level and uses its own GitHub App credentials. You don't manage this. Anthropic does. You just install the app and it works.

The `CLAUDE_CODE_OAUTH_TOKEN` in the hub repo is only used by the refinement agent (which runs Claude Code in the hub's own workflow to analyze tickets and generate specs). The actual implementation Claude instances are managed by the GitHub App.

### 11.3 GitHub PAT scope

The PAT needs access to every enrolled target repo. Use a fine-grained PAT with:

- **Repository access**: Select only the enrolled repos (not "all repos")
- **Permissions**: Contents (R/W), Issues (R/W), Pull requests (R/W), Metadata (R)
- **Expiry**: 90 days (set a reminder to rotate)

### 11.4 Security notes

- OAuth tokens last ~1 year. Rotate via `claude setup-token`.
- PATs should expire every 90 days. Use a calendar reminder.
- Use a dedicated Jira bot account, not a personal account.
- All secrets are GitHub encrypted secrets — never visible in logs.

---

## 12. Configuration reference

### 12.1 Hub repo file structure

```
devflow-hub/
├── .github/
│   └── workflows/
│       ├── refine.yml              # RefinementAgent workflow
│       ├── sync.yml                # SyncAgent workflow (polls for PR events)
│       └── dependency-chain.yml    # Handles sequential subtask dispatch
├── repo-map.json                   # Jira component → GitHub repo mapping
├── prompts/
│   ├── refine.md                   # Default refinement prompt template
│   ├── decompose.md                # Decomposition prompt template
│   └── issue-body.md               # GitHub issue body template
├── schemas/
│   ├── refinement-output.json      # JSON schema for refinement output
│   └── repo-map.schema.json        # JSON schema for repo-map.json
├── README.md
└── LICENSE
```

### 12.2 Prompt templates

Prompt templates use `{{variable}}` placeholders that the workflow fills in:

```markdown
<!-- prompts/refine.md -->
You are a senior technical architect. Analyze this Jira ticket and the
target repository to produce a technical specification.

## Ticket
Key: {{issue_key}}
Summary: {{summary}}
Description: {{description}}

## Repository context
The repository has been checked out at the current path. Read the
README, project structure, and key files to understand the codebase.

## Your task
1. Understand what the ticket is asking for.
2. Assess complexity (S/M/L).
3. Decide: can this be done as a single PR, or should it be decomposed?

ONLY decompose if:
- The ticket spans multiple independent concerns
- Subtasks can genuinely run in parallel
- Each subtask would produce a clean, mergeable PR on its own

Do NOT decompose if:
- It's a single logical change (even if it touches many files)
- Subtasks would depend on each other too heavily
- The ticket is already small and clear

4. Output your decision as JSON matching the provided schema.
```

### 12.3 Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes* | — | Claude Code OAuth token |
| `ANTHROPIC_API_KEY` | Yes* | — | Alternative to OAuth |
| `GITHUB_PAT` | Yes | — | Fine-grained PAT for cross-repo ops |
| `JIRA_BASE_URL` | Yes | — | e.g., `https://acme.atlassian.net` |
| `JIRA_USER_EMAIL` | Yes | — | Bot account email |
| `JIRA_API_TOKEN` | Yes | — | Jira API token |

*One of `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` is required.

---

## 13. Error handling and observability

### 13.1 Failure modes

| Failure | What happens | Recovery |
|---------|-------------|----------|
| Refinement agent times out | Hub workflow fails | Jira comment: "Refinement failed" + link to Actions log |
| Claude output doesn't match schema | Retry with clarified prompt (up to 2x) | If still fails, posts error to Jira |
| GitHub issue creation fails | 401/403/404 from API | Jira comment: "Failed to create issue in {repo}" |
| Claude Code App fails on @claude | PR not opened | Hub detects timeout, posts warning to Jira |
| PAT expired | All cross-repo ops fail | Jira comment: "Auth failed — PAT may be expired" |
| Jira API error | Non-blocking — agent continues | Logged in Actions, retried once |
| Merge conflict on PR | PR still opens, shows conflict | Jira comment: "PR has conflicts, needs manual resolution" |

### 13.2 Jira is the observability layer

Every agent posts structured comments to Jira. No external monitoring needed:

- **Refinement started**: "Analyzing ticket, reading codebase..."
- **Refinement complete**: Full spec or decomposition plan
- **Issue created**: Link to GitHub issue(s)
- **Implementation in progress**: (Claude Code App shows progress on the issue itself)
- **PR opened**: Link to PR
- **PR merged**: Confirmation + status transition
- **Error**: Description + link to GitHub Actions log

### 13.3 Tracking decomposed tickets

For decomposed tickets, the parent Jira ticket becomes a dashboard:

```
🔧 Decomposed into 3 subtasks:

📋 PROJ-101: Avatar upload endpoint
   Issue: github.com/org/backend-api/issues/31
   Status: ✅ PR #44 merged

📋 PROJ-102: S3 storage service
   Issue: github.com/org/backend-api/issues/32
   Status: ✅ PR #45 merged

📋 PROJ-103: Profile UI component
   Issue: github.com/org/web-app/issues/33
   Status: ⏳ PR #46 in review

Overall: 2/3 complete
```

---

## 14. Cost model

### 14.1 Per-ticket costs

| Resource | Cost | Notes |
|----------|------|-------|
| Claude Code (refinement in hub) | $0 with subscription | Uses OAuth token from Pro/Max plan |
| Claude Code (implementation via App) | $0 with subscription | GitHub App uses your linked plan |
| GitHub Actions (hub workflows) | ~$0.008/min | Free tier: 2,000 min/month |
| Jira Automation | 1 rule execution | Free: 100/month, Standard: 500 |

### 14.2 Monthly estimates

| Scale | Tickets/week | Hub Actions min | Jira runs | Extra cost |
|-------|-------------|----------------|-----------|-----------|
| Solo dev | 5 | ~50 | ~20 | Free tier covers it |
| Small team (3-5) | 15 | ~150 | ~60 | Free tier covers it |
| Medium team (5-10) | 30 | ~300 | ~120 | ~$2/month Actions |
| Large team (10+) | 60+ | ~600 | ~240 | ~$5/month Actions |

Note: Claude Code App execution time runs on GitHub's infrastructure and counts against the org's Actions minutes for the target repo, but the App itself has generous included compute.

---

## 15. Security model

### 15.1 Principle of least privilege

- **Hub repo PAT**: Only has access to enrolled repos, not all org repos
- **Claude Code App**: Only installed on enrolled repos
- **Jira credentials**: Use a bot account with project-level access
- **Target repos**: Have no awareness of DevFlow Kit — no elevated permissions

### 15.2 What Claude Code can access

When the Claude Code App responds to `@claude` on an issue, it can:
- Read all files in that repo
- Create branches and commits
- Open pull requests
- Run CLI tools (npm, pip, etc.) on the Actions runner

It cannot:
- Access other repos
- Access secrets from other repos
- Modify branch protection rules
- Merge PRs (humans do this)

### 15.3 PR review requirement

All Claude-generated PRs should require human review. Configure branch protection rules on target repos:
- Require at least 1 approving review
- Require status checks to pass (CI)
- The `ai-generated` label (set by Claude Code App) makes these PRs easy to filter

---

## 16. Extending DevFlow Kit

### 16.1 Adding a new agent

All agents live in the hub repo. To add one:

1. **Create a workflow file** in `.github/workflows/devflow-{agent}.yml`
2. **Create a prompt template** in `prompts/{agent}.md`
3. **Add a Jira Automation rule** (if triggered by Jira status change)
4. **Document the agent** in this file

The agent follows the same pattern as existing ones: receive event → do work → update Jira.

Example: a QA agent that runs when a PR is opened:

```yaml
# .github/workflows/devflow-qa.yml
name: QA Agent
on:
  repository_dispatch:
    types: [devflow-qa]
jobs:
  qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run QA analysis
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          prompt: |
            Review PR #${{ github.event.client_payload.pr_number }}
            in ${{ github.event.client_payload.repo }}.
            Check against acceptance criteria:
            ${{ github.event.client_payload.acceptance_criteria }}
          claude_args: --max-turns 20
      # Post review to PR via GitHub API...
```

### 16.2 Supporting other project management tools

DevFlow Kit is designed for Jira, but the architecture is tool-agnostic:

- **Linear**: Replace Jira webhook with Linear webhook → same hub pattern
- **GitHub Issues as PM tool**: Skip the hub routing; trigger Claude directly via issue labels
- **Shortcut/Notion**: Same webhook → `repository_dispatch` → hub pattern

The Jira-specific code (commenting, transitions, subtask creation) is isolated in the workflow files. Swapping tools means replacing those API calls.

### 16.3 Custom prompt overrides

To customize how the refinement agent works for a specific repo, add entries to `repo-map.json`:

```json
{
  "jira_project": "MYPROJ",
  "component": "backend",
  "github_repo": "your-org/backend-api",
  "refinement_prompt": "prompts/backend-refine.md",
  "issue_template": "prompts/backend-issue.md",
  "decompose_threshold": "L",
  "max_subtasks": 5
}
```

Per-route prompt overrides let you customize agent behavior for different repos without changing the core logic.

---

## 17. Roadmap

### v1.0 — Core pipeline
- [ ] Hub repo template with routing
- [ ] RefinementAgent (with smart decomposition)
- [ ] GitHub issue creation with `@claude`
- [ ] SyncAgent (PR → Jira sync)
- [ ] Parallel subtask execution
- [ ] Parent ticket completion tracking
- [ ] Setup documentation

### v1.1 — Dependency-aware chaining
- [ ] Sequential subtask dispatch (wait for dependencies)
- [ ] Cross-repo dependency tracking
- [ ] Interface contract generation for dependent subtasks

### v2.0 — Quality assurance
- [ ] QAAgent (acceptance criteria validation)
- [ ] Auto-review PR against spec
- [ ] Test coverage check

### v2.1 — Developer experience
- [ ] Setup CLI (`npx devflow-kit-setup`)
- [ ] Slack/Teams notifications
- [ ] Dashboard (GitHub Pages — still no server)

### v3.0 — Advanced agents
- [ ] SecurityAgent (vulnerability scanning)
- [ ] ReleaseNotesAgent (changelog from merged PRs)
- [ ] DocumentationAgent (auto-update docs)
- [ ] DependencyUpdateAgent (automated dependency PRs)

### v3.1 — Platform expansion
- [ ] Linear integration
- [ ] GitLab CI support
- [ ] Alternative AI backends (OpenAI, Gemini)

---

## 18. Glossary

| Term | Definition |
|------|-----------|
| **Hub repo** | The single repo forked into the org. Contains all workflows, config, and secrets. |
| **Target repo** | Any GitHub repo where code changes happen. Completely passive — nothing installed. |
| **Refinement agent** | The primary agent. Analyzes tickets, generates specs, decides on decomposition, creates GitHub issues. |
| **Sync agent** | Watches for PR events and updates Jira accordingly. |
| **Decomposition** | Breaking a large ticket into independently implementable subtasks. Not always done. |
| **`@claude`** | Trigger phrase in GitHub issues. The Claude Code GitHub App responds to this. |
| **repo-map.json** | Config file mapping Jira project/component to GitHub repos. |
| **CLAUDE.md** | Optional file in target repos that helps Claude understand the codebase better. |
| **Scope hint** | List of files a subtask should touch. Prevents parallel subtasks from conflicting. |
| **Interface contract** | API contract included in a dependent subtask's spec so Claude can code against it without waiting. |
| **Claude Code GitHub App** | Anthropic's official GitHub App. Installed at org level. Handles all implementation. |
| **OAuth token** | Long-lived token from `claude setup-token`. Used by the hub's refinement agent. |
| **PAT** | GitHub Personal Access Token. Used by the hub to create issues and read repos. |

---

## Appendix A: Hub repo file listing

```
devflow-hub/
├── .github/
│   └── workflows/
│       ├── refine.yml                # RefinementAgent
│       ├── sync.yml                  # SyncAgent (PR tracking)
│       └── dependency-chain.yml      # Sequential subtask dispatch
├── repo-map.json                     # Routing config
├── prompts/
│   ├── refine.md                     # Refinement prompt
│   ├── decompose.md                  # Decomposition criteria
│   └── issue-body.md                 # GitHub issue template
├── schemas/
│   ├── refinement-output.json        # Output validation schema
│   └── repo-map.schema.json          # Config validation schema
├── README.md
├── DOCUMENTATION.md                  # This file
├── LICENSE
└── CONTRIBUTING.md
```

---

## Appendix B: Decision log

| Decision | Rationale | Alternatives rejected |
|----------|-----------|----------------------|
| Single hub repo | Zero setup on target repos. One place for all config and secrets. | Per-repo workflows (N repos × N files = maintenance nightmare) |
| Claude Code GitHub App for implementation | Runs natively in target repos. No cloning. No workflow files needed. Org-level install covers all repos. | Hub cloning target repos (slow, needs write access), per-repo workflow dispatch (setup per repo) |
| `@claude` on GitHub Issues | Built-in mechanism. Each issue triggers independent Claude instance. Parallel by default. | Repository dispatch to target repos (needs workflows there), GitHub Actions reusable workflows (still needs per-repo setup) |
| Smart decomposition (not always) | Over-decomposing creates coordination overhead worse than the original problem. | Always decompose (fragmented PRs), never decompose (giant PRs) |
| Jira Automation for webhooks | Built-in, no middleware, no server. One rule covers everything. | Custom Forge app (complex), standalone webhook server (infrastructure) |
| PAT for cross-repo operations | Simple, fine-grained, works with issue creation and repo reads. | GitHub App (more complex setup), SSH keys (too broad) |
| Jira as observability layer | Already open, no extra tools. PM and eng see the same status. | Dedicated dashboard (extra infra), Slack only (not persistent) |
