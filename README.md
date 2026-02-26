<p align="center">
  <img src="https://img.shields.io/pypi/v/rigovo?style=for-the-badge&color=blue" alt="PyPI" />
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=for-the-badge" alt="Python" />
  <img src="https://img.shields.io/badge/tests-353_passed-brightgreen?style=for-the-badge" alt="Tests" />
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

RIGOVO │ Add user authentication with JWT and refresh tokens
  Team: engineering

  🔍 Scanned: 42 files (python, fastapi)
  🧠 Classified: feature (high)
     JWT auth with refresh tokens requires multiple new modules

  🔧 Pipeline: 📋 planner → 💻 coder → 🔍 reviewer → 🔒 security → 🧪 qa
     📋 planner → Claude Sonnet 4.6
     💻 coder → Claude Opus 4.6
     🔍 reviewer → Claude Sonnet 4.6
     🔒 security → Claude Haiku 4.5
     🧪 qa → Claude Haiku 4.5

─────────────────── 📋 planner ───────────────────
  ✓ 📋 planner 4,211 tok │ $0.0213 │ 3.2s

─────────────────── 💻 coder ────────────────────
  ✓ 💻 coder 12,847 tok │ $0.1024 │ 18.4s
    └─ 4 file(s): src/auth/router.py, src/auth/service.py, ...

  ✓ Gates passed for coder

  ⚡ Parallel execution: 🔍 reviewer 🔒 security 🧪 qa
  ✓ Parallel execution complete

╭──────────────────── Task Complete ────────────────────╮
│   Status      COMPLETED                               │
│   Duration    47.2s                                   │
│   Agents      📋 planner → 💻 coder → 🔍 reviewer    │
│               → 🔒 security → 🧪 qa                  │
│   Tokens      24,891                                  │
│   Cost        $0.3241                                 │
╰───────────────────────────────────────────────────────╯
```

That's it. One command. Full engineering team.

---

## Meet Your Team

```
$ rigovo agents

Rigovo — Agents

                        Software Engineering Agents
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Role ID  ┃ Name                      ┃ Model              ┃ Code ┃ Rules ┃ Tools ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━╇━━━━━━━┩
│ planner  │ Technical Planner         │ Claude Sonnet 4.6  │  —   │     — │     5 │
│ coder    │ Software Engineer         │ Claude Opus 4.6    │  ✓   │     7 │     8 │
│ reviewer │ Code Reviewer             │ Claude Sonnet 4.6  │  —   │     3 │     4 │
│ security │ Security Expert           │ Claude Haiku 4.5   │  —   │     — │     4 │
│ qa       │ QA Engineer               │ Claude Haiku 4.5   │  ✓   │     — │     6 │
│ devops   │ DevOps Engineer           │ Claude Haiku 4.5   │  ✓   │     — │     5 │
│ sre      │ Site Reliability Engineer │ Claude Haiku 4.5   │  ✓   │     — │     5 │
│ lead     │ Tech Lead                 │ Claude Opus 4.6    │  —   │     — │     4 │
└──────────┴───────────────────────────┴────────────────────┴──────┴───────┴───────┘
```

Each agent has a dedicated system prompt, specialized tools, and custom rules for your stack. Inspect any agent:

```
$ rigovo agents coder

Rigovo — Agents

  Software Engineer (coder)
  Implements code changes following the plan. Writes production-quality code.

  Model:          Claude Opus 4.6
  Produces code:  Yes
  Pipeline order: 1
  Tools:          read_file, write_file, list_directory, search_codebase,
                  run_command, read_dependencies, spawn_subtask, consult_agent

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

## Architecture Overview

Rigovo follows hexagonal architecture (ports & adapters) with strict dependency inversion. The domain layer has zero infrastructure imports — it defines interfaces that the infrastructure layer implements.

```mermaid
graph TB
    subgraph CLI["CLI Layer"]
        TYPER[Typer CLI<br/>15 commands]
        TUI[Rich Terminal UI<br/>Streaming output]
    end

    subgraph APP["Application Layer"]
        CMD[RunTaskCommand<br/>Task lifecycle orchestrator]
        GRAPH[LangGraph StateGraph<br/>Compiled orchestration graph]
        MASTER[Master Agent<br/>Classifier · Router · Enricher · Evaluator]
        CTX[Context Engineering<br/>Scanner · Memory · Enrichment]
    end

    subgraph DOMAIN["Domain Layer — Zero I/O"]
        ENT[Entities<br/>Task · Agent · Team · Quality · Memory]
        IFACE[Interfaces<br/>LLMProvider · QualityGate · DomainPlugin]
        SVC[Services<br/>CostCalculator · TeamAssembler · MemoryRanker]
    end

    subgraph INFRA["Infrastructure Layer"]
        LLM[LLM Providers<br/>Anthropic · OpenAI · Groq · Ollama]
        QG[Quality Gates<br/>Rigour CLI wrapper]
        FS[Filesystem<br/>ToolExecutor · ProjectScanner]
        DB[Persistence<br/>SQLite repos × 4]
    end

    subgraph PLUGINS["Domain Plugins"]
        ENG[Engineering Domain<br/>8 roles · 8 tools · AST gates]
        FUTURE[Future Domains<br/>LLM Training · Data Science · ...]
    end

    CLI --> APP
    APP --> DOMAIN
    APP --> INFRA
    INFRA -.->|implements| IFACE
    PLUGINS -.->|implements| IFACE
```

