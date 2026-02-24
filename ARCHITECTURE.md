# Rigovo Teams — Technical Architecture

> **Version:** 3.0 | **Date:** February 24, 2026
> **Status:** Architecture Review | **Author:** Generated from CTO vision

---

## 1. Product Model

Rigovo Teams is a **Virtual Engineering Team as a Service**.

Target customer: business owners, solo CTOs, startups who cannot afford or don't want to hire a full human engineering team. They get a virtual engineering org that works 24/7, learns their codebase, remembers past mistakes, and verifies its own work through deterministic quality gates.

### 1.1 Hierarchy

```
Workspace (Company A)
├── Master Agent (shared brain — VP of Engineering)
│   ├── Observes all teams
│   ├── Learns from every task
│   └── Enriches agents over time
│
├── Payment Team
│   ├── Backend Coder (specialist)
│   ├── Tech Lead (reviewer + architecture)
│   ├── Security Expert (Rigour gates + security patterns)
│   ├── QA Engineer (test generation + validation)
│   └── DevOps Engineer (deployment + infra)
│
├── Frontend Team
│   ├── React Coder (specialist)
│   ├── UI/UX Reviewer
│   └── Accessibility QA
│
├── Data Team
│   ├── Data Engineer
│   ├── ML Engineer
│   └── QA
│
└── Projects (running in parallel)
    ├── Project A: "Add Stripe integration" → Payment Team
    ├── Project B: "Redesign dashboard" → Frontend Team
    ├── Project C: "Build analytics pipeline" → Data Team
    ├── Project D: "Fix auth vulnerability" → Payment Team (parallel)
    └── Project E: "New landing page" → Frontend Team (parallel)
```

### 1.2 Key Concepts

- **Workspace** = Company. Multi-tenant. Isolated. Has billing, API keys, members.
- **Team** = Department. Created by CTO. Has specific agents configured for a domain. Reusable across projects. Persistent.
- **Agent** = Virtual employee. Not a disposable function. Has memory, performance history, domain expertise. Gets smarter over time. Knows YOUR codebase.
- **Master Agent** = VP of Engineering. ONE per workspace. Shared across ALL teams. Watches everything. Learns patterns. Enriches agents. The meta-learning layer.
- **Project** = A codebase or repo. Has tech stack config. Tasks belong to projects.
- **Task** = A unit of work. Assigned to a team. Runs through the team's pipeline. Async — user can leave and come back.

---

## 2. System Architecture

### 2.1 Core Constraint: Code Never Leaves the User's Machine

This is non-negotiable. Source code, API keys, environment variables, git history — all stay local. The cloud only receives metadata: task descriptions, gate results, memory text, cost data, audit entries.

This means **agent execution MUST be local**. A web app cannot access the user's codebase. The product is:

- **CLI** (`@rigovo/cli`) — runs on user's machine. This is v1.
- **Desktop App** — future. Wraps the CLI with a GUI (Tauri/Electron).
- **Cloud Dashboard** (`rigovo.com`) — web app for monitoring, configuration, analytics. Never touches code.

### 2.2 Architecture: Local Execution + Cloud Metadata

```
LOCAL (User's Machine)                              CLOUD (rigovo.com)
┌─────────────────────────────────────────┐         ┌─────────────────────────────────┐
│         @rigovo/cli (Python)             │         │   Next.js Web Dashboard          │
│                                          │         │                                  │
│  ├── LangGraph Orchestrator              │  sync   │  ├── CTO Dashboard               │
│  │   ├── Classify → Route → Execute      │◄───────►│  │   ├── Teams & Agents          │
│  │   ├── interrupt() for approvals       │ metadata│  │   ├── Cost Analytics           │
│  │   └── SQLite checkpointer (local)     │  only   │  │   ├── Performance Metrics     │
│  │                                       │         │  │   ├── Audit Trail              │
│  ├── Agent Execution                     │         │  │   └── Memory Explorer          │
│  │   ├── LLM calls (user's API key      │         │  │                                │
│  │   │   → provider directly)            │         │  ├── Team Configuration           │
│  │   ├── Isolated context per agent      │         │  │   (synced down to CLI)         │
│  │   └── Role-specific tools             │         │  │                                │
│  │                                       │         │  └── API Routes                   │
│  ├── Rigour Quality Gates                │         │      ├── /api/workspaces          │
│  │   ├── 24+ deterministic gates (AST)   │         │      ├── /api/teams               │
│  │   ├── Hallucination detection         │         │      ├── /api/agents              │
│  │   ├── Fix Packet V2 generation        │         │      ├── /api/analytics           │
│  │   └── Runs 100% locally               │         │      ├── /api/memory              │
│  │                                       │         │      └── /api/audit               │
│  ├── File I/O                            │         │                                  │
│  │   ├── Reads project code              │         └──────────────┬──────────────────┘
│  │   ├── Writes generated code           │                        │
│  │   └── Runs tests locally              │                        │
│  │                                       │                        ▼
│  ├── Local DB (SQLite)                   │         ┌─────────────────────────────────┐
│  │   ├── LangGraph checkpoints           │         │   Cloud PostgreSQL (Supabase)    │
│  │   ├── Pending tasks                   │         │                                  │
│  │   └── Offline cache                   │         │  ├── workspaces                  │
│  │                                       │         │  ├── teams + agents (configs)     │
│  └── Metadata Sync                       │         │  ├── memories (pgvector)          │
│      ├── Reports: task outcome, cost,    │         │  ├── tasks (metadata only)        │
│      │   gate results, duration          │         │  ├── audit_log                    │
│      ├── Never sends: code, API keys,    │         │  ├── cost_ledger                  │
│      │   env vars, git history           │         │  └── agent_stats                  │
│      └── Works offline → syncs when      │         │                                  │
│          connected                       │         └─────────────────────────────────┘
│                                          │
└─────────────────────────────────────────┘
```

### 2.3 Data Boundary (What Goes Where)

| Data | Local Only | Synced to Cloud |
|------|-----------|-----------------|
| Source code files | ✅ | ❌ NEVER |
| API keys / secrets | ✅ | ❌ NEVER |
| Environment variables | ✅ | ❌ NEVER |
| Git history | ✅ | ❌ NEVER |
| LLM API calls | ✅ (direct to provider) | ❌ NEVER |
| Rigour gate execution | ✅ | ❌ NEVER |
| Task descriptions | ✅ | ✅ metadata |
| Task outcomes (pass/fail) | ✅ | ✅ metadata |
| Gate result summaries | ✅ | ✅ (no code snippets) |
| Token usage / cost | ✅ | ✅ |
| Memory content | ✅ | ✅ (text, not code) |
| Team/agent configs | ✅ (cached) | ✅ (source of truth) |
| Audit trail entries | ✅ | ✅ |

