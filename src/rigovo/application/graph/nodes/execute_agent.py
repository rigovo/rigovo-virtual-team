"""Execute agent node — runs the current agent with context engineering.

Each agent execution follows the INTELLIGENT AGENT pattern:
1. PERCEIVE — project snapshot injected (scanned at task start)
2. REMEMBER — relevant memories from past tasks injected
3. REASON — system prompt + enrichment + quality contract
4. ACT — LLM generates response with tool calls (agentic loop)
5. VERIFY — Rigour gates check output (separate node)

Supports an **agentic tool loop**: the LLM calls tools (read_file,
write_file, run_command, etc.), we execute them and feed results back,
and the LLM continues until it has no more tool calls. This is how
agents actually write code, not just describe changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from rigovo.application.context.memory_retriever import MemoryRetriever, ROLE_MEMORY_PREFERENCES
from rigovo.application.context.context_builder import ContextBuilder
from rigovo.application.graph.state import TaskState, AgentOutput
from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider
from rigovo.domain.interfaces.llm_provider import LLMProvider, LLMResponse, LLMUsage
from rigovo.domain.interfaces.repositories import MemoryRepository
from rigovo.domain.services.cost_calculator import CostCalculator
from rigovo.domains.engineering.tools import TOOL_DEFINITIONS, get_engineering_tools
from rigovo.infrastructure.filesystem.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

# --- Named constants for agent execution defaults ---
DEFAULT_LLM_MODEL = "claude-sonnet-4-6"
DEFAULT_IDLE_TIMEOUT = 120     # No tokens for 2 min → something's wrong
DEFAULT_BATCH_TIMEOUT = 900    # 15 min hard ceiling for batch (non-streaming)
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 8192
MS_PER_SECOND = 1000
STREAM_CHUNK_MIN_SIZE = 4  # Minimum chars before emitting stream event
MAX_TOOL_ROUNDS = 25  # Safety limit to prevent infinite tool loops

# Per-role max_tokens — sized to what each role actually produces.
# Coder/QA need room for full file contents. Planner/reviewer are lighter.
ROLE_MAX_TOKENS: dict[str, int] = {
    "lead": 4096,
    "planner": 4096,
    "coder": 16384,      # Needs room for multi-file output
    "reviewer": 4096,
    "security": 4096,
    "qa": 8192,           # Test generation can be verbose
    "devops": 4096,
    "sre": 4096,
    "docs": 4096,
}

CONSULT_MAX_QUESTION_CHARS = 1200
CONSULT_MAX_RESPONSE_CHARS = 1200
SUBAGENT_MAX_SUBTASKS_PER_STEP = 3
SUBAGENT_MAX_ROUNDS = 10

# Role-to-role consultation policy. Advisory-only, never full step completion.
CONSULT_ALLOWED_TARGETS: dict[str, set[str]] = {
    "planner": {"lead", "security", "devops"},
    "coder": {"reviewer", "security", "qa"},
    "reviewer": {"planner", "coder", "security", "qa", "devops", "sre", "lead"},
    "security": {"coder", "reviewer", "devops", "sre", "lead"},
    "qa": {"coder", "reviewer"},
    "devops": {"security", "sre", "reviewer", "lead"},
    "sre": {"devops", "security", "reviewer", "lead"},
    "lead": {"planner", "coder", "reviewer", "security", "qa", "devops", "sre"},
}


def _resolve_consult_policy(state: TaskState | None) -> tuple[bool, int, int, dict[str, set[str]]]:
    """Resolve consultation policy from state with safe defaults."""
    enabled = True
    max_question_chars = CONSULT_MAX_QUESTION_CHARS
    max_response_chars = CONSULT_MAX_RESPONSE_CHARS
    allowed_targets = {k: set(v) for k, v in CONSULT_ALLOWED_TARGETS.items()}

    if not state:
        return enabled, max_question_chars, max_response_chars, allowed_targets

    raw_policy = state.get("consultation_policy", {}) or {}
    if isinstance(raw_policy, dict):
        enabled = bool(raw_policy.get("enabled", enabled))
        q_chars = raw_policy.get("max_question_chars", max_question_chars)
        r_chars = raw_policy.get("max_response_chars", max_response_chars)
        if isinstance(q_chars, int) and q_chars > 100:
            max_question_chars = q_chars
        if isinstance(r_chars, int) and r_chars > 100:
            max_response_chars = r_chars

        raw_targets = raw_policy.get("allowed_targets", {})
        if isinstance(raw_targets, dict):
            parsed: dict[str, set[str]] = {}
            for src_role, targets in raw_targets.items():
                if isinstance(src_role, str) and isinstance(targets, list):
                    parsed[src_role] = {str(t) for t in targets if str(t).strip()}
            if parsed:
                allowed_targets = parsed

    return enabled, max_question_chars, max_response_chars, allowed_targets


def _resolve_subagent_policy(state: TaskState | None) -> tuple[bool, int, int]:
    """Resolve sub-agent spawn policy from state with safe defaults."""
    enabled = True
    max_subtasks = SUBAGENT_MAX_SUBTASKS_PER_STEP
    max_rounds = SUBAGENT_MAX_ROUNDS
    if not state:
        return enabled, max_subtasks, max_rounds
    raw_policy = state.get("subagent_policy", {}) or {}
    if not isinstance(raw_policy, dict):
        return enabled, max_subtasks, max_rounds

    enabled = bool(raw_policy.get("enabled", enabled))
    raw_max_subtasks = raw_policy.get("max_subtasks_per_agent_step", max_subtasks)
    if isinstance(raw_max_subtasks, int) and raw_max_subtasks >= 0:
        max_subtasks = raw_max_subtasks
    raw_max_rounds = raw_policy.get("max_subtask_rounds", max_rounds)
    if isinstance(raw_max_rounds, int) and raw_max_rounds > 0:
        max_rounds = raw_max_rounds
    return enabled, max_subtasks, max_rounds


class BudgetExceededError(Exception):
    """Raised when the task's cost budget has been exceeded."""

    def __init__(self, spent: float, limit: float) -> None:
        self.spent = spent
        self.limit = limit
        super().__init__(f"Budget exceeded: ${spent:.4f} spent (limit ${limit:.2f})")


