.PHONY: help check setup setup-secrets setup-jira install lint format test test-verbose clean validate dev env run-refinement run-implementation

# Default target
help: ## Show this help
	@echo "DevFlow Kit — Setup & Development Commands"
	@echo ""
	@echo "FIRST TIME SETUP:"
	@echo "  make check          Check all prerequisites are installed"
	@echo "  make setup          Full setup (install + secrets + validate)"
	@echo ""
	@echo "INDIVIDUAL SETUP STEPS:"
	@echo "  make install        Install Python and Node dependencies"
	@echo "  make setup-secrets  Configure GitHub and Jira secrets on this repo"
	@echo "  make setup-jira     Print Jira Automation rule config to copy-paste"
	@echo "  make validate       Verify everything is configured correctly"
	@echo ""
	@echo "DEVELOPMENT:"
	@echo "  make test           Run all tests"
	@echo "  make test-verbose   Run tests with verbose output"
	@echo "  make lint           Run linter"
	@echo "  make format         Auto-format code"
	@echo "  make dev            Install dev dependencies + run tests + lint"
	@echo ""
	@echo "LOCAL RUNS:"
	@echo "  make env              Create .env from .env.example (first time)"
	@echo "  make run-refinement   Run the refinement agent locally"
	@echo "  make run-implementation Run the implementation agent locally"
	@echo ""
	@echo "OTHER:"
	@echo "  make test-dispatch  Send a test event to trigger the refinement agent"
	@echo "  make clean          Remove caches and build artifacts"

# ============================================================
# Prerequisites check
# ============================================================

check: ## Check all prerequisites are installed
	@echo "Checking prerequisites..."
	@echo ""
	@printf "Python 3.12+:  " && python3 --version 2>/dev/null || (echo "MISSING — install from python.org" && exit 1)
	@printf "Node.js 18+:   " && node --version 2>/dev/null || (echo "MISSING — install from nodejs.org" && exit 1)
	@printf "npm:           " && npm --version 2>/dev/null || (echo "MISSING — comes with Node.js" && exit 1)
	@printf "gh CLI:        " && gh --version 2>/dev/null | head -1 || (echo "MISSING — install from cli.github.com" && exit 1)
	@printf "Claude Code:   " && claude --version 2>/dev/null || (echo "MISSING — run: npm install -g @anthropic-ai/claude-code" && exit 1)
	@echo ""
	@echo "✅ All prerequisites installed."

# ============================================================
# Full setup
# ============================================================

setup: check env install setup-secrets validate ## Full first-time setup
	@echo ""
	@echo "============================================"
	@echo "✅ DevFlow Kit is ready!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Run 'make setup-jira' to get the Jira Automation rule config"
	@echo "  2. Create the rule in Jira (Project Settings → Automation)"
	@echo "  3. Move a ticket to 'To Refine' and watch the magic"
	@echo "============================================"

# ============================================================
# Install dependencies
# ============================================================

install: ## Install Python dependencies using uv
	@echo "Installing Python dependencies..."
	uv sync --all-extras
	@echo ""
	@echo "Installing Claude Code CLI..."
	npm install -g @anthropic-ai/claude-code
	@echo ""
	@echo "✅ Dependencies installed."

# ============================================================
# Secret configuration
# ============================================================

REPO := $(shell gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)

