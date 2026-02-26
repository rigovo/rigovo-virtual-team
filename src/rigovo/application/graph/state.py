"""LangGraph TaskState — the state that flows through the orchestration graph."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentOutput(TypedDict, total=False):
    """Output from a single agent's execution."""

    summary: str
    files_changed: list[str]
    tokens: int
    cost: float
    duration_ms: int


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

    task_type: str       # feature, bug, refactor, etc.
    complexity: str      # low, medium, high, critical
    reasoning: str       # Why this classification


class TeamConfig(TypedDict, total=False):
    """Team configuration for task execution."""

    team_id: str
    team_name: str
    domain: str
    agents: dict[str, dict[str, Any]]  # {role: agent_config}
    pipeline_order: list[str]          # Ordered role IDs


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

    # --- Classification (set by classify node) ---
    classification: ClassificationData

    # --- Team routing (set by route_team node) ---
    team_config: TeamConfig
    requested_team_name: str            # Optional user-requested team key/name

    # --- Pipeline execution ---
    current_agent_index: int            # Index into pipeline_order
    current_agent_role: str             # Current agent's role ID
    agent_outputs: dict[str, AgentOutput]  # {role: output}
    agent_messages: list[AgentMessage]  # Inter-agent consultation thread

    # --- Quality gates ---
    gate_results: dict[str, Any]        # Latest gate check result
    fix_packets: list[str]              # Accumulated fix packet prompts
    retry_count: int
    max_retries: int

    # --- Approval ---
    approval_status: str                # 'pending', 'approved', 'rejected'
    user_feedback: str

    # --- Cost tracking ---
    cost_accumulator: dict[str, dict[str, float]]  # {agent_id: {tokens, cost}}
    budget_max_cost_per_task: float
    budget_max_tokens_per_task: int
    consultation_policy: dict[str, Any]  # Runtime consultation policy from rigovo.yml
    deep_mode: str                      # never|final|ci|always|critical_only
    deep_pro: bool                      # Run deep in pro tier when deep enabled
    ci_mode: bool                       # Task was launched in CI mode

    # --- Context engineering ---
    project_snapshot: Any               # ProjectSnapshot from scanner (set at task start)
    enrichment_updates: list[dict[str, Any]]  # Learnings extracted post-pipeline

    # --- Agent debate ---
    debate_round: int                   # Current debate iteration (0 = first pass)
    max_debate_rounds: int              # Max coder↔reviewer iterations (default 2)
    reviewer_feedback: str              # Reviewer's CHANGES_REQUESTED feedback for coder

    # --- Memory ---
    memories_to_store: list[str]        # Memory text to persist post-task

    # --- Status ---
    status: str                         # Current phase name
    error: str                          # Error message if failed

    # --- Events (for terminal display / cloud sync) ---
    events: list[dict[str, Any]]
