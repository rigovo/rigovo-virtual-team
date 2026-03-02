<p align="center">
  <img src="apps/desktop/resources/icon.svg" width="80" alt="Rigovo" />
</p>

<h1 align="center">Rigovo Teams</h1>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/tests-946_passed-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
  <img src="https://img.shields.io/badge/desktop-Electron-blueviolet?style=flat-square" />
</p>

<p align="center">
  <strong>Your virtual AI engineering team. Describe a task — get production-ready code.</strong>
</p>

---

## What Is Rigovo Teams

Rigovo Teams assembles a coordinated team of AI agents to turn task descriptions into production-ready code. Each agent has a specific role, learns from past work, and is governed by quality gates that enforce real standards.

You describe what needs to be done. Rigovo handles the rest:

1. **Scans** your codebase to understand context
2. **Detects intent** — brainstorm, research, fix, or build — and allocates resources accordingly
3. **Classifies** task type and complexity
4. **Assembles** the right team (2–12 agents depending on intent)
5. **Executes** each agent with tools, quality gates, and automatic retries
6. **Reviews** code via parallel reviewer, security, and QA agents
7. **Learns** from every task — memories and skill profiles persist across projects

---

## The Team

| Role | What It Does | Default Model |
|---|---|---|
| **Planner** | Reads the codebase, produces a structured plan for the team | Sonnet |
| **Coder** | Implements the task — writes code, runs tests, uses tools | Opus |
| **Reviewer** | Reviews code for logic errors and improvements | Sonnet |
| **Security** | Scans for vulnerabilities, injection risks, auth issues | Haiku |
| **QA** | Writes and runs tests | Haiku |
| **DevOps** | CI/CD, Docker, GitHub Actions, infrastructure config | Haiku |
| **SRE** | Observability, alerting, SLOs, runbooks | Haiku |
| **Tech Lead** | Final review across all agent outputs — SHIP or HOLD | Opus |
| **Docs** | API docs, READMEs, architecture decision records | Sonnet |

All models are configurable per-agent from the Settings → Agents tab in the desktop app, or via `rigovo.yml`.

---

## Intent Detection — Smart Resource Allocation

Before any agent runs, Rigovo detects **what kind of task** you're asking for and allocates resources accordingly. This is zero-LLM, pure regex, under 5ms.

| Intent | Max Agents | Token Budget | File Reads | Planner Mode |
|---|---|---|---|---|
| **Brainstorm** | 2 | 50K | 0 | Think (no codebase) |
| **Research** | 3 | 150K | 15 | Survey |
| **Fix** | 5 | 300K | 30 | Survey |
| **Build** | 12 | 500K | Unlimited | Survey |

A brainstorming task that only needs a conversation won't burn 500K tokens assembling 12 agents. Intent detection ensures you only pay for what the task actually needs.

---

## The Pipeline

```
scan → classify → intent_gate → route_team → assemble
    ↓
[Optional] plan_approval → REJECTED → done
    ↓ approved
execute_agent → quality_check
    │              │
    │        pass  ↓
    │       next agent or parallel fan-out
    │
    │        fail → retry with fix packet (up to 5x)
    │        fail → replan → retry once more
    ↓
[reviewer ║ security ║ qa] ← parallel execution
    ↓
[Optional debate] ← if reviewer requests changes
    ↓
[Optional] commit_approval
    ↓
enrich → evaluate_skills → store_memory → finalize
```

---

## Quality Gates

After every code-producing agent, 23+ deterministic quality gates run automatically (no LLM cost, under 1 second):

- File size limits, type hints, naming conventions
- Error handling (no bare `except:`), magic number detection
- Async safety, import validation, forbidden content
- Hallucinated imports, secrets detection, command injection
- Output contract and persona boundary validation

When gates fail, a **fix packet** tells the agent exactly what's wrong and how to fix it. The agent retries automatically (up to 5 attempts). If retries are exhausted, a **replan** generates a corrective directive and the agent runs once more.

**Smart deep mode** adds LLM-powered analysis selectively — for critical tasks, security roles, high-retry agents, and final pipeline steps.

Every completed task receives a **confidence score** (0–100) based on gate pass rate, retry count, violations, and deep analysis results.

---

## Memory and Learning

Rigovo learns from every task:

- **Memories** — extracted learnings stored as vectors, retrieved by semantic similarity for future tasks. Works across projects.
- **Enrichment** — agent-specific pitfalls (e.g., "Never use bare except in auth code") persist and are injected into system prompts on subsequent tasks.
- **Skill profiles** — rolling performance metrics per agent (success rate, avg tokens, common violations) that improve team composition decisions over time.

---

## Desktop App

Cross-platform Electron app with dark/light theme.

**Key screens:**
- **Task Input** — describe what you want, select workspace
- **Agent Timeline** — watch agents execute in real-time
- **Pipeline Map** — visual DAG topology of the running pipeline
- **Agent Detail** — execution logs, tool calls, cost, consultation threads
- **Approval Cards** — approve/reject at plan and commit stages
- **Settings** — API keys, per-agent model selection, orchestration config, quality gates