setup-secrets: ## Configure GitHub secrets on this repo (interactive)
	@echo "Setting up secrets for: $(REPO)"
	@echo ""
	@if [ -z "$(REPO)" ]; then \
		echo "ERROR: Not in a GitHub repo or gh CLI not authenticated."; \
		echo "Run: gh auth login"; \
		exit 1; \
	fi
	@echo "Step 1/5: Claude Code OAuth Token"
	@echo "  Run 'claude setup-token' in another terminal if you haven't already."
	@echo "  Paste the token (starts with sk-ant-oat01-):"
	@read -r CLAUDE_TOKEN && \
		gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo $(REPO) --body "$$CLAUDE_TOKEN" && \
		echo "  ✅ CLAUDE_CODE_OAUTH_TOKEN set"
	@echo ""
	@echo "Step 2/5: GitHub Fine-Grained PAT"
	@echo "  Create one at: https://github.com/settings/personal-access-tokens/new"
	@echo "  Permissions: Contents (R/W), Issues (R/W), Pull Requests (R/W), Metadata (R)"
	@echo "  Scope: select the repos you want DevFlow Kit to access"
	@echo "  Paste the PAT (starts with github_pat_):"
	@read -r GH_PAT && \
		gh secret set GITHUB_PAT --repo $(REPO) --body "$$GH_PAT" && \
		echo "  ✅ GITHUB_PAT set"
	@echo ""
	@echo "Step 3/5: Jira Base URL"
	@echo "  Example: https://your-domain.atlassian.net"
	@read -rp "  URL: " JIRA_URL && \
		gh secret set JIRA_BASE_URL --repo $(REPO) --body "$$JIRA_URL" && \
		echo "  ✅ JIRA_BASE_URL set"
	@echo ""
	@echo "Step 4/5: Jira User Email"
	@echo "  The email of the Jira account (bot or personal) that will post comments."
	@read -rp "  Email: " JIRA_EMAIL && \
		gh secret set JIRA_USER_EMAIL --repo $(REPO) --body "$$JIRA_EMAIL" && \
		echo "  ✅ JIRA_USER_EMAIL set"
	@echo ""
	@echo "Step 5/5: Jira API Token"
	@echo "  Create one at: https://id.atlassian.com/manage-profile/security/api-tokens"
	@echo "  Paste the token:"
	@read -r JIRA_TOKEN && \
		gh secret set JIRA_API_TOKEN --repo $(REPO) --body "$$JIRA_TOKEN" && \
		echo "  ✅ JIRA_API_TOKEN set"
	@echo ""
	@echo "✅ All secrets configured for $(REPO)."

# ============================================================
# Jira Automation rule config
# ============================================================

setup-jira: ## Print Jira Automation rule config
	@if [ -z "$(REPO)" ]; then \
		echo "ERROR: Not in a GitHub repo. Run from the repo root."; \
		exit 1; \
	fi
	@echo "============================================"
	@echo "Jira Automation Rule — Copy this config"
	@echo "============================================"
	@echo ""
	@echo "Go to: Jira → Project Settings → Automation → Create Rule"
	@echo ""
	@echo "WHEN: Issue transitioned to 'To Refine'"
	@echo ""
	@echo "THEN: Send web request"
	@echo "  URL:     https://api.github.com/repos/$(REPO)/dispatches"
	@echo "  Method:  POST"
	@echo "  Headers:"
	@echo "    Authorization: Bearer <YOUR_GITHUB_PAT>"
	@echo "    Accept: application/vnd.github+json"
	@echo ""
	@echo "  Body (Custom data):"
	@echo '  {'
	@echo '    "event_type": "devflow-refine",'
	@echo '    "client_payload": {'
	@echo '      "issue_key": "{{issue.key}}",'
	@echo '      "project_key": "{{project.key}}",'
	@echo '      "component": "{{issue.components.name}}",'
	@echo '      "summary": "{{issue.summary}}",'
	@echo '      "description": "{{issue.description}}"'
	@echo '    }'
	@echo '  }'
	@echo ""
	@echo "============================================"
	@echo "Replace <YOUR_GITHUB_PAT> with the same PAT"
	@echo "you used in 'make setup-secrets'."
	@echo "============================================"

# ============================================================
# Validation
# ============================================================

