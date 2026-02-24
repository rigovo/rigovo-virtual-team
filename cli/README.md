# Rigovo Teams CLI

[![Rigour Score](https://img.shields.io/badge/Rigour_Score-73%2F100-brightgreen)](https://github.com/rigour-labs/rigour)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-261%20passed-success)]()

**Virtual Engineering Team as a Service** — AI-powered multi-agent orchestration for software development, governed by [Rigour](https://github.com/rigour-labs/rigour) deterministic quality gates.

Rigovo assembles specialized AI agents (planner, coder, reviewer, security, qa, devops, sre, lead) into a virtual engineering team. Every line of agent-generated code passes through Rigour's 23+ quality gates — catching hallucinated imports, hardcoded secrets, and floating promises **the instant they're written**, not after CI fails.

> Built by [Ashutosh Singh](https://github.com/erashu212) — author of [Rigour](https://github.com/rigour-labs/rigour).

---

## Installation

```bash
pip install rigovo
```

With optional extras:

```bash
pip install rigovo[embeddings]    # Adds sentence-transformers for semantic memory
pip install rigovo[groq]          # Adds Groq LLM provider support
pip install rigovo[dev]           # Development tools (pytest, ruff, mypy)
```

Requires **Python 3.10+** and **Node.js 18+** (for Rigour CLI via `npx`).

---

## Quick Start

```bash
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
Team Assembler picks agents (planner → coder → reviewer)
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

8 agent roles, each with a dedicated system prompt, tool set, and pipeline order:

| Role ID | Name | Pipeline Order | Produces Code | Default Model |
|---------|------|---------------|---------------|---------------|
| `lead` | Tech Lead | −1 (first when included) | No | `claude-sonnet-4-5-20250929` |
| `planner` | Technical Planner | 0 | No | `claude-sonnet-4-5-20250929` |
| `coder` | Software Engineer | 1 | Yes | `claude-sonnet-4-5-20250929` |
| `reviewer` | Code Reviewer | 2 | No | `claude-sonnet-4-5-20250929` |
| `security` | Security Expert | 3 | No | `claude-sonnet-4-5-20250929` |
| `qa` | QA Engineer | 4 | Yes | `claude-sonnet-4-5-20250929` |
| `devops` | DevOps Engineer | 5 | Yes | `claude-sonnet-4-5-20250929` |
| `sre` | Site Reliability Engineer | 6 | Yes | `claude-sonnet-4-5-20250929` |

Override models per agent in `rigovo.yml`:

```yaml
teams:
  engineering:
    agents:
      coder:
        model: "claude-opus-4-5-20251101"
        temperature: 0.1
        timeout_seconds: 120
        rules:
          - "Use Pydantic v2 model_validator"
          - "All endpoints must have OpenAPI docs"
      security:
        model: "claude-opus-4-5-20251101"
```

### Task Classification

The Master Agent classifies every task into:

| Type | Description |
|------|-------------|
| `FEATURE` | New functionality |
| `BUG` | Bug fix |
| `REFACTOR` | Code restructuring |
| `TEST` | Test creation or improvement |
| `DOCS` | Documentation |
| `INFRA` | Infrastructure changes |
| `SECURITY` | Security fixes |
| `PERFORMANCE` | Performance optimization |
| `INVESTIGATION` | Research or analysis |

And assigns complexity: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.

### Budget Controls

```yaml
orchestration:
  budget:
    max_cost_per_task: 2.00           # USD — hard limit per task
    max_tokens_per_task: 200000       # Token limit per task
    monthly_budget: 100.00            # USD — monthly cap
    alert_at_percent: 0.80            # Alert at 80% usage
    hard_stop_at_percent: 1.0         # Stop at 100%
```

Pipeline enforces hard limits — `BudgetExceededError` stops execution immediately if cost or token limits are hit.

### Human-in-the-Loop Approvals

```yaml
approval:
  after_planning: true      # Review the plan before coding starts
  after_coding: false       # Skip approval after coding
  after_review: false       # Skip approval after review
  before_commit: true       # Approve before any git commits
  auto_approve:             # Auto-approve certain task types
    - type: "test"
      max_files: 3
    - type: "docs"
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
| `rigovo run <description>` | Execute a task through the full pipeline |
| `rigovo run <description> --ci` | CI mode — JSON output, non-interactive |
| `rigovo run <description> --team <name>` | Target a specific team |
| `rigovo run <description> --offline` | Run without cloud sync |
| `rigovo init` | Initialize project with auto-detection |
| `rigovo init --force` | Overwrite existing rigovo.yml |
| `rigovo doctor` | Validate configuration, API keys, and Rigour gates |
| `rigovo version` | Show CLI version |

### Inspection

| Command | Description |
|---------|-------------|
| `rigovo teams` | List configured teams with agents, models, and rules |
| `rigovo agents` | Agent summary — all roles with models and tools |
| `rigovo agents <role_id>` | Detailed inspection of a specific agent (e.g., `rigovo agents coder`) |
| `rigovo config` | View current rigovo.yml configuration |
| `rigovo config <key>` | View a specific config key (dot notation, e.g., `orchestration.budget`) |
| `rigovo config <key> --set <value>` | Set config with dot notation (e.g., `rigovo config orchestration.max_retries --set 5`) |
| `rigovo status` | Project health — task stats, costs, Rigour score |

### History & Costs

| Command | Description |
|---------|-------------|
| `rigovo history` | Task execution history with audit trail |
| `rigovo history <task_id>` | Detailed view of a specific task run |
| `rigovo history --limit 50` | Show last 50 tasks (default: 20) |
| `rigovo history --status completed` | Filter by status |
| `rigovo costs` | Cost breakdown by agent with budget status |
| `rigovo export` | Export history as JSON (default) |
| `rigovo export --format csv` | Export as CSV |
| `rigovo export --output report.json` | Export to a specific file |

### Advanced

| Command | Description |
|---------|-------------|
| `rigovo replay <task_id>` | Re-run a failed task with same parameters |
| `rigovo dashboard` | Open Rigovo cloud dashboard in browser |
| `rigovo upgrade` | Check PyPI for updates |
| `rigovo login` | Authenticate with Rigovo Cloud |

**Total: 15 commands** — all documented above with exact signatures.

---

## Configuration

Rigovo uses a layered configuration system (higher layers override lower):

| Layer | Source | Purpose |
|-------|--------|---------|
| 1 | Built-in defaults | Sensible starting point |
| 2 | `rigovo.yml` | Project settings (version-controlled) |
| 3 | `rigour.yml` | Quality gate thresholds (version-controlled) |
| 4 | `.env` | Secrets — API keys (gitignored) |
| 5 | Environment variables | CI overrides |
| 6 | CLI flags | One-off overrides |

### Full rigovo.yml Reference

```yaml
version: "1"

# ── Project metadata (auto-detected by `rigovo init`) ──
project:
  name: my-app
  language: python                     # python, typescript, rust, go, java
  framework: fastapi                   # nextjs, fastapi, express, django
  monorepo: false
  test_framework: pytest               # pytest, jest, vitest, cargo-test
  package_manager: pip                 # npm, pnpm, yarn, pip, poetry, cargo
  source_dir: src
  test_dir: tests

# ── Teams and agent overrides ──
teams:
  engineering:
    enabled: true
    domain: engineering
    agents:
      coder:
        model: "claude-sonnet-4-5-20250929"
        temperature: 0.0
        max_tokens: 4096
        rules: ["Use Pydantic v2", "FastAPI dependency injection"]
        tools: ["read_file", "write_file", "list_directory", "search_codebase", "run_command"]
        approval_required: false
        max_retries: 3
        timeout_seconds: 300
      security:
        model: "claude-opus-4-5-20251101"

# ── Quality gate configuration ──
quality:
  rigour_enabled: true
  rigour_binary: null                  # Auto-detect (npx @rigour-labs/cli)
  rigour_timeout: 120                  # seconds
  gates:
    hardcoded-secrets:
      enabled: true
      severity: error                  # error | warning | info
      threshold: 0                     # 0 = zero tolerance
    file-size:
      enabled: true
      severity: warning
      threshold: 500
    function-length:
      enabled: true
      severity: warning
      threshold: 50
    hallucinated-imports:
      enabled: true
      severity: error
      threshold: 0
  custom_rules:
    - id: no-print-statements
      pattern: "print\\("
      message: "Use logger instead of print()"
      severity: warning
      file_types: ["*.py"]

# ── Human-in-the-loop approval gates ──
approval:
  after_planning: true
  after_coding: false
  after_review: false
  before_commit: true
  auto_approve:
    - type: test
      max_files: 3
    - type: docs

# ── Pipeline and execution ──
orchestration:
  max_retries: 3
  max_agents_per_task: 8
  timeout_per_agent: 300               # seconds
  parallel_agents: false
  budget:
    max_cost_per_task: 2.00            # USD per task
    max_tokens_per_task: 200000
    monthly_budget: 100.00             # USD per month
    alert_at_percent: 0.80             # Alert at 80%
    hard_stop_at_percent: 1.0          # Stop at 100%

# ── Cloud sync (metadata only — never source code) ──
cloud:
  enabled: false
  sync_on_completion: true
  sync_interval_seconds: 300

# ── CI/CD integration ──
ci:
  enabled: false
  mode: non-interactive                # non-interactive | minimal
  output_format: json                  # json | text
  fail_on_gate_failure: true
  github_actions: false
  gitlab_ci: false

# ── Logging ──
logging:
  level: info                          # debug | info | warning | error
  structured: false                    # JSON logging
  file: .rigovo/rigovo.log
```

### Required Environment Variables

```bash
# .env (auto-generated by rigovo init)
ANTHROPIC_API_KEY=sk-ant-...      # Required for Claude models
OPENAI_API_KEY=sk-...             # Required for GPT models
RIGOVO_API_KEY=...                # Optional — cloud sync
```

---

## Domain Entities

| Entity | Purpose | Key Fields |
|--------|---------|------------|
| `Task` | Unit of work through the pipeline | `description`, `task_type`, `complexity`, `status`, `pipeline_steps`, `total_cost_usd`, `duration_ms`, `retries` |
| `Agent` | Individual AI agent in a team | `role`, `name`, `system_prompt`, `llm_model`, `tools`, `custom_rules`, `pipeline_order` |
| `Team` | Group of agents for a domain | `name`, `domain`, `is_active` |
| `Workspace` | Top-level project container | `name`, `slug`, `owner_id`, `plan` (FREE/PRO/ENTERPRISE) |
| `Quality` | Gate results and violations | `GateResult`, `Violation`, `FixPacket` with severity and instructions |
| `CostEntry` | Per-invocation cost tracking | `llm_model`, `input_tokens`, `output_tokens`, `cost_usd`, `agent_id` |
| `Memory` | Cross-task learnings | `content`, `memory_type` (TASK_OUTCOME/PATTERN/ERROR_FIX/CONVENTION/etc.), `embedding`, `usage_count` |
| `AuditEntry` | Full audit trail | `action` (23 audit actions), `summary`, `agent_role`, `metadata` |

### Task Lifecycle

```
PENDING → CLASSIFYING → ROUTING → ASSEMBLING → AWAITING_APPROVAL → RUNNING → QUALITY_CHECK → COMPLETED
                                                                                              ↓
                                                                          (retry) ← ← ← ← FAILED
                                                                                              ↓
                                                                                           REJECTED
```

### Domain Interfaces

| Interface | Methods | Purpose |
|-----------|---------|---------|
| `LLMProvider` | `invoke()`, `stream()` | Abstract LLM adapter (Anthropic, OpenAI) |
| `QualityGate` | `run()` | Abstract quality gate (Rigour implementation) |
| `DomainPlugin` | `get_agent_roles()`, `get_quality_gates()` | Pluggable domain definitions |
| `EventEmitter` | `emit()`, `on()` | Pipeline event bus |
| `EmbeddingProvider` | `embed()` | Semantic embedding for memory |
| `TaskRepository` | `save()`, `get()`, `list_by_workspace()` | Task persistence |
| `AgentRepository` | `save()`, `get()` | Agent persistence |
| `CostRepository` | `save()`, `get_by_task()`, `get_monthly_total()` | Cost persistence |
| `AuditRepository` | `save()`, `get_by_task()` | Audit persistence |
| `MemoryRepository` | `save()`, `search()`, `get_by_type()` | Memory persistence |

---

## Architecture

```
rigovo/
├── domain/           # Pure domain (entities, interfaces, services)
│   ├── entities/     # Task, Agent, Team, Workspace, Quality, Memory, CostEntry, AuditEntry
│   ├── interfaces/   # LLMProvider, QualityGate, DomainPlugin, EventEmitter,
│   │                 # EmbeddingProvider, TaskRepo, AgentRepo, CostRepo, AuditRepo, MemoryRepo
│   └── services/     # CostCalculator, TeamAssembler, MemoryRanker
├── application/      # Use cases (commands, graph, master agent)
│   ├── commands/     # RunTaskCommand (full pipeline orchestrator)
│   ├── graph/        # LangGraph nodes + edges + state
│   │   └── nodes/    # classify, assemble, execute_agent, quality_check,
│   │                 # route_team, approval, finalize, store_memory
│   └── master/       # Classifier, Router, Enricher, Evaluator
├── infrastructure/   # Adapters (LLM providers, DB, filesystem)
│   ├── llm/          # Anthropic, OpenAI providers
│   ├── persistence/  # SQLite repos (tasks, costs, audit, memory)
│   ├── filesystem/   # ProjectReader, CodeWriter, CommandRunner
│   ├── quality/      # RigourQualityGate (wraps rigour CLI)
│   ├── cloud/        # CloudSyncClient
│   ├── embeddings/   # SentenceTransformer embedding provider
│   └── terminal/     # Rich console output
├── domains/          # Domain plugins
│   ├── engineering/  # 8 agent roles + engineering-specific gates
│   └── llm_training/ # Future: LLM training domain
├── config.py         # Merged config (YAML + .env + env vars)
├── config_schema.py  # rigovo.yml Pydantic schema + auto-detection intelligence
├── container.py      # Dependency injection (Composition Root)
└── main.py           # Typer CLI — 15 commands
```

Follows **Hexagonal Architecture** with **Dependency Inversion** — domain layer has zero infrastructure dependencies. All wiring happens in `container.py` (Composition Root pattern).

### Graph Pipeline (8 nodes)

```
classify → route_team → assemble → [approval] → execute_agent → quality_check → finalize → store_memory
                                                      ↑                ↓
                                                      └── retry (Fix Packet) ──┘
```

---

## Development

```bash
git clone https://github.com/rigovo/rigovo-virtual-team.git
cd rigovo-virtual-team/cli
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
| CLI commands | 42 | All 15 commands via Typer test runner |
| Graph nodes | 30+ | All 8 pipeline nodes in isolation |
| **Total** | **261** | **100% passing** |

### Versioning

This project uses [python-semantic-release](https://python-semantic-release.readthedocs.io/) with [Conventional Commits](https://www.conventionalcommits.org/):

```bash
feat: add new agent role       # → bumps minor (0.1.0 → 0.2.0)
fix: correct budget overflow   # → bumps patch (0.1.0 → 0.1.1)
perf: optimize gate execution  # → bumps patch
feat!: redesign pipeline API   # → bumps major (0.1.0 → 1.0.0)
```

GitHub Actions handles versioning, changelog, and PyPI publishing automatically on merge to `main`.

---

## Requirements

- Python 3.10+
- Node.js 18+ (for Rigour CLI — `npx @rigour-labs/cli`)
- An API key for at least one LLM provider (Anthropic recommended)

## License

MIT © [Rigovo](https://rigovo.com)

Built by [Ashutosh Singh](https://github.com/erashu212) — powering virtual engineering teams with deterministic quality gates.
