<p align="center">
  <img src="https://img.shields.io/pypi/v/rigovo?style=for-the-badge&color=blue" alt="PyPI" />
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=for-the-badge" alt="Python" />
  <img src="https://img.shields.io/badge/tests-261_passed-brightgreen?style=for-the-badge" alt="Tests" />
  <img src="https://img.shields.io/badge/license-MIT-yellow?style=for-the-badge" alt="License" />
</p>

<h1 align="center">Rigovo — Virtual Engineering Team as a Service</h1>

<p align="center">
  <strong>8 AI agents. One CLI. Production-grade code with deterministic quality gates.</strong><br/>
  Stop babysitting AI. Rigovo assembles a full engineering team — planner, coder, reviewer, security, QA, devops, SRE, tech lead — that ships code governed by <a href="https://github.com/rigour-labs/rigour">Rigour</a> quality gates.
</p>

---

## Get Started in 60 Seconds

```bash
pip install rigovo
```

```
$ cd your-project
$ rigovo init

Rigovo — Project Initialization

  Detected: python/fastapi
  Source:   src/
  Tests:    tests/
  Package:  pip

  Created: rigovo.yml
  Created: rigour.yml
  Created: .env (add your API key)
  Created: .rigovo/

  Next steps:
    1. Add your API key to .env
    2. Run: rigovo doctor
    3. Run: rigovo run "your first task"
```

```
$ rigovo doctor

Rigovo — Doctor

  ✓ Python 3.10.12
  ✓ Platform: Linux aarch64
  ✓ rigovo.yml found
  ✓ rigovo.yml valid (version 1)
  ✓ Project: python/fastapi
  ✓ .env found
  ✓ .rigovo/ directory exists
  ✓ Local database exists (116.0 KB)
  ✓ ANTHROPIC_API_KEY configured
  ✓ typer installed (CLI framework)
  ✓ rich installed (Terminal UI)
  ✓ pydantic installed (Configuration)
  ✓ anthropic installed (Anthropic SDK)
  ✓ langgraph installed (LangGraph orchestration)
  ✓ Rigour CLI available (npx @rigour-labs/cli)
  ✓ git found: /usr/bin/git
  ✓ Disk space: 2.3 GB free

  0 issue(s) found, 18 passed
```

```
$ rigovo run "Add user authentication with JWT and refresh tokens"

Rigovo — Running Task

  ▸ Classifying task...
    Type:       FEATURE
    Complexity: HIGH
    Agents:     planner → coder → reviewer → security → qa

  ▸ Planning...
    Tech Lead assigned context: python/fastapi, 12 existing endpoints
    Planner produced 4-step implementation plan

  ⏸ Approval required — review the plan? [Y/n] y

  ▸ Coding...
    Software Engineer writing: src/auth/router.py, src/auth/service.py,
    src/auth/models.py, src/auth/dependencies.py

  ▸ Reviewing...
    Code Reviewer: 2 suggestions (applied automatically)

  ▸ Security scan...
    Security Expert: PASSED — no vulnerabilities found

  ▸ Quality gates...
    Rigour: 23 gates passed, score 94/100

  ▸ QA...
    QA Engineer: 8 tests written, all passing

  ✓ Task completed in 47s — $0.32 total cost
    Files: 4 created, 1 modified
    Tests: 8 new, all passing
    Rigour: 94/100
```

That's it. One command. Full engineering team.

---

## Meet Your Team

```
$ rigovo agents

Rigovo — Agents

                        Software Engineering Agents
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Role ID  ┃ Name                      ┃ Model      ┃ Code ┃ Rules ┃ Tools ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━╇━━━━━━━╇━━━━━━━┩
│ planner  │ Technical Planner         │ sonnet-4.5 │  —   │     — │     4 │
│ coder    │ Software Engineer         │ sonnet-4.5 │  ✓   │     7 │     6 │
│ reviewer │ Code Reviewer             │ sonnet-4.5 │  —   │     3 │     3 │
│ security │ Security Expert           │ sonnet-4.5 │  —   │     — │     3 │
│ qa       │ QA Engineer               │ sonnet-4.5 │  ✓   │     — │     5 │
│ devops   │ DevOps Engineer           │ sonnet-4.5 │  ✓   │     — │     4 │
│ sre      │ Site Reliability Engineer │ sonnet-4.5 │  ✓   │     — │     4 │
│ lead     │ Tech Lead                 │ sonnet-4.5 │  —   │     — │     3 │
└──────────┴───────────────────────────┴────────────┴──────┴───────┴───────┘
```

Each agent has a dedicated system prompt, specialized tools, and custom rules for your stack. Inspect any agent:

