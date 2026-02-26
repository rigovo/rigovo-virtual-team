"""Store memory node — extracts lessons from the completed task."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from rigovo.application.graph.state import TaskState
from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.interfaces.repositories import MemoryRepository


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
    memory_repo: MemoryRepository | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    """Extract and store memories from the completed task."""
    events = list(state.get("events", []))
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

    parsed_memories: list[dict[str, str]] = []
    if isinstance(memories, list):
        for item in memories:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            parsed_memories.append(
                {
                    "content": content,
                    "type": str(item.get("type", "pattern")),
                }
            )

    memory_texts = [m["content"] for m in parsed_memories]
    deduped_memories = parsed_memories
    dedup_skipped = 0
    persisted_count = 0
    workspace_id = _parse_uuid(state.get("workspace_id"))
    source_task_id = _parse_uuid(state.get("task_id"))
    source_project_id = _derive_project_id(state.get("project_root"))
    learning_metrics = {
        "retrieved_memory_count": 0,
        "reinforced_memory_count": 0,
        "reinforcement_applied": False,
        "retrieval_success_rate": 0.0,
    }

    # Reinforce retrieved memories only on successful-quality tasks.
    retrieval_log = state.get("memory_retrieval_log", {}) or {}
    reinforce = _should_reinforce_retrieved_memories(state)
    if memory_repo and workspace_id and isinstance(retrieval_log, dict):
        retrieved_ids: set[str] = set()
        for entries in retrieval_log.values():
            if not isinstance(entries, list):
                continue
            for item in entries:
                if isinstance(item, dict):
                    memory_id = str(item.get("memory_id", "")).strip()
                    if memory_id:
                        retrieved_ids.add(memory_id)

        retrieved_count = len(retrieved_ids)
        reinforced_count = 0
        if retrieved_count > 0 and reinforce:
            existing = await memory_repo.list_by_workspace(workspace_id, limit=5000)
            by_id = {str(m.id): m for m in existing}
            for memory_id in sorted(retrieved_ids):
                memory = by_id.get(memory_id)
                if memory is None:
                    continue
                memory.record_usage(project_id=source_project_id)
                await memory_repo.save(memory)
                reinforced_count += 1

        learning_metrics = {
            "retrieved_memory_count": retrieved_count,
            "reinforced_memory_count": reinforced_count,
            "reinforcement_applied": bool(reinforce and retrieved_count > 0),
            "retrieval_success_rate": (
                round(reinforced_count / retrieved_count, 3) if retrieved_count else 0.0
            ),
        }
        if retrieved_count:
            events.append(
                {
                    "type": "memory_feedback_recorded",
                    **learning_metrics,
                }
            )

    if memory_repo and embedding_provider and workspace_id and parsed_memories:
        existing = await memory_repo.list_by_workspace(workspace_id, limit=500)
        existing_norm = {_normalize_memory_text(m.content) for m in existing}
        deduped_memories = []
        for item in parsed_memories:
            norm = _normalize_memory_text(item["content"])
            if not norm or norm in existing_norm:
                dedup_skipped += 1
                continue
            deduped_memories.append(item)
            existing_norm.add(norm)

        memory_texts = [m["content"] for m in deduped_memories]
        embeddings = await embedding_provider.embed_batch(memory_texts) if memory_texts else []
        for mem_data, embedding in zip(deduped_memories, embeddings):
            memory = Memory(
                workspace_id=workspace_id,
                source_project_id=source_project_id,
                source_task_id=source_task_id,
                content=mem_data["content"],
                memory_type=_coerce_memory_type(mem_data["type"]),
                embedding=embedding,
            )
            await memory_repo.save(memory)
            persisted_count += 1

    events.append(
        {
            "type": "memories_stored",
            "count": len(memory_texts),
            "persisted_count": persisted_count,
            "dedup_skipped": dedup_skipped,
        }
    )

    return {
        "memories_to_store": memory_texts,
        "memory_learning_metrics": learning_metrics,
        "status": "memories_extracted",
        "events": events,
    }


def _parse_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _coerce_memory_type(raw: str) -> MemoryType:
    try:
        return MemoryType(raw)
    except ValueError:
        return MemoryType.PATTERN


def _normalize_memory_text(text: str) -> str:
    return " ".join(text.lower().split())


def _derive_project_id(project_root: Any) -> UUID | None:
    root = str(project_root or "").strip()
    if not root:
        return None
    return uuid5(NAMESPACE_URL, root)


def _should_reinforce_retrieved_memories(state: TaskState) -> bool:
    """Only reinforce retrieved memories when quality outcomes are acceptable."""
    gate_history = state.get("gate_history", []) or []
    if isinstance(gate_history, list) and gate_history:
        return all(bool(entry.get("passed", False)) for entry in gate_history if isinstance(entry, dict))
    gate_results = state.get("gate_results", {}) or {}
    if isinstance(gate_results, dict) and gate_results:
        return bool(gate_results.get("passed", False) or gate_results.get("status") == "skipped")
    # If no gate data exists, default to conservative no-reinforcement.
    return False
