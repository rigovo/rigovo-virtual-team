# Rigovo Teams CLI

[![Rigour Score](https://img.shields.io/badge/Rigour_Score-73%2F100-brightgreen)](https://github.com/rigour-labs/rigour)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-261%20passed-success)]()

**Virtual Engineering Team as a Service** — AI-powered multi-agent orchestration for software development, governed by [Rigour](https://github.com/rigour-labs/rigour) deterministic quality gates.

Rigovo assembles specialized AI agents (planner, backend, frontend, reviewer, security auditor) into a virtual engineering team. Every line of agent-generated code passes through Rigour's 23+ quality gates — catching hallucinated imports, hardcoded secrets, and floating promises **the instant they're written**, not after CI fails.

> Built by [Ashutosh Singh](https://github.com/erashu212) — author of [Rigour](https://github.com/rigour-labs/rigour).

---

## Quick Start

```bash
pip install rigovo
cd your-project
rigovo init                                       # Auto-detects stack, generates rigovo.yml + rigour.yml
rigovo doctor                                     # Validates config, API keys, Rigour gates
rigovo run "Add user authentication with JWT"     # Full pipeline: plan → code → review → gates → done
```

---

## How It Works

```
You describe a task
    ↓
Master Agent classifies (feature/bugfix/refactor) + routes to team
    ↓
Team Assembler picks agents (planner → backend → reviewer)
    ↓
Agents execute sequentially with context isolation
    ↓
Rigour quality gates run (23 AST gates + 40 deep semantic checks)
    ↓
Gate FAIL? → Fix Packet generated → agents retry automatically
    ↓
Gate PASS → results persisted with cost tracking + audit trail
```

---

## Rigour Integration — The Governance Layer

Rigovo doesn't just generate code — it **enforces production standards** using [Rigour](https://github.com/rigour-labs/rigour), the deterministic quality gate engine for AI-generated code.

### How Rigour Governs Every Agent

**Layer 1 — Real-time hooks** (<200ms per file write):
As each agent writes code, Rigour hooks catch issues instantly — before the next agent even starts.

```bash
npx @rigour-labs/cli hooks init    # Wire into the pipeline
```

4 fast gates run on every file: `hallucinated-imports`, `promise-safety`, `security-patterns`, `file-size`.

**Layer 2 — Full quality gates** (23 gates per pipeline run):
After agent execution, `rigour check` runs the complete gate suite. Failures produce structured **Fix Packets** (JSON) that agents consume directly — no human interpretation needed.

```
Agent writes code → Rigour hook catches issue → Agent retries → Hook passes → Full check → PASS ✓
```

**Layer 3 — Deep analysis** (40+ LLM-powered semantic checks):
Optional deep analysis catches architectural issues: SOLID violations, god classes, feature envy, race conditions, circular dependencies.

```bash
npx @rigour-labs/cli check --deep                          # Local model (free, private)
npx @rigour-labs/cli check --deep --provider anthropic     # Cloud (higher quality)
```

### What Rigour Catches

**Security Gates:**

| Gate | What It Catches | Severity |
|------|----------------|----------|
| Hardcoded Secrets | API keys (`sk-`, `ghp_`, `AKIA`), passwords, tokens | critical |
| SQL Injection | Unsanitized query construction | critical |
| Command Injection | Shell execution with user input | critical |
| XSS Patterns | Dangerous DOM manipulation | high |
| Path Traversal | File operations with unsanitized paths | high |

**AI Drift Detection:**

| Gate | What It Catches | Severity |
|------|----------------|----------|
| Hallucinated Imports | Imports referencing packages that don't exist (8 languages) | critical |
| Duplication Drift | Near-identical functions — AI re-invents what it forgot | high |
| Context Window Artifacts | Quality degrades top-to-bottom — context overflow | high |
| Inconsistent Error Handling | Same error handled 4 different ways | high |
| Async & Error Safety | Floating promises, unhandled errors (6 languages) | high |
| Phantom APIs | Method calls to functions that don't exist on the module | high |
| Deprecated APIs | Security-deprecated APIs AI models trained on | critical |

**Structural Gates:**

| Gate | What It Enforces | Severity |
|------|-----------------|----------|
| Cyclomatic Complexity | Max 10 per function (configurable) | medium |
| File Size | Max lines per file (default 400) | low |
| Method/Param/Nesting | Max 12 methods, 5 params, 4 nesting levels | medium |
| Content Hygiene | Zero tolerance for TODO/FIXME left by agents | info |

**Agent Governance:**

| Gate | Purpose | Severity |
|------|---------|----------|
| Agent Team | Multi-agent scope isolation and conflict detection | high |
| Checkpoint | Long-running execution supervision | medium |
| Retry Loop Breaker | Detects and stops infinite agent loops | high |

### Fix Packet Schema (v2) — Machine-Readable Diagnostics

When gates fail, Rigour generates structured Fix Packets that agents consume directly:

```json
{
  "violations": [{
    "id": "ast-complexity",
    "severity": "high",
    "file": "src/auth.ts",
    "line": 45,
    "metrics": { "current": 15, "max": 10 },
    "instructions": [
      "Extract nested conditional logic into validateToken()",
      "Replace switch statement with strategy pattern"
    ]
  }],
  "constraints": {
    "no_new_deps": true,
    "do_not_touch": [".github/**", "docs/**"]
  }
}
```

### Rigour Scoring

Every gate failure carries a provenance tag (`ai-drift`, `traditional`, `security`, `governance`):

```
  Overall     ██████████████████████████░░░░ 73/100
  AI Health   █████████████████████████░░░░░ 75/100
  Structural  ██████████████████████████████ 98/100
```

| Severity | Deduction | What It Means |
|----------|-----------|---------------|
| critical | −20 pts | Security vulnerabilities, hallucinated code |
| high | −10 pts | AI drift patterns, architectural violations |
| medium | −5 pts | Complexity violations, structural issues |
| low | −2 pts | File size limits |
| info | 0 pts | TODOs — tracked but free |

### Rigour MCP Server

For IDE integration, Rigour exposes an MCP server:

```json
{
  "mcpServers": {
    "rigour": {
      "command": "npx",
      "args": ["-y", "@rigour-labs/mcp"]
    }
  }
}
```

Available MCP tools: `rigour_check`, `rigour_explain`, `rigour_get_fix_packet`, `rigour_review`, `rigour_check_deep`, `rigour_security_audit`, `rigour_check_pattern`, `rigour_remember`, `rigour_recall`, `rigour_run_supervised`, `rigour_agent_register`, `rigour_checkpoint`, `rigour_handoff`.

### Rigour Supervisor Mode

Run agents under Rigour's full supervision — automatic retry loop with quality gates:

```bash
npx @rigour-labs/cli run -- claude "Refactor auth module"
```

Runs the agent → checks gates → feeds Fix Packets back → retries until PASS or max retries.

---

## Features

### Intelligent Project Detection
`rigovo init` scans your project and auto-generates both `rigovo.yml` and `rigour.yml`:

- Detects language (Python, TypeScript, Rust, Go), framework (Next.js, FastAPI, Django, Express), test runner, package manager, monorepo structure
- Injects language-specific rules per agent role (e.g., "use Pydantic v2 validators" for Python backend agents)
- Configures Rigour quality gates with framework-appropriate thresholds
- Generates `.env` template with required API key placeholders

### Multi-Agent Pipeline

| Agent | Role | Default Model |
|-------|------|---------------|
| Technical Planner | Architecture, task breakdown | claude-sonnet-4-5 |
| Backend Engineer | Server-side implementation | claude-sonnet-4-5 |
| Frontend Engineer | UI/UX implementation | claude-sonnet-4-5 |
| Code Reviewer | Quality review, best practices | claude-sonnet-4-5 |
| Security Auditor | Vulnerability analysis, OWASP | claude-sonnet-4-5 |
| DevOps Engineer | CI/CD, infrastructure | claude-sonnet-4-5 |

Override models per agent:
```yaml
teams:
  default:
    agent_overrides:
      backend:
        llm_model: "claude-opus-4-5-20251101"
        temperature: 0.1
        timeout_seconds: 120
        rules:
          - "Use Pydantic v2 model_validator"
          - "All endpoints must have OpenAPI docs"
```

### Budget Controls

```yaml
budget:
  max_cost_per_task: 2.00
  max_tokens_per_task: 200000
  monthly_limit: 100.00
  alert_threshold: 0.8
```

Pipeline enforces hard limits — `BudgetExceededError` stops execution immediately if cost or token limits are hit.

### Human-in-the-Loop Approvals

```yaml
approval:
  after_planning: true      # Review the plan before coding starts
  before_commit: true       # Approve before any git commits
  after_coding: false       # Skip approval after coding
  after_review: false       # Skip approval after review
```

### CI Mode
Non-interactive JSON output for CI/CD pipelines:
```bash
rigovo run "Fix the auth bug" --ci
# Outputs: {"status": "completed", "score": 73, ...}
```

---

## CLI Commands

### Core
| Command | Description |
|---------|-------------|
| `rigovo run <task>` | Execute a task through the full pipeline |
| `rigovo run <task> --ci` | CI mode — JSON output, non-interactive |
| `rigovo init` | Initialize project with auto-detection |
| `rigovo doctor` | Validate configuration, API keys, and Rigour gates |
| `rigovo version` | Show version |

### Inspection
| Command | Description |
|---------|-------------|
| `rigovo teams` | List configured teams with agents, models, and rules |
| `rigovo agents` | Agent summary; `--detail <role>` for full inspection |
| `rigovo config` | View current configuration |
| `rigovo config --set <key> <value>` | Set config with dot notation (e.g., `orchestration.max_retries 5`) |
| `rigovo status` | Project health — task stats, costs, Rigour score |

### History & Costs
| Command | Description |
|---------|-------------|
| `rigovo history` | Task execution history with audit trail |
| `rigovo history --show <id>` | Detailed view of a specific task run |
| `rigovo costs` | Cost breakdown by agent with budget status |
| `rigovo export` | Export history as JSON or CSV |

### Advanced
| Command | Description |
|---------|-------------|
| `rigovo replay <task-id>` | Re-run a failed task with same parameters |
| `rigovo dashboard` | Open web dashboard (Rigour Studio) |
| `rigovo upgrade` | Check PyPI for updates |
| `rigovo login` | Authenticate with Rigovo Cloud |

---

## Configuration

Rigovo uses a layered configuration system:

| Layer | Source | Purpose |
|-------|--------|---------|
| 1 | Built-in defaults | Sensible starting point |
| 2 | `rigovo.yml` | Project settings (version-controlled) |
| 3 | `rigour.yml` | Quality gate thresholds (version-controlled) |
| 4 | `.env` | Secrets — API keys (gitignored) |
| 5 | Environment variables | CI overrides |
| 6 | CLI flags | One-off overrides |

### Example rigovo.yml
```yaml
project:
  name: my-app
  language: python
  framework: fastapi
  test_framework: pytest
  package_manager: pip

teams:
  default:
    agent_overrides:
      backend:
        llm_model: "claude-sonnet-4-5-20250929"
        rules: ["Use Pydantic v2", "FastAPI dependency injection"]
      security:
        llm_model: "claude-opus-4-5-20251101"

quality:
  rigour_enabled: true
  rigour_binary: "npx @rigour-labs/cli"
  gates:
    complexity:
      threshold: 15
      severity: error
    test-coverage:
      threshold: 80
      severity: warning

orchestration:
  max_retries: 3
  max_agents_per_task: 6

approval:
  after_planning: true
  before_commit: true

budget:
  max_cost_per_task: 2.00
  monthly_limit: 100.00
  alert_threshold: 0.8
```

### Required Environment Variables
```bash
# .env (auto-generated by rigovo init)
ANTHROPIC_API_KEY=sk-ant-...      # Required for Claude models
OPENAI_API_KEY=sk-...             # Required for GPT models
RIGOVO_API_KEY=...                # Optional — cloud sync
```

---

## Architecture

```
rigovo/
├── domain/           # Pure domain (entities, interfaces, services)
│   ├── entities/     # Task, Agent, Team, Quality, Memory, CostEntry, AuditEntry
│   ├── interfaces/   # LLMProvider, QualityGate, EventEmitter, Repositories
│   └── services/     # CostCalculator, TeamAssembler, MemoryRanker
├── application/      # Use cases (commands, graph, master agent)
│   ├── commands/     # RunTaskCommand (full pipeline orchestrator)
│   ├── graph/        # LangGraph nodes + edges + state
│   │   └── nodes/    # classify, assemble, execute_agent, quality_check,
│   │                 # finalize, store_memory, approval, route_team
│   └── master/       # Classifier, Router, Enricher, Evaluator
├── infrastructure/   # Adapters (LLM providers, DB, filesystem)
│   ├── llm/          # Anthropic, OpenAI providers
│   ├── persistence/  # SQLite repos (tasks, costs, audit, memory)
│   ├── filesystem/   # ProjectReader, CodeWriter, CommandRunner
│   ├── quality/      # RigourQualityGate (wraps rigour CLI)
│   └── cloud/        # CloudSyncClient
├── domains/          # Domain plugins (engineering roles + gates)
├── config.py         # Merged config (YAML + .env + env vars)
├── config_schema.py  # rigovo.yml Pydantic schema + auto-detection intelligence
├── container.py      # Dependency injection (Composition Root)
└── main.py           # Typer CLI — all commands
```

Follows **Hexagonal Architecture** with **Dependency Inversion** — domain layer has zero infrastructure dependencies. All wiring happens in `container.py` (Composition Root pattern).

---

## Development

```bash
git clone https://github.com/rigovo/rigovo-teams.git
cd rigovo-teams/cli
pip install -e ".[dev]"

# Quality
pytest                                    # 261 tests
ruff check src/                           # Lint
npx @rigour-labs/cli check               # Rigour gates (73/100)
npx @rigour-labs/cli check --deep         # + 40 semantic checks
```

### Test Coverage

| Test Suite | Count | What It Covers |
|-----------|-------|----------------|
| Domain entities | 50+ | Task lifecycle, Agent, Team, Quality, Memory |
| Master services | 30+ | Classifier, Router, Enricher, Evaluator |
| Infrastructure | 40+ | SQLite repos, LLM providers, Rigour gate |
| Config schema | 66 | YAML I/O, auto-detection, smart rules |
| CLI commands | 42 | All commands via Typer test runner |
| Graph nodes | 30+ | All pipeline nodes in isolation |
| **Total** | **261** | **100% passing** |

---

## Requirements

- Python 3.10+
- Node.js 18+ (for Rigour CLI — `npx @rigour-labs/cli`)
- An API key for at least one LLM provider (Anthropic recommended)

## License

MIT © [Rigovo](https://rigovo.com)

Built by [Ashutosh Singh](https://github.com/erashu212) — powering virtual engineering teams with deterministic quality gates.