class AgentTimeoutError(Exception):
    """Raised when an agent exceeds its timeout."""

    def __init__(self, role: str, timeout: int) -> None:
        self.role = role
        self.timeout = timeout
        super().__init__(f"Agent '{role}' timed out after {timeout}s")


def _schema_type_ok(expected: str, value: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True


def _validate_contract(
    schema: dict[str, Any],
    payload: Any,
    path: str = "$",
) -> list[str]:
    """Minimal JSON-schema-like validation for input/output contracts."""
    if not isinstance(schema, dict) or not schema:
        return []

    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _schema_type_ok(expected_type, payload):
        return [f"{path}: expected type '{expected_type}'"]

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and payload not in enum_values:
        errors.append(f"{path}: value '{payload}' not in enum {enum_values}")

    if isinstance(payload, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in payload:
                    errors.append(f"{path}.{key}: required field missing")

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in payload and isinstance(child_schema, dict):
                    errors.extend(
                        _validate_contract(child_schema, payload[key], f"{path}.{key}")
                    )

    if isinstance(payload, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(payload):
                errors.extend(_validate_contract(item_schema, item, f"{path}[{idx}]"))

    return errors


def _contract_failure_result(
    state: TaskState,
    current_role: str,
    stage: str,
    violations: list[str],
) -> dict[str, Any]:
    events = list(state.get("events", []))
    events.append(
        {
            "type": "contract_failed",
            "role": current_role,
            "stage": stage,
            "violations": violations[:10],
        }
    )
    return {
        "status": f"contract_failed_{current_role}",
        "error": f"{stage} contract failed for '{current_role}'",
        "contract_stage": stage,
        "contract_violations": violations,
        "events": events,
    }


def _build_agent_messages(
    state: TaskState,
    system_prompt: str,
    agent_config: dict[str, Any],
    current_role: str,
    memory_section_text: str = "",
) -> list[dict[str, Any]]:
    """Build the message list for an agent execution."""
    # Context engineering: assemble rich per-agent context
    context_builder = ContextBuilder()
    agent_context = context_builder.build(
        role=current_role,
        project_snapshot=state.get("project_snapshot"),
        enrichment_text=agent_config.get("enrichment_context", ""),
        previous_outputs=state.get("agent_outputs"),
        agent_messages=state.get("agent_messages"),
    )
    if memory_section_text:
        agent_context.memory_section = memory_section_text
    full_context = agent_context.to_full_context()
    if full_context:
        system_prompt += f"\n\n{full_context}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Task: {state['description']}"},
    ]

    # Add fix packet if retrying
    fix_packets = state.get("fix_packets", [])
    if fix_packets:
        messages.append({
            "role": "user",
            "content": f"[FIX REQUIRED]: {fix_packets[-1]}",
        })

    return messages


def _parse_state_uuid(value: Any) -> UUID | None:
    """Parse UUID values from state fields safely."""
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _resolve_memory_context_for_role(
    state: TaskState,
    current_role: str,
    memory_repo: MemoryRepository | None,
    embedding_provider: EmbeddingProvider | None,
    memory_retriever: MemoryRetriever | None,
) -> tuple[str, dict[str, str], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Retrieve, rank, and render relevant memory context for one role."""
    existing = state.get("memory_context_by_role", {}) or {}
    memory_context_by_role: dict[str, str] = {}
    if isinstance(existing, dict):
        memory_context_by_role = {str(role): str(text) for role, text in existing.items()}
    existing_log = state.get("memory_retrieval_log", {}) or {}
    memory_retrieval_log: dict[str, list[dict[str, Any]]] = {}
    if isinstance(existing_log, dict):
        for role, entries in existing_log.items():
            if isinstance(entries, list):
                memory_retrieval_log[str(role)] = [e for e in entries if isinstance(e, dict)]
    if current_role in memory_context_by_role:
        return memory_context_by_role[current_role], memory_context_by_role, memory_retrieval_log, []

    if not memory_repo or not embedding_provider:
        return "", memory_context_by_role, memory_retrieval_log, []

    workspace_id = _parse_state_uuid(state.get("workspace_id"))
    if workspace_id is None:
        return "", memory_context_by_role, memory_retrieval_log, []

    task_description = str(state.get("description", "")).strip()
    if not task_description:
        return "", memory_context_by_role, memory_retrieval_log, []

    retriever = memory_retriever or MemoryRetriever()
    events: list[dict[str, Any]] = []
    try:
        query_embedding = await embedding_provider.embed(task_description)
        preferred_types = ROLE_MEMORY_PREFERENCES.get(current_role) or None
        memories = await memory_repo.search(
            workspace_id=workspace_id,
            query_embedding=query_embedding,
            limit=24,
            memory_types=preferred_types,
        )
        similarity_scores = [
            _cosine_similarity(query_embedding, m.embedding or [])
            for m in memories
        ]
        retrieved = await retriever.retrieve(
            task_description=task_description,
            role=current_role,
            memories=memories,
            similarity_scores=similarity_scores,
        )
        memory_section_text = retrieved.to_context_section()
        memory_context_by_role[current_role] = memory_section_text
        memory_retrieval_log[current_role] = [
            {
                "memory_id": str(scored.memory.id),
                "score": round(float(scored.score), 6),
                "memory_type": scored.memory.memory_type.value,
            }
            for scored in retrieved.memories
        ]

        avg_score = (
            sum(sm.score for sm in retrieved.memories) / max(len(retrieved.memories), 1)
            if retrieved.memories
            else 0.0
        )
        top_score = max((sm.score for sm in retrieved.memories), default=0.0)

        events.append(
            {
                "type": "memories_retrieved",
                "role": current_role,
                "count": retrieved.count,
                "avg_score": round(avg_score, 3),
                "top_score": round(top_score, 3),
            }
        )
        return memory_section_text, memory_context_by_role, memory_retrieval_log, events
    except Exception as exc:
        logger.warning("Memory retrieval failed for role '%s': %s", current_role, exc)
        events.append(
            {
                "type": "memory_retrieval_failed",
                "role": current_role,
                "error": str(exc),
            }
        )
        memory_context_by_role[current_role] = ""
        return "", memory_context_by_role, memory_retrieval_log, events


def _check_budget_guards(state: TaskState, current_role: str) -> dict[str, Any] | None:
    """Check budget and token limits. Logs warnings but does NOT hard-stop.

    Returns error state dict if token limit exceeded, None otherwise.
    Cost overruns are logged as warnings — user should be informed, not blocked.
    """
    accumulated_cost = sum(
        v.get("cost", 0) for v in state.get("cost_accumulator", {}).values()
    )
    budget_limit = state.get("budget_max_cost_per_task", 0)
    if budget_limit > 0 and accumulated_cost >= budget_limit:
        logger.warning(
            "Budget warning: $%.4f spent (soft limit $%.2f) — continuing task. "
            "Adjust budget.max_cost_per_task in rigovo.yml to change the limit.",
            accumulated_cost, budget_limit,
        )

    accumulated_tokens = sum(
        v.get("tokens", 0) for v in state.get("cost_accumulator", {}).values()
    )
    token_limit = state.get("budget_max_tokens_per_task", 0)
    if token_limit > 0 and accumulated_tokens >= token_limit:
        return {
            "status": "budget_exceeded_tokens",
            "error": (
                f"Token limit exceeded: {accumulated_tokens:,} tokens "
                f"(limit {token_limit:,})"
            ),
            "events": state.get("events", []) + [{
                "type": "budget_exceeded",
                "role": current_role,
                "tokens_used": accumulated_tokens,
                "token_limit": token_limit,
            }],
        }
    return None


def _resolve_tool_definitions(agent_config: dict[str, Any], current_role: str) -> list[dict[str, Any]]:
    """Resolve tool names in agent_config to full tool definitions for the LLM."""
    role_defs = get_engineering_tools(current_role)
    configured = agent_config.get("tools")
    if configured is None:
        return role_defs
    if not isinstance(configured, list) or not configured:
        return []

    by_name = {tool.get("name", ""): tool for tool in role_defs if tool.get("name")}
    # Allow explicitly-configured ecosystem tool when policy enables it,
    # even if not part of legacy role defaults.
    if "invoke_integration" in configured and "invoke_integration" in TOOL_DEFINITIONS:
        by_name.setdefault("invoke_integration", TOOL_DEFINITIONS["invoke_integration"])

    resolved: list[dict[str, Any]] = []
    for name in configured:
        tool_def = by_name.get(str(name))
        if tool_def:
            resolved.append(tool_def)
    return resolved


def _derive_project_id(project_root: Any) -> UUID | None:
    root = str(project_root or "").strip()
    if not root:
        return None
    return uuid5(NAMESPACE_URL, root)


def _new_message_id(agent_messages: list[dict[str, Any]]) -> str:
    """Generate a stable message id for inter-agent consult records."""
    return f"msg-{int(time.time() * 1000)}-{len(agent_messages) + 1}"


def _handle_consult_agent(
    state: TaskState,
    from_role: str,
    tool_input: dict[str, Any],
    agent_messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> str:
    """
    Handle an inter-agent consultation request.

    The consultation is asynchronous by design:
    - If the target role already has output, return it immediately.
    - Otherwise enqueue a pending request that the target role will see
      in its context and auto-fulfill when it completes.
    """
    enabled, max_question_chars, max_response_chars, policy_targets = _resolve_consult_policy(state)
    if not enabled:
        return json.dumps({"status": "error", "error": "Consultation is disabled by policy"})

    team_agents = state.get("team_config", {}).get("agents", {})
    to_role = str(tool_input.get("to_role", "")).strip()
    question = str(tool_input.get("question", "")).strip()

    if not to_role:
        return json.dumps({"status": "error", "error": "Missing required field: to_role"})
    if to_role not in team_agents:
        return json.dumps({"status": "error", "error": f"Unknown role: {to_role}"})
    if not question:
        return json.dumps({"status": "error", "error": "Missing required field: question"})
    allowed_targets = policy_targets.get(from_role, set())
    if to_role not in allowed_targets:
        return json.dumps(
            {
                "status": "error",
                "error": (
                    f"Consultation from '{from_role}' to '{to_role}' is not allowed by policy"
                ),
            }
        )
    if len(question) > max_question_chars:
        question = question[:max_question_chars] + "..."

    request_id = _new_message_id(agent_messages)
    request = {
        "id": request_id,
        "type": "consult_request",
        "from_role": from_role,
        "to_role": to_role,
        "content": question,
        "status": "pending",
        "created_at": time.time(),
    }
    agent_messages.append(request)
    events.append({
        "type": "agent_consult_requested",
        "from_role": from_role,
        "to_role": to_role,
        "message_id": request_id,
    })

    existing_output = state.get("agent_outputs", {}).get(to_role, {})
    existing_summary = existing_output.get("summary", "")
    if existing_summary:
        answer = existing_summary[:max_response_chars]
        request["status"] = "answered"

        response_id = _new_message_id(agent_messages)
        agent_messages.append({
            "id": response_id,
            "type": "consult_response",
            "from_role": to_role,
            "to_role": from_role,
            "content": answer,
            "status": "answered",
            "linked_to": request_id,
            "created_at": time.time(),
        })
        events.append({
            "type": "agent_consult_completed",
            "from_role": from_role,
            "to_role": to_role,
            "message_id": request_id,
        })
        return json.dumps(
            {
                "status": "answered",
                "to_role": to_role,
                "message_id": request_id,
                "response": f"[ADVISORY] {answer}",
                "advisory_only": True,
            }
        )

    return json.dumps(
        {
            "status": "pending",
            "to_role": to_role,
            "message_id": request_id,
            "note": (
                f"Consult request queued for '{to_role}'. "
                "Response will be attached when that role completes."
            ),
            "advisory_only": True,
        }
    )


def _fulfill_pending_consults(
    current_role: str,
    final_text: str,
    state: TaskState,
    agent_messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    """Auto-respond to pending consult requests addressed to the current role."""
    enabled, _, max_response_chars, _ = _resolve_consult_policy(state)
    if not enabled:
        return
    answer = final_text[:max_response_chars] if final_text else "Completed work. No summary provided."
    for msg in agent_messages:
        if (
            msg.get("type") == "consult_request"
            and msg.get("to_role") == current_role
            and msg.get("status") == "pending"
        ):
            msg["status"] = "answered"
            response_id = _new_message_id(agent_messages)
            agent_messages.append({
                "id": response_id,
                "type": "consult_response",
                "from_role": current_role,
                "to_role": msg.get("from_role", ""),
                "content": f"[ADVISORY] {answer}",
                "status": "answered",
                "linked_to": msg.get("id", ""),
                "created_at": time.time(),
            })
            events.append({
                "type": "agent_consult_completed",
                "from_role": msg.get("from_role", ""),
                "to_role": current_role,
                "message_id": msg.get("id", ""),
            })


async def _run_subtask(
    llm: LLMProvider,
    tool_executor: ToolExecutor,
    description: str,
    files_context: list[str],
    system_prompt: str,
    stream_callback: Any | None = None,
    batch_timeout: int = DEFAULT_BATCH_TIMEOUT,
    max_rounds: int = SUBAGENT_MAX_ROUNDS,
) -> dict[str, Any]:
    """
    Run a sub-agent loop for a spawned subtask.

    Like Claude Code's Task tool: creates a child execution context with
    the same LLM and tools, focused on a specific piece of work.
    """
    # Build context from files
    context_parts = []
    for fp in files_context:
        try:
            result = await tool_executor.execute("read_file", {"path": fp})
            context_parts.append(f"--- {fp} ---\n{result}")
        except Exception as exc:
            logger.debug("Subtask context read failed for %s: %s", fp, exc)

    context_text = "\n\n".join(context_parts) if context_parts else ""

    sub_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"SUBTASK: {description}\n\n"
                + (f"CONTEXT FILES:\n{context_text}" if context_text else "")
            ),
        },
    ]

    # Get coder tools (without spawn_subtask to prevent recursion)
    sub_tool_defs = [
        t for t in get_engineering_tools("coder")
        if t["name"] != "spawn_subtask"
    ]

    if stream_callback:
        try:
            stream_callback("subtask", f"\n  🔀 Sub-agent: {description[:60]}...\n")
        except Exception as exc:
            logger.debug("Stream callback failed for subtask start: %s", exc)

    text, inp_tok, out_tok, files, _ = await _run_agentic_loop(
        llm=llm,
        messages=sub_messages,
        tool_defs=sub_tool_defs,
        tool_executor=tool_executor,
        agent_config={"temperature": 0.0, "max_tokens": 16384},
        role="subtask",
        stream_callback=stream_callback,
        batch_timeout=batch_timeout,
        max_rounds=max_rounds,
    )

    return {
        "summary": text[:2000],
        "files_changed": files,
        "input_tokens": inp_tok,
        "output_tokens": out_tok,
    }


async def _run_agentic_loop(
    llm: LLMProvider,
    messages: list[dict[str, Any]],
    tool_defs: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    agent_config: dict[str, Any],
    role: str,
    state: TaskState | None = None,
    agent_messages: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    stream_callback: Any | None = None,
    batch_timeout: int = DEFAULT_BATCH_TIMEOUT,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> tuple[str, int, int, list[str], dict[str, Any]]:
    """
    Run the agentic tool loop: LLM calls tools → execute → feed back → repeat.

    Returns:
        (final_text, total_input_tokens, total_output_tokens, files_changed)
    """
    total_input_tokens = 0
    total_output_tokens = 0
    all_text_parts: list[str] = []
    subtask_count_ref = {"value": 0}
    subtask_token_total_ref = {"value": 0}
    agent_messages = agent_messages if agent_messages is not None else []
    events = events if events is not None else []
    temperature = agent_config.get("temperature", DEFAULT_TEMPERATURE)
    # Use per-role max_tokens for smarter token allocation
    max_tokens = agent_config.get("max_tokens") or ROLE_MAX_TOKENS.get(role, DEFAULT_MAX_TOKENS)
    subagent_enabled, max_subtasks_per_step, max_subtask_rounds = _resolve_subagent_policy(state)

    for round_num in range(max_rounds):
        logger.info(
            "Agent %s: tool loop round %d (messages: %d)",
            role, round_num + 1, len(messages),
        )

        # Call LLM with tools
        response: LLMResponse = await asyncio.wait_for(
            llm.invoke(
                messages=messages,
                tools=tool_defs,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            timeout=batch_timeout,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Collect any text from this response
        if response.content:
            all_text_parts.append(response.content)
            # Stream the text to the callback if available
            if stream_callback:
                try:
                    stream_callback(role, response.content)
                except Exception:
                    logger.debug("Stream callback error for %s", role)

        # Check if LLM wants to call tools
        if not response.tool_calls:
            # No tool calls — agent is done
            logger.info("Agent %s: finished after %d rounds (no more tool calls)", role, round_num + 1)
            break

        # Execute each tool call
        logger.info(
            "Agent %s: executing %d tool call(s): %s",
            role, len(response.tool_calls),
            [tc.get("name", "?") for tc in response.tool_calls],
        )

        # Build the assistant message with tool_use content blocks
        # This is needed so the LLM sees what it previously said
        assistant_content: list[dict[str, Any]] = []
        if response.content:
            assistant_content.append({"type": "text", "text": response.content})
        for tc in response.tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc["input"],
            })

        messages.append({"role": "assistant", "content": assistant_content})

        # Execute tools — handle spawn_subtask specially (it runs a child LLM loop)
        tool_results_content: list[dict[str, Any]] = []

        async def _exec_single_tool(tc: dict) -> tuple[dict, str]:
            """Execute a single tool call, handling spawn_subtask as a meta-tool."""
            nonlocal total_input_tokens, total_output_tokens
            if tc["name"] == "spawn_subtask":
                if not subagent_enabled:
                    result_str = json.dumps({
                        "status": "blocked",
                        "reason": "subagents_disabled_by_policy",
                    })
                    events.append({
                        "type": "subtask_blocked",
                        "role": role,
                        "reason": "subagents_disabled_by_policy",
                    })
                elif subtask_count_ref["value"] >= max_subtasks_per_step:
                    result_str = json.dumps({
                        "status": "blocked",
                        "reason": "subtask_limit_reached",
                        "max_subtasks_per_agent_step": max_subtasks_per_step,
                    })
                    events.append({
                        "type": "subtask_blocked",
                        "role": role,
                        "reason": "subtask_limit_reached",
                        "max_subtasks_per_agent_step": max_subtasks_per_step,
                    })
                else:
                    subtask_count_ref["value"] += 1
                    subtask_description = str(tc["input"].get("description", "")).strip()
                    events.append({
                        "type": "subtask_spawned",
                        "role": role,
                        "subtask_index": subtask_count_ref["value"],
                        "description": subtask_description[:140],
                    })
                    sub_result = await _run_subtask(
                        llm=llm,
                        tool_executor=tool_executor,
                        description=subtask_description,
                        files_context=tc["input"].get("files_context", []),
                        system_prompt=agent_config.get("system_prompt", "You are a coding agent."),
                        stream_callback=stream_callback,
                        batch_timeout=batch_timeout,
                        max_rounds=max_subtask_rounds,
                    )
                    sub_in = int(sub_result.get("input_tokens", 0) or 0)
                    sub_out = int(sub_result.get("output_tokens", 0) or 0)
                    subtask_token_total_ref["value"] += sub_in + sub_out
                    total_input_tokens += sub_in
                    total_output_tokens += sub_out
                    events.append({
                        "type": "subtask_complete",
                        "role": role,
                        "subtask_index": subtask_count_ref["value"],
                        "input_tokens": sub_in,
                        "output_tokens": sub_out,
                        "files_changed": len(sub_result.get("files_changed", []) or []),
                    })
                    result_str = json.dumps(sub_result, default=str)
            elif tc["name"] == "consult_agent":
                if state is None:
                    result_str = json.dumps(
                        {"status": "error", "error": "consult_agent unavailable without state"}
                    )
                else:
                    result_str = _handle_consult_agent(
                        state=state,
                        from_role=role,
                        tool_input=tc.get("input", {}),
                        agent_messages=agent_messages,
                        events=events,
                    )
            else:
                started = time.monotonic()
                result_str = await tool_executor.execute(tc["name"], tc["input"])
                if tc["name"] == "invoke_integration":
                    elapsed_ms = int((time.monotonic() - started) * MS_PER_SECOND)
                    try:
                        integration_result = json.loads(result_str)
                    except json.JSONDecodeError:
                        integration_result = {}
                    event_type = (
                        "integration_blocked"
                        if integration_result.get("blocked")
                        else "integration_invoked"
                    )
                    events.append({
                        "type": event_type,
                        "role": role,
                        "kind": str(tc.get("input", {}).get("kind", "")),
                        "plugin_id": str(tc.get("input", {}).get("plugin_id", "")),
                        "target_id": str(tc.get("input", {}).get("target_id", "")),
                        "operation": str(tc.get("input", {}).get("operation", "")),
                        "dry_run": bool(integration_result.get("dry_run", False)),
                        "blocked_reason": str(integration_result.get("error", "")),
                        "status": str(integration_result.get("status", "")),
                        "latency_ms": elapsed_ms,
                    })
            return tc, result_str

        if len(response.tool_calls) > 1:
            # Parallel execution — fire all tools simultaneously
            logger.info("Agent %s: executing %d tools in parallel", role, len(response.tool_calls))

            parallel_results = await asyncio.gather(
                *[_exec_single_tool(tc) for tc in response.tool_calls],
                return_exceptions=True,
            )

            for result in parallel_results:
                if isinstance(result, Exception):
                    logger.error("Parallel tool execution error: %s", result)
                    continue
                tc, result_str = result
                if stream_callback:
                    try:
                        stream_callback(role, f"\n  ⚡ {tc['name']}({_summarize_input(tc['input'])})\n")
                    except Exception as exc:
                        logger.debug("Stream callback failed for parallel tool result: %s", exc)
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result_str,
                })
        else:
            # Single tool call — execute directly
            tc = response.tool_calls[0]
            _, result_str = await _exec_single_tool(tc)
            if stream_callback:
                try:
                    stream_callback(role, f"\n  ⚡ {tc['name']}({_summarize_input(tc['input'])})\n")
                except Exception as exc:
                    logger.debug("Stream callback failed for tool result: %s", exc)
            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results_content})

    else:
        logger.warning("Agent %s: hit max tool rounds (%d)", role, max_rounds)

    # Extract files changed from write_file tool calls in message history
    files_changed = _extract_written_files(messages)

    final_text = "\n".join(all_text_parts)
    return final_text, total_input_tokens, total_output_tokens, files_changed, {
        "subtask_count": subtask_count_ref["value"],
        "subtask_tokens": subtask_token_total_ref["value"],
    }


def _extract_written_files(messages: list[dict[str, Any]]) -> list[str]:
    """Extract file paths from write_file tool calls in message history."""
    files = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                if block.get("name") == "write_file":
                    path = block.get("input", {}).get("path", "")
                    if path and path not in files:
                        files.append(path)
    return files


def _summarize_input(tool_input: dict[str, Any]) -> str:
    """Create a short summary of tool input for display."""
    if "path" in tool_input:
        path = tool_input["path"]
        if "content" in tool_input:
            content_len = len(tool_input["content"])
            return f'"{path}", {content_len} chars'
        return f'"{path}"'
    if "command" in tool_input:
        return f'"{tool_input["command"]}"'
    if "pattern" in tool_input:
        return f'"{tool_input["pattern"]}"'
    return json.dumps(tool_input)[:60]


async def execute_agent_node(
    state: TaskState,
    llm_factory: Any,
    cost_calculator: CostCalculator,
    stream_callback: Any | None = None,
    memory_repo: MemoryRepository | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    memory_retriever: MemoryRetriever | None = None,
) -> dict[str, Any]:
    """
    Execute the current agent with context isolation and tool calling.

    This now implements the full agentic loop:
    1. Send messages + tool definitions to LLM
    2. LLM returns text + tool_calls
    3. Execute tool calls (read_file, write_file, run_command, etc.)
    4. Feed tool results back to LLM
    5. Repeat until LLM has no more tool calls

    Args:
        state: Current graph state.
        llm_factory: Creates LLM providers for given model names.
        cost_calculator: Calculates token costs.
        stream_callback: Optional callback(role, chunk) for streaming text.
    """
    team_config = state.get("team_config", {})
    current_role = state.get("current_agent_role", "")
    agents = team_config.get("agents", {})
    if current_role not in agents:
        return {
            "status": f"agent_{current_role}_error",
            "error": f"Agent role '{current_role}' not found in team config",
            "events": state.get("events", []) + [{
                "type": "agent_timeout",
                "role": current_role,
                "error": f"Role '{current_role}' not configured",
            }],
        }
    agent_config = agents[current_role]

    # --- Contract guards (input) ---
    input_contract = agent_config.get("input_contract", {}) or {}
    input_payload = {
        "task_description": state.get("description", ""),
        "role": current_role,
        "project_root": state.get("project_root", ""),
        "classification": state.get("classification", {}),
        "previous_outputs": state.get("agent_outputs", {}),
        "fix_packets": state.get("fix_packets", []),
    }
    input_violations = _validate_contract(input_contract, input_payload)
    if input_violations:
        return _contract_failure_result(state, current_role, "input", input_violations)

    # --- Budget guards ---
    budget_error = _check_budget_guards(state, current_role)
    if budget_error:
        return budget_error

    # --- Memory retrieval and context assembly ---
    memory_section_text, memory_context_by_role, memory_retrieval_log, memory_events = await _resolve_memory_context_for_role(
        state=state,
        current_role=current_role,
        memory_repo=memory_repo,
        embedding_provider=embedding_provider,
        memory_retriever=memory_retriever,
    )

    # --- Build messages ---
    system_prompt = agent_config["system_prompt"]
    messages = _build_agent_messages(
        state,
        system_prompt,
        agent_config,
        current_role,
        memory_section_text=memory_section_text,
    )

    # --- Resolve tool definitions ---
    tool_defs = _resolve_tool_definitions(agent_config, current_role)

    # --- Create ToolExecutor ---
    project_root = Path(state.get("project_root", "."))
    tool_executor = ToolExecutor(
        project_root,
        integration_catalog=state.get("integration_catalog", {}),
        integration_policy=state.get("integration_policy", {}),
        worktree_mode=str(state.get("worktree_mode", "project")),
        worktree_root=str(state.get("worktree_root", "")),
        filesystem_sandbox_mode=str(state.get("filesystem_sandbox_mode", "project_root")),
    )

    # --- LLM setup ---
    llm_model = agent_config.get("llm_model", DEFAULT_LLM_MODEL)
    llm: LLMProvider = llm_factory(llm_model)
    batch_timeout = agent_config.get("timeout_seconds", DEFAULT_BATCH_TIMEOUT)

    # Emit agent_started event
    events = list(state.get("events", []))
    events.extend(memory_events)
    agent_messages_log = list(state.get("agent_messages", []))
    events.append({
        "type": "agent_started",
        "role": current_role,
        "name": agent_config["name"],
    })

    start_time = time.monotonic()

    try:
        if tool_defs:
            # --- Agentic tool loop (for agents with tools) ---
            # Always use batch invoke for tool-calling agents.
            # This is the standard pattern: invoke → tools → invoke → tools → done.
            final_text, input_tokens, output_tokens, files_changed, subtask_metrics = await _run_agentic_loop(
                llm=llm,
                messages=messages,
                tool_defs=tool_defs,
                tool_executor=tool_executor,
                agent_config=agent_config,
                role=current_role,
                state=state,
                agent_messages=agent_messages_log,
                events=events,
                stream_callback=stream_callback,
                batch_timeout=batch_timeout,
            )
            total_tokens = input_tokens + output_tokens

            # Calculate cost
            cost = cost_calculator.calculate(
                model=llm_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        elif stream_callback:
            # --- Streaming mode for text-only agents (no tools) ---
            idle_timeout = agent_config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT)
            response = await _execute_streaming(
                llm, messages, agent_config, idle_timeout,
                current_role, stream_callback,
            )
            final_text = response.content
            total_tokens = response.usage.total_tokens
            files_changed = []
            cost = cost_calculator.calculate(
                model=llm_model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            subtask_metrics = {"subtask_count": 0, "subtask_tokens": 0}
        else:
            # --- Batch mode for text-only agents (no tools, no streaming) ---
            response = await asyncio.wait_for(
                llm.invoke(
                    messages=messages,
                    temperature=agent_config.get("temperature", DEFAULT_TEMPERATURE),
                    max_tokens=agent_config.get("max_tokens", DEFAULT_MAX_TOKENS),
                ),
                timeout=batch_timeout,
            )
            final_text = response.content
            total_tokens = response.usage.total_tokens
            files_changed = []
            cost = cost_calculator.calculate(
                model=llm_model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            subtask_metrics = {"subtask_count": 0, "subtask_tokens": 0}

    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start_time) * MS_PER_SECOND)
        logger.warning("Agent %s timed out after %ds", current_role, batch_timeout)
        events.append({
            "type": "agent_timeout",
            "role": current_role,
            "timeout_seconds": batch_timeout,
            "duration_ms": duration_ms,
        })
        return {
            "status": f"agent_{current_role}_timeout",
            "error": f"Agent '{current_role}' timed out after {batch_timeout}s",
            "events": events,
        }

    duration_ms = int((time.monotonic() - start_time) * MS_PER_SECOND)

    # If this role had pending consultations, auto-respond with latest summary.
    _fulfill_pending_consults(
        current_role=current_role,
        final_text=final_text,
        state=state,
        agent_messages=agent_messages_log,
        events=events,
    )

    # --- Build output ---
    agent_output: AgentOutput = {
        "summary": final_text,
        "files_changed": files_changed,
        "tokens": total_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
        "subtask_count": int(subtask_metrics.get("subtask_count", 0) or 0),
        "subtask_tokens": int(subtask_metrics.get("subtask_tokens", 0) or 0),
    }

    # --- Contract guards (output) ---
    output_contract = agent_config.get("output_contract", {}) or {}
    output_payload = {
        "summary": final_text,
        "files_changed": files_changed,
        "tokens": total_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
        "status": f"agent_{current_role}_complete",
    }
    output_violations = _validate_contract(output_contract, output_payload)
    if output_violations:
        return _contract_failure_result(state, current_role, "output", output_violations)

    events.append({
        "type": "agent_complete",
        "role": current_role,
        "name": agent_config["name"],
        "tokens": total_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
        "files_changed": files_changed,
        "summary": final_text,
        "subtask_count": int(subtask_metrics.get("subtask_count", 0) or 0),
    })

    return {
        "agent_outputs": {
            **state.get("agent_outputs", {}),
            current_role: agent_output,
        },
        "cost_accumulator": {
            **state.get("cost_accumulator", {}),
            agent_config["id"]: {
                "tokens": total_tokens,
                "cost": cost,
            },
        },
        "status": f"agent_{current_role}_complete",
        "agent_messages": agent_messages_log,
        "memory_context_by_role": memory_context_by_role,
        "memory_retrieval_log": memory_retrieval_log,
        "events": events,
    }


async def _execute_streaming(
    llm: LLMProvider,
    messages: list[dict[str, Any]],
    agent_config: dict[str, Any],
    idle_timeout: int,
    role: str,
    stream_callback: Any,
) -> LLMResponse:
    """Execute agent with streaming using idle timeout (text-only, no tools).

    Unlike a wall-clock timeout, this only triggers if NO tokens arrive
    for `idle_timeout` seconds. As long as the LLM is actively streaming,
    it runs indefinitely (like Claude Code, Cursor, Aider).
    """
    collected_text = ""
    stream = llm.stream(
        messages=messages,
        temperature=agent_config.get("temperature", DEFAULT_TEMPERATURE),
        max_tokens=agent_config.get("max_tokens", DEFAULT_MAX_TOKENS),
    )
    stream_iter = stream.__aiter__()

    while True:
        try:
            chunk = await asyncio.wait_for(
                stream_iter.__anext__(), timeout=idle_timeout,
            )
        except StopAsyncIteration:
            break  # Stream finished normally
        except asyncio.TimeoutError:
            logger.warning(
                "Agent %s idle for %ds (no tokens), aborting stream",
                role, idle_timeout,
            )
            break

        collected_text += chunk
        try:
            stream_callback(role, chunk)
        except Exception:
            logger.debug("Stream callback error for %s", role)

    # Build a synthetic LLMResponse from streamed content
    estimated_input = sum(len(m.get("content", "")) // 4 for m in messages if isinstance(m.get("content"), str))
    estimated_output = len(collected_text) // 4

    return LLMResponse(
        content=collected_text,
        usage=LLMUsage(
            input_tokens=estimated_input,
            output_tokens=estimated_output,
        ),
        model=agent_config.get("llm_model", DEFAULT_LLM_MODEL),
        stop_reason="end_turn",
    )


async def execute_agents_parallel(
    state: TaskState,
    roles: list[str],
    llm_factory: Any,
    cost_calculator: CostCalculator,
    stream_callback: Any | None = None,
    memory_repo: MemoryRepository | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    memory_retriever: MemoryRetriever | None = None,
) -> dict[str, Any]:
    """
    Execute multiple independent agents in parallel (item 8).

    Only used for agents that have no dependencies on each other's output.
    Each agent sees the SAME state — they don't see each other's results.
    """
    def _build_role_state(base: TaskState, role: str) -> TaskState:
        """Create an isolated task state for one parallel role execution."""
        role_state: TaskState = dict(base)
        role_state["current_agent_role"] = role
        # Isolate mutable collections so parallel agents can't cross-contaminate.
        role_state["events"] = []
        role_state["agent_messages"] = []
        role_state["agent_outputs"] = dict(base.get("agent_outputs", {}))
        role_state["cost_accumulator"] = dict(base.get("cost_accumulator", {}))
        role_state["memory_context_by_role"] = dict(base.get("memory_context_by_role", {}))
        role_state["memory_retrieval_log"] = dict(base.get("memory_retrieval_log", {}))
        return role_state

    tasks = []
    for role in roles:
        role_state = _build_role_state(state, role)
        tasks.append(
            execute_agent_node(
                role_state,
                llm_factory,
                cost_calculator,
                stream_callback,
                memory_repo=memory_repo,
                embedding_provider=embedding_provider,
                memory_retriever=memory_retriever,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge results
    merged_outputs = dict(state.get("agent_outputs", {}))
    merged_costs = dict(state.get("cost_accumulator", {}))
    merged_memory_context = dict(state.get("memory_context_by_role", {}))
    merged_memory_log = dict(state.get("memory_retrieval_log", {}))
    merged_events = list(state.get("events", []))

    for i, result in enumerate(results):
        role = roles[i]
        if isinstance(result, Exception):
            logger.error("Parallel agent %s failed: %s", role, result)
            merged_events.append({
                "type": "agent_timeout",
                "role": role,
                "error": str(result),
            })
            continue
        if isinstance(result, dict):
            role_outputs = result.get("agent_outputs", {})
            if role in role_outputs:
                merged_outputs[role] = role_outputs[role]

            # Merge only the current role's cost entry to avoid stale overwrites.
            role_agent_id = str(
                state.get("team_config", {}).get("agents", {}).get(role, {}).get("id", "")
            )
            role_costs = result.get("cost_accumulator", {})
            if role_agent_id and role_agent_id in role_costs:
                merged_costs[role_agent_id] = role_costs[role_agent_id]
            elif role in merged_outputs:
                merged_costs[role_agent_id or role] = {
                    "tokens": merged_outputs[role].get("tokens", 0),
                    "cost": merged_outputs[role].get("cost", 0.0),
                }
            merged_memory_context.update(result.get("memory_context_by_role", {}))
            role_memory_log = result.get("memory_retrieval_log", {})
            if isinstance(role_memory_log, dict):
                for role_key, entries in role_memory_log.items():
                    if not isinstance(entries, list):
                        continue
                    existing_entries = merged_memory_log.get(role_key, [])
                    if not isinstance(existing_entries, list):
                        existing_entries = []
                    seen = {
                        str(e.get("memory_id", ""))
                        for e in existing_entries
                        if isinstance(e, dict)
                    }
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        mem_id = str(entry.get("memory_id", ""))
                        if not mem_id or mem_id in seen:
                            continue
                        existing_entries.append(entry)
                        seen.add(mem_id)
                    merged_memory_log[role_key] = existing_entries

            # Child role states start with events=[], so this extends only new events.
            merged_events.extend(result.get("events", []))

    return {
        "agent_outputs": merged_outputs,
        "cost_accumulator": merged_costs,
        "memory_context_by_role": merged_memory_context,
        "memory_retrieval_log": merged_memory_log,
        "events": merged_events,
        "status": "parallel_complete",
    }