### 2.4 CLI User Flow

```bash
# First time setup
$ rigovo init
→ Creates rigovo.yml in project root
→ Prompts for Rigovo API key (for cloud sync)
→ Prompts for LLM API key (stored locally in .env)

# Login (connects to cloud workspace)
$ rigovo login
→ Opens browser for WorkOS auth
→ Syncs team configs from cloud to local

# Run a task
$ rigovo run "add Stripe payment integration"
→ Master Agent classifies task locally
→ Routes to Payment Team (config from cloud)
→ Shows plan in terminal: "Feature task, high complexity.
   Team: Planner → Coder → Reviewer → QA. Approve? [Y/n]"
→ User approves
→ Agents execute locally (LLM calls direct to Claude)
→ Rigour gates run locally
→ Real-time status in terminal
→ Code written to local project
→ Metadata synced to cloud (task outcome, cost, audit)

# Check team status
$ rigovo teams
→ Lists teams from cloud config

# Check costs
$ rigovo costs
→ Shows cost breakdown (from local + cloud data)

# Offline mode
$ rigovo run "fix login bug" --offline
→ Uses cached team config
→ Runs fully local
→ Syncs metadata when back online
```

### 2.5 Why CLI First

| Factor | CLI | Web App | Desktop App |
|--------|-----|---------|-------------|
| Access to local code | ✅ Native | ❌ Impossible | ✅ Native |
| Ship speed | Days | Already exists (dashboard) | Weeks |
| Target user (v1) | Developers, CTOs | Monitoring only | Non-techies (v2) |
| LLM calls local | ✅ | ❌ | ✅ |
| Rigour gates local | ✅ | ❌ | ✅ |
| Offline capable | ✅ | ❌ | ✅ |

The web dashboard already exists for monitoring. The CLI is the missing piece that actually DOES the work.

---

## 3. Database Schema

### 3.1 Core Tables

```sql
-- Workspaces (tenant root)
CREATE TABLE workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  owner_id TEXT NOT NULL,
  plan TEXT DEFAULT 'free',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Teams (per workspace, persistent, reusable)
CREATE TABLE teams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID REFERENCES workspaces(id) NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  domain TEXT,                           -- 'payments', 'frontend', 'data', 'infra'
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, name)
);

-- Agents (virtual employees, per team, persistent)
CREATE TABLE agents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id UUID REFERENCES teams(id) NOT NULL,
  workspace_id UUID REFERENCES workspaces(id) NOT NULL,
  role TEXT NOT NULL,                    -- 'coder', 'reviewer', 'lead', 'qa', 'sre', 'devops', 'security'
  name TEXT NOT NULL,                    -- "Backend Coder", "Security Expert"
  description TEXT,

  -- Agent configuration
  system_prompt TEXT,                    -- Base personality + domain expertise
  llm_model TEXT DEFAULT 'claude-sonnet-4-5-20250929',
  tools JSONB DEFAULT '[]',             -- Available tools for this agent
  custom_rules JSONB DEFAULT '[]',      -- CTO-defined rules: "always check PCI compliance"

  -- Performance tracking
  tasks_completed INTEGER DEFAULT 0,
  first_pass_rate REAL DEFAULT 0,       -- % of tasks that pass gates on first attempt
  avg_duration_ms INTEGER DEFAULT 0,
  total_tokens_used BIGINT DEFAULT 0,
  total_cost_usd REAL DEFAULT 0,

  -- Agent memory enrichment (set by Master Agent)
  enrichment_context JSONB DEFAULT '{}', -- Learnings injected by Master Agent
  last_enriched_at TIMESTAMPTZ,

  pipeline_order INTEGER DEFAULT 0,      -- Execution order within team
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Projects (codebase metadata, no code stored)
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID REFERENCES workspaces(id) NOT NULL,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  tech_stack JSONB,
  config JSONB,                          -- rigovo.yml parsed
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, slug)
);

-- Tasks (units of work)
CREATE TABLE tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID REFERENCES workspaces(id) NOT NULL,
  project_id UUID REFERENCES projects(id),
  team_id UUID REFERENCES teams(id),     -- Which team is working on this
  description TEXT NOT NULL,
  type TEXT,                             -- classified: feature, bug, refactor, etc.
  complexity TEXT,                       -- low, medium, high
  status TEXT DEFAULT 'pending',         -- pending, classifying, awaiting_approval, running, completed, failed, rejected

  -- Approval state
  current_checkpoint TEXT,               -- 'plan_ready', 'code_ready', 'deploy_ready'
  approval_data JSONB,                   -- What was presented to user for approval

  -- Results
  pipeline_steps JSONB DEFAULT '[]',     -- [{role, status, durationMs, tokens, cost}]
  total_tokens INTEGER DEFAULT 0,
  total_cost_usd REAL DEFAULT 0,
  duration_ms INTEGER,
  retries INTEGER DEFAULT 0,

  -- LangGraph thread
  langgraph_thread_id TEXT,              -- For resuming from checkpoints

  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Cost Ledger (granular token tracking per agent per task)
CREATE TABLE cost_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID REFERENCES workspaces(id) NOT NULL,
  team_id UUID REFERENCES teams(id),
  agent_id UUID REFERENCES agents(id),
  task_id UUID REFERENCES tasks(id),
  project_id UUID REFERENCES projects(id),

  llm_model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  total_tokens INTEGER NOT NULL,
  cost_usd REAL NOT NULL,                -- Calculated from model pricing

  created_at TIMESTAMPTZ DEFAULT now()
);

-- Memories (flat, workspace-wide, semantic search)
CREATE TABLE memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID REFERENCES workspaces(id) NOT NULL,
  source_project_id UUID REFERENCES projects(id),
  source_task_id UUID REFERENCES tasks(id),
  source_agent_id UUID REFERENCES agents(id),

  content TEXT NOT NULL,
  type TEXT NOT NULL,                    -- 'task_outcome', 'pattern', 'error_fix', 'tech_stack', 'convention'
  embedding VECTOR(1536),               -- pgvector for semantic search

  usage_count INTEGER DEFAULT 0,
  cross_project_usage INTEGER DEFAULT 0, -- Times used outside source project
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Audit Log (every agent action, enterprise-grade)
CREATE TABLE audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID REFERENCES workspaces(id) NOT NULL,
  team_id UUID REFERENCES teams(id),
  agent_id UUID REFERENCES agents(id),
  task_id UUID REFERENCES tasks(id),

  action_type TEXT NOT NULL,             -- 'classify', 'assign', 'execute', 'review', 'approve', 'reject', 'retry', 'complete', 'fail', 'enrich'
  agent_role TEXT,
  summary TEXT,
  metadata JSONB DEFAULT '{}',

  created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX idx_memories_embedding ON memories USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_memories_workspace ON memories(workspace_id);
CREATE INDEX idx_tasks_workspace ON tasks(workspace_id);
CREATE INDEX idx_tasks_team ON tasks(team_id);
CREATE INDEX idx_cost_workspace ON cost_ledger(workspace_id);
CREATE INDEX idx_cost_team ON cost_ledger(team_id);
CREATE INDEX idx_cost_agent ON cost_ledger(agent_id);
CREATE INDEX idx_audit_workspace ON audit_log(workspace_id);
CREATE INDEX idx_audit_task ON audit_log(task_id);
```

