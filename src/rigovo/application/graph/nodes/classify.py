"""Classify node — Master Agent classifies the task type and complexity."""

from __future__ import annotations

import json
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.application.master.classifier import TaskClassifier
from rigovo.domain.interfaces.llm_provider import LLMProvider

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
    """Classify the task using the Master Agent's LLM."""
    # If a pre-built classifier is injected (e.g. from container), use it.
    # Then merge in workspace_type from project snapshot if available.
    if classifier is not None:
        result = await classifier.classify(state["description"])
        classification: dict[str, Any] = {
            "task_type": str(result.task_type.value),
            "complexity": str(result.complexity.value),
            "reasoning": result.reasoning,
        }
        # Derive workspace_type from the project snapshot when classifier
        # doesn't produce it (backward compatibility)
        classification["workspace_type"] = _derive_workspace_type(state, classification)

        return {
            "classification": classification,
            "status": "classified",
            "cost_accumulator": {
                **state.get("cost_accumulator", {}),
                "classifier": {
                    "tokens": 0,
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

    response = await llm.invoke(
        messages=[
            {"role": "system", "content": CLASSIFICATION_PROMPT},
            {"role": "user", "content": state["description"]},
        ],
        temperature=0.0,
        max_tokens=256,
    )

    try:
        # Strip markdown code fences if LLM wraps JSON in ```json ... ```
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

    # If LLM didn't produce workspace_type, derive it from the snapshot
    if "workspace_type" not in classification:
        classification["workspace_type"] = _derive_workspace_type(state, classification)

    return {
        "classification": classification,
        "status": "classified",
        "cost_accumulator": {
            **state.get("cost_accumulator", {}),
            "classifier": {
                "tokens": response.usage.total_tokens,
                "cost": 0.0,  # Will be calculated by cost tracker
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
    """Derive workspace_type when the LLM didn't produce it.

    Uses two signals:
    1. task_type == new_project → clearly new
    2. project snapshot source file count < threshold → nearly empty workspace
    """
    if classification.get("task_type") == "new_project":
        return "new_project"

    snapshot = state.get("project_snapshot")
    if snapshot is not None:
        # ProjectSnapshot.workspace_type is set by the scanner based on file count
        wt = getattr(snapshot, "workspace_type", "existing_project")
        if wt == "new_project":
            return "new_project"

    return "existing_project"
