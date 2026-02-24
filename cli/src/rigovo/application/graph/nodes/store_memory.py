"""Store memory node — extracts lessons from the completed task."""

from __future__ import annotations

import json
from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.domain.interfaces.llm_provider import LLMProvider


MEMORY_EXTRACTION_PROMPT = """\
You are analyzing a completed engineering task to extract reusable lessons.

Given the task description and agent outputs, identify knowledge worth remembering.

Categories:
- task_outcome: What happened and what worked
- pattern: Recurring patterns that should be applied to future tasks
- error_fix: How a specific error was resolved
- convention: Code or project conventions discovered
- domain_knowledge: Domain-specific facts or rules

Extract 1-5 memories. Respond with ONLY valid JSON:
[
    {"content": "...", "type": "pattern|error_fix|convention|domain_knowledge|task_outcome"}
]

If nothing worth remembering, respond with: []
"""


async def store_memory_node(
    state: TaskState,
    llm: LLMProvider,
) -> dict[str, Any]:
    """Extract and store memories from the completed task."""
    agent_outputs = state.get("agent_outputs", {})

    # Build context from all agent outputs
    context_parts = [f"Task: {state['description']}"]
    for role, output in agent_outputs.items():
        summary = output.get("summary", "")
        # Truncate long outputs for memory extraction
        if len(summary) > 1000:
            summary = summary[:1000] + "..."
        context_parts.append(f"[{role.upper()}]: {summary}")

    context = "\n\n".join(context_parts)

    response = await llm.invoke(
        messages=[
            {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
            {"role": "user", "content": context},
        ],
        temperature=0.0,
        max_tokens=1024,
    )

    try:
        memories = json.loads(response.content)
    except json.JSONDecodeError:
        memories = []

    memory_texts = [m.get("content", "") for m in memories if m.get("content")]

    return {
        "memories_to_store": memory_texts,
        "status": "memories_extracted",
        "events": state.get("events", []) + [{
            "type": "memories_stored",
            "count": len(memory_texts),
        }],
    }
