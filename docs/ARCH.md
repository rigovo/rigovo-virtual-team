# Rigovo Teams — Architecture

## Layered Architecture

Rigovo follows Clean Architecture / Hexagonal Architecture with strict
dependency rules: outer layers depend inward, never the reverse.

```
┌─────────────────────────────────────────────┐
│  CLI (main.py, cli/)                        │  ← Typer commands
├─────────────────────────────────────────────┤
│  Application (application/)                 │  ← Use cases, graph
├─────────────────────────────────────────────┤
│  Domain (domain/)                           │  ← Entities, interfaces
├─────────────────────────────────────────────┤
│  Infrastructure (infrastructure/)           │  ← Implementations
└─────────────────────────────────────────────┘
```

## Domain Layer (`domain/`)

Pure business logic. No framework imports.

- **entities/** — Task, Agent, Team, Memory, Quality, CostEntry, AuditEntry
- **interfaces/** — Abstract contracts: LLMProvider, QualityGate, EventEmitter,
  repositories (TaskRepo, CostRepo, AuditRepo, MemoryRepo)
- **services/** — TeamAssembler, CostCalculator, MemoryRanker

## Application Layer (`application/`)

Orchestrates domain objects to fulfil use cases.

### LangGraph Pipeline (`application/graph/`)

Each task flows through a directed graph:

```
classify → route_team → assemble → execute_agent → quality_check
                                         ↑              │
                                         └──── retry ────┘
                                                         │
                                         approve → finalize → store_memory
```

- **state.py** — TypedDict defining the graph state
- **builder.py** — Constructs the LangGraph StateGraph
- **edges.py** — Conditional routing functions
- **nodes/** — One module per graph node (classify, assemble, execute, etc.)

### Master Intelligence (`application/master/`)

Pre-pipeline analysis that enriches the task before agents act:

- **classifier.py** — Task type + complexity classification
- **enricher.py** — Adds codebase context, relevant files, patterns
- **evaluator.py** — Post-pipeline quality evaluation
- **router.py** — Selects appropriate team for the task

### Commands (`application/commands/`)

- **run_task.py** — RunTaskCommand: builds graph, executes, returns result

## Infrastructure Layer (`infrastructure/`)

Concrete implementations of domain interfaces.

- **llm/** — LLM providers (Anthropic, OpenAI), model catalog + registry
- **persistence/** — SQLite repos (tasks, costs, audit, memory)
- **filesystem/** — ProjectReader, CodeWriter, CommandRunner, ToolExecutor
- **quality/** — Rigour gate integration
- **cloud/** — Optional metadata sync client
- **embeddings/** — Local embedding provider for memory search
- **terminal/** — Rich terminal UI, approval prompts
- **events.py** — In-process event emitter

## Domains (`domains/`)

Pluggable domain configurations. Each domain registers agents, roles,
tools, and quality gates.

- **engineering/** — 8 agents (Lead → SRE), code-specific gates, file tools
- **llm_training/** — Future: dataset curation, fine-tuning pipelines

## Configuration

- **config.py** — Loads `.env` + `rigovo.yml` into a typed Config dataclass
- **config_schema.py** — Pydantic models for `rigovo.yml`
- **config_detection.py** — Auto-detection (language, framework, tests, monorepo)
- **config_rules.py** — Smart defaults per language/framework
- **container.py** — Dependency injection container

## CLI (`main.py` + `cli/`)

Typer-based CLI with commands split by concern:

- **main.py** — P0: `run`, `init`, `doctor`, `version`
- **cli/commands_info.py** — `teams`, `agents`, `config`, `status`
- **cli/commands_data.py** — `history`, `costs`, `export`, `login`
- **cli/commands_lifecycle.py** — `dashboard`, `replay`, `upgrade`

## Key Design Decisions

1. **Provider-neutral** — Any LLM from any provider works. Model catalog
   provides recommendations, never restrictions.
2. **Deterministic quality gates** — Every code-producing agent passes
   through Rigour AST checks before output is accepted.
3. **Event-driven UI** — Graph nodes emit events; terminal UI subscribes
   and renders. Decoupled from business logic.
4. **Local-first storage** — SQLite for all persistence. Optional cloud
   sync sends metadata only, never source code.
5. **Plugin architecture** — Domains register via DomainPlugin interface.
   New verticals (data science, ML ops) plug in without core changes.
