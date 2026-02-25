"""Classify node — Master Agent classifies the task type and complexity."""

from __future__ import annotations

import json
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.domain.interfaces.llm_provider import LLMProvider


CLASSIFICATION_PROMPT = """\
You are a task classifier for a software engineering team.

Given a task description, determine:
1. task_type: one of [feature, bug, refactor, test, docs, infra, security, performance, investigation]
2. complexity: one of [low, medium, high, critical]
3. reasoning: a brief explanation of your classification

Respond with ONLY valid JSON:
{
    "task_type": "...",
    "complexity": "...",
    "reasoning": "..."
}
"""


async def classify_node(
    state: TaskState,
    llm: LLMProvider,
) -> dict[str, Any]:
    """Classify the task using the Master Agent's LLM."""
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
            "reasoning": "Failed to parse classification, defaulting to feature/medium.",
        }

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
        "events": state.get("events", []) + [{
            "type": "task_classified",
            "task_type": classification.get("task_type"),
            "complexity": classification.get("complexity"),
            "reasoning": classification.get("reasoning"),
        }],
    }
