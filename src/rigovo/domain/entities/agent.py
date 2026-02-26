"""Agent — a persistent virtual employee within a team."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from rigovo.domain._compat import StrEnum
from typing import Any
from uuid import UUID, uuid4


class AgentRole(StrEnum):
    """Standard agent roles. Domain plugins can extend with custom roles."""

    # Engineering domain
    CODER = "coder"
    REVIEWER = "reviewer"
    LEAD = "lead"
    QA = "qa"
    SRE = "sre"
    DEVOPS = "devops"
    SECURITY = "security"
    PLANNER = "planner"

    # LLM Training domain (future)
    ANNOTATOR = "annotator"
    EVALUATOR = "evaluator"
    BENCHMARKER = "benchmarker"
    TRAJECTORY_GEN = "trajectory_gen"
    QC = "qc"


@dataclass
class AgentStats:
    """Performance statistics for an agent. Updated after each task."""

    tasks_completed: int = 0
    first_pass_rate: float = 0.0  # % of tasks passing gates on first try
    avg_duration_ms: int = 0
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0

    def record_task(
        self,
        duration_ms: int,
        tokens: int,
        cost: float,
        passed_first_try: bool,
    ) -> None:
        """Update stats after a task completes."""
        self.tasks_completed += 1
        self.total_tokens_used += tokens
        self.total_cost_usd += cost

        # Rolling average for duration
        prev_total = self.avg_duration_ms * (self.tasks_completed - 1)
        self.avg_duration_ms = (prev_total + duration_ms) // self.tasks_completed

        # Rolling average for first-pass rate
        prev_passes = self.first_pass_rate * (self.tasks_completed - 1)
        new_pass = 1.0 if passed_first_try else 0.0
        self.first_pass_rate = (prev_passes + new_pass) / self.tasks_completed


@dataclass
class EnrichmentContext:
    """
    Knowledge injected by the Master Agent into an agent's context.

    This is how agents learn from past experience without retraining.
    The Master Agent periodically analyses each agent's performance
    and updates this context.
    """

    common_mistakes: list[str] = field(default_factory=list)
    domain_knowledge: list[str] = field(default_factory=list)
    pre_check_rules: list[str] = field(default_factory=list)
    workspace_conventions: list[str] = field(default_factory=list)
    last_enriched_at: datetime | None = None

    def to_prompt_section(self) -> str:
        """Render enrichment context as a prompt section for the agent."""
        sections: list[str] = []

        if self.common_mistakes:
            items = "\n".join(f"  - {m}" for m in self.common_mistakes)
            sections.append(f"KNOWN PITFALLS (learn from past mistakes):\n{items}")

        if self.domain_knowledge:
            items = "\n".join(f"  - {k}" for k in self.domain_knowledge)
            sections.append(f"DOMAIN KNOWLEDGE (accumulated expertise):\n{items}")

        if self.pre_check_rules:
            items = "\n".join(f"  - {r}" for r in self.pre_check_rules)
            sections.append(f"PRE-CHECK RULES (verify before submitting):\n{items}")

        if self.workspace_conventions:
            items = "\n".join(f"  - {c}" for c in self.workspace_conventions)
            sections.append(f"WORKSPACE CONVENTIONS:\n{items}")

        return "\n\n".join(sections) if sections else ""


@dataclass
class Agent:
    """
    A persistent virtual employee.

    Not a disposable function — an agent has memory, performance history,
    domain expertise, and gets enriched by the Master Agent over time.
    """

    team_id: UUID
    workspace_id: UUID
    role: str  # AgentRole value or custom role from domain plugin
    name: str

    id: UUID = field(default_factory=uuid4)
    description: str = ""

    # Configuration
    system_prompt: str = ""
    llm_model: str = "claude-sonnet-4-6"
    tools: list[str] = field(default_factory=list)
    custom_rules: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)

    # Performance
    stats: AgentStats = field(default_factory=AgentStats)

    # Enrichment (set by Master Agent)
    enrichment: EnrichmentContext = field(default_factory=EnrichmentContext)

    # Pipeline ordering within team
    pipeline_order: int = 0
    is_active: bool = True

    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def build_full_prompt(
        self,
        team_context: str = "",
        project_context: str = "",
    ) -> str:
        """
        Compose the full system prompt for this agent.

        Layers:
        1. Base system prompt (role definition)
        2. Enrichment context (Master Agent's learnings)
        3. Custom rules (CTO-defined constraints)
        4. Team context (domain, conventions)
        5. Project context (tech stack, patterns)
        """
        sections: list[str] = [self.system_prompt]

        enrichment_text = self.enrichment.to_prompt_section()
        if enrichment_text:
            sections.append(enrichment_text)

        if self.custom_rules:
            rules = "\n".join(f"  - {r}" for r in self.custom_rules)
            sections.append(f"CUSTOM RULES (defined by your CTO):\n{rules}")

        if team_context:
            sections.append(f"TEAM CONTEXT:\n{team_context}")

        if project_context:
            sections.append(f"PROJECT CONTEXT:\n{project_context}")

        return "\n\n---\n\n".join(sections)

    def record_task_completion(
        self,
        duration_ms: int,
        tokens: int,
        cost: float,
        passed_first_try: bool,
    ) -> None:
        """Update performance stats after completing a task."""
        self.stats.record_task(duration_ms, tokens, cost, passed_first_try)
        self.updated_at = datetime.utcnow()