### Project Structure

```
rigovo/
├── cli/                  # Typer commands (15 total) + Rich terminal UI
│   ├── main.py           # CLI entry point — rigovo run, init, doctor, ...
│   ├── commands_*.py     # Command implementations grouped by concern
│   └── terminal/         # Rich console: streaming, approval prompts, summary
├── application/          # Use-case orchestration — the "brain"
│   ├── commands/         # RunTaskCommand — full task lifecycle orchestrator
│   ├── graph/            # LangGraph pipeline: builder, state, edges, 10 nodes
│   ├── master/           # Master Agent: classifier, router, enricher, evaluator
│   └── context/          # Context engineering: scanner, memory retriever, builder
├── domain/               # Pure domain logic — zero infrastructure dependencies
│   ├── entities/         # Task, Agent, Team, Workspace, Quality, Memory, Cost, Audit
│   ├── interfaces/       # LLMProvider, QualityGate, DomainPlugin, EventEmitter
│   └── services/         # CostCalculator, TeamAssembler, MemoryRanker
├── infrastructure/       # Concrete implementations (adapters)
│   ├── llm/              # Anthropic, OpenAI providers + model catalog + registry
│   ├── quality/          # Rigour CLI quality gate wrapper
│   ├── persistence/      # SQLite: tasks, costs, audit, memory (4 repos)
│   ├── filesystem/       # Tool executor: read/write files, run commands
│   ├── embeddings/       # Embedding models for memory similarity search
│   └── terminal/         # Rich console output with streaming
├── domains/              # Pluggable domain definitions
│   └── engineering/      # 8 agent roles, 8 tools, engineering-specific gates
├── config.py             # Layered config: built-in → YAML → .env → env vars → CLI
└── container.py          # Dependency injection (Composition Root)
```

---

## Pipeline Architecture

Every task flows through a compiled LangGraph `StateGraph` — a directed acyclic graph with conditional edges, parallel fan-out, and SQLite checkpointing for crash recovery.

```mermaid
flowchart TD
    START((START)) --> SCAN

    subgraph PERCEIVE["Phase 1: Perception"]
        SCAN[🔍 scan_project<br/>Read codebase structure,<br/>detect tech stack, entry points]
    end

    SCAN --> CLASSIFY

    subgraph THINK["Phase 2: Classification & Assembly"]
        CLASSIFY[🧠 classify<br/>Master Agent classifies<br/>task type & complexity]
        CLASSIFY --> ASSEMBLE[🔧 assemble<br/>TeamAssembler builds<br/>agent pipeline & gate schedule]
    end

    ASSEMBLE --> PLAN_APPROVAL

    subgraph APPROVE_PLAN["Phase 3: Plan Approval"]
        PLAN_APPROVAL{⚠️ plan_approval<br/>User reviews pipeline}
    end

    PLAN_APPROVAL -->|rejected| FINALIZE
    PLAN_APPROVAL -->|approved| EXECUTE

    subgraph EXECUTE_LOOP["Phase 4: Agent Execution Loop"]
        EXECUTE[⚡ execute_agent<br/>Run current agent with<br/>context engineering]
        EXECUTE -.-> CONSULT[💬 consult_agent<br/>Advisory-only role-to-role<br/>consultation policy-gated]
        CONSULT -.-> EXECUTE
        EXECUTE --> QUALITY[🛡️ quality_check<br/>Run Rigour AST gates<br/>on files changed]
        QUALITY --> GATE_ROUTE{Gates passed?}
        GATE_ROUTE -->|fail + retries left| EXECUTE
        GATE_ROUTE -->|fail + max retries| FINALIZE
        GATE_ROUTE -->|pass| ROUTE_NEXT[route_next<br/>Advance pipeline index]
        ROUTE_NEXT --> PIPELINE_CHECK{Pipeline complete?}
        PIPELINE_CHECK -->|more agents| EXECUTE
        PIPELINE_CHECK -->|parallelizable agents| PARALLEL
        PIPELINE_CHECK -->|done| COMMIT
    end

    subgraph PARALLEL_PHASE["Phase 5: Parallel Fan-Out"]
        PARALLEL[⚡ parallel_fan_out<br/>Execute reviewer + QA +<br/>security simultaneously]
        PARALLEL --> DEBATE_CHECK{Reviewer requested<br/>changes?}
        DEBATE_CHECK -->|debate needed| DEBATE[💬 debate_check<br/>Inject reviewer feedback,<br/>reset to coder]
        DEBATE --> EXECUTE
        DEBATE_CHECK -->|debate done| COMMIT
    end

    subgraph COMMIT_PHASE["Phase 6: Commit Approval"]
        COMMIT{⚠️ commit_approval<br/>User reviews all results}
    end

    COMMIT -->|rejected| FINALIZE
    COMMIT -->|approved| ENRICH

    subgraph LEARN["Phase 7: Learning Loop"]
        ENRICH[📚 enrich<br/>Extract learnings from<br/>gate violations & retries]
        ENRICH --> MEMORY[💾 store_memory<br/>Persist reusable lessons<br/>to memory repository]
    end

    MEMORY --> FINALIZE

    subgraph DONE["Phase 8: Finalization"]
        FINALIZE[📊 finalize<br/>Aggregate totals,<br/>determine final status]
    end

    FINALIZE --> END_NODE((END))
```