**Settings are hot-reloaded** — changes apply to the next task immediately, no restart needed.

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 20+ and pnpm 9+ (desktop app)
- API key: Anthropic, OpenAI, Google, DeepSeek, Groq, or Mistral
- WorkOS account (optional — for auth in desktop app)

### Install

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
# Checks: Python, config, API keys, database, Rigour CLI, git
```

### Run a Task (CLI)

```bash
rigovo run "Add input validation to all API endpoints with proper error responses"
```

### Desktop App (Development)

```bash
./scripts/e2e_desktop.sh
```

### Desktop App (Production Build)

```bash
pnpm -C apps/desktop install
pnpm -C apps/desktop run build
pnpm -C apps/desktop run dist
# Output: apps/desktop/release/ (macOS .dmg, Windows .exe, Linux .AppImage)
```

---

## Configuration

### API Keys

API keys are stored **encrypted in SQLite** — not in plain text files. Set them via the desktop Settings page or `.env` for CLI usage.

```bash
# .env (CLI usage)
ANTHROPIC_API_KEY=sk-ant-...
```

### Per-Agent Model Configuration

Three ways to configure which model each agent uses (highest priority wins):

1. **Settings UI** — Desktop app → Settings → Agents tab (saves to `rigovo.yml`)
2. **rigovo.yml** — `teams.engineering.agents.<role>.model`
3. **Environment variable** — `LLM_AGENT_MODELS='{"coder":"claude-opus-4-6","qa":"claude-haiku-4-5"}'`

### rigovo.yml

```yaml
version: "1"

teams:
  engineering:
    agents:
      planner:
        model: "claude-sonnet-4-6"
      coder:
        model: "claude-opus-4-6"
      reviewer:
        model: "claude-sonnet-4-6"

orchestration:
  max_retries: 5
  max_agents_per_task: 10
  consultation:
    enabled: true
  replan:
    enabled: true
    strategy: deterministic  # deterministic | llm

approval:
  after_planning: true
  before_commit: true

quality:
  deep_mode: "smart"  # never | final | smart | always | ci

database:
  backend: sqlite      # sqlite | postgres
  local_path: ".rigovo/local.db"
```

### Auth (WorkOS)

```bash
# .env
WORKOS_CLIENT_ID=client_01...
RIGOVO_IDENTITY_PROVIDER=workos
```

Redirect URI must be `http://127.0.0.1:8787/v1/auth/callback` — set this in your WorkOS dashboard.

---

## API

```
POST   /v1/tasks                    Create a task
GET    /v1/tasks/{id}               Task status + outputs + confidence score
GET    /v1/tasks/{id}/detail        Full detail with events + execution logs
GET    /v1/ui/inbox                 Task list
GET    /v1/ui/approvals             Pending approvals
POST   /v1/tasks/{id}/approve       Approve
POST   /v1/tasks/{id}/deny          Reject
GET    /v1/settings                 Current settings
POST   /v1/settings                 Update settings (hot-reloaded)
GET    /v1/auth/url                 WorkOS auth URL
GET    /v1/auth/callback            Auth redirect handler
GET    /v1/auth/session             Current session
POST   /v1/auth/logout              Clear session
GET    /v1/projects                 List projects
POST   /v1/projects                 Register project
GET    /health                      Health check
```

---

## Running Tests

```bash
# Python (946 tests)
pytest tests/ -q --ignore=tests/unit/infrastructure/test_dashboard.py

# TypeScript (zero errors)
cd apps/desktop && npx tsc --noEmit
```

---

## Project Structure

```
src/rigovo/
├── api/control_plane.py          # FastAPI endpoints + event streaming
├── application/
│   ├── graph/
│   │   ├── builder.py            # LangGraph pipeline builder
│   │   ├── edges.py              # Conditional routing
│   │   ├── state.py              # TaskState (pipeline data)
│   │   └── nodes/                # Pipeline nodes (scan, classify, intent_gate,
│   │                             #   route_team, assemble, execute_agent,
│   │                             #   quality_check, replan, enrich, finalize)
│   ├── context/                  # Codebase scanning, memory retrieval
│   ├── commands/run_task.py      # Task execution entry point
│   └── master/                   # Classification, routing, enrichment
├── domains/engineering/          # Agent roles, tools, rules
├── infrastructure/
│   ├── llm/                      # LLM providers (Anthropic, OpenAI, etc.)
│   ├── persistence/              # SQLite + PostgreSQL
│   ├── quality/                  # Rigour quality gate builder
│   └── filesystem/               # Sandboxed tool executor
├── config.py                     # Config loading (rigovo.yml + .env + env vars)
└── container.py                  # Dependency injection + hot-reload

apps/desktop/
├── src/main/                     # Electron main process
├── src/preload/                  # Context bridge
└── src/renderer/src/components/  # React UI (TaskDetail, AgentTimeline,
                                  #   Settings, ApprovalCard, etc.)
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
