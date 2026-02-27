<p align="center">
  <img src="apps/desktop/resources/icon.svg" width="80" alt="Rigovo" />
</p>

<h1 align="center">Rigovo — Virtual Engineering Team as a Service</h1>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/tests-661_passed_|_7_failing-yellow?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
  <img src="https://img.shields.io/badge/desktop-Electron_0.1.0-blueviolet?style=flat-square" />
</p>

<p align="center">
  <strong>8 AI agents. One pipeline. Production-grade code governed by deterministic quality gates.</strong>
</p>

---

> **The Matrix Vision** — Neo is the Master Agent that orchestrates everything. Morpheus is the Planner who maps the territory before Neo fights. Trinity (Rigour) is the quality conscience that never lets a bad line through. Mr. Smith is DevOps/SecOps/Governance — the adversary that keeps Neo honest, always pinching, always pushing, so Neo constantly learns and improves. Without Mr. Smith's pressure, Neo gets complacent.

---

## Table of Contents

- [What Is This](#what-is-this)
- [The Brain — How It Works](#the-brain--how-it-works)
- [The Agents — The Team](#the-agents--the-team)
- [How Agents Talk and Decide](#how-agents-talk-and-decide)
- [The Quality Loop — Mr. Smith Never Sleeps](#the-quality-loop--mr-smith-never-sleeps)
- [Memory — Neo Remembers Every Fight](#memory--neo-remembers-every-fight)
- [The Full Pipeline](#the-full-pipeline)
- [Desktop App](#desktop-app)
- [Current Status — Honest Assessment](#current-status--honest-assessment)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Architecture Deep Dive](#architecture-deep-dive)

---

## What Is This

Rigovo turns a single task description into production-ready code by assembling a **coordinated team of 8 AI agents** — each with a specific role, memory of past work, and governed by deterministic quality gates.

You describe what needs to be done. Rigovo:

1. Scans your codebase to understand the project context
2. Classifies the task (complexity, type)
3. Assembles the right team (planner → coder → parallel reviewer/security/QA → lead)
4. Executes each agent in dependency order
5. Runs quality gates after every code-producing agent
6. Lets agents retry, self-correct, or request a full replan when stuck
7. Optionally pauses for your approval before committing
8. Extracts what was learned — memory persists across tasks and projects

The result: files changed, summary, cost, token count, audit trail — all in one shot.

---

## The Brain — How It Works

### The Orchestration Engine: LangGraph DAG

The system is built on **LangGraph** — a checkpoint-based directed acyclic graph (DAG) execution engine. Every task is a graph traversal. Every node is a Python async function. Every edge is a routing decision.

```
scan_project → classify → route_team → assemble
      ↓
[Optional] plan_approval ──► REJECTED → done
      ↓ approved
execute_agent ──► quality_check
      │                │
      │          pass  ↓
      │         next agent or parallel fan-out
      │
      │          fail → retry (max 5x)
      │          fail → replan → retry once more
      │          fail → task fails
      ↓
[reviewer ║ security ║ qa] ← parallel execution
      ↓
[Optional debate] ← if reviewer requests changes, coder re-runs
      ↓
[Optional] commit_approval
      ↓
enrich → store_memory → finalize
```

**Why LangGraph?** Because checkpointing means if the process dies mid-execution, the task resumes from the last completed node — not from scratch. Every node writes its output to SQLite before the next node runs.

### The Master Agent: Neo

Neo (the Master Agent) makes **three decisions** that shape every task:

1. **Classification** (`classify_node`) — LLM call to determine `task_type` and `complexity`
   - `task_type`: feature / bug_fix / refactor / test / docs / security / devops / analysis
   - `complexity`: low / medium / high / critical
   - Reasoning stored in state for audit

2. **Routing** (`route_team_node`) — LLM call to select which team handles the task
   - Currently: `engineering` domain (8-agent pipeline)
   - Considers complexity, task type, available agents

3. **Assembly** (`assemble_node`) — Deterministic. Reads team config. Builds the execution DAG.
   - Each agent declares `depends_on: [role, ...]`
   - Computes `ready_roles` (can run now) and `blocked_roles` (dependency failed)
   - Identifies roles that can run in parallel: `{reviewer, qa, security, docs}`

### The TaskState: The Bloodstream

Every node reads from and writes to a single **TaskState dictionary**. This flows through the entire pipeline, checkpointed at every step.

| Section | What It Holds |
|---|---|
| Identity | `task_id`, `description`, `project_root`, `workspace_id` |
| Classification | `task_type`, `complexity`, `reasoning` |
| Team Config | `team_id`, `agents`, `pipeline_order`, `execution_dag`, `gates_after` |
| Execution | `current_agent_role`, `ready_roles`, `completed_roles`, `blocked_roles` |
| Outputs | `agent_outputs[role]` → summary, files_changed, tokens, cost, duration_ms |
| Inter-agent | `agent_messages` → consultation thread between agents |
| Gates | `gate_results`, `gate_history`, `fix_packets`, `retry_count` |
| Approval | `approval_status` (pending / approved / rejected), `user_feedback` |
| Budget | `cost_accumulator[agent_id]`, `budget_max_cost_per_task` |
| Memory | `memories_to_store`, `memory_context_by_role`, `memory_retrieval_log` |
| Enrichment | `enrichment_updates` → pitfalls extracted from this run |
| Debate | `debate_round`, `reviewer_feedback`, `debate_target_role` |
| Context | `project_snapshot` → tech stack, files, entry points |
| Audit | `events[]` → every significant moment, timestamped |

---

## The Agents — The Team

Eight roles. Each is a Python `Agent` entity with: system prompt, tool list, LLM model, enrichment context, `depends_on`, and output contract.

### 1. Planner — Morpheus
> "I can only show you the door, Neo. You're the one that has to walk through it."

Maps the territory before anyone writes a line of code. Reads the codebase (read-only tools), understands the task, produces a structured plan that every downstream agent receives as context.

- **Tools**: `read_file`, `search_codebase`, `list_directory`, `read_dependencies`
- **Depends on**: nothing (runs first)
- **Output**: structured plan — which files to change, why, what approach
- **Gates**: SKIPPED (no code produced)
- **Model**: Claude Sonnet

### 2. Coder — Neo
> "There is no spoon."

The central agent. Receives the planner's map, reads relevant code, implements the task. Most tokens, cost, and time go here.

- **Tools**: `read_file`, `write_file`, `list_directory`, `search_codebase`, `run_command`, `consult_agent`, `spawn_subtask`
- **Depends on**: planner
- **Output**: modified/created files, implementation summary
- **Gates**: ALWAYS RUN — file size, type hints, naming, error handling, imports, etc.
- **Retry loop**: up to 5x with fix packets if gates fail
- **Model**: Claude Opus (most capable)

### 3. Reviewer — The Oracle
> "You've already made the choice. Now you have to understand it."

Reads what the coder wrote, identifies logic errors, suggests improvements. Does not write code — critiques.

- **Tools**: `read_file`, `search_codebase`, `list_directory`
- **Depends on**: coder
- **Runs**: in parallel with security and QA
- **Output**: APPROVED or CHANGES_REQUESTED + specific feedback
- **Debate trigger**: if CHANGES_REQUESTED → coder re-runs with feedback (max 2 debate rounds)
- **Model**: Claude Sonnet

### 4. Security — Agent Smith (the constructive one)
> "Me, me, me."

Always finds problems. Scans for vulnerabilities, injection risks, auth issues, exposed secrets, insecure defaults.

- **Tools**: `read_file`, `search_codebase`, `list_directory`, `run_command`
- **Depends on**: coder
- **Runs**: in parallel with reviewer and QA
- **Output**: PASS or VULNERABILITIES_FOUND + CVE-style findings
- **Model**: Claude Sonnet

### 5. QA — Tank (the operator)
> "I'm going to need guns. Lots of guns."

Writes tests. Not reviews tests — writes them. Reads the implementation, understands contracts, produces test files.

- **Tools**: `read_file`, `write_file`, `run_command`, `search_codebase`
- **Depends on**: coder
- **Runs**: in parallel with reviewer and security
- **Output**: test files, test run results
- **Gates**: RUN (QA produces code)
- **Model**: Claude Sonnet

### 6. DevOps — Mr. Smith (infrastructure)
> "It's the sound of inevitability."

Handles deployment configuration: CI/CD, Docker, Kubernetes, GitHub Actions, IaC. Runs when task requires it.

- **Tools**: `read_file`, `write_file`, `run_command`, `list_directory`
- **Depends on**: coder, qa
- **Model**: Claude Sonnet

### 7. SRE — The Twins
> "We don't crash."

Adds observability, alerting, SLOs, runbooks. Ensures code is operable in production, not just functional.

- **Tools**: `read_file`, `write_file`, `search_codebase`
- **Depends on**: devops
- **Model**: Claude Sonnet

### 8. Tech Lead — The Architect
> "There is only one constant. Action. Reaction. Cause and effect."

Reviews the entire output across all agents — code, process, security, tests. Signs off on the final result.

- **Tools**: `read_file`, `search_codebase` (read-only)
- **Depends on**: all other agents (runs last)
- **Output**: SHIP or HOLD + reasoning
- **Gates**: SKIPPED (assessment role)
- **Model**: Claude Opus

---

## How Agents Talk and Decide

### Inter-Agent Consultation

Any agent can **consult another agent** mid-execution using the `consult_agent` tool:

```python
# Coder mid-implementation:
consult_agent(target_role="security", question="Is this JWT validation approach safe?")

# Security responds immediately:
"Use PyJWT with algorithm whitelist. Never use 'none' algorithm.
 Validate exp, iat, and iss claims. Consider refresh token rotation."

# Response injected back into coder's tool results → coder continues with this knowledge
```

Consultation policy from `rigovo.yml`:
```yaml
consultation:
  enabled: true
  max_question_chars: 1200
  max_response_chars: 1200
  allowed_targets:
    planner: [lead, security, devops]
    coder: [reviewer, security, qa]
    qa: [coder, security]
```

The full consultation thread is stored in `agent_messages` in TaskState, visible to every subsequent agent.

### The Coder ↔ Reviewer Debate

If reviewer outputs `CHANGES_REQUESTED`:

1. Reviewer's feedback injected into coder's next run as `reviewer_feedback`
2. Coder re-runs with full context of the critique
3. Coder makes changes, output re-evaluated
4. Max 2 debate rounds — then whatever coder produced is committed

Implemented via `check_parallel_postprocess()` → `prepare_debate_round()` in `edges.py`. Parallel roles (`reviewer`, `qa`, `security`, `docs`) run via `asyncio.gather`.

### The Agentic Tool Loop

Each agent runs in a **tool loop** — not one LLM call, many:

```
1. LLM receives: system_prompt + task + context + (optional fix packet)
2. LLM decides: call a tool OR produce final output
3. If tool call → execute tool → feed result back to LLM
4. Repeat until LLM stops calling tools OR safety limits hit
```

Safety limits:
- Max 25 tool call rounds per agent execution
- Idle timeout: 2 minutes
- Batch timeout: 15 minutes

Context injected into every agent (in order):
1. Base system prompt (role identity)
2. Enrichment context (learned pitfalls from past tasks)
3. Memory context (semantically similar past task learnings)
4. Project snapshot (tech stack, key files, structure)
5. Previous agents' outputs (what planner decided, what coder did)
6. Consultation thread (what agents said mid-task)
7. Fix packet (if retrying: "Fix these violations...")

---

## The Quality Loop — Mr. Smith Never Sleeps

### Rigour Gates

After every **code-producing agent** (coder, qa, devops, sre), `quality_check_node` runs:

```
Agent outputs files
       ↓
quality_check_node → Rigour CLI gates (deterministic, < 1s, no LLM)
       ↓
PASS → advance to next agent
FAIL → generate FixPacket → inject into agent's next run → retry
```

| Gate | What It Checks |
|---|---|
| `file_size` | Files must be < 400 lines |
| `type_hints` | Python functions need type annotations |
| `naming` | PEP 8 — snake_case functions, PascalCase classes |
| `error_handling` | No bare `except:` — must specify exception type |
| `magic_numbers` | Extract constants, no raw numbers in logic |
| `async_safety` | `async def` functions must actually await something |
| `import_validation` | Only import packages that exist in requirements |
| `forbidden_content` | No TODOs, no placeholder text, no empty `pass` bodies |

### The Fix Packet

When gates fail, a `FixPacket` is injected as a prefix to the agent's next system prompt:

```
[FIX REQUIRED #1]
The following violations were found in your output:

1. file_size: src/auth/router.py has 412 lines (limit: 400)
   Suggestion: Split into router.py (routes only) and service.py (logic)

2. error_handling: bare `except:` on line 47
   Suggestion: Use `except (ValueError, TypeError) as e:` and log the error

Fix ALL violations before re-submitting. Do not introduce new violations.
```

Agent reads, understands, fixes specifically what was wrong. Max 5 attempts per role.

### The Replan Node

When retry loop is exhausted AND replan is enabled:

```
retry_count >= max_retries AND replan.enabled = true
        ↓
replan_node(state, master_llm)
   Strategy "deterministic": rule-based (no model variance)
   Strategy "llm":           Master Agent generates correction plan
        ↓
"[REPLAN #1] Coder consistently fails file_size. New directive:
 immediately extract all logic to service.py. Keep router.py
 to route definitions only. Max 150 lines each."
        ↓
Agent runs ONCE more with replan directive
        ↓
Still fails → task status = "gate_failed_{role}"
```

Max replans per task: 1 (configurable). Replans do not retry indefinitely.

---

## Memory — Neo Remembers Every Fight

### What Gets Stored

After every completed task, the Master Agent extracts 1–5 memories and stores them as vectors:

```python
# Stored memory examples:
{"content": "JWT validation must whitelist algorithms. Never accept 'none'. Validate exp and iat.",
 "memory_type": "domain_knowledge"}

{"content": "FastAPI: use Depends() for services, not global state. Prevents test isolation issues.",
 "memory_type": "pattern"}

{"content": "Error: bare except in auth code caused gate failure. Fix: except (JWTError,) as e: log then raise 401.",
 "memory_type": "error_fix"}
```

Each memory is embedded (vectorized) and stored in SQLite with the vector alongside it.

### How Memory Is Retrieved

Before each agent runs:

1. Task description embedded (same model)
2. Cosine similarity search against all workspace memories
3. Top-K relevant memories filtered by role preference
4. Injected into agent system prompt:

```
RELEVANT MEMORIES FROM PAST TASKS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[0.92] JWT validation must whitelist algorithms...
[0.84] FastAPI: use Depends() for services...
[0.79] bare except in auth code caused gate failure...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Memory Reinforcement

When a task **passes all quality gates**, memories that were retrieved get:
- `usage_count += 1`
- `cross_project_usage += 1` (if used in a different project)

Useful memories rank higher in future retrievals. Memories that don't help don't get reinforced.

### Agent Enrichment — The Permanent Upgrade

Separate from memories, each Agent entity has an `EnrichmentContext` persisted in the database:

```python
@dataclass
class EnrichmentContext:
    common_mistakes: list[str]        # "Never use bare except"
    domain_knowledge: list[str]       # "Always validate CSRF tokens in FastAPI"
    pre_check_rules: list[str]        # "Verify type hints exist before submitting"
    workspace_conventions: list[str]  # "Use @dataclass not NamedTuple in this repo"
    last_enriched_at: datetime | None
```

After every task, `enrich_node` analyzes gate violations and retry patterns, maps them to pitfalls (via `GATE_TO_PITFALL_MAP`), and **updates the agent's enrichment context** so the next task starts with that knowledge pre-loaded.

```
Gate: file_size violated 3 times by coder
          ↓
enrich_node appends to coder.enrichment.common_mistakes:
  "Keep files under 400 lines. Split large files into focused modules."
          ↓
Next task: coder's system prompt includes this from the start
          ↓
Coder avoids the violation on first attempt
          ↓
Mr. Smith finds nothing to complain about → Neo improves
```

---

## The Full Pipeline

```
User: "Add OAuth2 social login with Google and GitHub"

Step 1 — PERCEPTION (scan_project_node)
  Scans codebase → 67 source files
  Detects: python, fastapi, sqlalchemy, pytest
  Builds: ProjectSnapshot (tech_stack, key_files, patterns)

Step 2 — CLASSIFICATION (classify_node) [Master Agent / Neo]
  LLM: Claude Sonnet
  Output: task_type=feature, complexity=high

Step 3 — ROUTING (route_team_node) [Master Agent / Neo]
  Output: team=engineering
  Pipeline: planner → coder → [reviewer ‖ security ‖ qa] → lead

Step 4 — ASSEMBLY (assemble_node)
  Builds execution DAG from team config + complexity.
  ready_roles = [planner]  (no deps)

Step 5 — APPROVAL #1 (plan_approval, tier="approve")
  Shows plan to user via desktop UI
  Graph pauses via LangGraph interrupt() + threading.Event
  User: approve / reject

Step 6 — PLANNER [Morpheus]
  Model: Claude Sonnet | Tools: read_file, search_codebase
  Output: structured plan (which files, why, what approach)
  Gates: SKIPPED

Step 7 — CODER [Neo]
  Model: Claude Opus | Tools: read_file, write_file, run_command, consult_agent
  Mid-execution → consult_agent("security", "Is it safe to trust Google's email field?")
  Security: "Yes, verified. Add email_verified check for robustness."
  Writes 4 files.
  Gates RUN:
    ✗ error_handling — bare except on line 89
  FixPacket generated → Coder retries (attempt 2/5)
  → Fixes bare except → All gates pass

Step 8 — PARALLEL WAVE [Reviewer ‖ Security ‖ QA] via asyncio.gather
  Reviewer: CHANGES_REQUESTED — "OAuth state param not validated (CSRF)"
  Security: VULNERABILITIES_FOUND — "State param not validated, token not bound"
  QA: writes tests/auth/test_oauth.py (34 tests), all pass

Step 9 — DEBATE ROUND [Coder ↔ Reviewer]
  Reviewer feedback injected → Coder adds state validation + rate limiting
  Gates re-run: all pass. Reviewer does not trigger second debate.

Step 10 — TECH LEAD [The Architect]
  Model: Claude Opus | Reads all outputs + gate results + QA report
  Verdict: SHIP — "CSRF mitigated. 34 passing tests. Security clean."

Step 11 — APPROVAL #2 (commit_approval)
  User reviews files changed, gate results, QA results → approves

Step 12 — ENRICHMENT (enrich_node)
  Coder required 1 retry (error_handling gate)
  → coder.enrichment.common_mistakes.append("bare except in auth code")
  Next task: coder sees this from the start

Step 13 — MEMORY (store_memory_node)
  Master Agent extracts 3 memories, embeds, stores in SQLite
  Reinforces retrieved memories that helped

Step 14 — FINALIZE
  status: completed
  files_changed: 5 files
  total_tokens: 31,420 | total_cost_usd: $0.38 | total_duration_ms: 52,400
  retries: 1 (coder, gate: error_handling)
```

---

## Desktop App

The **Rigovo Control Plane** is a cross-platform Electron desktop app (v0.1.0).

### Architecture

```
Electron Main Process (Node.js / TypeScript)
  ├── Engine lifecycle — spawns/kills rigovo serve subprocess
  ├── IPC handlers — engine:start/stop/status, dialog:open-folder,
  │                  fs:list-project-files, git:clone, shell:open-external
  └── Port management — kills stale port 8787 on production startup

Preload Script (contextBridge)
  └── Exposes safe electronAPI to renderer:
      engineStatus, startEngine, stopEngine, engineLastError,
      openExternal, openFolder, listProjectFiles, gitClone, pickCloneDest

React Renderer (Vite + TailwindCSS)
  ├── AuthScreen     — WorkOS PKCE sign-in flow
  ├── Sidebar        — task inbox, navigation
  ├── TaskInput      — new task entry + workspace selector (WorkspaceStrip)
  ├── TaskDetail     — live agent progress, event stream
  ├── AgentTimeline  — per-agent status visualization
  ├── ApprovalCard   — approve/reject gate UI
  ├── ActivityLog    — event stream viewer
  ├── FileViewer     — changed files with Monaco editor
  └── Settings       — model, permissions, API keys config
```

### Running in Development

```bash
# Start API + Electron together
./scripts/e2e_desktop.sh

# This script:
# 1. Checks if API healthy at http://127.0.0.1:8787 — reuses if yes
# 2. If not: kills stale process on 8787, starts Python source API
# 3. Waits for /health to pass
# 4. Launches: VITE_RIGOVO_API=http://127.0.0.1:8787 pnpm -C apps/desktop run dev
```

**WorkOS redirect URI**: must be `http://127.0.0.1:8787/v1/auth/callback` — set this exactly in WorkOS dashboard. Port 8787 is non-negotiable.

### Auth Flow (WorkOS PKCE)

```
1. User clicks "Sign in"
2. Renderer → GET /v1/auth/url → WorkOS URL with PKCE code_challenge
3. electronAPI.openExternal() opens browser → user authenticates at WorkOS
4. WorkOS redirects → http://127.0.0.1:8787/v1/auth/callback?code=...
5. API: exchanges code + code_verifier → session (2-minute timeout on polling)
6. Renderer polls GET /v1/auth/session every 1.5s
7. signed_in=true → renderer enters control plane
```

If sign-in fails or times out: renderer shows error with "Try again" button. No infinite spinner.

### Building for Distribution

```bash
pnpm -C apps/desktop run build && pnpm -C apps/desktop run dist
# Output: apps/desktop/release/
#   macOS:   Rigovo Control Plane.dmg
#   Windows: Rigovo Control Plane Setup.exe
#   Linux:   Rigovo-Control-Plane.AppImage
```

GitHub Actions (`desktop-release.yml`) builds all three platforms on `v*` tag push.

---

## Current Status — Honest Assessment

### Real Test Numbers (as of `a76680c`)

```
Total tests:  668
Passed:       661
Failed:         7
Duration:    ~11 seconds
```

### What Works

| Feature | Status |
|---|---|
| LangGraph pipeline (full DAG) | ✅ Working |
| All 8 engineering agents | ✅ Working |
| Quality gates + fix packets + retry loop | ✅ Working |
| Agentic tool loop (multi-round LLM ↔ tools) | ✅ Working |
| SQLite checkpointing (crash recovery) | ✅ Working |
| Inter-agent consultation | ✅ Working |
| Parallel agent execution (asyncio.gather) | ✅ Working |
| Coder ↔ Reviewer debate loop | ✅ Working |
| Replan node (deterministic + LLM strategies) | ✅ Working |
| Memory system (extract, embed, retrieve, reinforce) | ✅ Working |
| Agent enrichment context (persistent learning) | ✅ Working |
| Human-in-the-loop approval (threading.Event pause) | ✅ Working |
| WorkOS PKCE auth (correct redirect URI) | ✅ Working |
| SQLite + PostgreSQL persistence | ✅ Working |
| Multi-LLM support (Anthropic, OpenAI) | ✅ Working |
| CLI (rigovo run / init / doctor / serve) | ✅ Working |
| Electron desktop app (auth + tasks + approvals) | ✅ Working |
| Rigovo brand icon in desktop (dev + production) | ✅ Working |
| Open folder + Clone repo buttons | ✅ Working (fixed -webkit-app-region bug) |
| Cross-platform desktop builds (mac/win/linux) | ✅ Working (GitHub Actions) |
| CI pipeline (tests + lint + rigour gates) | ✅ Working |
| Cost tracking per agent (tokens + USD) | ✅ Working |
| Budget soft-limit warning | ✅ Working |

### Known Issues

| Issue | Severity | Detail |
|---|---|---|
| Budget hard-stop not enforced | Low | Logs warning and continues. `BudgetExceededError` not raised. 1 test failing. |
| 6 dashboard UI tests failing | Low | `TestCostTracker`, `TestTaskHeader` rendering tests — cosmetic only |
| Demo mode removed | By design | API unreachable → stays on auth screen with status dot. No silent demo login. |
| Git worktree execution | Partial | Config exists in state, execution path not fully wired |

### Not Yet Built

| Feature | Notes |
|---|---|
| Cloud sync (rigovo.com) | Infrastructure stub exists, not connected |
| Multi-workspace collaboration | Single-workspace only |
| Data / Infra / Security domain plugins | Only engineering domain exists |
| MCP (Model Context Protocol) tools | Connector infrastructure exists, not wired |
| Real-time SSE in desktop UI | Currently polling every 1.5–4s |
| Cost hard-stop enforcement | Soft warning only |
| Plugin marketplace | Planned |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 20+ and pnpm 9+ (desktop only)
- Anthropic API key (or OpenAI)
- WorkOS account (for auth — optional for headless/CLI)

### Install (CLI)

```bash
pip install rigovo
```

### Initialize a Project

```bash
cd your-project
rigovo init
# Creates: rigovo.yml, rigour.yml, .env, .rigovo/
```

### Validate Setup

```bash
rigovo doctor
# Checks Python, config, API keys, database, Rigour CLI, git
```

### Run a Task

```bash
rigovo run "Add input validation to all API endpoints with proper error responses"
```

### Desktop App (Development)

```bash
# Set up .env with your WorkOS + Anthropic keys
# Then:
./scripts/e2e_desktop.sh
```

### Desktop App (Production Build)

```bash
pnpm -C apps/desktop install
pnpm -C apps/desktop run build
pnpm -C apps/desktop run dist
```

### Run Tests

```bash
pytest tests/ -q
# Expect: 661 passed, 7 failed (known, non-blocking)
```

---

## Configuration

### `.env`

```bash
ANTHROPIC_API_KEY=sk-ant-...
WORKOS_CLIENT_ID=client_01...
WORKOS_API_KEY=sk_test_...         # optional — org/role admin features
RIGOVO_IDENTITY_PROVIDER=workos
RIGOVO_WORKTREE_MODE=project       # project | git_worktree
```

### `rigovo.yml`

```yaml
version: "1"
workspace_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

teams:
  - id: engineering
    name: "Engineering"
    domain: engineering
    agents:
      - role: planner
        llm_model: "claude-sonnet-4-6"
        depends_on: []
      - role: coder
        llm_model: "claude-opus-4-6"
        depends_on: [planner]
      - role: reviewer
        llm_model: "claude-sonnet-4-6"
        depends_on: [coder]
      - role: security
        llm_model: "claude-sonnet-4-6"
        depends_on: [coder]
      - role: qa
        llm_model: "claude-sonnet-4-6"
        depends_on: [coder]
      - role: lead
        llm_model: "claude-opus-4-6"
        depends_on: [reviewer, security, qa]

orchestration:
  max_retries: 5
  max_agents_per_task: 8

  consultation:
    enabled: true
    max_question_chars: 1200

  replan:
    enabled: true
    max_replans_per_task: 1
    strategy: deterministic          # deterministic | llm

approval:
  after_planning: true               # pause before first agent runs
  before_commit: true                # pause before finalize

quality:
  deep_mode: "final"                 # never | final | ci | always

database:
  backend: sqlite                    # sqlite | postgres
  local_path: ".rigovo/local.db"

plugins:
  allowed_shell_commands: [npm, python3, pytest, git, docker]
  min_trust_level: 0
```

---

## Architecture Deep Dive

### Directory Map

```
src/rigovo/
├── api/control_plane.py             # FastAPI — all HTTP endpoints
├── application/
│   ├── graph/
│   │   ├── builder.py               # GraphBuilder — compiles LangGraph StateGraph
│   │   ├── edges.py                 # All conditional routing functions
│   │   ├── state.py                 # TaskState — the pipeline's bloodstream
│   │   └── nodes/
│   │       ├── scan_project.py      # Project perception → ProjectSnapshot
│   │       ├── classify.py          # Master Agent: task_type + complexity
│   │       ├── route_team.py        # Master Agent: team selection
│   │       ├── assemble.py          # DAG construction from team config
│   │       ├── approval.py          # Human-in-the-loop (plan + commit)
│   │       ├── execute_agent.py     # Agent execution engine (the core)
│   │       ├── quality_check.py     # Rigour gate runner + fix packet generation
│   │       ├── replan.py            # Mid-run correction when retries exhausted
│   │       ├── enrich.py            # Extract learnings → update agent enrichment
│   │       ├── store_memory.py      # Persist + reinforce semantic memories
│   │       └── finalize.py          # Aggregate results, set final status
│   ├── context/
│   │   ├── project_scanner.py       # Codebase scan → ProjectSnapshot
│   │   ├── memory_retriever.py      # Semantic search against memory repo
│   │   └── context_builder.py       # Per-agent prompt context assembly
│   ├── commands/run_task.py         # Task execution entry (CLI + API)
│   └── master/
│       ├── classifier.py            # Task classification logic
│       ├── router.py                # Team routing logic
│       ├── enricher.py              # Enrichment context analysis
│       └── evaluator.py             # Post-execution quality scoring
├── domain/
│   ├── entities/                    # Task, Agent, Memory, Team, Quality, AuditEntry
│   ├── interfaces/                  # LLMProvider, QualityGate, Repositories (abstract)
│   └── services/                    # CostCalculator, TeamAssembler, MemoryRanker
├── infrastructure/
│   ├── llm/                         # LLMFactory, ModelCatalog, Anthropic/OpenAI
│   ├── persistence/                 # SQLite + PostgreSQL backends
│   ├── quality/                     # Rigour CLI gate builder
│   ├── filesystem/                  # Safe tool executor (path sanitization)
│   ├── embeddings/                  # Local vector embeddings
│   └── plugins/                     # Connector/plugin system (MCP-ready)
├── domains/engineering/             # Default domain: 8 agents, tools, rules
├── config.py                        # Config loading (.env + rigovo.yml)
└── container.py                     # Dependency injection root
```

### Conditional Routing Reference

| Edge Function | Outputs | Leads To |
|---|---|---|
| `check_approval(state)` | `approved` \| `rejected` | next agent \| done |
| `check_gates_and_route(state)` | `pass_next_agent` \| `fail_fix_loop` \| `trigger_replan` \| `fail_max_retries` | advance \| retry \| replan \| fail |
| `check_replan_result(state)` | `replan_failed` \| `replan_continue` | fail \| retry once |
| `check_pipeline_complete(state)` | `pipeline_done` \| `more_agents` \| `parallel_fan_out` | finalize \| next \| parallel |
| `check_parallel_postprocess(state)` | pipeline route \| `debate_needed` | advance \| debate |
| `advance_to_next_agent(state)` | next role name | execute_agent |

### API Endpoints

```
POST   /v1/tasks                       # Create task (description, tier, project_id)
GET    /v1/tasks/{task_id}             # Task status + agent outputs
GET    /v1/tasks/{task_id}/detail      # Full task detail with events
GET    /v1/ui/inbox                    # Task list for UI
GET    /v1/ui/approvals                # Pending approvals
POST   /v1/tasks/{task_id}/approve     # Approve (unblocks LangGraph)
POST   /v1/tasks/{task_id}/deny        # Reject task
GET    /v1/auth/url                    # Get WorkOS auth URL (PKCE)
GET    /v1/auth/callback               # WorkOS redirect handler
GET    /v1/auth/session                # Current session
POST   /v1/auth/logout                 # Clear session
GET    /v1/projects                    # List projects
POST   /v1/projects                    # Register project
GET    /v1/settings                    # Workspace settings
PATCH  /v1/settings                    # Update settings
GET    /v1/control/state               # Control plane state (personas, connectors)
GET    /health                         # Health check → {"status": "ok"}
```

---

## Contributing

```bash
# Python setup
pip install -e ".[dev]"

# Desktop setup
pnpm -C apps/desktop install

# Run tests
pytest tests/ -q

# Lint + format
ruff format src/
ruff check src/

# Quality gates
npx @rigour-labs/cli check

# Start dev environment
./scripts/e2e_desktop.sh
```

---

## License

MIT — see [LICENSE](LICENSE)

---

<p align="center">
  Built on <a href="https://github.com/langchain-ai/langgraph">LangGraph</a> ·
  Governed by <a href="https://github.com/rigour-labs/rigour">Rigour</a> ·
  Authenticated by <a href="https://workos.com">WorkOS</a>
</p>
