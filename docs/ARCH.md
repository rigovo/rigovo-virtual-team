# Rigovo Teams — Architecture

## System Topology

```
User's Machine                          Rigovo Cloud
┌──────────────────────┐    metadata    ┌────────────────────────┐
│ @rigovo/cli           │──────────────→│ Next.js App (Vercel)   │
│   reads/writes code   │               │   Dashboard UI         │
│   calls LLM directly  │               │   API Routes (tRPC)    │
│   user's API key      │               │   WebSocket realtime   │
│                       │               │                        │
│ @rigour-labs/core     │               │ Supabase               │
│   quality gates local │               │   Postgres + pgvector  │
│   AST analysis        │               │   memories (semantic)  │
│   hallucination detect│               │   tasks, audit_log     │
│   results → cloud     │               │   RLS isolation        │
└──────────────────────┘               │                        │
                                        │ WorkOS                 │
                                        │   Auth, SSO, SCIM      │
                                        └────────────────────────┘
```

## Data Boundary

**Never leaves user's machine:** source code, API keys, git history, LLM API calls, Rigour gate execution.

**Goes to Rigovo Cloud (metadata only):** task descriptions, outcomes, memory content (learnings not code), gate result summaries, team configs, audit trail.

## Package Structure (pnpm monorepo)

- `packages/core` — @rigovo/core: Master Agent, BaseAgent, MessageBus, MemoryClient, AuditLogger
- `packages/eng` — @rigovo/eng: CoderAgent, ReviewerAgent, QA, Planner, tools
- `packages/cli` — @rigovo/cli: CLI commands (run, init, login, team, memory, status)
- `packages/app` — @rigovo/app: Next.js dashboard

## Tech Stack

- TypeScript (strict mode), pnpm workspace, Vitest
- Supabase (Postgres + pgvector + RLS + Realtime)
- WorkOS (auth, SSO, SCIM)
- Next.js 15 on Vercel
- Rigour for quality gates (local execution)

## Agent Communication

Agents communicate via typed MessageBus. Messages include: task_assignment, code_output, review_result, fix_packet, test_result, approval_request, completion.

## Quality Gate Flow

Coder generates code → self-checks via Rigour → passes to Reviewer → Reviewer runs 24+ gates → if fail: generates Fix Packet → Coder retries → max 3 retries from config.

## Memory Design

Flat table, no scoping. Every memory tagged with source_project_id but never locked to that project. Semantic search via pgvector across all workspace memories. Relevance ranking handles scoping naturally.
