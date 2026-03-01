<p align="center">
  <img src="apps/desktop/resources/icon.svg" width="80" alt="Rigovo" />
</p>

<h1 align="center">Rigovo Teams — Virtual Engineering Team as a Service</h1>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.2.0-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/tests-790_passed-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
  <img src="https://img.shields.io/badge/desktop-Electron_0.1.0-blueviolet?style=flat-square" />
</p>

<p align="center">
  <strong>10 AI agents. One intelligent pipeline. Production-grade code governed by deterministic + deep quality gates.</strong>
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
- [Confidence Scoring](#confidence-scoring)
- [Execution Verification](#execution-verification)
- [Smart Deep Mode](#smart-deep-mode)
- [The Full Pipeline](#the-full-pipeline)
- [Desktop App](#desktop-app)
- [Current Status — Honest Assessment](#current-status--honest-assessment)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Architecture Deep Dive](#architecture-deep-dive)

---

## What Is This

Rigovo Teams turns a single task description into production-ready code by assembling a **coordinated team of 10 AI agents** — each with a specific role, skill profile that evolves over time, memory of past work across projects, and governed by deterministic + LLM-powered quality gates.

You describe what needs to be done. Rigovo:

1. Scans your codebase to understand the project context
2. Retrieves cross-project memories and team performance data from past tasks
3. Classifies the task (complexity, type) — persisted on the Task entity
4. Assembles the right team with instance-based agents (e.g. `backend-engineer-1`, `frontend-engineer-1`)
5. Executes each agent in DAG dependency order with parallel fan-out
6. Runs quality gates after every code-producing agent — with mandatory execution verification
7. Lets agents retry, self-correct, consult peers, spawn sub-tasks, or request a full replan when stuck
8. Optionally pauses for your approval before committing
9. Computes a confidence score (0–100) based on gate results, retries, and deep analysis
10. Extracts what was learned — memories and skill profiles persist across tasks and projects

The result: files changed, summary, cost, token count, confidence score, execution logs, audit trail — all in one shot.

---

## The Brain — How It Works

### The Orchestration Engine: LangGraph DAG

The system is built on **LangGraph** — a checkpoint-based directed acyclic graph (DAG) execution engine. Every task is a graph traversal. Every node is a Python async function. Every edge is a routing decision.

```
scan_project → classify → route_team → assemble
      ↓
[Optional] plan_approval ──► REJECTED → done
      ↓ approved
execute_agent ──► quality_check (deterministic + smart deep)
      │                │
      │          pass  ↓
      │         next agent or parallel fan-out
      │
      │          fail → retry (max 5x with fix packets)
      │          fail → replan → retry once more
      │          fail → pipeline_failed
      ↓
[reviewer ║ security ║ qa] ← parallel execution (asyncio.gather)
      ↓
[Optional debate] ← if reviewer requests changes, coder re-runs
      ↓
[Optional] commit_approval
      ↓
enrich → evaluate_skills → store_memory → finalize
```

**Why LangGraph?** Because checkpointing means if the process dies mid-execution, the task resumes from the last completed node — not from scratch. Every node writes its output to SQLite before the next node runs.

### The Master Agent: Neo

Neo (the Master Agent) makes **three decisions** that shape every task:

1. **Classification** (`classify_node`) — LLM call to determine `task_type` and `complexity`
   - `task_type`: feature / bug / refactor / test / docs / infra / security / performance / investigation / new_project
   - `complexity`: low / medium / high / critical
   - Classification is persisted on the Task entity after graph completes (not just in state)
   - Enriched with cross-project learnings, team performance data, and architecture insights

2. **Staffing** — LLM call to build an instance-based team with explicit DAG dependencies
   - Produces a `StaffingPlan` with `AgentAssignment` entries
   - Each agent has: `instance_id` (e.g. `backend-engineer-1`), `role`, `specialisation`, `assignment`, `depends_on`, `verification`
   - Conventional flow order enforced: planner → coders → reviewer → security → qa → devops → sre → lead (last)
   - Historical intelligence from past tasks informs team composition

3. **Assembly** (`assemble_node`) — Deterministic. Reads staffing plan. Builds the execution DAG.
   - Each agent declares `depends_on: [instance_id, ...]`
   - Computes `ready_roles` (can run now) and `blocked_roles` (dependency failed)
   - Identifies roles that can run in parallel: `{reviewer, qa, security, docs}`

### The TaskState: The Bloodstream

Every node reads from and writes to a single **TaskState dictionary**. This flows through the entire pipeline, checkpointed at every step.

| Section | What It Holds |
|---|---|
| Identity | `task_id`, `description`, `project_root`, `workspace_id` |
| Classification | `task_type`, `complexity`, `domain_analysis`, `architecture_notes` |
| Team Config | `team_id`, `agents`, `pipeline_order`, `execution_dag`, `gates_after` |
| Execution | `current_agent_role`, `ready_roles`, `completed_roles`, `blocked_roles` |
| Outputs | `agent_outputs[role]` → summary, files_changed, tokens, cost, duration_ms |
| Inter-agent | `agent_messages` → consultation thread between agents |
| Gates | `gate_results`, `gate_history`, `fix_packets`, `retry_count`, `confidence_score` |
| Approval | `approval_status` (pending / approved / rejected), `user_feedback` |
| Budget | `cost_accumulator[agent_id]`, `budget_max_cost_per_task` |
| Memory | `memories_to_store`, `memory_context_by_role`, `memory_retrieval_log` |
| Enrichment | `enrichment_updates` → pitfalls extracted from this run |
| Skill Profiles | `agent_skill_updates` → rolling performance metrics per role |
| Debate | `debate_round`, `reviewer_feedback`, `debate_target_role` |
| Replan | `replan_count`, `replan_history`, `replan_policy` |
| Context | `project_snapshot` → tech stack, files, entry points |
| Deep Mode | `deep_mode`, `deep_pro`, `ci_mode` |
| Execution Verification | `execution_log`, `execution_verified` per pipeline step |
| Audit | `events[]` → every significant moment, timestamped |

---

## The Agents — The Team

Ten roles. Each is a Python `Agent` entity with: system prompt, tool list, LLM model, enrichment context, skill profile, `depends_on`, and output contract.

### 1. Chief Architect — Neo (Master Agent)
> "I know kung fu."

The orchestrator. Classifies tasks, assembles teams, routes objectives. Enriched with cross-project learnings, team performance history, and architecture insights from past tasks.

- **Tools**: classification, staffing plan generation
- **Memory**: retrieves gate_learnings, team_performance, architecture_insights before every decision
- **Model**: Claude Opus

### 2. Project Manager — Morpheus
> "I can only show you the door, Neo. You're the one that has to walk through it."

Maps the territory before anyone writes a line of code. Reads the codebase (read-only tools), understands the task, produces a structured plan that every downstream agent receives as context.

- **Tools**: `read_file`, `search_codebase`, `list_directory`, `read_dependencies`
- **Depends on**: nothing (runs first)
- **Output**: structured plan — which files to change, why, what approach
- **Gates**: SKIPPED (no code produced)
- **Model**: Claude Sonnet

### 3. Software Engineer — Neo
> "There is no spoon."

The central agent. Receives the planner's map, reads relevant code, implements the task. Most tokens, cost, and time go here. Can consult peers and spawn sub-tasks.

- **Tools**: `read_file`, `write_file`, `list_directory`, `search_codebase`, `run_command`, `consult_agent`, `spawn_subtask`
- **Depends on**: planner
- **Output**: modified/created files, implementation summary, execution_log
- **Gates**: ALWAYS RUN — file size, type hints, naming, error handling, imports, etc.
- **Execution Verification**: must actually run code (tests, build, lint) — verified via execution_log
- **Retry loop**: up to 5x with fix packets if gates fail
- **Model**: Claude Opus (most capable)

### 4. Code Reviewer — The Oracle
> "You've already made the choice. Now you have to understand it."

Reads what the coder wrote, identifies logic errors, suggests improvements. Does not write code — critiques.

- **Tools**: `read_file`, `search_codebase`, `list_directory`
- **Depends on**: coder
- **Runs**: in parallel with security and QA
- **Output**: APPROVED or CHANGES_REQUESTED + specific feedback
- **Debate trigger**: if CHANGES_REQUESTED → coder re-runs with feedback (max 2 debate rounds)
- **Model**: Claude Sonnet

### 5. Security Engineer — Agent Smith (the constructive one)
> "Me, me, me."

Always finds problems. Scans for vulnerabilities, injection risks, auth issues, exposed secrets, insecure defaults.

- **Tools**: `read_file`, `search_codebase`, `list_directory`, `run_command`
- **Depends on**: coder
- **Runs**: in parallel with reviewer and QA
- **Output**: PASS or VULNERABILITIES_FOUND + CVE-style findings
- **Execution Verification**: must actually run security scanning tools
- **Model**: Claude Sonnet

### 6. QA Engineer — Tank (the operator)
> "I'm going to need guns. Lots of guns."

Writes tests. Not reviews tests — writes them. Reads the implementation, understands contracts, produces test files.

- **Tools**: `read_file`, `write_file`, `run_command`, `search_codebase`
- **Depends on**: coder
- **Runs**: in parallel with reviewer and security
- **Output**: test files, test run results, execution_log
- **Gates**: RUN (QA produces code)
- **Model**: Claude Sonnet

### 7. DevOps Engineer — Mr. Smith (infrastructure)
> "It's the sound of inevitability."

Handles deployment configuration: CI/CD, Docker, Kubernetes, GitHub Actions, IaC. Runs when task requires it.

- **Tools**: `read_file`, `write_file`, `run_command`, `list_directory`
- **Depends on**: coder, qa
- **Model**: Claude Sonnet

### 8. SRE Engineer — The Twins
> "We don't crash."

Adds observability, alerting, SLOs, runbooks. Ensures code is operable in production, not just functional.

- **Tools**: `read_file`, `write_file`, `search_codebase`
- **Depends on**: devops
- **Model**: Claude Sonnet

### 9. Tech Lead — The Architect
> "There is only one constant. Action. Reaction. Cause and effect."

Reviews the entire output across all agents — code, process, security, tests. Signs off on the final result. **Always runs last** in the pipeline.

- **Tools**: `read_file`, `search_codebase` (read-only)
- **Depends on**: all other agents (runs last per staffing rules)
- **Output**: SHIP or HOLD + reasoning
- **Gates**: SKIPPED (assessment role)
- **Model**: Claude Opus

### 10. Technical Writer — Dozer
> "Read this, and you'll understand."

Produces documentation when the task requires it. API docs, READMEs, architecture decision records.

- **Tools**: `read_file`, `write_file`, `search_codebase`
- **Depends on**: coder
- **Model**: Claude Sonnet

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
1. LLM receives: system_prompt + task + context + expert context + (optional fix packet)
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
2. Expert context (past violations + workspace conventions from skill profiles)
3. Enrichment context (learned pitfalls from past tasks)
4. Memory context (semantically similar past task learnings — cross-project)
5. Project snapshot (tech stack, key files, structure)
6. Previous agents' outputs (what planner decided, what coder did)
7. Consultation thread (what agents said mid-task)
8. Fix packet (if retrying: "Fix these violations...")

---

## The Quality Loop — Mr. Smith Never Sleeps

### Rigour Gates (23+ Deterministic Gates)

After every **code-producing agent** (coder, qa, devops, sre), `quality_check_node` runs:

```
Agent outputs files
       ↓
quality_check_node → Rigour CLI gates (deterministic, < 1s, no LLM)
       ↓
PASS → advance to next agent
FAIL → generate FixPacket → inject into agent's next run → retry
NO FILES → gate event with reason: "no_files_produced"
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
| `persona_boundary` | Agent acted within its defined role scope |
| `output_contract` | Agent output structure matches expected schema |
| + 13 more | Hallucinated imports, secrets, command injection, etc. |

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

Max replans per task: 1 (configurable). Replan history tracked for auditability.

---

## Memory — Neo Remembers Every Fight

### What Gets Stored

After every completed task, the Master Agent extracts 1–5 memories and stores them as vectors:

```python
# Stored memory examples (with types):
{"content": "JWT validation must whitelist algorithms. Never accept 'none'.",
 "memory_type": "gate_learning"}

{"content": "Engineering team: 3-agent pipeline (planner→coder→reviewer) optimal for medium bugs",
 "memory_type": "team_performance"}

{"content": "FastAPI: use Depends() for services, not global state. Prevents test isolation issues.",
 "memory_type": "architecture_insight"}
```

Memory types: `gate_learning`, `team_performance`, `architecture_insight`, `domain_knowledge`, `pattern`, `error_fix`.

Each memory is embedded (vectorized) and stored in SQLite with the vector alongside it.

### How Memory Is Retrieved

Before the Master Agent classifies and staffs:

1. `retrieve_for_master()` fetches memories categorized by type
2. Gate learnings inform quality expectations
3. Team performance data informs staffing decisions
4. Architecture insights inform technical direction

Before each agent runs:

1. Task description embedded (same model)
2. Cosine similarity search against all workspace memories
3. Top-K relevant memories filtered by role preference
4. Injected into agent system prompt as `RELEVANT MEMORIES FROM PAST TASKS`

### Cross-Project Learning

Memories are scoped to workspace but **cross-project usage is tracked**. When a memory from Project A helps in Project B:
- `cross_project_usage += 1`
- Memory relevance increases for future cross-project retrieval

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

---

## Confidence Scoring

Every completed task receives a **confidence score** (0–100) computed deterministically from:

| Factor | Weight | Logic |
|---|---|---|
| Gate pass rate | 40% | % of gates passed across all agents |
| Retry ratio | 25% | Fewer retries = higher confidence |
| Violation count | 20% | Total violations found (lower = better) |
| Deep analysis | 15% | Bonus for deep mode pass, penalty for skip |

The confidence score is displayed in the desktop UI and persisted on the Task entity. It provides an at-a-glance quality assessment without requiring manual review.

---

## Execution Verification

Code-producing agents (coder, qa, devops, sre, security) have **mandatory execution checkpoints**. "Assuming it works" is never acceptable.

Each PipelineStep tracks:

```python
@dataclass
class PipelineStep:
    # ... other fields ...
    execution_log: list[dict[str, Any]]  # Commands run and their results
    execution_verified: bool              # Whether execution actually happened
```

The execution log captures every command the agent ran (tests, builds, lints) with stdout/stderr. This data flows through the full pipeline: agent execution → state → PipelineStep entity → SQLite serialization → API response → frontend display.

In the desktop UI, the Agent Detail Panel shows the execution log as an expandable section with command/output pairs.

---

## Smart Deep Mode

Quality gates run in two tiers:

1. **Deterministic gates** — always run, < 1s, no LLM cost (23+ AST-based checks)
2. **Deep analysis** — LLM-powered semantic analysis (code quality, security, architecture)

**Smart deep mode** (the default) enables deep analysis selectively:

| Trigger | When Deep Activates |
|---|---|
| Retry threshold | Agent required 2+ retries — something is consistently wrong |
| Critical task | Task classified as `critical` complexity |
| Security role | Security agent always gets deep analysis |
| Final pipeline step | Last agent in pipeline gets deep as a final safety net |

This balances cost (deep analysis uses LLM tokens) with quality (catches subtle issues that deterministic gates miss).

Other deep modes: `never`, `final` (only last step), `always`, `ci` (in CI pipeline only).

---

## The Full Pipeline

```
User: "Add OAuth2 social login with Google and GitHub"

Step 1 — PERCEPTION (scan_project_node)
  Scans codebase → 67 source files
  Detects: python, fastapi, sqlalchemy, pytest
  Builds: ProjectSnapshot (tech_stack, key_files, patterns)

Step 2 — MEMORY RETRIEVAL (retrieve_for_master)
  Fetches gate_learnings, team_performance, architecture_insights
  Enriches Master Agent with cross-project intelligence

Step 3 — CLASSIFICATION (classify_node) [Master Agent / Neo]
  LLM: Claude Sonnet (enriched with memory context)
  Output: task_type=feature, complexity=high
  Classification persisted on Task entity

Step 4 — STAFFING (route_team_node) [Master Agent / Neo]
  Builds StaffingPlan with instance-based agents:
    planner-1 → backend-engineer-1 → [reviewer-1 ‖ security-1 ‖ qa-1] → lead-1
  Each with specific assignment and verification criteria

Step 5 — ASSEMBLY (assemble_node)
  Builds execution DAG from staffing plan + complexity.
  ready_roles = [planner-1]  (no deps)

Step 6 — APPROVAL #1 (plan_approval, tier="approve")
  Shows plan to user via desktop UI
  Graph pauses via LangGraph interrupt() + threading.Event
  User: approve / reject

Step 7 — PROJECT MANAGER [Morpheus]
  Model: Claude Sonnet | Tools: read_file, search_codebase
  Expert context injected: past violations + workspace conventions
  Output: structured plan (which files, why, what approach)
  Gates: SKIPPED

Step 8 — SOFTWARE ENGINEER [Neo]
  Model: Claude Opus | Tools: read_file, write_file, run_command, consult_agent
  Mid-execution → consult_agent("security", "Is it safe to trust Google's email field?")
  Security: "Yes, verified. Add email_verified check for robustness."
  Writes 4 files. Runs pytest → execution_log captured.
  Gates RUN:
    ✗ error_handling — bare except on line 89
  FixPacket generated → Coder retries (attempt 2/5)
  → Fixes bare except → All gates pass
  Execution verified: true

Step 9 — PARALLEL WAVE [Reviewer ‖ Security ‖ QA] via asyncio.gather
  Reviewer: CHANGES_REQUESTED — "OAuth state param not validated (CSRF)"
  Security: VULNERABILITIES_FOUND — "State param not validated, token not bound"
  QA: writes tests/auth/test_oauth.py (34 tests), all pass

Step 10 — DEBATE ROUND [Coder ↔ Reviewer]
  Reviewer feedback injected → Coder adds state validation + rate limiting
  Gates re-run: all pass. Reviewer does not trigger second debate.

Step 11 — TECH LEAD [The Architect] (runs LAST)
  Model: Claude Opus | Reads all outputs + gate results + QA report
  Verdict: SHIP — "CSRF mitigated. 34 passing tests. Security clean."

Step 12 — APPROVAL #2 (commit_approval)
  User reviews files changed, gate results, QA results → approves

Step 13 — ENRICHMENT (enrich_node)
  Coder required 1 retry (error_handling gate)
  → coder.enrichment.common_mistakes.append("bare except in auth code")
  Next task: coder sees this from the start

Step 14 — SKILL EVALUATION (evaluate_skills)
  Updates AgentSkillProfile for each agent that ran:
    success_rate, avg_tokens, avg_duration, common_violations (rolling averages)

Step 15 — MEMORY (store_memory_node)
  Master Agent extracts 3 memories, embeds, stores in SQLite
  Reinforces retrieved memories that helped
  Cross-project usage tracked

Step 16 — FINALIZE
  confidence_score: 87
  status: completed
  files_changed: 5 files
  total_tokens: 31,420 | total_cost_usd: $0.38 | total_duration_ms: 52,400
  retries: 1 (coder, gate: error_handling)
```

---

## Desktop App

The **Rigovo Control Plane** is a cross-platform Electron desktop app with full dark/light theme support.

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
  ├── AuthScreen              — WorkOS PKCE sign-in flow
  ├── Sidebar                 — task inbox, navigation
  ├── TaskInput               — new task entry + workspace selector (WorkspaceStrip)
  ├── TaskDetail              — live agent progress, confidence score, event stream
  ├── AgentTimeline           — narrative-style agent execution visualization
  ├── NeuralCalibrationMap    — React Flow pipeline topology graph (static + fallback edges)
  ├── AgentDetailPanel        — deep agent detail with execution logs, cost, consultation
  ├── ResponseRenderer        — rich markdown rendering of agent outputs
  ├── ApprovalCard            — approve/reject gate UI
  ├── ActivityLog             — event stream viewer
  ├── FileViewer              — changed files with Monaco editor
  ├── LogViewer               — real-time agent log streaming
  └── Settings                — model, permissions, API keys config
```

### Theme System

The UI supports automatic dark/light theme via `data-theme` attribute and `prefers-color-scheme` media query. All colors use CSS custom variables (`--canvas`, `--surface`, `--t1` through `--t4`, `--border`, `--accent`, `--s-running`, `--s-complete`, `--s-failed`, `--s-waiting`) that flip between warm light and warm dark palettes.

Role-specific tinted surfaces (agent cards, badges, gate pills) use the `role-*` CSS class system (`role-surface-*`, `role-border-*`, `role-text-*`, `role-badge-*`) with `rgba()` overlays that adapt to both themes.

### NeuralCalibrationMap — Pipeline Visualization

The pipeline topology graph shows all active agents as nodes connected by animated signal edges. Key features:

- **Static edges** define the full pipeline topology (15 edges)
- **Fallback edges** activate conditionally when certain nodes are absent (e.g. in small pipelines without devops/sre, fallback edges connect coder→lead directly)
- **Instance-agent resolution**: nodes map from base roles (e.g. `coder`) to actual instance agents (e.g. `backend-engineer-1`)
- **Live status**: nodes pulse when running, dim when idle, glow when complete

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

### Real Test Numbers

```
Python tests:  790 passed (1 pre-existing exclusion: dashboard UI test)
TypeScript:    TSC clean (zero errors)
Duration:      ~11 seconds
```

### What Works

| Feature | Status |
|---|---|
| LangGraph pipeline (full DAG with checkpointing) | ✅ Working |
| All 10 engineering agent roles | ✅ Working |
| Instance-based agents (backend-engineer-1, etc.) | ✅ Working |
| Quality gates (23+ deterministic) + fix packets + retry loop | ✅ Working |
| Smart deep mode (selective LLM analysis) | ✅ Working |
| Confidence scoring (0–100 per task) | ✅ Working |
| Execution verification (mandatory for code-producing agents) | ✅ Working |
| Agentic tool loop (multi-round LLM ↔ tools) | ✅ Working |
| SQLite checkpointing (crash recovery) | ✅ Working |
| Inter-agent consultation | ✅ Working |
| Sub-task spawning | ✅ Working |
| Parallel agent execution (asyncio.gather) | ✅ Working |
| Coder ↔ Reviewer debate loop | ✅ Working |
| Replan node (deterministic + LLM strategies) | ✅ Working |
| Memory system (extract, embed, retrieve, reinforce) | ✅ Working |
| Cross-project memory and learning | ✅ Working |
| Agent enrichment context (persistent learning) | ✅ Working |
| Agent skill profiles (rolling performance metrics) | ✅ Working |
| Expert context injection (past violations → system prompt) | ✅ Working |
| Master Agent cross-project intelligence | ✅ Working |
| Task classification persistence | ✅ Working |
| Human-in-the-loop approval (threading.Event pause) | ✅ Working |
| WorkOS PKCE auth (correct redirect URI) | ✅ Working |
| SQLite + PostgreSQL persistence | ✅ Working |
| Multi-LLM support (Anthropic, OpenAI) | ✅ Working |
| CLI (rigovo run / init / doctor / serve) | ✅ Working |
| Electron desktop app (auth + tasks + approvals) | ✅ Working |
| Dark/light theme (auto + manual toggle) | ✅ Working |
| NeuralCalibrationMap (pipeline topology with fallback edges) | ✅ Working |
| AgentTimeline (narrative-style execution view) | ✅ Working |
| AgentDetailPanel (execution logs, cost, consultation) | ✅ Working |
| Polling-based live updates (1.5s running, 5s complete) | ✅ Working |
| Rigovo brand icon in desktop (dev + production) | ✅ Working |
| Open folder + Clone repo buttons | ✅ Working |
| Cross-platform desktop builds (mac/win/linux) | ✅ Working (GitHub Actions) |
| CI pipeline (tests + lint + rigour gates) | ✅ Working |
| Cost tracking per agent (tokens + USD) | ✅ Working |
| Budget soft-limit warning | ✅ Working |

### Not Yet Built

| Feature | Notes |
|---|---|
| Cloud sync (rigovo.com) | Infrastructure stub exists, not connected |
| Multi-workspace collaboration | Single-workspace only |
| Data / Infra / Security domain plugins | Only engineering domain exists |
| MCP (Model Context Protocol) tools | Connector infrastructure exists, not wired |
| Real-time SSE/WebSocket in desktop UI | Currently adaptive polling |
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
# Python
pytest tests/ -q --ignore=tests/unit/infrastructure/test_dashboard.py
# Expect: 790 passed

# TypeScript
cd apps/desktop && npx tsc --noEmit
# Expect: zero errors
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
      - role: devops
        llm_model: "claude-sonnet-4-6"
        depends_on: [coder, qa]
      - role: sre
        llm_model: "claude-sonnet-4-6"
        depends_on: [devops]
      - role: lead
        llm_model: "claude-opus-4-6"
        depends_on: [reviewer, security, qa]

orchestration:
  max_retries: 5
  max_agents_per_task: 10

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
  deep_mode: "smart"                 # never | final | smart | always | ci

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
├── api/control_plane.py             # FastAPI — all HTTP endpoints + live event handler
├── application/
│   ├── graph/
│   │   ├── builder.py               # GraphBuilder — compiles LangGraph StateGraph
│   │   ├── edges.py                 # All conditional routing functions
│   │   ├── state.py                 # TaskState — the pipeline's bloodstream
│   │   └── nodes/
│   │       ├── scan_project.py      # Project perception → ProjectSnapshot
│   │       ├── classify.py          # Master Agent: task_type + complexity
│   │       ├── route_team.py        # Master Agent: team selection + staffing
│   │       ├── assemble.py          # DAG construction from staffing plan
│   │       ├── approval.py          # Human-in-the-loop (plan + commit)
│   │       ├── execute_agent.py     # Agent execution engine (agentic tool loop)
│   │       ├── quality_check.py     # Rigour gate runner + fix packet + confidence
│   │       ├── replan.py            # Mid-run correction when retries exhausted
│   │       ├── enrich.py            # Extract learnings → update agent enrichment
│   │       ├── store_memory.py      # Persist + reinforce semantic memories
│   │       └── finalize.py          # Aggregate results, set final status
│   ├── context/
│   │   ├── project_scanner.py       # Codebase scan → ProjectSnapshot
│   │   ├── memory_retriever.py      # Semantic search + master retrieval
│   │   └── context_builder.py       # Per-agent prompt context assembly
│   ├── commands/run_task.py         # Task execution entry (CLI + API)
│   └── master/
│       ├── classifier.py            # Task classification + staffing plan generation
│       ├── router.py                # Team routing logic
│       ├── enricher.py              # Context enrichment (gate_learnings, team_perf, arch)
│       └── evaluator.py             # Skill profile updates + post-execution scoring
├── domain/
│   ├── entities/                    # Task, Agent, Memory, Team, Quality, AuditEntry, AgentSkillProfile
│   ├── interfaces/                  # LLMProvider, QualityGate, Repositories (abstract)
│   └── services/                    # CostCalculator, TeamAssembler, MemoryRanker
├── infrastructure/
│   ├── llm/                         # LLMFactory, ModelCatalog, Anthropic/OpenAI
│   ├── persistence/                 # SQLite + PostgreSQL backends
│   ├── quality/                     # Rigour CLI gate builder
│   ├── filesystem/                  # Safe tool executor (path sanitization)
│   ├── embeddings/                  # Local vector embeddings
│   └── plugins/                     # Connector/plugin system (MCP-ready)
├── domains/engineering/             # Default domain: 10 agents, tools, rules
├── config.py                        # Config loading (.env + rigovo.yml)
└── container.py                     # Dependency injection root

apps/desktop/
├── src/
│   ├── main/                        # Electron main process + IPC handlers
│   ├── preload/                     # contextBridge API exposure
│   └── renderer/src/
│       ├── components/
│       │   ├── TaskDetail.tsx        # Main task view with confidence score
│       │   ├── AgentTimeline.tsx     # Narrative-style execution timeline
│       │   ├── NeuralCalibrationMap.tsx  # React Flow pipeline topology
│       │   ├── AgentDetailPanel.tsx  # Deep agent detail + execution logs
│       │   ├── ResponseRenderer.tsx  # Rich markdown output rendering
│       │   ├── ApprovalCard.tsx      # Approve/reject UI
│       │   ├── ActivityLog.tsx       # Event stream
│       │   ├── FileViewer.tsx        # Monaco-based file viewer
│       │   ├── LogViewer.tsx         # Agent log streaming
│       │   └── Settings.tsx          # Configuration panel
│       ├── types.ts                  # TypeScript interfaces (TaskStep, ExecutionLogEntry, etc.)
│       └── index.css                 # Theme system (CSS variables + role colors)
└── electron-builder.yml             # Cross-platform build config
```

### Conditional Routing Reference

| Edge Function | Outputs | Leads To |
|---|---|---|
| `check_approval(state)` | `approved` \| `rejected` | next agent \| done |
| `check_gates_and_route(state)` | `pass_next_agent` \| `fail_fix_loop` \| `trigger_replan` \| `fail_max_retries` | advance \| retry \| replan \| fail |
| `check_replan_result(state)` | `replan_failed` \| `replan_continue` | fail \| retry once |
| `check_pipeline_complete(state)` | `pipeline_done` \| `more_agents` \| `parallel_fan_out` \| `pipeline_failed` | finalize \| next \| parallel \| fail |
| `check_parallel_postprocess(state)` | pipeline route \| `debate_needed` | advance \| debate |
| `advance_to_next_agent(state)` | next role name | execute_agent |

### API Endpoints

```
POST   /v1/tasks                       # Create task (description, tier, project_id)
GET    /v1/tasks/{task_id}             # Task status + agent outputs + confidence_score
GET    /v1/tasks/{task_id}/detail      # Full task detail with events + execution_logs
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
pytest tests/ -q --ignore=tests/unit/infrastructure/test_dashboard.py

# TypeScript check
cd apps/desktop && npx tsc --noEmit

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
