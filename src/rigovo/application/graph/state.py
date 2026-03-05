"""LangGraph TaskState — the state that flows through the orchestration graph."""

from __future__ import annotations

from typing import Any, TypedDict


class ExecutionLogEntry(TypedDict, total=False):
    """Record of a single executed command (Phase 14)."""

    command: str
    exit_code: int
    summary: str


class AgentOutput(TypedDict, total=False):
    """Output from a single agent's execution."""

    summary: str
    files_changed: list[str]
    input_tokens: int
    output_tokens: int
    tokens: int
    cost: float
    duration_ms: int
    subtask_count: int
    subtask_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    cache_source: str
    cache_saved_tokens: int
    cache_saved_cost_usd: float
    execution_log: list[ExecutionLogEntry]  # Phase 14 execution verification
    execution_verified: bool  # Whether execution verification passed


class AgentMessage(TypedDict, total=False):
    """Structured inter-agent message for consultation and handoff."""

    id: str
    type: str  # consult_request | consult_response
    from_role: str
    to_role: str
    content: str
    status: str  # pending | answered
    linked_to: str  # Request message id for responses
    created_at: float  # epoch seconds


class ClassificationData(TypedDict, total=False):
    """Master Agent's classification of a task."""

    task_type: str  # feature, bug, refactor, new_project, etc.
    complexity: str  # low, medium, high, critical
    workspace_type: str  # new_project | existing_project
    reasoning: str  # Why this classification


class TeamConfig(TypedDict, total=False):
    """Team configuration for task execution."""

    team_id: str
    team_name: str
    domain: str
    agents: dict[str, dict[str, Any]]  # {role: agent_config}
    pipeline_order: list[str]  # Ordered role IDs
    execution_dag: dict[str, list[str]]  # {role: [depends_on_roles]}