### Pipeline Nodes (10 total)

| # | Node | Purpose | Input | Output |
|---|------|---------|-------|--------|
| 1 | `scan_project` | Read codebase structure, detect tech stack | `project_root` | `ProjectSnapshot` |
| 2 | `classify` | Master Agent classifies task type & complexity | description + snapshot | `ClassificationData` |
| 3 | `assemble` | Build agent pipeline based on classification | classification + agents | `TeamConfig` with pipeline_order |
| 4 | `plan_approval` | User approves proposed pipeline | team config | approval_status |
| 5 | `execute_agent` | Run agent with full context engineering | agent config + context | `AgentOutput` |
| 6 | `quality_check` | Run Rigour AST gates on changed files | files_changed | `GateResult` |
| 7 | `route_next` | Advance to next agent, reset retry state | pipeline index | next agent config |
| 8 | `parallel_fan_out` | Execute independent agents simultaneously | remaining roles | merged `AgentOutput`s |
| 9 | `commit_approval` | User approves final results before commit | all outputs | approval_status |
| 10 | `enrich` + `store_memory` + `finalize` | Extract learnings, persist, aggregate | full state | final result |

---

## State Machine

All state flows through a single `TaskState` TypedDict — checkpointed after every node for crash recovery.

```mermaid
classDiagram
    class TaskState {
        +str task_id
        +str workspace_id
        +str description
        +str project_root
        +ClassificationData classification
        +TeamConfig team_config
        +int current_agent_index
        +str current_agent_role
        +dict agent_outputs
        +list agent_messages
        +dict gate_results
        +list fix_packets
        +int retry_count
        +int max_retries
        +str approval_status
        +dict cost_accumulator
        +float budget_max_cost_per_task
        +int budget_max_tokens_per_task
        +Any project_snapshot
        +int debate_round
        +int max_debate_rounds
        +str reviewer_feedback
        +list memories_to_store
        +str status
        +list events
    }

    class ClassificationData {
        +str task_type
        +str complexity
        +str reasoning
    }

    class TeamConfig {
        +str team_id
        +str team_name
        +dict agents
        +list pipeline_order
    }

    class AgentOutput {
        +str summary
        +list files_changed
        +int tokens
        +float cost
        +int duration_ms
    }

    class AgentMessage {
        +str id
        +str type
        +str from_role
        +str to_role
        +str status
        +str linked_to
        +str content
    }

    TaskState --> ClassificationData
    TaskState --> TeamConfig
    TaskState --> AgentOutput
    TaskState --> AgentMessage
```

---

## Agent Execution — Context Engineering

Each agent executes within a 5-phase context engineering loop inspired by the Perceive → Remember → Reason → Act → Verify pattern.

```mermaid
flowchart LR
    subgraph CONTEXT["Context Assembly (per agent)"]
        direction TB
        P[📂 Project Snapshot<br/>File tree, tech stack,<br/>key file contents]
        M[🧠 Retrieved Memories<br/>Ranked by similarity,<br/>recency, utility]
        E[📚 Enrichment Context<br/>Known pitfalls,<br/>domain knowledge]
        PI[📋 Pipeline Context<br/>Previous agent outputs]
        Q[🛡️ Quality Contract<br/>Role-specific expectations]
    end

    subgraph LOOP["Agentic Tool Loop"]
        direction TB
        LLM[LLM Invocation<br/>System prompt +<br/>assembled context]
        LLM -->|tool_calls| TOOLS[Tool Executor<br/>read_file, write_file,<br/>search, run_command,<br/>spawn_subtask, consult_agent]
        TOOLS -->|results| LLM
        LLM -->|end_turn| DONE[Agent Output<br/>summary, files_changed,<br/>tokens, cost]
    end

    CONTEXT --> LOOP
```

## Inter-Agent Consultation (Advisory Channel)

Agents can request targeted advice from other roles during execution via `consult_agent`. This is advisory-only and never replaces the target role's pipeline step.

