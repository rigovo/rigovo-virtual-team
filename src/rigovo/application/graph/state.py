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
    tokens: int
    cost: float
    duration_ms: int
    subtask_count: int
    subtask_tokens: int
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
    user_feedback: str

    # --- Cost tracking ---
    cost_accumulator: dict[str, dict[str, float]]  # {agent_id: {tokens, cost}}
    budget_max_cost_per_task: float
    budget_max_tokens_per_task: int
    consultation_policy: dict[str, Any]  # Runtime consultation policy from rigovo.yml
    subagent_policy: dict[str, Any]  # Runtime sub-agent spawn policy from rigovo.yml
    replan_policy: dict[str, Any]  # Runtime replanning policy from rigovo.yml
    replan_count: int  # Replans already triggered in this task
    replan_history: list[dict[str, Any]]  # Replan trigger/failure history for auditability
    deep_mode: str  # never|final|ci|always|critical_only
    deep_pro: bool  # Run deep in pro tier when deep enabled
    ci_mode: bool  # Task was launched in CI mode

    # --- Context engineering ---
    project_snapshot: Any  # ProjectSnapshot from scanner (set at task start)
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
    integration_policy: dict[str, Any]  # Runtime policy for plugin/connector/MCP tooling
    integration_catalog: dict[str, Any]  # Loaded plugin capability catalog

    # --- Status ---
    status: str  # Current phase name
    error: str  # Error message if failed

    # --- Events (for terminal display / cloud sync) ---
    events: list[dict[str, Any]]
