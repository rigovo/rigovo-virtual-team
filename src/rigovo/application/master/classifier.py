"""Master Agent — Distinguished Engineer / SME.

The Master Agent is the most senior technical mind in Rigovo. It does NOT
just classify tasks — it **understands** them the way a Distinguished
Engineer with 20+ years of experience would.

Given a task and a project snapshot, the Master Agent produces:
1. A domain analysis (what kind of engineering problem is this?)
2. A staffing plan (which roles, how many of each, what specialisations)
3. A dependency graph (who blocks whom, what can run in parallel)
4. Risk assessment (what could go wrong, where are the landmines)
5. Acceptance criteria (how do we know the work is done correctly)

The old ClassificationResult is preserved for backward compatibility
but the primary output is now ``StaffingPlan``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from rigovo.domain.entities.task import TaskComplexity, TaskType
from rigovo.domain.interfaces.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


# ── Data structures ────────────────────────────────────────────────────


@dataclass
class AgentAssignment:
    """A single agent slot in the staffing plan."""

    instance_id: str  # e.g. "backend-engineer-1", "qa-engineer-1"
    role: str  # canonical role: coder, qa, devops, security, sre, reviewer
    specialisation: str  # e.g. "backend-api", "frontend-react", "database", "infra"
    assignment: str  # specific work description for this agent
    depends_on: list[str] = field(default_factory=list)  # instance_ids this agent waits for
    tools_required: list[str] = field(default_factory=list)  # extra tools beyond role default
    verification: str = ""  # how this agent's work will be verified (must run tests, etc.)


@dataclass
class StaffingPlan:
    """Full staffing plan from the Master Agent.

    This replaces the old static TASK_PIPELINES dict with an intelligent,
    per-task team composition.
    """

    task_type: TaskType
    complexity: TaskComplexity
    workspace_type: str  # new_project | existing_project

    # The SME's domain analysis
    domain_analysis: str  # "This is a payment gateway — PCI-DSS compliance required..."
    architecture_notes: str  # "Use hexagonal architecture, separate domain from infra..."

    # Staffing
    agents: list[AgentAssignment]  # ordered by execution priority

    # Risk
    risks: list[str]
    acceptance_criteria: list[str]

    # The SME's reasoning for the team composition
    reasoning: str
    execution_mode: str = "linear"  # linear | parallel | supervised_parallel
    consultation_requirements: list[dict[str, Any]] = field(default_factory=list)
    spawn_candidates: list[dict[str, Any]] = field(default_factory=list)
    completion_contract: list[str] = field(default_factory=list)
    risk_actions: list[dict[str, Any]] = field(default_factory=list)
    required_approvals: list[dict[str, Any]] = field(default_factory=list)
    supervision_checkpoints: list[str] = field(default_factory=list)

    @property
    def instance_ids(self) -> list[str]:
        return [a.instance_id for a in self.agents]

    @property
    def execution_dag(self) -> dict[str, list[str]]:
        """Build the dependency graph from agent assignments."""
        dag: dict[str, list[str]] = {}
        for a in self.agents:
            # Filter deps to only include agents that are in this plan
            valid_deps = [d for d in a.depends_on if d in self.instance_ids]
            dag[a.instance_id] = valid_deps
        return dag

    @property
    def parallel_groups(self) -> list[list[str]]:
        """Compute which agents can run simultaneously."""
        dag = self.execution_dag
        completed: set[str] = set()
        remaining = set(self.instance_ids)
        groups: list[list[str]] = []

        while remaining:
            # Find all agents whose dependencies are satisfied
            ready = [aid for aid in remaining if all(d in completed for d in dag.get(aid, []))]
            if not ready:
                # Deadlock — break by taking first remaining
                ready = [sorted(remaining)[0]]
            groups.append(ready)
            completed.update(ready)
            remaining -= set(ready)

        return groups


@dataclass
class ClassificationResult:
    """Legacy result — kept for backward compatibility with existing code.

    New code should use StaffingPlan instead.
    """

    task_type: TaskType
    complexity: TaskComplexity
    reasoning: str


# ── Prompts ────────────────────────────────────────────────────────────

MASTER_AGENT_SYSTEM_PROMPT = """\
You are the Master Agent — a Distinguished Engineer staffing virtual engineering teams.
Given a task + project snapshot, produce a staffing plan as JSON.

ROLES: lead, planner, coder, reviewer, security, qa, devops, sre
CODER specialisations: backend-api, backend-db, frontend-react, fullstack, systems, data-pipeline
QA specialisations: unit-tests, integration-tests, e2e-tests