---

## 4. Master Agent — The Shared Brain

The Master Agent is NOT a per-task orchestrator. It is a persistent, workspace-level intelligence that:

### 4.1 Responsibilities

1. **Task Classification** — Understands what kind of work this is (feature, bug, refactor, incident, infra, test).
2. **Team Routing** — Decides which team should handle this task. "This is a payment task → Payment Team."
3. **Agent Enrichment** — After every N tasks, reviews agent performance and injects learnings into their context:
   - "Your Coder keeps missing error handling. Adding to briefing."
   - "This workspace's security pattern: always check CSRF on POST endpoints."
   - "Payment Team: Stripe webhooks need idempotency keys (learned from 3 past tasks)."
4. **Memory Evaluation** — After task completion, extracts reusable lessons and stores them.
5. **Pattern Detection** — "Auth tasks fail CSRF 40% of the time across all teams → pre-load for everyone."
6. **Performance Monitoring** — Tracks which agents are efficient, which are bottlenecks.

### 4.2 Enrichment Loop

```python
# Runs periodically or after every N tasks
async def enrich_agents(workspace_id: str):
    # 1. Get all agents in workspace
    agents = await db.get_agents(workspace_id)

    # 2. For each agent, analyze recent performance
    for agent in agents:
        recent_tasks = await db.get_agent_tasks(agent.id, limit=50)

        # 3. Extract patterns
        patterns = await master_llm.analyze_patterns(
            agent_role=agent.role,
            task_history=recent_tasks,
            gate_failures=await db.get_gate_failures(agent.id),
        )

        # 4. Update agent's enrichment context
        await db.update_agent_enrichment(agent.id, {
            "common_mistakes": patterns.mistakes,
            "domain_knowledge": patterns.knowledge,
            "pre_check_rules": patterns.rules,
            "last_enriched": datetime.now().isoformat(),
        })

    # 5. Audit the enrichment
    await db.audit_log(workspace_id, "enrich", f"Enriched {len(agents)} agents")
```

### 4.3 How Enrichment Flows Into Agent Execution

When an agent starts a task, its system prompt is dynamically composed:

```
BASE SYSTEM PROMPT (role definition, tools, rules)
+
TEAM CONTEXT (team domain, team conventions)
+
ENRICHMENT CONTEXT (Master Agent's learnings for THIS agent)
+
TASK CONTEXT (relevant memories from workspace memory)
+
PROJECT CONTEXT (tech stack, conventions from this project)
```

This is how agents get smarter without retraining the LLM.

---

## 5. Orchestration Graph (LangGraph)

### 5.1 Graph Definition

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

# State that flows through the graph
class TaskState(TypedDict):
    task_id: str
    workspace_id: str
    team_id: str
    description: str
    classification: dict           # task type, complexity
    team_config: dict              # agents, pipeline order
    current_agent: str             # who's working now
    agent_outputs: dict            # {role: output}
    gate_results: dict             # Rigour quality gate results
    fix_packets: list              # Accumulated fix packets
    retry_count: int
    max_retries: int
    approval_status: str           # 'pending', 'approved', 'rejected'
    user_feedback: str
    cost_accumulator: dict         # {agent_id: {tokens, cost}}
    memories_to_store: list
    status: str                    # Current phase
    events: list                   # SSE events to broadcast

# Build the graph
graph = StateGraph(TaskState)

graph.add_node("classify", classify_node)
graph.add_node("route_team", route_to_team_node)
graph.add_node("assemble", assemble_pipeline_node)
graph.add_node("await_plan_approval", plan_approval_node)      # interrupt()
graph.add_node("execute_agent", execute_agent_node)             # Runs current agent
graph.add_node("rigour_check", rigour_gate_node)                # Deterministic gates
graph.add_node("route_next", route_next_agent_or_fix_node)      # Decides: next agent, fix loop, or done
graph.add_node("await_commit_approval", commit_approval_node)   # interrupt()
graph.add_node("store_memory", store_memory_node)
graph.add_node("finalize", finalize_node)

# Edges
graph.add_edge(START, "classify")
graph.add_edge("classify", "route_team")
graph.add_edge("route_team", "assemble")
graph.add_edge("assemble", "await_plan_approval")
graph.add_conditional_edges("await_plan_approval", check_approval, {
    "approved": "execute_agent",
    "rejected": "finalize",
})
graph.add_edge("execute_agent", "rigour_check")
graph.add_conditional_edges("rigour_check", check_gates_and_route, {
    "pass_next_agent": "route_next",
    "fail_fix_loop": "execute_agent",       # Back to coder with fix packet
    "fail_max_retries": "finalize",
})
graph.add_conditional_edges("route_next", check_pipeline_complete, {
    "more_agents": "execute_agent",
    "pipeline_done": "await_commit_approval",
})
graph.add_conditional_edges("await_commit_approval", check_approval, {
    "approved": "store_memory",
    "rejected": "finalize",
})
graph.add_edge("store_memory", "finalize")
graph.add_edge("finalize", END)

# Compile with Postgres persistence
checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)
app = graph.compile(checkpointer=checkpointer)
```

### 5.2 Human-in-the-Loop (interrupt)

```python
from langgraph.types import interrupt, Command

