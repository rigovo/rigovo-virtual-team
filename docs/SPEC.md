# Rigovo Teams — Product Specification

## Vision

Virtual Engineering Team as a Service. One CLI command spins up 8 AI
agents that plan, code, review, test, and deploy — with deterministic
quality gates and live cost tracking.

## Core Workflow

```
rigovo init          → detect stack, generate rigovo.yml
rigovo doctor        → verify setup (API keys, tools, config)
rigovo run "task"    → execute full agent pipeline
rigovo               → (future) TUI dashboard
```

## Agent Pipeline

Each task flows through a pipeline of specialised agents:

1. **Lead** — classifies task type and complexity
2. **Planner** — breaks task into implementation steps
3. **Coder** — writes code following the plan
4. **Reviewer** — reviews code for bugs, security, and style
5. **QA** — writes and runs tests
6. **Security** — scans for vulnerabilities
7. **DevOps** — generates CI/CD, Docker, infrastructure
8. **SRE** — monitors, alerts, runbooks

## Quality Gates

All code-producing agents pass through Rigour quality gates:

- Hardcoded secrets detection
- Hallucinated imports (non-existent packages)
- File size limits (SRP enforcement)
- Context window artifact detection
- Async safety analysis
- Custom regex rules per project

## Model Flexibility

- Any model from any provider works
- 3 built-in presets: budget, recommended, premium
- Per-agent model overrides in rigovo.yml
- Custom provider support for self-hosted endpoints
- Live cost tracking (known models show $, unknown show tokens)

## Configuration

- `rigovo.yml` — version-controlled project config (auto-generated)
- `.env` — secrets (API keys, never committed)
- CLI flags — runtime overrides

## Data Storage

- SQLite local database (`.rigovo/local.db`)
- Task history, audit trail, cost tracking
- Optional cloud sync (metadata only, never source code)