```
$ rigovo agents coder

Rigovo — Agents

  Software Engineer (coder)
  Implements code changes following the plan. Writes production-quality code.

  Model:          claude-sonnet-4-5-20250929
  Produces code:  Yes
  Pipeline order: 1
  Tools:          read_file, write_file, list_directory, search_codebase,
                  run_command, read_dependencies

  Custom rules (7):
    • Use type hints on all function signatures
    • Follow PEP 8 conventions
    • Use dataclasses or Pydantic models for structured data
    • Use pathlib.Path instead of os.path
    • Use Pydantic models for all request/response schemas
    • Add OpenAPI descriptions to all endpoints
    • Use dependency injection for services
```

Rules are auto-generated based on your stack. Python/FastAPI gets different rules than TypeScript/Next.js.

---

## How It Works

```
You describe a task
    ↓
Master Agent classifies → FEATURE / BUG / REFACTOR / SECURITY / ...
    ↓
Team Assembler picks the right agents for the job
    ↓
Agents execute in sequence with context isolation
    ↓
Rigour quality gates run (23+ AST gates — no LLM opinions)
    ↓
Gate FAIL? → Fix Packet → agents retry automatically
    ↓
Gate PASS → results persisted with cost tracking + audit trail
```

### Task Classification

The Master Agent routes every task to the right pipeline:

| Type | Example | Agents Used |
|------|---------|-------------|
| `FEATURE` | "Add JWT auth" | planner → coder → reviewer → security → qa |
| `BUG` | "Fix login crash" | coder → reviewer → qa |
| `REFACTOR` | "Split auth module" | planner → coder → reviewer |
| `SECURITY` | "Fix SQL injection" | security → coder → reviewer → qa |
| `TEST` | "Add unit tests for auth" | qa |
| `INFRA` | "Add Docker support" | devops → sre |
| `PERFORMANCE` | "Optimize query N+1" | coder → reviewer |

Complexity (LOW / MEDIUM / HIGH / CRITICAL) determines budget allocation and timeout.

---

## Quality Gates — Powered by Rigour