```mermaid
flowchart LR
    A[Requesting Agent<br/>e.g. reviewer] -->|consult request to role| P{Policy Gate<br/>allowed_targets}
    P -->|blocked| ERR[Tool Error<br/>policy violation]
    P -->|allowed| READY{Target role<br/>already has output?}
    READY -->|yes| IMM[Immediate Advisory Response<br/>from target summary]
    READY -->|no| Q[Queue Pending Consult Request]
    Q --> TGT[Target Role executes later<br/>normal pipeline step]
    TGT --> AUTO[Auto-fulfill pending consult<br/>as advisory response]
    IMM --> THREAD[agent_messages thread]
    AUTO --> THREAD
```

### Consultation Policy via `rigovo.yml`

```yaml
orchestration:
  consultation:
    enabled: true
    max_question_chars: 1200
    max_response_chars: 1200
    allowed_targets:
      planner: [lead, security, devops]
      coder: [reviewer, security, qa]
      reviewer: [planner, coder, security, qa, devops, sre, lead]
      qa: [coder, reviewer]
```

- `consultation.allowed_targets` overrides the default matrix.
- Consultation responses are tagged advisory-only and do not count as task completion for the consulted role.

### Context Budget

Context is assembled with hard character limits to prevent blowup:

| Layer | Max Chars | Content |
|-------|-----------|---------|
| Project Snapshot | 15,000 | File tree, tech stack, entry points, key file contents |
| Retrieved Memories | 5,000 | Top 8 memories ranked by relevance to role |
| Enrichment Context | 5,000 | Known pitfalls, domain knowledge, conventions |
| Pipeline Context | 8,000 | Previous agent outputs (planner's plan, coder's files) |
| Quality Contract | 2,000 | Role-specific expectations ("Pass gates on first try") |
| **Total Budget** | **40,000** | Hard cap across all layers |

### Memory Retrieval & Ranking

Memories are ranked per-agent using a weighted scoring formula:

```
score = (0.6 × similarity) + (0.2 × recency) + (0.2 × utility)
```

Each role gets role-specific memory preferences — the coder prefers `ERROR_FIX` and `PATTERN` memories, while the planner prefers `CONVENTION` and `DOMAIN_KNOWLEDGE`. Maximum 8 memories per agent to keep context focused.

---

## Task Classification & Routing

The Master Agent classifies every task at temperature 0.0 (deterministic) before any agent executes.

```mermaid
flowchart LR
    DESC[Task Description] --> CLASSIFIER[Master Agent<br/>TaskClassifier<br/>T=0.0]
    CLASSIFIER --> TYPE[Task Type]
    CLASSIFIER --> CX[Complexity]
    TYPE --> ASSEMBLER[TeamAssembler]
    CX --> ASSEMBLER
    ASSEMBLER --> PIPELINE[Pipeline Order +<br/>Gate Schedule]
```

### Task Types → Agent Pipelines

| Type | Example | Pipeline | Gates After |
|------|---------|----------|-------------|
| `FEATURE` | "Add JWT auth" | planner → coder → reviewer → qa | coder |
| `BUG` | "Fix login crash" | coder → reviewer | coder |
| `REFACTOR` | "Split auth module" | planner → coder → reviewer | coder |
| `SECURITY` | "Fix SQL injection" | security → coder → reviewer → qa | coder |
| `TEST` | "Add unit tests" | qa | qa |
| `INFRA` | "Add Docker support" | devops → sre → reviewer | devops, sre |
| `PERFORMANCE` | "Optimize N+1 query" | coder → reviewer | coder |

### Complexity Adjustments

| Complexity | Modifications |
|------------|---------------|
| `LOW` | Minimal pipeline, lower budget |
| `MEDIUM` | Standard pipeline |
| `HIGH` | Prepend `lead` for architectural oversight |
| `CRITICAL` | Prepend `lead` + append `security` if not present |

---

## Quality Gates — Powered by Rigour

