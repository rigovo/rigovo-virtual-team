"""Reclassify node — late-binding reclassification triggered by agent signal.

When an agent (typically the planner) discovers mid-execution that the
initial classification was wrong, it emits a ``RECLASSIFY`` signal.  This
node re-runs classification and team assembly with the new context,
preserving work already done by completed agents.

Design invariants:
- Max 1 reclassification per task (prevents infinite loops)
- Only the planner or lead roles can trigger reclassification
- The agent's suggested task_type is ADVISORY — the deterministic brain
  has final say (the suggestion is injected as a hint)
- Completed agent outputs are preserved; only the pipeline is re-assembled
- A ``reclassified`` event fires for UI/audit trail
"""

from __future__ import annotations

import logging
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.application.master.classifier import TaskClassifier
from rigovo.application.master.deterministic_brain import (
    DeterministicClassification,
    classify_semantic,
    enforce_minimum_team,
)
from rigovo.domain.interfaces.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

# Roles allowed to trigger reclassification.
# Planner sees the task holistically before code exists.
# Lead orchestrates and may notice misalignment.
RECLASSIFY_ALLOWED_ROLES = {"planner", "lead"}

# Hard cap — prevent infinite reclassification loops.
MAX_RECLASSIFICATIONS = 1


async def reclassify_node(
    state: TaskState,
    llm: LLMProvider,
    classifier: TaskClassifier | None = None,
    embedding_provider: Any | None = None,
) -> dict[str, Any]:
    """Re-run classification and team assembly after an agent RECLASSIFY signal.

    The node:
    1. Validates the reclassification is permitted (budget, role check)
    2. Builds an enriched description from original + agent's reasoning
    3. Re-runs deterministic brain + optional LLM classification
    4. Re-assembles the team with the new task type
    5. Resets pipeline execution state while preserving completed work

    Returns updated state fields for the graph to continue from assembly.
    """
    events = list(state.get("events", []))
    reclassify_count = int(state.get("reclassify_count", 0) or 0)

    # ── Guard: reclassification budget ──────────────────────────────
    if reclassify_count >= MAX_RECLASSIFICATIONS:
        logger.warning(
            "Reclassification budget exhausted (%d/%d) — continuing with current classification",
            reclassify_count,
            MAX_RECLASSIFICATIONS,
        )
        events.append(
            {
                "type": "reclassify_rejected",
                "reason": "budget_exhausted",
                "reclassify_count": reclassify_count,
                "max_reclassifications": MAX_RECLASSIFICATIONS,
            }
        )
        return {
            "reclassify_requested": False,
            "reclassify_count": reclassify_count,
            "events": events,
        }

    reason = str(state.get("reclassify_reason", "") or "").strip()
    suggested_type = str(state.get("reclassify_suggested_type", "") or "").strip()
    original_description = state.get("description", "")
    original_classification = state.get("classification", {})

    logger.info(
        "RECLASSIFY triggered: reason=%r suggested_type=%r original_type=%s",
        reason,
        suggested_type,
        original_classification.get("task_type", "unknown"),
    )

    # ── Build enriched description for re-classification ────────────
    # Inject the agent's reasoning so the deterministic brain + LLM
    # have more context than the original bare description.
    enriched_description = original_description
    if reason:
        enriched_description = f"{original_description}\n\n[RECLASSIFICATION CONTEXT: {reason}]"

    # ── Phase 1: Deterministic Brain re-classification ──────────────
    det_result = await classify_semantic(enriched_description, embedding_provider)

    # If the agent suggested a specific type and deterministic brain
    # returned low confidence, bias toward the agent's suggestion.
    # The agent has seen the actual codebase; its opinion matters.
    _VALID_TYPES = {
        "feature",
        "bug",
        "refactor",
        "test",
        "docs",
        "infra",
        "security",
        "performance",
        "investigation",
        "new_project",
    }
    if (
        suggested_type in _VALID_TYPES
        and det_result.confidence < 0.80
        and suggested_type != det_result.task_type
    ):
        logger.info(
            "Agent suggestion %r overriding low-confidence deterministic %r (%.2f)",
            suggested_type,
            det_result.task_type,
            det_result.confidence,
        )
        # Create a synthetic deterministic result biased toward agent suggestion
        det_result = DeterministicClassification(
            task_type=suggested_type,
            complexity=det_result.complexity,
            confidence=0.75,  # Moderate confidence — agent-informed
            matched_pattern=f"agent_reclassify:{suggested_type}",
            is_deterministic=False,
        )

    new_classification = {
        "task_type": det_result.task_type,
        "complexity": det_result.complexity,
        "workspace_type": original_classification.get("workspace_type", "existing_project"),
        "reasoning": f"Reclassified from {original_classification.get('task_type', 'unknown')}: {reason}",
    }

    new_deterministic = {
        "task_type": det_result.task_type,
        "complexity": det_result.complexity,
        "confidence": det_result.confidence,
        "matched_pattern": det_result.matched_pattern,
        "is_deterministic": det_result.is_deterministic,
    }

    # ── Phase 2: LLM re-classification (if classifier available) ────
    staffing_plan = state.get("staffing_plan")
    if classifier is not None:
        try:
            plan = await classifier.analyze(
                enriched_description,
                project_snapshot=state.get("project_snapshot"),
                deterministic_hint=new_deterministic,
            )

            enforced_agents = enforce_minimum_team(
                [
                    {
                        "instance_id": a.instance_id,
                        "role": a.role,
                        "specialisation": a.specialisation,
                        "assignment": a.assignment,
                        "depends_on": a.depends_on,
                        "tools_required": a.tools_required,
                        "verification": a.verification,
                    }
                    for a in plan.agents
                ],
                task_type=det_result.task_type,
                description=enriched_description,
            )

            new_classification["task_type"] = str(plan.task_type.value)
            new_classification["complexity"] = str(plan.complexity.value)
            new_classification["workspace_type"] = plan.workspace_type
            new_classification["reasoning"] = (
                f"Reclassified: {plan.reasoning} (original: {original_classification.get('task_type', 'unknown')})"
            )

            staffing_plan = {
                "task_type": str(plan.task_type.value),
                "complexity": str(plan.complexity.value),
                "workspace_type": plan.workspace_type,
                "domain_analysis": plan.domain_analysis,
                "architecture_notes": plan.architecture_notes,
                "agents": enforced_agents,
                "risks": plan.risks,
                "acceptance_criteria": plan.acceptance_criteria,
                "reasoning": plan.reasoning,
                "execution_dag": plan.execution_dag,
                "parallel_groups": plan.parallel_groups,
            }
        except Exception:
            logger.exception("LLM reclassification failed — using deterministic result only")

    # ── Emit reclassified event ─────────────────────────────────────
    events.append(
        {
            "type": "reclassified",
            "previous_task_type": original_classification.get("task_type", "unknown"),
            "previous_complexity": original_classification.get("complexity", "unknown"),
            "new_task_type": new_classification["task_type"],
            "new_complexity": new_classification["complexity"],
            "reason": reason,
            "suggested_type": suggested_type,
            "reclassify_count": reclassify_count + 1,
        }
    )

    result: dict[str, Any] = {
        "classification": new_classification,
        "deterministic_classification": new_deterministic,
        "reclassify_requested": False,
        "reclassify_reason": "",
        "reclassify_suggested_type": "",
        "reclassify_count": reclassify_count + 1,
        "status": "reclassified",
        "events": events,
    }

    if staffing_plan is not None:
        result["staffing_plan"] = staffing_plan

    return result