Every line of agent-generated code passes through [Rigour](https://github.com/rigour-labs/rigour) — deterministic AST checks, not LLM opinions. Catches issues the instant they're written, not after CI fails.

**What Rigour catches:**

| Category | Gates | Examples |
|----------|-------|---------|
| **Security** | Hardcoded secrets, SQL injection, command injection, XSS, path traversal | `sk-ant-...` in source, `f"SELECT * FROM {user_input}"` |
| **AI Drift** | Hallucinated imports, duplication drift, context window artifacts, phantom APIs | `from utils.magic import solve` (doesn't exist) |
| **Structure** | Cyclomatic complexity, file size, function length, nesting depth | 500-line god function, 8 levels of nesting |
| **Safety** | Floating promises, unhandled errors, deprecated APIs, bare excepts | `async fetch()` with no `await` |

When gates fail, Rigour generates structured **Fix Packets** — machine-readable diagnostics that agents consume directly. No human interpretation needed. Agents retry automatically until gates pass.

```
Agent writes code → Rigour gate catches issue → Fix Packet generated → Agent retries → PASS ✓
```

---

## All 15 Commands

### Setup

| Command | What it does |
|---------|-------------|
| `rigovo init` | Auto-detect your stack, generate `rigovo.yml` + `rigour.yml` + `.env` |
| `rigovo doctor` | Validate everything — config, API keys, dependencies, Rigour gates |
| `rigovo version` | Show CLI version |
| `rigovo upgrade` | Check PyPI for updates |

### Run

| Command | What it does |
|---------|-------------|
| `rigovo run "Add JWT auth"` | Full pipeline — plan → code → review → gates → done |
| `rigovo run "Fix bug" --ci` | CI mode — JSON output, non-interactive |
| `rigovo run "Deploy" --team ops` | Target a specific team |
| `rigovo replay <task_id>` | Re-run a failed task with same parameters |

### Inspect

| Command | What it does |
|---------|-------------|
| `rigovo teams` | List teams with agents, models, and rules |
| `rigovo agents` | Agent summary table |
| `rigovo agents coder` | Deep inspect a specific agent |
| `rigovo config` | View full `rigovo.yml` |
| `rigovo config orchestration.budget` | View a specific config section |
| `rigovo status` | Project health — tasks, costs, Rigour score |

### Track

| Command | What it does |
|---------|-------------|
| `rigovo history` | Task history with outcomes, costs, durations |
| `rigovo history <task_id>` | Detailed view of a specific run |
| `rigovo costs` | Cost breakdown — per task, per agent, totals |
| `rigovo export` | Export as JSON (default) or `--format csv` |
| `rigovo login` | Authenticate with Rigovo Cloud |
| `rigovo dashboard` | Open cloud dashboard in browser |

---

## Configuration

Rigovo uses layered configuration — higher layers override lower:

```
Built-in defaults → rigovo.yml → rigour.yml → .env → env vars → CLI flags
```

### Quick Config Examples

**Override agent model:**
```yaml
# rigovo.yml
teams:
  engineering:
    agents:
      coder:
        model: "claude-opus-4-5-20251101"    # Use Opus for coding
        temperature: 0.1
      security:
        model: "claude-opus-4-5-20251101"    # Use Opus for security
```

**Set budget limits:**
```yaml
orchestration:
  budget:
    max_cost_per_task: 2.00       # USD per task
    max_tokens_per_task: 200000
    monthly_budget: 100.00        # USD per month
    alert_at_percent: 0.80        # Alert at 80%
```

**Add custom rules per agent:**
```yaml
teams:
  engineering:
    agents:
      coder:
        rules:
          - "Use Pydantic v2 model_validator"
          - "All endpoints must have OpenAPI docs"
          - "Use dependency injection for services"
```

**Human-in-the-loop approvals:**
```yaml
approval:
  after_planning: true     # Review the plan before coding
  before_commit: true      # Approve before git commits
  auto_approve:
    - type: "test"         # Auto-approve test tasks
      max_files: 3
    - type: "docs"         # Auto-approve docs tasks
```

### Environment Variables

```bash
# .env (auto-generated by rigovo init — gitignored)
ANTHROPIC_API_KEY=sk-ant-...      # Required for Claude models
# OPENAI_API_KEY=sk-...           # Alternative: GPT models
# RIGOVO_API_KEY=...              # Optional: cloud sync
```

---

## Architecture

```
rigovo/
├── domain/           # Pure domain — zero infrastructure dependencies
│   ├── entities/     # Task, Agent, Team, Workspace, Quality, Memory, Cost, Audit
│   ├── interfaces/   # LLMProvider, QualityGate, DomainPlugin, EventEmitter
│   └── services/     # CostCalculator, TeamAssembler, MemoryRanker
├── application/      # Use cases
│   ├── commands/     # RunTaskCommand (full pipeline orchestrator)
│   ├── graph/        # LangGraph pipeline — 8 nodes
│   └── master/       # Classifier, Router, Enricher, Evaluator
├── infrastructure/   # Adapters
│   ├── llm/          # Anthropic, OpenAI providers
│   ├── persistence/  # SQLite (tasks, costs, audit, memory)
│   ├── quality/      # Rigour quality gate integration
│   └── terminal/     # Rich console output
├── domains/          # Pluggable domain definitions
│   └── engineering/  # 8 agent roles + engineering-specific gates
├── config.py         # Merged config (YAML + .env + env vars)
├── container.py      # Dependency injection (Composition Root)
└── main.py           # Typer CLI — 15 commands
```

Hexagonal architecture with dependency inversion. Domain layer has zero infrastructure imports.

### Pipeline Flow

```
classify → route_team → assemble → [approval] → execute_agent → quality_check → finalize → store_memory
                                                       ↑                ↓
                                                       └── retry (Fix Packet) ──┘
```

---

## CI/CD

GitHub Actions workflows included. CI runs tests, lint, and Rigour gates. Publishing happens only after CI passes — no duplicate work.

```bash
# CI triggers on push to main/develop (cli/** paths only)
# Publish triggers via workflow_run AFTER CI succeeds
# Uses PyPI Trusted Publishing (OIDC) — no API keys in secrets
```

Versioning uses [python-semantic-release](https://python-semantic-release.readthedocs.io/) with [Conventional Commits](https://www.conventionalcommits.org/):

```bash
feat: add new agent role       # → minor bump (0.1.0 → 0.2.0)
fix: correct budget overflow   # → patch bump (0.1.0 → 0.1.1)
feat!: redesign pipeline API   # → major bump (0.1.0 → 1.0.0)
```

---

## Development

```bash
git clone https://github.com/rigovo/rigovo-virtual-team.git
cd rigovo-virtual-team/cli
pip install -e ".[dev]"

pytest                                    # 261 tests
ruff check src/                           # Lint
npx @rigour-labs/cli check               # Rigour gates
```

---

## Requirements

- Python 3.10+
- Node.js 18+ (for Rigour CLI via `npx`)
- API key for at least one LLM provider (Anthropic recommended)

## License

MIT — [Rigovo](https://rigovo.com)

Built by [Ashutosh Singh](https://github.com/erashu212) — author of [Rigour](https://github.com/rigour-labs/rigour).