class TaskState(TypedDict, total=False):
    """
    The state that flows through the LangGraph orchestration graph.

    Every graph node reads from and writes to this state.
    State is checkpointed after every node for crash recovery.
    """

    # --- Identity ---
    task_id: str
    workspace_id: str
    description: str
    project_root: str
    worktree_mode: str  # project|git_worktree
    worktree_root: str  # Optional worktree root within project sandbox
    filesystem_sandbox_mode: str  # project_root|worktree

    # --- Classification (set by classify node) ---
    classification: ClassificationData

    # --- Deterministic classification (set by classify node BEFORE LLM) ---
    # Instant two-pass result: regex + vector similarity (<50ms, zero LLM).
    # This is the FLOOR — the LLM can upgrade but NEVER downgrade.
    deterministic_classification: dict[str, Any]

    # --- Intent profile (set by intent_gate node AFTER classify) ---
    # Shapes the entire pipeline: team size, token budget, file read limits.
    # brainstorm=50K tokens, research=150K, fix=300K, build=500K.
    intent_profile: dict[str, Any]

    # --- Staffing plan (set by classify node — Master Agent SME analysis) ---
    # Contains per-instance agent assignments, dependency DAG, risks, acceptance
    # criteria, domain analysis. This is the Master Agent's full output.
    staffing_plan: dict[str, Any]

    # --- Team routing (set by route_team node) ---
    team_config: TeamConfig
    requested_team_name: str  # Optional user-requested team key/name

    # --- Pipeline execution ---
    current_agent_index: int  # Index into pipeline_order
    current_agent_role: str  # Current agent's role ID
    current_instance_id: str  # Current agent instance (e.g. "backend-engineer-1")
    ready_roles: list[str]  # DAG roles/instances ready to execute
    completed_roles: list[str]  # DAG roles/instances already completed
    blocked_roles: list[str]  # DAG roles/instances blocked by dependency failure
    agent_outputs: dict[str, AgentOutput]  # {instance_id: output}
    agent_messages: list[AgentMessage]  # Inter-agent consultation thread

    # --- Feedback loops (reviewer → engineer, QA → engineer) ---
    feedback_loops: list[dict[str, Any]]  # History of push-backs and re-work cycles
    active_feedback: dict[str, Any]  # Current feedback being addressed (if any)

    # --- Execution verification (Phase 4) ---
    # Per-agent runtime verification: build results, test results, config validation
    execution_verification: dict[str, Any]  # Latest verification result for current agent
    verification_history: list[dict[str, Any]]  # Per-agent verification summaries

    # --- Quality gates ---
    gate_results: dict[str, Any]  # Latest gate check result
    gate_history: list[dict[str, Any]]  # Per-role gate summaries across pipeline
    fix_packets: list[str]  # Accumulated fix packet prompts
    retry_count: int
    max_retries: int

    # --- Approval ---
    approval_status: str  # 'pending', 'approved', 'rejected'
    approval_data: dict[str, Any]  # payload shown to user at approval checkpoints
    user_feedback: str

    # --- Cost tracking ---
    cost_accumulator: dict[str, dict[str, float]]  # {agent_id: {tokens, cost}}
    budget_max_cost_per_task: float
    budget_max_tokens_per_task: int
    adaptive_token_budget_by_intent: dict[
        str, dict[str, int]
    ]  # Workspace history-derived p50/p75/p95
    adaptive_budget_user_cap: bool  # True when max_tokens_per_task is explicitly user-defined
    adaptive_budget_min_sample: int  # Minimum sample size required for adaptive application
    budget_policy: dict[str, Any]  # Runtime token-pressure policy (warning/compaction/soft-fail)
    budget_warning_emitted_at_tokens: int  # Last token count at which warning was emitted
    budget_soft_extensions_used: int  # Number of soft auto-extensions applied
    budget_auto_compactions: int  # Number of auto-compactions applied
    compaction_checkpoints: list[dict[str, Any]]  # Multi-stage compaction history + replay pointers
    compaction_synthesis: str  # Cross-agent synthesis generated during compaction
    consultation_policy: dict[str, Any]  # Runtime consultation policy from rigovo.yml
    subagent_policy: dict[str, Any]  # Runtime sub-agent spawn policy from rigovo.yml
    replan_policy: dict[str, Any]  # Runtime replanning policy from rigovo.yml
    learning_policy: dict[str, Any]  # Runtime self-tuning policy (safe-mode by default)
    replan_count: int  # Replans already triggered in this task
    replan_history: list[dict[str, Any]]  # Replan trigger/failure history for auditability
    deep_mode: str  # never|final|ci|always|critical_only
    deep_pro: bool  # Run deep in pro tier when deep enabled
    ci_mode: bool  # Task was launched in CI mode

    # --- Context engineering ---
    project_snapshot: Any  # ProjectSnapshot from scanner (set at task start)
    code_knowledge_graph: Any  # CodeKnowledgeGraph — imports, exports, dependencies
    enrichment_updates: list[dict[str, Any]]  # Learnings extracted post-pipeline

    # --- Agent debate ---
    debate_round: int  # Current debate iteration (0 = first pass)
    max_debate_rounds: int  # Max coder↔reviewer iterations (default 2)
    reviewer_feedback: str  # Reviewer's CHANGES_REQUESTED feedback for coder
    debate_target_role: str  # Role to force-run after coder in debate cycle

    # --- Memory ---
    memories_to_store: list[str]  # Memory text to persist post-task
    memory_context_by_role: dict[str, str]  # Cached retrieved memory prompt section per role
    memory_retrieval_log: dict[str, list[dict[str, Any]]]  # Retrieved memory IDs/scores by role
    memory_learning_metrics: dict[str, Any]  # Per-task feedback metrics for memory loop
    memory_layer_policy: dict[str, Any]  # task/workspace/agent_skill memory layer policy
    memory_layer_counters: dict[str, int]  # Persisted/blocked counters by memory layer
    agent_learning_updates: dict[
        str, list[dict[str, Any]]
    ]  # Proposed/promoted role-level learning deltas
    behavior_change_audit: list[dict[str, Any]]  # Why agent behavior changed (promotion trail)
    memory_snapshots: list[dict[str, Any]]  # Versioned memory snapshots for rollback
    integration_policy: dict[str, Any]  # Runtime policy for plugin/connector/MCP tooling
    integration_catalog: dict[str, Any]  # Loaded plugin capability catalog

    # --- Late-binding reclassification ---
    reclassify_requested: bool  # True when an agent emits RECLASSIFY signal
    reclassify_reason: str  # Agent's justification for reclassification
    reclassify_suggested_type: str  # Agent's suggested new task_type (advisory)
    reclassify_count: int  # Number of reclassifications already performed (max 1)

    # --- History states (checkpoint timeline + resume intelligence) ---
    checkpoint_timeline: list[dict[str, Any]]  # Serialized CheckpointRecord list
    resume_context: dict[str, Any]  # Injected when resuming an interrupted task
    last_heartbeat: float  # Epoch seconds — stale detection for interrupted tasks
    is_resuming: bool  # True when this execution is a resume (not fresh start)

    # --- Status ---
    status: str  # Current phase name
    error: str  # Error message if failed

    # --- Events (for terminal display / cloud sync) ---
    events: list[dict[str, Any]]