Every line of agent-generated code passes through [Rigour](https://github.com/rigour-labs/rigour) — deterministic AST checks, not LLM opinions. Catches issues the instant they're written, not after CI fails.

```mermaid
flowchart LR
    CODE[Agent writes code] --> RIGOUR[Rigour CLI<br/>rigour check --json<br/>+ auto --deep by policy]
    RIGOUR --> PASS{Passed?}
    PASS -->|yes| NEXT[Next agent]
    PASS -->|no| FP[Fix Packet<br/>Machine-readable<br/>diagnostics]
    FP --> RETRY[Agent retries<br/>with fix packet context]
    RETRY --> RIGOUR
```

### Automatic Deep Analysis Policy (Default)

Rigovo does not rely on manual user flags for deep analysis. By default:

- `orchestration.deep_mode: final`
- Deep analysis runs automatically on the **final gated role** in the pipeline.
- Earlier gated roles use fast deterministic checks for speed.

Available modes:

- `never` — disable deep analysis
- `final` — deep on final gated role (default)
- `ci` — deep only when running `rigovo run --ci ...`
- `always` — deep on every gated role
- `critical_only` — deep only for `critical` complexity tasks

Use `orchestration.deep_pro: true` to run deep in pro tier.

Deep/pro output is parsed into the same violation model as standard gates, so agents receive fix packets and auto-correct without user intervention.

### What Rigour Catches

| Category | Gates | Examples |
|----------|-------|---------|
| **Security** | Hardcoded secrets, SQL injection, command injection, XSS, path traversal | `sk-ant-...` in source, `f"SELECT * FROM {user_input}"` |
| **AI Drift** | Hallucinated imports, duplication drift, context window artifacts, phantom APIs | `from utils.magic import solve` (doesn't exist) |
| **Structure** | Cyclomatic complexity, file size, function length, nesting depth | 500-line god function, 8 levels of nesting |
| **Safety** | Floating promises, unhandled errors, deprecated APIs, bare excepts | `async fetch()` with no `await` |

### Fix Packet Protocol

When gates fail, Rigour generates structured **Fix Packets** — machine-readable diagnostics that agents consume directly. No human interpretation needed.

```
[FIX PACKET]
Attempt 1 of 5:
- [ERROR] no_hardcoded_secrets: Found API key in src/config.py:42
  Suggestion: Move to environment variable, use os.getenv("API_KEY")
- [WARNING] max_function_length: Function process_data() is 127 lines
  Suggestion: Extract helper functions for each processing step
```

Agents retry automatically with the fix packet injected into their context, up to `max_retries` (default: 5).

---

## Agent Debate Protocol

When the reviewer requests changes, the system enters a structured debate loop between the coder and reviewer — like a real code review.

```mermaid
sequenceDiagram
    participant C as Coder
    participant G as Quality Gates
    participant R as Reviewer
    participant Q as QA
    participant S as Security

    C->>G: Write code
    G->>G: AST check (PASS)

    par Parallel Review
        G->>R: Review code
        G->>Q: Write tests
        G->>S: Security audit
    end

    R-->>C: CHANGES_REQUESTED<br/>"Extract auth middleware,<br/>add input validation"

    Note over C,R: Debate Round 1

    C->>G: Revise code with feedback
    G->>G: AST check (PASS)
    G->>R: Re-review

    R-->>C: APPROVED

    Note over C,R: Max 2 debate rounds
```

The debate protocol detects markers in reviewer output (`CHANGES_REQUESTED`, `BLOCKED`, `needs revision`), injects the reviewer's feedback as a fix packet, and routes the coder back for another pass. Maximum 2 debate rounds by default.

---

## Parallel Execution

Independent agents execute simultaneously — cutting review-phase time from sum(individual) to max(individual).

```mermaid
flowchart TD
    CODER[💻 Coder<br/>Sequential — must run first] --> GATES[🛡️ Gates PASS]
    GATES --> FAN{All remaining<br/>agents parallelizable?}
    FAN -->|yes| PAR

    subgraph PAR["⚡ Parallel Fan-Out"]
        direction LR
        REV[🔍 Reviewer]
        QA[🧪 QA]
        SEC[🔒 Security]
    end

    FAN -->|no| SEQ[Sequential execution]

    PAR --> MERGE[Fan-In & Merge]
    SEQ --> MERGE
    MERGE --> DEBATE{Debate needed?}
```

### Parallelizable Roles

These roles have no inter-dependency — they all read the coder's output independently:

- `reviewer` — Code review and feedback
- `qa` — Test generation and validation
- `security` — Security audit
- `docs` — Documentation generation

Non-parallelizable roles (planner, coder, lead) must run sequentially because later agents depend on their output.

### Parallel Tool Execution

Within a single agent's tool loop, multiple tool calls from one LLM response execute simultaneously via `asyncio.gather()`. When the coder asks to read 5 files at once, all 5 reads happen in parallel.

---

## Sub-Agent Spawning

Agents can decompose complex tasks by spawning independent sub-agents — each with full tool access.

```mermaid
flowchart TD
    CODER[💻 Coder Agent] -->|spawn_subtask| SUB1[Sub-Agent 1<br/>Implement auth module]
    CODER -->|spawn_subtask| SUB2[Sub-Agent 2<br/>Add API endpoint]
    CODER -->|spawn_subtask| SUB3[Sub-Agent 3<br/>Write migration]

    SUB1 -->|result| CODER
    SUB2 -->|result| CODER
    SUB3 -->|result| CODER
```

The `spawn_subtask` tool allows agents to create parallel sub-agents during their agentic loop. Each sub-agent receives full tool access (read_file, write_file, search_codebase, run_command) and returns its output to the parent agent.

---

## Model Selection System

Rigovo uses intelligent per-role model defaults — the right model for each job.

```mermaid
flowchart TD
    ROLE[Agent Role] --> RESOLVE[resolve_model_for_role]

    RESOLVE --> USER{User override<br/>in rigovo.yml?}
    USER -->|yes| USE_USER[Use user's model]
    USER -->|no| DEFAULT[Role default<br/>from ROLE_DEFAULT_MODELS]

    DEFAULT --> PROVIDER{Provider<br/>available?}
    PROVIDER -->|yes| USE_DEFAULT[Use default model]
    PROVIDER -->|no| CATALOG[Model Catalog<br/>Find best alternative<br/>for available providers]
    CATALOG --> USE_ALT[Use alternative model]
```

### Default Model Assignments

| Role | Default Model | Tier | Why |
|------|---------------|------|-----|
| `lead` | Claude Opus 4.6 | Premium | Architectural decisions need strongest reasoning |
| `planner` | Claude Sonnet 4.6 | Standard | Planning: fast + smart enough |
| `coder` | Claude Opus 4.6 | Premium | Coding: best agent model for complex implementations |
| `reviewer` | Claude Sonnet 4.6 | Standard | Code review needs analysis, Sonnet suffices |
| `security` | Claude Haiku 4.5 | Budget | Checklist-based security audit |
| `qa` | Claude Haiku 4.5 | Budget | Test generation is formulaic |
| `devops` | Claude Haiku 4.5 | Budget | Template-based configurations |
| `sre` | Claude Haiku 4.5 | Budget | Template-based configurations |
| `docs` | Claude Haiku 4.5 | Budget | Text generation |

### Multi-Provider Support

Rigovo is provider-agnostic. If you only have an OpenAI key, the catalog resolves the best GPT model for each tier. Supported providers:

| Provider | Models | SDK |
|----------|--------|-----|
| Anthropic | Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 | `anthropic` |
| OpenAI | GPT-5, GPT-5 Mini, GPT-4o, o1, o3-mini | `openai` |
| Google | Gemini 2.5 Pro, Gemini 2.5 Flash | `openai` compatible |
| DeepSeek | V3.2, R1 | `openai` compatible |
| Mistral | Large 3, Medium 3, Codestral | `openai` compatible |
| Groq | Llama 3.3 70B | `openai` compatible |
| Ollama | Any local model | `openai` compatible |
| Custom | Any OpenAI-compatible endpoint | `openai` compatible |

### Preset System

Three presets auto-assign models across all roles:

| Preset | Description | Estimated Cost/Task |
|--------|-------------|---------------------|
| `budget` | Cheapest — still good for most tasks | ~$0.02 |
| `recommended` | Best quality/cost ratio | ~$0.15 |
| `premium` | Maximum quality — for critical tasks | ~$0.50 |

---

## LLM Provider Architecture

All LLM interactions go through a unified `LLMProvider` interface — the application layer never touches a concrete SDK.

```mermaid
classDiagram
    class LLMProvider {
        <<interface>>
        +model_name: str
        +invoke(messages, tools, temperature, max_tokens) LLMResponse
        +stream(messages, tools, temperature, max_tokens) AsyncIterator
    }

    class LLMResponse {
        +str content
        +LLMUsage usage
        +str model
        +str stop_reason
        +list tool_calls
        +Any raw
    }

    class LLMUsage {
        +int input_tokens
        +int output_tokens
        +total_tokens: int
    }

    class AnthropicProvider {
        -api_key: str
        -model: str
        +invoke() LLMResponse
        +stream() AsyncIterator
        -_invoke_with_retry()
    }

    class OpenAIProvider {
        -api_key: str
        -model: str
        -base_url: str
        +invoke() LLMResponse
        +stream() AsyncIterator
        -_invoke_with_retry()
    }

    LLMProvider <|.. AnthropicProvider
    LLMProvider <|.. OpenAIProvider
    LLMProvider --> LLMResponse
    LLMResponse --> LLMUsage
```

### Token Optimization

- **Prompt Caching (Anthropic):** System prompts use `cache_control: {type: "ephemeral"}` — saving 90% of input tokens after the first call in an agentic loop (cached tokens cost 10% of fresh tokens).
- **Prompt Caching (OpenAI):** Automatic prefix-based caching for repeated message prefixes (1024+ tokens). Optimized by keeping system messages at the start for prefix matching.
- **Tool Result Truncation:** Tool results are capped at 30,000 characters to prevent context window blowup from large file reads.
- **Retry with Exponential Backoff:** Both providers retry transient errors (429, 529, 500, 502, 503) with exponential backoff (1s, 2s, 4s, 8s, 16s) — up to 5 attempts.

---

## Cost Tracking & Budget Guards

Every LLM call is tracked. Budget guards prevent runaway costs by halting execution when limits are exceeded.

```mermaid
flowchart LR
    CALL[LLM Call] --> TRACK[CostCalculator<br/>input_tokens × price/1M<br/>+ output_tokens × price/1M]
    TRACK --> ACC[cost_accumulator<br/>Per-agent running total]
    ACC --> GUARD{Budget exceeded?}
    GUARD -->|cost ≥ max_cost| HALT[🛑 BudgetExceededError<br/>Task halts immediately]
    GUARD -->|tokens ≥ max_tokens| HALT
    GUARD -->|within budget| CONTINUE[Continue execution]
```

Default limits: `$2.00` per task, `200,000` tokens per task. Configurable in `rigovo.yml`.

---

## Approval System

Two human-in-the-loop checkpoints ensure you stay in control:

```mermaid
flowchart LR
    subgraph CP1["Checkpoint 1: Plan Approval"]
        PLAN[Pipeline assembled:<br/>task type, complexity,<br/>agent pipeline, budget]
    end

    subgraph CP2["Checkpoint 2: Commit Approval"]
        COMMIT[All agents complete:<br/>files changed, costs,<br/>gate results, agent outputs]
    end

    PLAN -->|approved| EXECUTE[Execute Agents]
    PLAN -->|rejected| FAIL1[Finalize: rejected]
    EXECUTE --> COMMIT
    COMMIT -->|approved| LEARN[Enrich + Memory]
    COMMIT -->|rejected| FAIL2[Finalize: rejected]
```

- **Plan Approval** — Review the proposed pipeline before any agent executes
- **Commit Approval** — Review all results before finalizing

Both checkpoints can be auto-approved for CI/CD workflows or interactive for human-in-the-loop development.

---

## Memory & Learning Loop

Rigovo learns from every task — quality gate failures become training data, not just errors.

```mermaid
flowchart TD
    TASK[Task Execution] --> GATE_FAIL[Gate Violations]
    TASK --> RETRIES[Retry Loops]
    TASK --> SUCCESS[Success Patterns]

    GATE_FAIL --> ENRICHER[ContextEnricher<br/>Extract pitfalls,<br/>domain knowledge]
    RETRIES --> ENRICHER
    SUCCESS --> ENRICHER

    ENRICHER --> INJECT[Inject into future<br/>agent contexts]

    TASK --> MEMORY[Memory Extraction<br/>Master Agent extracts<br/>reusable lessons]
    MEMORY --> STORE[SQLite Memory Store]
    STORE --> RETRIEVE[MemoryRetriever<br/>Ranked by similarity,<br/>recency, utility]
    RETRIEVE --> INJECT
```

### Memory Types

| Type | Example | Used By |
|------|---------|---------|
| `PATTERN` | "Use factory pattern for service creation" | Coder, Planner |
| `ERROR_FIX` | "SQLAlchemy async sessions need `expire_on_commit=False`" | Coder |
| `CONVENTION` | "All endpoints use Pydantic v2 model_validator" | Coder, Reviewer |
| `DOMAIN_KNOWLEDGE` | "Auth module uses JWT with 15-min access tokens" | All agents |
| `TASK_OUTCOME` | "Adding endpoints requires updating OpenAPI docs" | Planner |

---

## Persistence Layer

Four SQLite repositories handle all persistence — zero external database dependencies.

```mermaid
erDiagram
    TASKS {
        uuid id PK
        uuid workspace_id FK
        string description
        string status
        int total_tokens
        float total_cost_usd
        int duration_ms
        datetime created_at
    }

    COSTS {
        uuid id PK
        uuid task_id FK
        string agent_role
        int input_tokens
        int output_tokens
        float cost_usd
        string model
    }

    AUDIT {
        uuid id PK
        uuid workspace_id FK
        uuid task_id FK
        string action
        string agent_role
        string summary
        json metadata
        datetime created_at
    }

    MEMORIES {
        uuid id PK
        uuid workspace_id FK
        string memory_type
        string content
        float utility_score
        datetime created_at
    }

    TASKS ||--o{ COSTS : "has"
    TASKS ||--o{ AUDIT : "logged in"
```

Additionally, LangGraph uses a separate SQLite database (`.rigovo/checkpoints.db`) for state checkpointing — enabling crash recovery mid-task.

---

## Domain Plugin System

Rigovo is domain-extensible through a plugin interface. The `engineering` domain ships built-in; future domains (LLM training, data science) plug in the same way.

```mermaid
classDiagram
    class DomainPlugin {
        <<interface>>
        +get_agent_roles() list~AgentRoleDefinition~
        +get_task_types() list~TaskTypeDefinition~
        +get_quality_gates() list~QualityGate~
        +get_tools(role_id) list~ToolDefinition~
        +build_system_prompt(role_id, context) str
    }

    class EngineeringDomain {
        +get_agent_roles() 8 roles
        +get_tools(role_id) 7 tools
        +build_system_prompt() stack-aware prompts
    }

    DomainPlugin <|.. EngineeringDomain

    class AgentRoleDefinition {
        +str role_id
        +str name
        +str description
        +int pipeline_order
        +bool produces_code
        +str preferred_tier
        +str default_system_prompt
        +list default_tools
    }

    EngineeringDomain --> AgentRoleDefinition
```

### Engineering Domain — 8 Roles

| Role | Name | Produces Code | Pipeline Order | Tools |
|------|------|:---:|:---:|---|
| `planner` | Technical Planner | — | 0 | read_file, list_directory, search_codebase, read_dependencies |
| `coder` | Software Engineer | ✓ | 1 | read_file, write_file, list_directory, search_codebase, run_command, read_dependencies, spawn_subtask |
| `reviewer` | Code Reviewer | — | 2 | read_file, list_directory, search_codebase |
| `security` | Security Expert | — | 3 | read_file, list_directory, search_codebase |
| `qa` | QA Engineer | ✓ | 4 | read_file, write_file, list_directory, search_codebase, run_command |
| `devops` | DevOps Engineer | ✓ | 5 | read_file, write_file, list_directory, run_command |
| `sre` | Site Reliability Engineer | ✓ | 6 | read_file, write_file, list_directory, run_command |
| `lead` | Tech Lead | — | 7 | read_file, list_directory, search_codebase |

### Tool Definitions

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with optional line range |
| `write_file` | Create or modify files (creates parent directories) |
| `list_directory` | Recursive directory listing |
| `search_codebase` | Regex search across project files |
| `run_command` | Execute shell commands (tests, builds, linting) with timeout |
| `read_dependencies` | Parse package.json, pyproject.toml, requirements.txt, etc. |
| `spawn_subtask` | Spawn independent sub-agent with full tool access |

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

`rigovo init` writes a complete `rigovo.yml` with all schema fields and defaults. The examples below show common overrides.

**Override agent model:**
```yaml
# rigovo.yml
teams:
  engineering:
    agents:
      coder:
        model: "gpt-5"             # Use GPT-5 for coding
        temperature: 0.1
      security:
        model: "claude-opus-4-6"    # Use Opus for security
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

**Select database backend (company mode):**
```yaml
database:
  backend: postgres               # sqlite|postgres
  local_path: .rigovo/local.db    # used when backend=sqlite
```

Set `RIGOVO_DB_URL` in `.env` when using `postgres`.

**Deep analysis policy (automatic by default):**
```yaml
orchestration:
  deep_mode: final                # never|final|ci|always|critical_only
  deep_pro: false                 # true = use pro deep tier
```

**Inter-agent consultation policy:**
```yaml
orchestration:
  consultation:
    enabled: true
    max_question_chars: 1200
    max_response_chars: 1200
    allowed_targets:
      reviewer: [planner, coder, security, qa, devops, sre, lead]
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

**Custom OpenAI-compatible provider:**
```yaml
providers:
  my_local:
    base_url: "http://localhost:11434/v1"
    api_key_env: "OLLAMA_API_KEY"
    input_price: 0.0
    output_price: 0.0
```

### Environment Variables

```bash
# .env (auto-generated by rigovo init — gitignored)
ANTHROPIC_API_KEY=sk-ant-...      # Required for Claude models
# OPENAI_API_KEY=sk-...           # Alternative: GPT models
# GOOGLE_API_KEY=...              # Alternative: Gemini models
# DEEPSEEK_API_KEY=...            # Alternative: DeepSeek models
# GROQ_API_KEY=...                # Alternative: Groq models
# MISTRAL_API_KEY=...             # Alternative: Mistral models
# RIGOVO_API_KEY=...              # Optional: cloud sync
```

---

## Rigour CLI Auto-Install

The Rigour quality gate CLI auto-installs on first use — no manual setup required.

```mermaid
flowchart LR
    START[Quality gate needed] --> CHECK1{rigour in PATH?}
    CHECK1 -->|yes| USE[Use system binary]
    CHECK1 -->|no| CHECK2{~/.rigovo/bin/rigour<br/>cached?}
    CHECK2 -->|yes| USE2[Use cached binary]
    CHECK2 -->|no| INSTALL[Background install<br/>npm install -g @rigour-labs/cli]
    INSTALL --> USE3[Use installed binary]
    INSTALL -->|failed| NPX[Fallback: npx -y @rigour-labs/cli]
    NPX -->|failed| BUILTIN[Fallback: built-in AST checks]
```

The install runs in background alongside the planner agent — by the time quality gates need the CLI, it's already ready. Eliminates the 30-60s first-run latency entirely.

---

## CI/CD

GitHub Actions with PyPI Trusted Publishing (OIDC). CI runs tests + lint + Rigour gates. Versioning via [python-semantic-release](https://python-semantic-release.readthedocs.io/) with [Conventional Commits](https://www.conventionalcommits.org/).

---

## Development

```bash
git clone https://github.com/rigovo/rigovo-virtual-team.git && cd rigovo-virtual-team
pip install -e ".[dev]"
pytest                                    # 353 tests
npx @rigour-labs/cli check               # Rigour gates
```

Requires Python 3.10+, Node.js 18+ (for Rigour CLI), and an API key for at least one LLM provider.

## License

MIT — [Rigovo](https://rigovo.com)

Built by [Ashutosh Singh](https://github.com/erashu212) — author of [Rigour](https://github.com/rigour-labs/rigour).