validate: ## Verify configuration is correct
	@echo "Validating setup..."
	@echo ""
	@echo "1. Checking repo-map.json..."
	@python3 -c "import json; d=json.load(open('repo-map.json')); \
		routes=d.get('routes',[]); defaults=d.get('defaults',{}); \
		print(f'   Routes: {len(routes)} configured'); \
		print(f'   Default repo: {defaults.get(\"github_repo\", \"NOT SET\")}'); \
		[print(f'   → {r[\"jira_project\"]}/{r.get(\"component\",\"*\")} → {r[\"github_repo\"]}') for r in routes]"
	@echo ""
	@echo "2. Checking MCP config..."
	@python3 -c "import json; d=json.load(open('.claude/settings.json')); \
		servers=d.get('mcpServers',{}); \
		print(f'   MCP servers: {list(servers.keys())}'); \
		[print(f'   → {k}: {v[\"command\"]} {\" \".join(v[\"args\"])}') for k,v in servers.items()]"
	@echo ""
	@echo "3. Checking secrets are set..."
	@if [ -n "$(REPO)" ]; then \
		echo "   Secrets on $(REPO):"; \
		gh secret list --repo $(REPO) 2>/dev/null | while read line; do \
			echo "   ✅ $$line"; \
		done || echo "   ⚠️  Could not list secrets (need admin access)"; \
	else \
		echo "   ⚠️  Not in a GitHub repo — skipping secret check"; \
	fi
	@echo ""
	@echo "4. Running tests..."
	@python3 -m pytest tests/ -q
	@echo ""
	@echo "✅ Validation complete."

# ============================================================
# Test dispatch (sends a real event)
# ============================================================

test-dispatch: ## Send a test refinement event to the hub
	@if [ -z "$(REPO)" ]; then \
		echo "ERROR: Not in a GitHub repo."; \
		exit 1; \
	fi
	@echo "Sending test devflow-refine event to $(REPO)..."
	@echo ""
	@read -rp "GitHub PAT (for auth): " PAT && \
	read -rp "Jira project key (e.g., MYPROJ): " PROJECT && \
	read -rp "Component (e.g., backend): " COMPONENT && \
	read -rp "Test issue key (e.g., MYPROJ-999): " ISSUE && \
	read -rp "Summary: " SUMMARY && \
	HTTP_CODE=$$(curl -s -o /dev/null -w "%{http_code}" \
		-X POST \
		-H "Authorization: Bearer $$PAT" \
		-H "Accept: application/vnd.github+json" \
		"https://api.github.com/repos/$(REPO)/dispatches" \
		-d "{\"event_type\":\"devflow-refine\",\"client_payload\":{\"issue_key\":\"$$ISSUE\",\"project_key\":\"$$PROJECT\",\"component\":\"$$COMPONENT\",\"summary\":\"$$SUMMARY\",\"description\":\"Test ticket from make test-dispatch\"}}") && \
	if [ "$$HTTP_CODE" = "204" ]; then \
		echo ""; \
		echo "✅ Dispatched (HTTP 204). Check:"; \
		echo "   https://github.com/$(REPO)/actions"; \
	else \
		echo ""; \
		echo "❌ HTTP $$HTTP_CODE — check PAT permissions."; \
	fi

# ============================================================
# Local environment
# ============================================================

env: ## Create .env from .env.example (skips if .env already exists)
	@if [ -f .env ]; then \
		echo "✅ .env already exists — skipping. Edit it manually if needed."; \
	else \
		cp .env.example .env; \
		echo "✅ .env created from .env.example."; \
		echo ""; \
		echo "👉 Open .env and fill in your credentials before running agents."; \
	fi

run-refinement: ## Run the refinement agent locally (loads .env automatically)
	@test -f .env || (echo "❌ .env not found. Run: make env" && exit 1)
	@echo "Loading .env and running refinement agent..."
	set -a && . ./.env && set +a && uv run python run_agent.py refinement

run-implementation: ## Run the implementation agent locally (loads .env automatically)
	@test -f .env || (echo "❌ .env not found. Run: make env" && exit 1)
	@echo "Loading .env and running implementation agent..."
	set -a && . ./.env && set +a && uv run python run_agent.py implementation

# ============================================================
# Development
# ============================================================

test: ## Run tests
	python3 -m pytest tests/ -q

test-verbose: ## Run tests with verbose output
	python3 -m pytest tests/ -v

lint: ## Run linter
	python3 -m ruff check .

format: ## Auto-format code
	python3 -m ruff format .
	python3 -m ruff check . --fix

dev: install test lint ## Install + test + lint
	@echo "✅ Dev environment ready."

clean: ## Remove caches and build artifacts
	rm -rf __pycache__ */__pycache__ */*/__pycache__
	rm -rf .pytest_cache .ruff_cache
	rm -rf *.egg-info dist build
	@echo "✅ Cleaned."
