"""Context builder — assembles rich per-agent context.

This is the ASSEMBLY layer that turns raw signals (project snapshot,
memories, enrichment, previous outputs) into a single coherent context
that makes the agent intelligent instead of guessing.

Three context layers are injected per agent:
1. PROJECT CONTEXT — what does the codebase look like right now?
2. MEMORY CONTEXT — what did we learn from past tasks?
3. ENRICHMENT CONTEXT — what mistakes should we avoid?
4. PIPELINE CONTEXT — what did previous agents produce?

A chatbot sees: system prompt + user message.
An intelligent agent sees: system prompt + project + memories +
enrichment + pipeline outputs + quality expectations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from rigovo.application.context.memory_retriever import RetrievedMemories
from rigovo.application.context.project_scanner import ProjectSnapshot
from rigovo.domain.services.behavior_hsm import build_hsm_prompt_section
from rigovo.domain.services.code_knowledge_graph import CodeKnowledgeGraph

logger = logging.getLogger(__name__)

# --- Context budget (prevent prompt blowup) ---
MAX_PROJECT_CONTEXT_CHARS = 10_000
MAX_MEMORY_CONTEXT_CHARS = 3_000
MAX_PIPELINE_CONTEXT_CHARS = 4_000
MAX_TOTAL_CONTEXT_CHARS = 20_000

# Role-specific quality expectations injected alongside context
ROLE_QUALITY_CONTRACT: dict[str, str] = {
    "planner": (
        "Your execution plan will be reviewed by the Tech Lead and executed by "
        "multiple engineers (Coder, QA, DevOps). A vague plan causes rework "
        "across the entire team — specificity saves tokens and time. "
        "Every step must have: (1) exact file paths, (2) specific function/class "
        "changes, (3) effort estimate (S/M/L), (4) dependencies on other steps, "
        "and (5) verification criteria. The acceptance criteria you write inform "
        "the QA Engineer's test strategy. The dependency graph you describe is "
        "reviewed by the Tech Lead for architectural correctness."
    ),
    "coder": (
        "Your code will be checked by deterministic quality gates (AST analysis). "
        "Gates check: file size (<400 lines), no magic numbers, proper error handling, "
        "type hints, no hallucinated imports, no swallowed exceptions. "
        "If gates fail, you will receive a fix packet with exact violations to fix. "
        "Write clean code the FIRST time to avoid retry loops."
    ),
    "reviewer": (
        "You review the Coder's output against the plan. Focus on logic correctness, "
        "not style. If the code passes quality gates, don't block on minor issues."
    ),
    "security": (
        "You audit for real vulnerabilities, not theoretical ones. "
        "Check: injection, auth gaps, secrets in code, missing input validation. "
        "Don't flag well-known safe patterns."
    ),
    "qa": (
        "Your tests will be run by quality gates. Write deterministic tests "
        "that pass reliably. Mock external dependencies. Cover edge cases. "
        "If tests fail the gate, you get a fix packet."
    ),
    "devops": (
        "Your infrastructure code is checked by quality gates. "
        "No hardcoded values, no latest tags, health checks required."
    ),
    "sre": (
        "Focus on observability: logging, monitoring, timeouts, circuit breakers. "
        "Don't over-engineer for trivial changes."
    ),
    "lead": (
        "You provide architectural oversight. Approve or flag concerns. "
        "Don't micromanage implementation details."
    ),
}


@dataclass
class AgentContext:
    """Complete context assembled for a single agent execution.

    This is everything the agent sees beyond its system prompt.
    """

    role: str
    project_section: str = ""
    architecture_section: str = ""  # Code Knowledge Graph summary
    memory_section: str = ""
    enrichment_section: str = ""
    pipeline_section: str = ""
    message_section: str = ""
    quality_contract: str = ""
    behavioral_section: str = ""  # HSM behavioral state injection
    resume_section: str = ""  # History state: injected when resuming interrupted task

    def to_full_context(self) -> str:
        """Assemble all sections into a single context string."""
        sections = []

        # Behavioral state comes FIRST — it defines mandatory workflow phases
        if self.behavioral_section:
            sections.append(self.behavioral_section)

        if self.quality_contract:
            sections.append(
                f"--- QUALITY CONTRACT (what's expected of you) ---\n{self.quality_contract}"
            )

        if self.project_section:
            sections.append(self.project_section)

        # Architecture goes right after project context — it's structural understanding
        if self.architecture_section:
            sections.append(self.architecture_section)

        if self.memory_section:
            sections.append(self.memory_section)

        if self.enrichment_section:
            sections.append(self.enrichment_section)

        if self.pipeline_section:
            sections.append(self.pipeline_section)

        if self.message_section:
            sections.append(self.message_section)

        # Resume context comes last — it's critical override info
        if self.resume_section:
            sections.append(self.resume_section)

        full = "\n\n".join(sections)

        # Hard cap to prevent prompt blowup
        if len(full) > MAX_TOTAL_CONTEXT_CHARS:
            full = full[:MAX_TOTAL_CONTEXT_CHARS] + "\n... (context truncated)"
            logger.warning(
                "Agent context for %s truncated at %d chars",
                self.role,
                MAX_TOTAL_CONTEXT_CHARS,
            )

        return full


class ContextBuilder:
    """Assembles rich context for each agent in the pipeline.

    This is the central orchestrator of context engineering.
    It takes raw signals and produces a coherent, budgeted
    context per agent role.
    """

    def build(
        self,
        role: str,
        project_snapshot: ProjectSnapshot | None = None,
        memories: RetrievedMemories | None = None,
        enrichment_text: str = "",
        previous_outputs: dict[str, dict[str, Any]] | None = None,
        agent_messages: list[dict[str, Any]] | None = None,
        specialisation: str = "",
        task_type: str = "",
        knowledge_graph: CodeKnowledgeGraph | None = None,
        resume_context: dict[str, Any] | None = None,
    ) -> AgentContext:
        """Build complete context for an agent.

        Args:
            role: Agent role (coder, reviewer, etc.).
            project_snapshot: Scanned project structure.
            memories: Retrieved relevant memories.
            enrichment_text: Accumulated enrichment from past tasks.
            previous_outputs: Outputs from agents earlier in pipeline.
            specialisation: Agent's specialisation (e.g., "frontend", "backend").
            task_type: Current task classification (e.g., "feature", "infra").
            knowledge_graph: Code knowledge graph for architecture understanding.

        Returns:
            AgentContext with all sections assembled and budgeted.
        """
        ctx = AgentContext(role=role)

        # 0. Behavioral state (HSM) — mandatory workflow phases
        ctx.behavioral_section = build_hsm_prompt_section(
            role=role,
            specialisation=specialisation,
            task_type=task_type,
        )

        # 1. Quality contract — what this role is held to
        ctx.quality_contract = ROLE_QUALITY_CONTRACT.get(role, "")

        # 1b. Workspace-type quality contract addendum
        if project_snapshot is not None:
            wt = getattr(project_snapshot, "workspace_type", "existing_project")
            if wt in {"new_project", "new_subfolder_project"}:
                ctx.quality_contract += (
                    "\n\nWORKSPACE IS A GREENFIELD TARGET: There are no existing "
                    "patterns to match. Create the full project structure from scratch. "
                    "Choose sensible framework defaults. Do not look for files that "
                    "don't exist yet."
                )
            else:
                ctx.quality_contract += (
                    "\n\nWORKSPACE IS AN EXISTING PROJECT: Match the code style, naming "
                    "conventions, directory layout, and tech stack already present. "
                    "Do not introduce new frameworks or patterns unless explicitly required."
                )

        # 2. Project context — what the codebase looks like
        if project_snapshot:
            ctx.project_section = self._build_project_section(
                project_snapshot,
                role,
            )

        # 2b. Architecture context — structural understanding from knowledge graph
        if knowledge_graph and knowledge_graph.node_count > 0:
            # Planner and Lead get the full architecture summary
            # Others get a condensed version (they have probe tools)
            if role in ("planner", "lead"):
                arch_budget = 3000
            elif role in ("coder", "reviewer", "security"):
                arch_budget = 2000
            else:
                arch_budget = 1000
            ctx.architecture_section = knowledge_graph.to_context_section(
                max_chars=arch_budget,
            )

        # 3. Memory context — lessons from past tasks
        if memories and memories.count > 0:
            ctx.memory_section = self._budget_text(
                memories.to_context_section(),
                MAX_MEMORY_CONTEXT_CHARS,
            )

        # 4. Enrichment context — accumulated learnings for this agent
        if enrichment_text:
            ctx.enrichment_section = enrichment_text

        # 5. Pipeline context — what previous agents produced
        if previous_outputs:
            ctx.pipeline_section = self._build_pipeline_section(
                previous_outputs,
                role,
            )

        # 6. Message context — direct consults and responses between agents
        if agent_messages:
            ctx.message_section = self._build_message_section(agent_messages, role)

        # 7. Resume context — injected when task is resuming from interruption
        if resume_context and resume_context.get("is_resuming"):
            ctx.resume_section = self._build_resume_section(resume_context)

        return ctx

    def _build_project_section(
        self,
        snapshot: ProjectSnapshot,
        role: str,
    ) -> str:
        """Build project context section, tailored per role."""
        # Planner and Lead get full tree + all key files
        # Coder gets tree + dependency files
        # Reviewer gets tree only
        # Others get minimal context

        full_context = snapshot.to_context_section()

        if role in ("planner", "lead"):
            budget = MAX_PROJECT_CONTEXT_CHARS
        elif role in ("coder", "qa", "devops", "sre"):
            budget = MAX_PROJECT_CONTEXT_CHARS * 3 // 4  # 75%
        elif role in ("reviewer", "security"):
            budget = MAX_PROJECT_CONTEXT_CHARS // 2  # 50%
        else:
            budget = MAX_PROJECT_CONTEXT_CHARS // 4  # 25%

        return self._budget_text(full_context, budget)

    def _build_pipeline_section(
        self,
        outputs: dict[str, dict[str, Any]],
        current_role: str,
    ) -> str:
        """Build pipeline section from previous agent outputs.

        Agents see SUMMARIES of previous agents, not their reasoning.
        This maintains context isolation while preserving information flow.
        """
        if not outputs:
            return ""

        parts = ["--- PREVIOUS AGENT OUTPUTS ---"]

        for role, output in outputs.items():
            summary = output.get("summary", "")
            if not summary:
                continue

            # Budget each previous output
            max_per_output = MAX_PIPELINE_CONTEXT_CHARS // max(len(outputs), 1)
            if len(summary) > max_per_output:
                summary = summary[:max_per_output] + "..."

            parts.append(f"\n[{role.upper()} output]:\n{summary}")

        return "\n".join(parts)

    def _budget_text(self, text: str, max_chars: int) -> str:
        """Truncate text to budget with indicator."""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... (truncated for context budget)"

    def _build_resume_section(self, resume_context: dict[str, Any]) -> str:
        """Build resume context section for agents running after task resume."""
        parts = ["--- RESUME CONTEXT (this task was interrupted and is being resumed) ---"]

        checkpoint = resume_context.get("resumed_from_checkpoint", "")
        if checkpoint:
            parts.append(f"Resumed from: {checkpoint}")

        completed = resume_context.get("completed_agents", [])
        if completed:
            parts.append(f"Already completed agents: {', '.join(completed)}")

        summaries = resume_context.get("previous_agent_summaries", {})
        if summaries:
            parts.append("\nPrevious agent outputs (before interruption):")
            for role, summary in summaries.items():
                if summary:
                    parts.append(f"  [{role}]: {str(summary)[:150]}")

        files = resume_context.get("files_already_changed", [])
        if files:
            parts.append(f"\nFiles already modified: {', '.join(files[:20])}")

        parts.append(
            "\nIMPORTANT: Do NOT repeat work already completed by previous agents. "
            "Build upon their outputs. Check which files already exist before creating new ones."
        )

        return "\n".join(parts)

    def _build_message_section(
        self,
        messages: list[dict[str, Any]],
        current_role: str,
    ) -> str:
        """Build consultation context for the current role from message thread."""
        if not messages:
            return ""

        relevant: list[dict[str, Any]] = [
            m
            for m in messages
            if m.get("to_role") == current_role or m.get("from_role") == current_role
        ]
        if not relevant:
            return ""

        # Keep only the latest messages to bound prompt size.
        relevant = relevant[-8:]
        parts = ["--- AGENT CONSULT THREAD ---"]
        for msg in relevant:
            msg_type = msg.get("type", "message")
            from_role = msg.get("from_role", "?")
            to_role = msg.get("to_role", "?")
            status = msg.get("status", "unknown")
            content = str(msg.get("content", ""))
            if len(content) > 700:
                content = content[:700] + "..."
            parts.append(f"[{msg_type}] {from_role} -> {to_role} ({status})\n{content}")

        return self._budget_text("\n\n".join(parts), MAX_PIPELINE_CONTEXT_CHARS)