def plan_approval_node(state: TaskState) -> TaskState:
    """Pauses graph until user approves the plan + team."""

    # This call PAUSES the graph. State saved to Postgres.
    # User can close browser. Graph resumes when they call approve endpoint.
    response = interrupt({
        "checkpoint": "plan_ready",
        "summary": f"Task: {state['classification']['type']} ({state['classification']['complexity']})",
        "team": state["team_config"],
        "estimated_cost": estimate_cost(state),
    })

    return {
        **state,
        "approval_status": "approved" if response["approved"] else "rejected",
        "user_feedback": response.get("feedback", ""),
    }
```

### 5.3 Agent Node Execution (Context Isolation)

```python
async def execute_agent_node(state: TaskState) -> TaskState:
    """Execute the current agent with isolated context."""

    current_role = state["current_agent"]
    agent_config = state["team_config"]["agents"][current_role]

    # 1. Build isolated context — agent ONLY sees:
    #    - Its own system prompt
    #    - Its enrichment context (from Master Agent)
    #    - Relevant workspace memories
    #    - Task description and previous agent outputs (NOT their reasoning)
    #    - NOT other agents' system prompts or chain-of-thought

    system_prompt = build_agent_prompt(
        base=agent_config["system_prompt"],
        enrichment=agent_config["enrichment_context"],
        team_context=state["team_config"]["domain"],
        project_context=state.get("project_tech_stack"),
    )

    # 2. Build messages — only include OUTPUTS from previous agents, not their thinking
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=build_task_message(state)),
    ]

    # Add previous agent outputs (sanitized — no chain-of-thought)
    for role, output in state["agent_outputs"].items():
        messages.append(HumanMessage(content=f"[{role} output]: {output['summary']}"))

    # Add fix packet if in retry
    if state["fix_packets"]:
        messages.append(HumanMessage(content=f"[Fix required]: {state['fix_packets'][-1]}"))

    # 3. Call LLM with agent's tools
    llm = get_llm(agent_config["llm_model"])
    tools = get_agent_tools(current_role, agent_config["tools"])
    response = await llm.ainvoke(messages, tools=tools)

    # 4. Track cost
    cost = calculate_cost(response.usage, agent_config["llm_model"])

    # 5. Update state
    return {
        **state,
        "agent_outputs": {
            **state["agent_outputs"],
            current_role: {
                "summary": response.content,
                "files_changed": extract_files(response),
                "tokens": response.usage.total_tokens,
                "cost": cost,
            },
        },
        "cost_accumulator": {
            **state["cost_accumulator"],
            agent_config["id"]: {
                "tokens": response.usage.total_tokens,
                "cost": cost,
            },
        },
        "events": state["events"] + [{
            "type": "agent_complete",
            "role": current_role,
            "summary": response.content[:200],
            "tokens": response.usage.total_tokens,
            "cost": cost,
        }],
    }
```

### 5.4 Rigour Gate Node (The Moat)

```python
async def rigour_gate_node(state: TaskState) -> TaskState:
    """Run deterministic quality gates. No LLM opinions."""

    current_role = state["current_agent"]

    # Only run gates on code-producing agents
    if current_role not in ("coder", "devops"):
        return {**state, "gate_results": {"passed": True, "skipped": True}}

    # Run Rigour CLI — deterministic AST analysis
    result = subprocess.run(
        ["npx", "@rigour-labs/cli", "check", "--json"],
        capture_output=True,
        cwd=project_root,
    )

    gate_report = json.loads(result.stdout)

    if not gate_report["passed"]:
        # Build Fix Packet V2 — structured, machine-readable
        fix_packet = build_fix_packet(gate_report["violations"])

        return {
            **state,
            "gate_results": gate_report,
            "fix_packets": state["fix_packets"] + [fix_packet],
            "retry_count": state["retry_count"] + 1,
            "events": state["events"] + [{
                "type": "gate_results",
                "score": gate_report["score"],
                "passed": False,
                "violations": len(gate_report["violations"]),
            }],
        }

    return {
        **state,
        "gate_results": gate_report,
        "events": state["events"] + [{
            "type": "gate_results",
            "score": gate_report["score"],
            "passed": True,
        }],
    }
```

---

## 6. Cost Tracking

Every LLM call records token usage and maps it to a dollar cost.

### 6.1 Model Pricing Table

```python
MODEL_PRICING = {
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},   # per 1M tokens
    "claude-opus-4-5-20251101": {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}

def calculate_cost(usage, model: str) -> float:
    pricing = MODEL_PRICING.get(model, {"input": 5.00, "output": 15.00})
    input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)
```

### 6.2 CTO Dashboard Queries

```sql
-- Cost per team this month
SELECT t.name AS team_name,
       SUM(cl.cost_usd) AS total_cost,
       SUM(cl.total_tokens) AS total_tokens,
       COUNT(DISTINCT cl.task_id) AS tasks_completed
FROM cost_ledger cl
JOIN teams t ON cl.team_id = t.id
WHERE cl.workspace_id = $1
  AND cl.created_at >= date_trunc('month', now())
GROUP BY t.name;

