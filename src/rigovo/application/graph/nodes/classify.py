"""Classify node — Master Agent (Distinguished Engineer) analyzes the task.

This node is the Master Agent's moment. It receives the task description
and the project snapshot (from scan_project) and produces a full staffing
plan — which agents, how many, what each one does, and in what order.

The output is stored in ``state["staffing_plan"]`` (new) and
``state["classification"]`` (backward-compatible).
"""

from __future__ import annotations

import json
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.application.master.classifier import (
    StaffingPlan,
    TaskClassifier,
)
from rigovo.domain.interfaces.llm_provider import LLMProvider

# Lightweight fallback prompt (used when no classifier is injected)
CLASSIFICATION_PROMPT = """\
You are a task classifier for a software engineering team.

Given a task description, determine:
1. task_type: one of [feature, bug, refactor, test, docs, infra, security, performance, \
investigation, new_project]
   - Use "new_project" when the task is to CREATE a new project from scratch (e.g.
     "build a Flask app", "create a React app", "write a CLI tool", "init a project")
   - Use "feature" for adding functionality to an EXISTING project
2. complexity: one of [low, medium, high, critical]
3. workspace_type: one of [new_project, existing_project]
   - "new_project" = blank workspace, build the full project structure from scratch
   - "existing_project" = workspace has established code, match existing patterns
4. reasoning: a brief explanation

Respond with ONLY valid JSON:
{
    "task_type": "...",
    "complexity": "...",
    "workspace_type": "...",
    "reasoning": "..."
}
"""


async def classify_node(
    state: TaskState,
    llm: LLMProvider,
    classifier: TaskClassifier | None = None,
) -> dict[str, Any]:
    """Run the Master Agent's analysis on the task.

    When a full ``TaskClassifier`` is injected (the normal path via
    container), it runs the SME ``analyze()`` method which produces a
    ``StaffingPlan``.  The plan is stored in state and the legacy
    ``classification`` dict is derived from it.

    Falls back to a lightweight LLM classification when no classifier
    is available (unit tests, minimal setups).
    """
    project_snapshot = state.get("project_snapshot")

    # ── Primary path: Full SME analysis ──────────────────────────────
    if classifier is not None:
        plan: StaffingPlan = await classifier.analyze(
            state["description"],
            project_snapshot=project_snapshot,
        )

        # Build legacy classification dict for backward compatibility
        classification: dict[str, Any] = {
            "task_type": str(plan.task_type.value),
            "complexity": str(plan.complexity.value),
            "workspace_type": plan.workspace_type,
            "reasoning": plan.reasoning,
        }

        # Serialize the staffing plan for state transport
        staffing_plan_dict = _serialize_staffing_plan(plan)

        return {
            "classification": classification,
            "staffing_plan": staffing_plan_dict,
            "status": "classified",
            "cost_accumulator": {
                **state.get("cost_accumulator", {}),
                "master_agent": {
                    "tokens": 0,
                    "cost": 0.0,
                },
            },
            "events": state.get("events", [])
            + [
                {
                    "type": "task_classified",
                    "task_type": classification["task_type"],
                    "complexity": classification["complexity"],
                    "workspace_type": classification["workspace_type"],
                    "reasoning": classification["reasoning"],
                    "domain_analysis": plan.domain_analysis,
                    "agent_count": len(plan.agents),
                    "agent_instances": [
                        {
                            "instance_id": a.instance_id,
                            "role": a.role,
                            "specialisation": a.specialisation,
                            "assignment": a.assignment[:200],
                        }
                        for a in plan.agents
                    ],
                    "risks": plan.risks[:5],
                    "acceptance_criteria": plan.acceptance_criteria[:5],
                }
            ],
        }

    # ── Fallback: lightweight LLM classification ──────────────────────
    response = await llm.invoke(
        messages=[
            {"role": "system", "content": CLASSIFICATION_PROMPT},
            {"role": "user", "content": state["description"]},
        ],
        temperature=0.0,
        max_tokens=256,
    )

    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        classification = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        classification = {
            "task_type": "feature",
            "complexity": "medium",
            "workspace_type": "existing_project",
            "reasoning": "Failed to parse classification, defaulting to feature/medium.",
        }

    if "workspace_type" not in classification:
        classification["workspace_type"] = _derive_workspace_type(state, classification)

    return {
        "classification": classification,
        "status": "classified",
        "cost_accumulator": {
            **state.get("cost_accumulator", {}),
            "classifier": {
                "tokens": response.usage.total_tokens,
                "cost": 0.0,
            },
        },
        "events": state.get("events", [])
        + [
            {
                "type": "task_classified",
                "task_type": classification.get("task_type"),
                "complexity": classification.get("complexity"),
                "workspace_type": classification.get("workspace_type"),
                "reasoning": classification.get("reasoning"),
            }
        ],
    }


def _derive_workspace_type(state: TaskState, classification: dict[str, Any]) -> str:
    """Derive workspace_type when the LLM didn't produce it."""
    if classification.get("task_type") == "new_project":
        return "new_project"
    snapshot = state.get("project_snapshot")
    if snapshot is not None:
        wt = getattr(snapshot, "workspace_type", "existing_project")
        if wt == "new_project":
            return "new_project"
    return "existing_project"


def _serialize_staffing_plan(plan: StaffingPlan) -> dict[str, Any]:
    """Serialize a StaffingPlan to a dict suitable for graph state."""
    return {
        "task_type": str(plan.task_type.value),
        "complexity": str(plan.complexity.value),
        "workspace_type": plan.workspace_type,
        "domain_analysis": plan.domain_analysis,
        "architecture_notes": plan.architecture_notes,
        "agents": [
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
        "risks": plan.risks,
        "acceptance_criteria": plan.acceptance_criteria,
        "reasoning": plan.reasoning,
        "execution_dag": plan.execution_dag,
        "parallel_groups": plan.parallel_groups,
    }
