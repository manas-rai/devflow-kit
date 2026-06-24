# Graphify Integration Plan

Maintain a persistent [Graphify](https://graphify.net) knowledge graph for every
target repo the hub manages, so agents consume a rich, multi-language code graph
instead of (or alongside) the live AST map from `tools/repo_map.py`.

Two automated lifecycle events:

- **Onboard** — a new project is added to `repo-map.json` → build the full graph once.
- **Keep fresh** — the target repo's default branch moves (PR merge or direct push)
  → incrementally update the graph (only changed files are re-processed).

## Decisions

| Question | Choice |
|----------|--------|
| Where graphs are stored | **External object storage** (S3-compatible: AWS S3, GCS interop, Cloudflare R2, MinIO) |
| Change detection | **Poll the default-branch HEAD SHA** (pull-based — nothing installed in target repos) |
| Index depth | **Full multimodal semantics** (code + docs + diagrams) |

## Hard constraints (from DevFlow Kit's design)

1. **Target repos stay untouched** — no workflows or files in them. Change detection
   is therefore pull-based (poll the GitHub API), never a workflow in the target repo.
2. **Never block the agent** — if a graph is missing, stale, or its build failed,
   fall back to the existing `tools/repo_map.py` AST map.

## Architecture

```
ONBOARD                                  KEEP FRESH (cron ~15m)              CONSUME (agent run)
push repo-map.json                       graphify-sync.yml                   run_agent._generate_repo_map
   │                                        │ discover: HEAD sha vs store        │  engine=graphify
   ▼                                        ▼ (changed repos → matrix)           ▼
graphify-onboard.yml                     per repo:                           graph_store.read_report(repo)
 discover repos missing from store        restore cache/ from store           ├─ fresh → inject GRAPH_REPORT.md
 per repo (matrix):                       clone @ new sha                      │         + communities (decompose)
   clone --depth1 default branch          graphify (only changed files)       └─ miss/stale/err → AST fallback
   graphify (full multimodal)             upload report+cache+sha             (never blocks the agent)
   upload report+cache+sha+meta
                       └──────────────► S3-compatible bucket ◄────────────────────────┘
```

The full multimodal cost is paid **once per repo at onboard**. Merges are near-free
because the per-file `graphify-out/` cache is restored from the bucket before each
incremental run, so only changed files are re-processed.

## Object-storage layout

```
s3://<bucket>/graphs/<owner>__<repo>/
    manifest.json        # { repo, last_sha, updated_at, graphify_version, model }
    GRAPH_REPORT.md      # agent context (Community Hubs, God Nodes, Surprising Connections)
    cache/               # graphify-out/ contents — restored before incremental runs
    graph.html           # optional, human/debug
```

Per-repo `manifest.json` is the source of truth for `last_sha` — there is **no shared
global manifest**, so concurrent updates to different repos cannot clobber each other.
Repo keys are the full `owner/name`, so multiple GitHub accounts/orgs are namespaced
automatically.

## Components

| File | Status | Purpose |
|------|--------|---------|
| `tools/graph_store.py` | **new** | S3-compatible bucket I/O: manifest, report, cache up/download |
| `tools/graphify_engine.py` | **new** | Wraps the `graphify` CLI (full + incremental) |
| `tools/graphify_cli.py` | **new** | `discover` / `onboard` / `update` subcommands for the workflows |
| `.github/workflows/graphify-onboard.yml` | **new** | Build graphs for newly added repos (push + dispatch) |
| `.github/workflows/graphify-sync.yml` | *Phase 3* | Cron SHA-diff → incremental update, per-repo concurrency |
| `run_agent.py` (`_generate_repo_map`) | *Phase 4* | Fetch report from store, AST fallback |
| `agents/decomposition.py`, `prompts/decompose.md` | *Phase 5* | Cut subtasks along graph communities |
| `pyproject.toml` | **updated** | `graphify` + `storage` optional extras |

## Configuration

New secrets / env:

| Name | Purpose |
|------|---------|
| `GRAPH_STORE_BUCKET` | Target bucket name |
| `GRAPH_STORE_ENDPOINT` | Optional — for GCS interop / R2 / MinIO |
| `GRAPH_STORE_PREFIX` | Optional — key prefix (default `graphs`) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | Bucket credentials (read by boto3) |
| `GRAPHIFY_CMD` | Optional — override the `graphify` invocation |
| `GRAPHIFY_MAX_FILES` | Optional — skip onboarding/update if a repo exceeds this file count (0 = unlimited) |
| `GRAPH_STALENESS_CHECK` | Optional — set `0` to skip the live HEAD-vs-graph staleness check at consume time |

Reuses the existing model API key (multimodal semantic step) and `GH_PAT` (clone
private target repos). Per-route opt-out: set `"graph": false` on a `repo-map.json` route.

## Phasing

1. **Storage + engine + CLI + dispatch onboard** ← *this PR*.
2. **Auto-onboard** on `repo-map.json` push (discover → matrix fan-out) ← *this PR*.
3. **Incremental sync** — `graphify-sync.yml`, cache restore/save, per-repo concurrency.
4. **Consumption** — `_generate_repo_map` graphify engine behind `REPO_MAP_ENGINE`, AST fallback.
5. **Decomposition communities** — parallel-subtask boundaries from clusters.
6. **Hardening** — done: live staleness banner (`GRAPH_STALENESS_CHECK`), onboarding cost guard (`GRAPHIFY_MAX_FILES`) + token-cost logging, and an additive ticket-keyword focus pointer. **Deferred:** feature-branch indexing (indexing PR head branches is a larger feature — default-branch indexing covers merges/pushes today).

## Risks & mitigations

- **Onboard token cost (full multimodal):** one-time per repo; log token spend; per-route
  opt-out; model is configurable.
- **Large/slow repos:** matrix-per-repo isolation; generous timeout; shallow clone.
- **Cache races:** `concurrency: graphify-<repo>` serializes writers per repo; per-repo
  manifest avoids a shared mutable index.
- **Graphify maturity / unverified CLI flags:** pin the version; the wrapper invokes the
  documented bare `graphify` command (overridable via `GRAPHIFY_CMD`) and locates outputs
  by documented filenames — verify on first real run. AST fallback is always available.

## Assumptions to confirm on first run

- An S3-compatible bucket + credentials exist. The store is endpoint-configurable, so
  AWS / GCS / R2 / MinIO all work without code changes.
- "Every change" == default-branch HEAD movement (covers PR merges + direct pushes).
  Feature-branch indexing is deferred to Phase 6.
- Graphify's exact model-config env var and CLI flags are confirmed against the installed
  `graphifyy` version (the wrapper is intentionally thin to make this easy to adjust).