-- Cost per agent (who's expensive?)
SELECT a.name AS agent_name, a.role,
       SUM(cl.cost_usd) AS total_cost,
       AVG(cl.total_tokens) AS avg_tokens_per_task,
       a.first_pass_rate
FROM cost_ledger cl
JOIN agents a ON cl.agent_id = a.id
WHERE cl.workspace_id = $1
GROUP BY a.id, a.name, a.role, a.first_pass_rate
ORDER BY total_cost DESC;

-- Monthly burn rate vs equivalent human cost
SELECT date_trunc('month', cl.created_at) AS month,
       SUM(cl.cost_usd) AS ai_cost,
       COUNT(DISTINCT cl.task_id) AS tasks,
       -- Rough estimate: 1 task = ~2 hours human work
       COUNT(DISTINCT cl.task_id) * 2 * 75 AS equivalent_human_cost  -- $75/hr
FROM cost_ledger cl
WHERE cl.workspace_id = $1
GROUP BY month
ORDER BY month;
```

---

## 7. Inter-Agent Communication

Agents communicate through the LangGraph state. The graph edges control routing.

### 7.1 Agent-to-Agent Requests

When the Reviewer needs input from SRE (e.g., "is this deployment config safe?"):

```python
def check_gates_and_route(state: TaskState) -> str:
    """Conditional edge: decides what happens after gate check."""

    gate_results = state["gate_results"]

    # If security gates failed and team has SRE → route to SRE first
    if not gate_results["passed"]:
        security_violations = [v for v in gate_results["violations"] if v["category"] == "security"]
        if security_violations and "sre" in state["team_config"]["agents"]:
            return "consult_sre"  # Edge to SRE agent node

    # Normal routing
    if not gate_results["passed"] and state["retry_count"] < state["max_retries"]:
        return "fail_fix_loop"

    if gate_results["passed"]:
        return "pass_next_agent"

    return "fail_max_retries"
```

### 7.2 Cross-Team Requests (Future)

```python
# Payment Team finishes backend → requests Frontend Team to update checkout UI
def cross_team_request_node(state: TaskState) -> TaskState:
    """Create a new task for another team based on this task's output."""

    new_task = {
        "description": f"Update frontend for: {state['description']}",
        "parent_task_id": state["task_id"],
        "target_team": "frontend",
        "context": state["agent_outputs"]["coder"]["summary"],
    }

    # Creates a new task in the DB — another team picks it up
    create_task(state["workspace_id"], new_task)

    return state
```

---

## 8. Async Execution Model

### 8.1 Flow

1. User submits task via UI → `POST /api/tasks`
2. Next.js saves task to DB (status: `pending`), returns task ID immediately
3. Next.js sends task to Python orchestration service (HTTP or queue)
4. Python starts LangGraph execution with a unique thread_id
5. Graph runs: classify → route → assemble → **interrupt (await approval)**
6. State saved to Postgres. Python process can even restart — state persists.
7. User gets SSE notification: "Plan ready, awaiting your approval"
8. User can close browser, go for coffee. Task stays paused.
9. User returns, opens task, clicks "Approve" → `POST /api/tasks/:id/approve`
10. Next.js calls Python service: "Resume thread X with approval"
11. Python resumes graph from checkpoint. Pipeline continues.
12. Agents work. Each node checkpointed. Cost tracked per agent.
13. Pipeline complete → memory stored, audit logged, cost tallied
14. SSE: "Task complete. 3 agents, $0.42 total cost, 24/24 gates passed."

### 8.2 Crash Recovery

Because LangGraph checkpoints state to Postgres after every node:
- Server crashes mid-execution → restart → resume from last checkpoint
- Network interruption → reconnect → continue
- User disconnects → doesn't matter → state is in DB

---

## 9. Project Structure (Revised)

```
rigovo-teams/
├── apps/
│   └── web/                          # Next.js (TypeScript)
│       ├── src/
│       │   ├── app/                  # Pages + API routes
│       │   ├── components/           # React components
│       │   └── lib/                  # Utilities, Prisma client
│       └── package.json
│
├── services/
│   └── orchestrator/                 # Python LangGraph service
│       ├── src/
│       │   ├── graph/                # LangGraph graph definition
│       │   │   ├── state.py          # TaskState definition
│       │   │   ├── nodes/            # Graph nodes
│       │   │   │   ├── classify.py
│       │   │   │   ├── route_team.py
│       │   │   │   ├── assemble.py
│       │   │   │   ├── execute_agent.py
│       │   │   │   ├── rigour_check.py
│       │   │   │   ├── approval.py
│       │   │   │   ├── store_memory.py
│       │   │   │   └── finalize.py
│       │   │   ├── edges.py          # Conditional routing logic
│       │   │   └── builder.py        # Graph construction
│       │   │
│       │   ├── agents/               # Agent definitions
│       │   │   ├── base.py           # Base agent (prompt builder, context isolation)
│       │   │   ├── coder.py
│       │   │   ├── reviewer.py
│       │   │   ├── planner.py
│       │   │   ├── qa.py
│       │   │   ├── sre.py
│       │   │   ├── devops.py
│       │   │   └── security.py
│       │   │
│       │   ├── master/               # Master Agent (workspace intelligence)
│       │   │   ├── classifier.py     # Task classification
│       │   │   ├── enricher.py       # Agent enrichment loop
│       │   │   ├── memory.py         # Post-task memory extraction
│       │   │   └── router.py         # Team routing
│       │   │
│       │   ├── rigour/               # Rigour integration
│       │   │   ├── gate_runner.py    # Calls @rigour-labs/cli
│       │   │   └── fix_packet.py     # Fix Packet V2 builder
│       │   │
│       │   ├── cost/                 # Cost tracking
│       │   │   ├── pricing.py        # Model pricing tables
│       │   │   └── tracker.py        # Per-agent cost accumulation
│       │   │
│       │   ├── db/                   # Database access
│       │   │   ├── models.py
│       │   │   └── queries.py
│       │   │
│       │   └── api.py                # FastAPI server (receives tasks from Next.js)
│       │
│       ├── pyproject.toml
│       └── Dockerfile
│
├── packages/                          # Shared TypeScript packages (kept for web)
│   └── ... (existing, but orchestration moves to Python)
│
├── docker-compose.yml                 # Postgres + Python service + Next.js
└── ARCHITECTURE.md                    # This document
```

---

## 10. Communication Between Next.js and Python

### 10.1 Option A: HTTP (Simple, MVP)

```
Next.js → POST http://orchestrator:8000/tasks/run {taskId, description, workspaceId}
Next.js → POST http://orchestrator:8000/tasks/:id/resume {threadId, response}
Next.js ← GET  http://orchestrator:8000/tasks/:id/events (SSE stream from Python)
```

### 10.2 Option B: Task Queue (Scale)

```
Next.js → Redis queue → Python worker picks up
Python → Postgres (state) + Redis pub/sub (events) → Next.js SSE relay
```

MVP starts with Option A. Scale to Option B when needed.

---

## 11. What This Architecture Delivers

| Feature | How |
|---------|-----|
| Multiple teams per workspace | Teams table + agent-team relationship |
| Agents as virtual employees | Persistent agents with memory, performance stats, enrichment |
| Master Agent shared brain | Workspace-level enrichment loop, pattern detection |
| Parallel project execution | Each task = separate LangGraph thread, independent execution |
| Async (user can leave) | Postgres checkpointer persists state, interrupt() for approvals |
| Cost transparency | cost_ledger tracks every token per agent per task |
| Deterministic quality gates | Rigour CLI integration in rigour_check node |
| Agent context isolation | Each agent node builds its own prompt, no shared chain-of-thought |
| Human-in-the-loop | LangGraph interrupt() at configurable checkpoints |
| Crash recovery | Checkpointed state resumes from last node |
| Cross-team collaboration | New tasks created for other teams from completion context |
| Audit trail | Every node execution logged with metadata |
| Agent performance tracking | first_pass_rate, avg_duration, cost per agent |

---

## 12. Domain-Agnostic Design

Rigovo is NOT just an engineering tool. It's a **virtual workforce platform**. The same orchestration engine runs any domain.

### 12.1 The Insight

What makes a "Backend Coder" different from an "LLM Annotator" or a "Content Writer"?

| Component | Engineering Domain | LLM Training Domain | Content Domain |
|-----------|-------------------|---------------------|----------------|
| System prompt | "You are a senior backend engineer..." | "You are an expert data annotator..." | "You are a senior editor..." |
| Tools | File I/O, Git, package manager | Dataset tools, label schemas, trajectory formats | CMS tools, grammar checker, style guide |
| Quality gates | Rigour (AST, security, hallucination) | Label consistency, inter-annotator agreement, schema validation | Plagiarism check, readability score, fact-check |
| Output format | Code files, tests | Annotations, trajectories, eval datasets | Articles, reports, copy |

The **framework** (orchestration, teams, memory, cost tracking, approval gates, audit) stays identical. The **domain** is plugged in via configuration.

### 12.2 Plugin Architecture for Domains

```python
# Abstract base — any domain implements this
class DomainPlugin(ABC):
    """Defines what makes a domain unique."""

    @abstractmethod
    def get_agent_roles(self) -> list[AgentRoleDefinition]:
        """Available roles in this domain (coder, reviewer, annotator, etc.)."""

    @abstractmethod
    def get_quality_gates(self) -> list[QualityGate]:
        """Domain-specific quality gates."""

    @abstractmethod
    def get_tools(self, role: str) -> list[Tool]:
        """Tools available to an agent of this role."""

    @abstractmethod
    def get_task_types(self) -> list[TaskType]:
        """Task types this domain handles (feature, bug, annotation, eval, etc.)."""

    @abstractmethod
    def build_system_prompt(self, role: str, enrichment: dict) -> str:
        """Construct the system prompt for an agent role."""


# Engineering domain (ships with Rigovo)
class EngineeringDomain(DomainPlugin):
    def get_agent_roles(self):
        return [
            AgentRoleDefinition(id="coder", name="Software Engineer", ...),
            AgentRoleDefinition(id="reviewer", name="Code Reviewer", ...),
            AgentRoleDefinition(id="qa", name="QA Engineer", ...),
            AgentRoleDefinition(id="sre", name="SRE", ...),
            AgentRoleDefinition(id="devops", name="DevOps Engineer", ...),
            AgentRoleDefinition(id="security", name="Security Expert", ...),
            AgentRoleDefinition(id="lead", name="Tech Lead", ...),
            AgentRoleDefinition(id="planner", name="Planner", ...),
        ]

    def get_quality_gates(self):
        return [
            RigourGate("file-size", threshold=500),
            RigourGate("complexity", threshold=15),
            RigourGate("hallucinated-imports", threshold=0),
            RigourGate("security-patterns", threshold=0),
            # ... 24+ gates
        ]


# LLM Training domain (future)
class LLMTrainingDomain(DomainPlugin):
    def get_agent_roles(self):
        return [
            AgentRoleDefinition(id="annotator", name="Data Annotator", ...),
            AgentRoleDefinition(id="evaluator", name="Eval Specialist", ...),
            AgentRoleDefinition(id="benchmarker", name="Benchmark Engineer", ...),
            AgentRoleDefinition(id="trajectory_gen", name="Trajectory Generator", ...),
            AgentRoleDefinition(id="qc", name="Quality Controller", ...),
        ]

    def get_quality_gates(self):
        return [
            ConsistencyGate("inter-annotator-agreement", threshold=0.85),
            SchemaGate("label-schema-validation"),
            CoverageGate("edge-case-coverage", threshold=0.7),
        ]
```

### 12.3 Team Creation with Domain Plugins

```
CTO Dashboard:
┌─────────────────────────────────────────┐
│  Create Team                             │
│                                          │
│  Team Name: [Payment Team            ]   │
│  Domain:    [Engineering         ▼]      │  ← Selects domain plugin
│                                          │
│  Available Roles (from domain):          │
│  ☑ Software Engineer                     │
│  ☑ Code Reviewer                         │
│  ☑ Security Expert                       │
│  ☐ QA Engineer                           │
│  ☑ DevOps Engineer                       │
│  ☐ SRE                                   │
│                                          │
│  Custom Rules:                           │
│  + "Always check PCI compliance"         │
│  + "Use Stripe SDK v12+"                 │
│                                          │
│  [Create Team]                           │
└─────────────────────────────────────────┘
```

---

## 13. Engineering Principles & Design Patterns

### 13.1 SOLID Principles

| Principle | Application |
|-----------|------------|
| **Single Responsibility** | Each module does one thing. `gate_runner.py` runs gates. `cost_tracker.py` tracks cost. `enricher.py` enriches agents. No god objects. |
| **Open/Closed** | New domains via DomainPlugin. New agent roles via config. New quality gates via gate registry. Extend without modifying core. |
| **Liskov Substitution** | Any QualityGate subclass (RigourGate, ConsistencyGate, SchemaGate) works wherever QualityGate is expected. |
| **Interface Segregation** | Agents depend on `AgentContext` (what they need), not on `TaskState` (everything). Quality gates depend on `GateInput`, not full agent output. |
| **Dependency Inversion** | Core orchestration depends on abstractions (DomainPlugin, QualityGate, AgentExecutor). Concrete implementations injected at startup. |

### 13.2 Clean Architecture Layers

```
┌──────────────────────────────────────────┐
│           Presentation Layer              │  ← Next.js UI, API routes
│  (React components, SSE, REST endpoints)  │
├──────────────────────────────────────────┤
│           Application Layer               │  ← Use cases, orchestration
│  (LangGraph graph, node functions,        │
│   task commands, approval handlers)       │
├──────────────────────────────────────────┤
│             Domain Layer                  │  ← Pure business logic
│  (Agent, Team, Workspace, Memory,         │
│   QualityGate, CostEntry, AuditEntry)     │
│  NO framework dependencies here.          │
├──────────────────────────────────────────┤
│          Infrastructure Layer             │  ← External concerns
│  (Postgres repos, LLM clients, Rigour     │
│   CLI wrapper, embedding providers,       │
│   SSE broadcaster, file I/O)              │
└──────────────────────────────────────────┘
```

Domain layer contains only:
- Dataclasses / value objects (no ORM, no framework)
- Business rules (validation, domain logic)
- Abstract interfaces (repositories, services)

Infrastructure layer implements those interfaces with concrete tech.

### 13.3 Key Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Repository** | Database access | `AgentRepository`, `TeamRepository`, `TaskRepository`, `MemoryRepository`. Domain never touches SQL. |
| **Strategy** | Quality gates, LLM providers | Swap Rigour for custom gates. Swap Claude for GPT. No code changes to orchestration. |
| **Observer** | Event system | Nodes emit events → SSE relay picks up. Decoupled. |
| **Factory** | Agent creation | `AgentFactory` builds agents from config + domain plugin. Orchestration doesn't know concrete agent types. |
| **Template Method** | Agent execution | Base agent defines the flow (build context → call LLM → parse output → track cost). Subclasses override specific steps. |
| **State Machine** | Task lifecycle | LangGraph IS the state machine. States are graph nodes. Transitions are edges. Persistence is built in. |
| **Plugin** | Domain extensibility | DomainPlugin interface. Engineering, LLM Training, Content — all plug in without touching core. |
| **Unit of Work** | Cost tracking | Accumulate cost entries during task execution, flush to DB at finalize. |

### 13.4 Dependency Injection

```python
# Container (configured at startup)
class Container:
    def __init__(self, config: AppConfig):
        # Infrastructure
        self.db = PostgresDatabase(config.database_url)
        self.llm_factory = LLMFactory(config.llm_defaults)
        self.embedding_provider = create_embedding_provider(config.embedding)
        self.event_bus = EventBus()

        # Repositories (interface → implementation)
        self.workspace_repo: WorkspaceRepository = PgWorkspaceRepository(self.db)
        self.team_repo: TeamRepository = PgTeamRepository(self.db)
        self.agent_repo: AgentRepository = PgAgentRepository(self.db)
        self.task_repo: TaskRepository = PgTaskRepository(self.db)
        self.memory_repo: MemoryRepository = PgMemoryRepository(self.db)
        self.audit_repo: AuditRepository = PgAuditRepository(self.db)
        self.cost_repo: CostRepository = PgCostRepository(self.db)

        # Domain plugins (registered by domain ID)
        self.domains: dict[str, DomainPlugin] = {
            "engineering": EngineeringDomain(),
            # "llm_training": LLMTrainingDomain(),  # Future
            # "content": ContentDomain(),            # Future
        }

        # Application services
        self.master_agent = MasterAgentService(
            workspace_repo=self.workspace_repo,
            agent_repo=self.agent_repo,
            memory_repo=self.memory_repo,
            llm_factory=self.llm_factory,
        )
        self.cost_tracker = CostTracker(
            cost_repo=self.cost_repo,
            pricing=ModelPricing(),
        )
        self.graph_builder = GraphBuilder(
            domains=self.domains,
            agent_repo=self.agent_repo,
            cost_tracker=self.cost_tracker,
            event_bus=self.event_bus,
        )
```

---

## 14. Revised Project Structure (Final)

```
rigovo-teams/
│
├── cli/                                        # @rigovo/cli (Python) — LOCAL EXECUTION
│   ├── src/
│   │   └── rigovo/                             # Python package: rigovo
│   │       │
│   │       ├── domain/                         # ── DOMAIN LAYER (pure, no deps) ──
│   │       │   ├── __init__.py
│   │       │   ├── entities/                   # Business entities (dataclasses)
│   │       │   │   ├── __init__.py
│   │       │   │   ├── workspace.py            # Workspace value object
│   │       │   │   ├── team.py                 # Team entity
│   │       │   │   ├── agent.py                # Agent entity (role, config, stats)
│   │       │   │   ├── task.py                 # Task entity (state, results)
│   │       │   │   ├── memory.py               # Memory value object
│   │       │   │   ├── cost_entry.py           # Cost tracking value object
│   │       │   │   ├── audit_entry.py          # Audit log value object
│   │       │   │   └── quality.py              # GateResult, FixPacket, Violation
│   │       │   │
│   │       │   ├── interfaces/                 # Abstract interfaces (ports)
│   │       │   │   ├── __init__.py
│   │       │   │   ├── repositories.py         # All repository interfaces
│   │       │   │   ├── llm_provider.py         # LLMProvider interface
│   │       │   │   ├── embedding_provider.py
│   │       │   │   ├── quality_gate.py         # QualityGate interface
│   │       │   │   ├── domain_plugin.py        # DomainPlugin interface
│   │       │   │   └── event_emitter.py        # EventEmitter interface
│   │       │   │
│   │       │   └── services/                   # Domain services (pure logic)
│   │       │       ├── __init__.py
│   │       │       ├── cost_calculator.py      # Token → dollar conversion
│   │       │       ├── team_assembler.py       # Pipeline assembly logic
│   │       │       └── memory_ranker.py        # Memory relevance scoring
│   │       │
│   │       ├── application/                    # ── APPLICATION LAYER (use cases) ──
│   │       │   ├── __init__.py
│   │       │   ├── graph/                      # LangGraph orchestration
│   │       │   │   ├── __init__.py
│   │       │   │   ├── state.py                # TaskState TypedDict
│   │       │   │   ├── builder.py              # Graph construction + compilation
│   │       │   │   └── nodes/                  # Graph nodes (thin — delegate to domain)
│   │       │   │       ├── __init__.py
│   │       │   │       ├── classify.py
│   │       │   │       ├── route_team.py
│   │       │   │       ├── assemble.py
│   │       │   │       ├── execute_agent.py
│   │       │   │       ├── quality_check.py
│   │       │   │       ├── approval.py         # interrupt() for human-in-the-loop
│   │       │   │       ├── store_memory.py
│   │       │   │       └── finalize.py
│   │       │   │
│   │       │   ├── master/                     # Master Agent service
│   │       │   │   ├── __init__.py
│   │       │   │   ├── classifier.py           # Task classification
│   │       │   │   ├── enricher.py             # Agent enrichment loop
│   │       │   │   ├── router.py               # Team routing
│   │       │   │   └── evaluator.py            # Post-task memory extraction
│   │       │   │
│   │       │   └── commands/                   # Command handlers
│   │       │       ├── __init__.py
│   │       │       ├── run_task.py             # rigovo run "..."
│   │       │       ├── approve_task.py         # Resume from interrupt
│   │       │       └── enrich_agents.py        # Enrichment cycle
│   │       │
│   │       ├── infrastructure/                 # ── INFRASTRUCTURE LAYER (adapters) ──
│   │       │   ├── __init__.py
│   │       │   ├── persistence/                # Database implementations
│   │       │   │   ├── __init__.py
│   │       │   │   ├── sqlite_local.py         # Local SQLite for checkpoints + cache
│   │       │   │   ├── sqlite_task_repo.py     # Local task state
│   │       │   │   └── sqlite_cache_repo.py    # Offline team/agent config cache
│   │       │   │
│   │       │   ├── cloud/                      # Cloud sync (metadata only)
│   │       │   │   ├── __init__.py
│   │       │   │   ├── sync_client.py          # HTTP client to rigovo.com API
│   │       │   │   ├── cloud_team_repo.py      # Fetch team configs from cloud
│   │       │   │   ├── cloud_memory_repo.py    # Sync memories to/from cloud
│   │       │   │   ├── cloud_audit_repo.py     # Push audit entries to cloud
│   │       │   │   └── cloud_cost_repo.py      # Push cost data to cloud
│   │       │   │
│   │       │   ├── llm/                        # LLM provider implementations
│   │       │   │   ├── __init__.py
│   │       │   │   ├── factory.py              # LLMFactory (creates provider by name)
│   │       │   │   ├── anthropic_provider.py   # Claude (direct API call, user's key)
│   │       │   │   ├── openai_provider.py      # GPT
│   │       │   │   ├── groq_provider.py        # Groq
│   │       │   │   └── ollama_provider.py      # Local models
│   │       │   │
│   │       │   ├── quality/                    # Quality gate implementations
│   │       │   │   ├── __init__.py
│   │       │   │   ├── rigour_gate.py          # Rigour CLI wrapper (engineering)
│   │       │   │   └── registry.py             # Gate registry (maps gate ID → impl)
│   │       │   │
│   │       │   ├── embeddings/                 # Embedding providers
│   │       │   │   ├── __init__.py
│   │       │   │   ├── openai_embeddings.py
│   │       │   │   └── local_embeddings.py     # sentence-transformers (local)
│   │       │   │
│   │       │   ├── filesystem/                 # Local file operations
│   │       │   │   ├── __init__.py
│   │       │   │   ├── project_reader.py       # Read project structure, tech stack
│   │       │   │   ├── code_writer.py          # Write generated code files
│   │       │   │   └── git_ops.py              # Git operations (commit, branch, PR)
│   │       │   │
│   │       │   └── terminal/                   # Terminal UI
│   │       │       ├── __init__.py
│   │       │       ├── rich_output.py          # Rich console output
│   │       │       ├── approval_prompt.py      # Interactive approval prompts
│   │       │       └── progress_display.py     # Real-time agent status display
│   │       │
│   │       ├── domains/                        # ── DOMAIN PLUGINS ──
│   │       │   ├── __init__.py
│   │       │   ├── engineering/                # Ships with v1
│   │       │   │   ├── __init__.py
│   │       │   │   ├── plugin.py               # EngineeringDomain(DomainPlugin)
│   │       │   │   ├── roles.py                # Role definitions + system prompts
│   │       │   │   ├── tools.py                # Engineering tools (file I/O, git, etc.)
│   │       │   │   └── gates.py                # Rigour gate configuration
│   │       │   │
│   │       │   └── llm_training/               # Future
│   │       │       ├── __init__.py
│   │       │       ├── plugin.py
│   │       │       ├── roles.py
│   │       │       ├── tools.py
│   │       │       └── gates.py
│   │       │
│   │       ├── container.py                    # Dependency injection container
│   │       ├── config.py                       # Load rigovo.yml + .env
│   │       └── main.py                         # CLI entry point (click/typer)
│   │
│   ├── tests/
│   │   ├── unit/
│   │   │   ├── domain/                         # Pure domain logic tests (fast)
│   │   │   ├── application/                    # Use case tests (mocked infra)
│   │   │   └── infrastructure/                 # Adapter tests
│   │   ├── integration/                        # Full pipeline with real LLM
│   │   └── conftest.py                         # Shared fixtures
│   │
│   ├── pyproject.toml                          # Dependencies, build config
│   └── README.md
│
├── apps/
│   └── web/                                    # Next.js — CLOUD DASHBOARD (monitoring only)
│       ├── src/
│       │   ├── app/
│       │   │   ├── (auth)/                     # Login, signup (WorkOS)
│       │   │   ├── dashboard/
│       │   │   │   ├── page.tsx                # Overview: teams, projects, recent tasks
│       │   │   │   ├── teams/                  # Team CRUD, agent configuration
│       │   │   │   ├── projects/               # Project list + metadata
│       │   │   │   ├── tasks/                  # Task history (synced from CLI)
│       │   │   │   ├── analytics/              # Cost dashboard, performance metrics
│       │   │   │   ├── memory/                 # Memory explorer
│       │   │   │   └── audit/                  # Audit trail viewer
│       │   │   └── api/
│       │   │       ├── workspaces/             # Workspace CRUD
│       │   │       ├── teams/                  # Team CRUD (CLI syncs from here)
│       │   │       ├── agents/                 # Agent CRUD + performance
│       │   │       ├── tasks/                  # Task metadata (synced from CLI)
│       │   │       ├── memory/                 # Memory CRUD + semantic search
│       │   │       ├── audit/                  # Audit log queries
│       │   │       └── analytics/              # Cost + performance analytics
│       │   ├── components/
│       │   │   ├── ui/                         # Shadcn/Radix primitives
│       │   │   └── dashboard/                  # Dashboard components
│       │   └── lib/
│       │       ├── prisma.ts
│       │       └── supabase.ts
│       ├── prisma/
│       │   └── schema.prisma                   # Cloud DB schema
│       └── package.json
│
├── docker-compose.yml                          # Local dev: Postgres (for cloud DB dev)
├── rigovo.yml.example                          # Example project config
├── ARCHITECTURE.md                             # This document
└── README.md
```

### 14.1 Module Dependency Rules

```
Presentation (Next.js) → Application (only via HTTP API)
Application → Domain (imports entities, interfaces, services)
Application → Infrastructure (via dependency injection, never direct)
Domain → NOTHING (pure, zero external dependencies)
Infrastructure → Domain (implements interfaces)
Domains (plugins) → Domain (implements DomainPlugin interface)
```

**Rule: No layer imports from a layer above it. Domain never imports from Application or Infrastructure.**

### 14.2 Testing Strategy

| Layer | Test Type | What's Mocked | Speed |
|-------|-----------|---------------|-------|
| Domain | Unit | Nothing (pure logic) | Instant |
| Application | Unit | All repositories, LLM providers | Fast |
| Infrastructure | Integration | Nothing (real DB, real APIs) | Slow |
| E2E | System | Nothing | Slowest |

Domain tests are the most valuable — they test business rules without any infrastructure noise. If domain tests pass, the logic is correct regardless of what database or LLM provider is used.