RULES:
- Every task: planner + coder minimum
- new_project: add lead, devops
- API work: add security
- high/critical: add lead + reviewer + qa
- Pipeline: planner → coder(s) → reviewer → security → qa → devops → sre → lead (last)
- Each agent needs specific assignment + verification step
- Dependencies must be explicit

Respond with ONLY valid JSON:
{"task_type":"feature|bug|refactor|test|docs|infra|security|performance|investigation|new_project",
"complexity":"low|medium|high|critical",
"workspace_type":"new_project|existing_project",
"execution_mode":"linear|parallel|supervised_parallel",
"domain_analysis":"2-3 sentences",
"architecture_notes":"key patterns",
"agents":[{"instance_id":"planner-1","role":"planner","specialisation":"requirements","assignment":"...","depends_on":[],"tools_required":[],"verification":"..."}],
"consultation_requirements":[{"from_role":"coder","to_role":"security","reason":"auth surface"}],
"spawn_candidates":[{"role":"coder","specialisation":"backend-api","reason":"separable API branch","bounded_assignment":"auth endpoints","estimated_cost_delta_usd":0.4,"estimated_time_delta_ms":120000}],
"completion_contract":["working code","verification passed"],
"risk_actions":[{"kind":"deploy","summary":"deploy to protected environment","policy":"approval_required","severity":"high"}],
"required_approvals":[{"kind":"budget_extension","summary":"token budget extension beyond policy band","policy":"approval_required"}],
"supervision_checkpoints":["before_first_implementation","after_first_rigour_failure","before_final_completion"],
"risks":["..."],
"acceptance_criteria":["..."],
"reasoning":"..."}
"""


# ── The Master Agent ───────────────────────────────────────────────────


class TaskClassifier:
    """
    The Master Agent — Distinguished Engineer.

    Despite the class name (kept for backward compatibility), this is now
    a full SME that produces staffing plans, not just classifications.

    Two entry points:
    - ``classify()`` — legacy, returns ClassificationResult
    - ``analyze()`` — full SME analysis, returns StaffingPlan

    The Master Agent learns from every execution via:
    - MemoryRetriever: fetches historical intelligence (gate learnings, team performance, etc.)
    - This shapes the staffing plan to avoid past pitfalls and repeat successes
    """

    def __init__(
        self,
        llm: LLMProvider,
        memory_retriever: Any = None,  # Optional MemoryRetriever for historical intelligence
    ) -> None:
        self._llm = llm
        self._memory_retriever = memory_retriever

    async def classify(
        self, description: str, project_snapshot: Any = None
    ) -> ClassificationResult:
        """Legacy classification — extracts type/complexity from full analysis.

        If a project_snapshot is available, the full SME analysis runs and
        the classification is extracted from it. Otherwise falls back to
        a lightweight classification.
        """
        if project_snapshot is not None:
            plan = await self.analyze(description, project_snapshot)
            return ClassificationResult(
                task_type=plan.task_type,
                complexity=plan.complexity,
                reasoning=plan.reasoning,
            )

        # Lightweight fallback when no snapshot available
        return await self._classify_lightweight(description)

    async def analyze(
        self,
        description: str,
        project_snapshot: Any = None,
        memories: list[Any] | None = None,
        memory_scores: list[float] | None = None,
        deterministic_hint: dict[str, Any] | None = None,
    ) -> StaffingPlan:
        """Full SME analysis — the Master Agent's primary function.

        Produces a complete staffing plan with agent assignments,
        dependency graph, risks, and acceptance criteria.

        The Master Agent uses historical intelligence from past executions
        to inform its staffing decisions.

        Args:
            description: The task to analyze.
            project_snapshot: Project file structure, language, framework info.
            memories: Optional list of Memory objects from workspace history.
            memory_scores: Optional similarity scores for each memory (0.0-1.0).
            deterministic_hint: Pre-classification from Deterministic Brain.
                The LLM can refine but NEVER downgrade this classification.
        """
        # Build context from project snapshot
        project_context = self._build_project_context(project_snapshot)

        # Build historical intelligence section (if memories available)
        historical_intelligence = ""
        if memories and self._memory_retriever:
            try:
                scores = memory_scores or [0.5] * len(memories)
                retrieved = await self._memory_retriever.retrieve_for_master(
                    description,
                    memories,
                    scores,
                )
                if retrieved.memories:
                    historical_intelligence = retrieved.to_context_section()
            except Exception as e:
                logger.warning("Failed to retrieve historical intelligence: %s", e)

        # Build deterministic hint section (inject as floor constraint)
        deterministic_section = ""
        if deterministic_hint and deterministic_hint.get("is_deterministic"):
            det_type = deterministic_hint.get("task_type", "feature")
            det_complexity = deterministic_hint.get("complexity", "medium")
            det_confidence = deterministic_hint.get("confidence", 0.0)
            deterministic_section = (
                f"\n\nDETERMINISTIC PRE-CLASSIFICATION (confidence {det_confidence:.0%}):\n"
                f"  task_type: {det_type}\n"
                f"  complexity: {det_complexity}\n"
                f"This is a FLOOR — you can upgrade (e.g., add security concerns, raise "
                f"complexity) but NEVER downgrade below this classification. If the "
                f"pre-classification says 'new_project', your staffing plan MUST include "
                f"agents suitable for a new project (planner, coder, reviewer at minimum)."
            )

        # Build user message with all context
        message_parts = [
            "TASK DESCRIPTION:",
            description,
            "",
            "PROJECT CONTEXT:",
            project_context,
        ]

        if historical_intelligence:
            message_parts.extend(["", historical_intelligence])

        if deterministic_section:
            message_parts.append(deterministic_section)

        message_parts.append(
            "\nAnalyze this task as a Distinguished Engineer. Produce the staffing plan."
        )

        user_message = "\n".join(message_parts)

        response = await self._llm.invoke(
            messages=[
                {"role": "system", "content": MASTER_AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,  # Slight creativity for team composition
            max_tokens=4096,  # Staffing plans — compact JSON, 4k is sufficient
        )

        return self._parse_staffing_plan(response.content, description)

    def _build_project_context(self, snapshot: Any) -> str:
        """Extract relevant project info from the scanner's snapshot."""
        if snapshot is None:
            return "No project snapshot available. Assume new/empty workspace."

        parts = []

        # Language and framework
        lang = getattr(snapshot, "primary_language", None)
        if lang:
            parts.append(f"Language: {lang}")
        framework = getattr(snapshot, "framework", None)
        if framework:
            parts.append(f"Framework: {framework}")

        # Workspace type
        ws_type = getattr(snapshot, "workspace_type", "existing_project")
        parts.append(f"Workspace: {ws_type}")

        # File count
        file_count = getattr(snapshot, "file_count", 0)
        if file_count:
            parts.append(f"Files: {file_count}")

        # Source structure (truncated)
        structure = getattr(snapshot, "structure_summary", None) or getattr(snapshot, "tree", None)
        if structure:
            text = str(structure)[:2000]
            parts.append(f"Structure:\n{text}")

        # Dependencies
        deps = getattr(snapshot, "dependencies", None)
        if deps:
            text = str(deps)[:1000]
            parts.append(f"Dependencies:\n{text}")

        return "\n".join(parts) if parts else "Empty project — no files detected."

    def _parse_staffing_plan(self, content: str, description: str) -> StaffingPlan:
        """Parse the Master Agent's JSON response into a StaffingPlan."""
        try:
            text = content.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            data = json.loads(text)
            return self._data_to_plan(data)

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse staffing plan: %s — %s", e, content[:500])
            return self._fallback_plan(description, str(e))

    def _data_to_plan(self, data: dict[str, Any]) -> StaffingPlan:
        """Convert parsed JSON dict to StaffingPlan dataclass."""
        # Parse task type (with new_project support)
        raw_type = data.get("task_type", "feature")
        try:
            task_type = TaskType(raw_type)
        except ValueError:
            task_type = TaskType.FEATURE

        try:
            complexity = TaskComplexity(data.get("complexity", "medium"))
        except ValueError:
            complexity = TaskComplexity.MEDIUM

        # Parse agent assignments
        agents: list[AgentAssignment] = []
        for agent_data in data.get("agents", []):
            if not isinstance(agent_data, dict):
                continue
            agents.append(
                AgentAssignment(
                    instance_id=str(agent_data.get("instance_id", f"agent-{len(agents)}")),
                    role=str(agent_data.get("role", "coder")),
                    specialisation=str(agent_data.get("specialisation", "general")),
                    assignment=str(agent_data.get("assignment", "")),
                    depends_on=list(agent_data.get("depends_on", [])),
                    tools_required=list(agent_data.get("tools_required", [])),
                    verification=str(agent_data.get("verification", "")),
                )
            )

        # Ensure at least a planner and coder exist
        roles_present = {a.role for a in agents}
        if "planner" not in roles_present:
            agents.insert(
                0,
                AgentAssignment(
                    instance_id="planner-1",
                    role="planner",
                    specialisation="requirements",
                    assignment="Analyze requirements and create technical plan",
                    depends_on=[],
                    verification="Plan is complete with file paths and steps",
                ),
            )
        if "coder" not in roles_present:
            agents.append(
                AgentAssignment(
                    instance_id="coder-1",
                    role="coder",
                    specialisation="fullstack",
                    assignment="Implement the planned changes",
                    depends_on=["planner-1"],
                    verification="Code compiles and tests pass",
                )
            )

        return StaffingPlan(
            task_type=task_type,
            complexity=complexity,
            workspace_type=str(data.get("workspace_type", "existing_project")),
            domain_analysis=str(data.get("domain_analysis", "")),
            architecture_notes=str(data.get("architecture_notes", "")),
            agents=agents,
            execution_mode=str(data.get("execution_mode", "linear") or "linear"),
            consultation_requirements=[
                item for item in data.get("consultation_requirements", []) if isinstance(item, dict)
            ],
            spawn_candidates=[
                item for item in data.get("spawn_candidates", []) if isinstance(item, dict)
            ],
            completion_contract=[
                str(item) for item in data.get("completion_contract", []) if str(item).strip()
            ],
            risk_actions=[item for item in data.get("risk_actions", []) if isinstance(item, dict)],
            required_approvals=[
                item for item in data.get("required_approvals", []) if isinstance(item, dict)
            ],
            supervision_checkpoints=[
                str(item)
                for item in data.get("supervision_checkpoints", [])
                if str(item).strip()
            ],
            risks=list(data.get("risks", [])),
            acceptance_criteria=list(data.get("acceptance_criteria", [])),
            reasoning=str(data.get("reasoning", "")),
        )

    def _fallback_plan(self, description: str, error: str) -> StaffingPlan:
        """Safe fallback when SME analysis fails to parse."""
        logger.warning("Using fallback staffing plan due to: %s", error)
        return StaffingPlan(
            task_type=TaskType.NEW_PROJECT
            if "from scratch" in description.lower() or "new project" in description.lower()
            else TaskType.FEATURE,
            complexity=TaskComplexity.MEDIUM,
            workspace_type="new_project"
            if "from scratch" in description.lower() or "new project" in description.lower()
            else "existing_project",
            domain_analysis=f"Analysis failed ({error}), using safe defaults.",
            architecture_notes="Follow existing project patterns.",
            agents=[
                AgentAssignment(
                    instance_id="planner-1",
                    role="planner",
                    specialisation="requirements",
                    assignment="Analyze the task and create a technical implementation plan.",
                    depends_on=[],
                    verification="Plan includes specific file paths and ordered steps.",
                ),
                AgentAssignment(
                    instance_id="coder-1",
                    role="coder",
                    specialisation="fullstack",
                    assignment="Implement all changes described in the plan.",
                    depends_on=["planner-1"],
                    tools_required=["run_command"],
                    verification="Code compiles, linter passes, relevant tests pass.",
                ),
                AgentAssignment(
                    instance_id="reviewer-1",
                    role="reviewer",
                    specialisation="code-review",
                    assignment="Review all code changes for correctness and patterns.",
                    depends_on=["coder-1"],
                    verification="Review verdict is APPROVED or issues are actionable.",
                ),
            ],
            execution_mode="linear",
            consultation_requirements=[],
            spawn_candidates=[],
            completion_contract=[
                "Implementation satisfies requested outcome",
                "Verification commands pass",
            ],
            risk_actions=[],
            required_approvals=[],
            supervision_checkpoints=[
                "before_first_implementation",
                "after_first_rigour_failure",
                "before_final_completion",
            ],
            risks=["Fallback plan — Master Agent analysis failed, may miss domain-specific needs."],
            acceptance_criteria=[
                "All files compile",
                "No lint errors",
                "Existing tests still pass",
            ],
            reasoning=f"Fallback plan due to parse failure: {error}",
        )

    async def _classify_lightweight(self, description: str) -> ClassificationResult:
        """Lightweight classification when no project snapshot is available."""
        response = await self._llm.invoke(
            messages=[
                {"role": "system", "content": _LIGHTWEIGHT_CLASSIFIER_PROMPT},
                {"role": "user", "content": f"Classify this task:\n\n{description}"},
            ],
            temperature=0.0,
            max_tokens=256,
        )
        return self._parse_classification(response.content)

    def _parse_classification(self, content: str) -> ClassificationResult:
        """Parse lightweight classification JSON."""
        try:
            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            data = json.loads(text)
            return ClassificationResult(
                task_type=TaskType(data["task_type"]),
                complexity=TaskComplexity(data["complexity"]),
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Lightweight classification failed: %s", e)
            return ClassificationResult(
                task_type=TaskType.FEATURE,
                complexity=TaskComplexity.MEDIUM,
                reasoning=f"Parse failed, using defaults: {e}",
            )


_LIGHTWEIGHT_CLASSIFIER_PROMPT = """\
You are a task classifier. Given a task description, respond with ONLY JSON:
{"task_type": "feature|bug|refactor|test|docs|infra|security|performance|investigation|new_project",
 "complexity": "low|medium|high|critical",
 "reasoning": "one sentence"}
"""
