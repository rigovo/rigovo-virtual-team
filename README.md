# Rigovo Teams

Composable AI engineering team platform. Describe a task in plain English — the Master Agent classifies it, assembles the right team of specialized agents, and delivers production-ready code verified through 24+ deterministic quality gates.

## What Makes This Different

- **Inter-agent verification** — Agents verify each other's work through Rigour quality gates. The Coder cannot pass its own review.
- **Flat semantic memory** — Learnings from any project are available to every future task. Relevance decides, not scope rules.
- **Hallucination detection** — Catches hallucinated imports, phantom APIs, deprecated APIs across 8 languages.
- **Agent isolation** — Reviewer doesn't inherit Coder's context or biases. Separate agents, separate contexts.
- **Full audit trail** — Every agent action logged with timestamp, workspace, task context.

## Architecture

```
@rigovo/cli (local)       → reads/writes code on user's machine
                          → calls LLM directly (user's API key)
                          → reports task results to Rigovo Cloud

Rigovo Cloud              → Supabase (Postgres + pgvector + Auth + RLS)
                          → Master Agent orchestration
                          → Shared memory + semantic search
                          → Team management + Audit trail + Dashboard

@rigour-labs/core (local) → quality gates execute on user's machine
                          → results sent to cloud as metadata
```

## Quick Start

```bash
npx @rigovo/cli init
npx @rigovo/cli login
npx @rigovo/cli run "add user authentication with JWT"
```

## Packages

| Package | Description |
|---------|-------------|
| `@rigovo/core` | Master Agent, BaseAgent, MessageBus, MemoryClient, AuditLogger |
| `@rigovo/eng` | CoderAgent, ReviewerAgent, QA, Planner, tools |
| `@rigovo/cli` | CLI interface for local execution |
| `@rigovo/app` | Next.js dashboard |

## Quality Gates

Built on [Rigour](https://rigour.run) — 24+ deterministic quality gates including AST complexity, security patterns, hallucinated imports, phantom APIs, deprecated APIs, test quality, and more. Every gate is structural analysis, not LLM opinions.

## License

MIT
