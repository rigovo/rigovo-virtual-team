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

from rigovo.application.context.context_builder import ContextBuilder
from rigovo.application.graph.state import TaskState, AgentOutput
from rigovo.domain.interfaces.llm_provider import LLMProvider, LLMResponse, LLMUsage
from rigovo.domain.services.cost_calculator import CostCalculator
from rigovo.domains.engineering.tools import get_engineering_tools
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


def _build_agent_messages(
    state: TaskState,
    system_prompt: str,
    agent_config: dict[str, Any],
    current_role: str,
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


def _check_budget_guards(state: TaskState, current_role: str) -> dict[str, Any] | None:
    """Check budget and token limits. Returns error state dict if exceeded, None otherwise."""
    accumulated_cost = sum(
        v.get("cost", 0) for v in state.get("cost_accumulator", {}).values()
    )
    budget_limit = state.get("budget_max_cost_per_task", 0)
    if budget_limit > 0 and accumulated_cost >= budget_limit:
        raise BudgetExceededError(accumulated_cost, budget_limit)

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
    # agent_config["tools"] is a list of tool names like ["read_file", "write_file"]
    # We need to convert these to full LLM tool definitions
    tool_names = agent_config.get("tools", [])
    if not tool_names:
        return []
    return get_engineering_tools(current_role)


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

    # Run a mini agentic loop (max 10 rounds for subtasks)
    text, inp_tok, out_tok, files = await _run_agentic_loop(
        llm=llm,
        messages=sub_messages,
        tool_defs=sub_tool_defs,
        tool_executor=tool_executor,
        agent_config={"temperature": 0.0, "max_tokens": 16384},
        role="subtask",
        stream_callback=stream_callback,
        batch_timeout=batch_timeout,
        max_rounds=10,
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
) -> tuple[str, int, int, list[str]]:
    """
    Run the agentic tool loop: LLM calls tools → execute → feed back → repeat.

    Returns:
        (final_text, total_input_tokens, total_output_tokens, files_changed)
    """
    total_input_tokens = 0
    total_output_tokens = 0
    all_text_parts: list[str] = []
    agent_messages = agent_messages if agent_messages is not None else []
    events = events if events is not None else []
    temperature = agent_config.get("temperature", DEFAULT_TEMPERATURE)
    # Use per-role max_tokens for smarter token allocation
    max_tokens = agent_config.get("max_tokens") or ROLE_MAX_TOKENS.get(role, DEFAULT_MAX_TOKENS)

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
            if tc["name"] == "spawn_subtask":
                # Sub-agent spawning — run a child agentic loop
                sub_result = await _run_subtask(
                    llm=llm,
                    tool_executor=tool_executor,
                    description=tc["input"].get("description", ""),
                    files_context=tc["input"].get("files_context", []),
                    system_prompt=agent_config.get("system_prompt", "You are a coding agent."),
                    stream_callback=stream_callback,
                    batch_timeout=batch_timeout,
                )
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
                result_str = await tool_executor.execute(tc["name"], tc["input"])
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
    return final_text, total_input_tokens, total_output_tokens, files_changed


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

    # --- Budget guards ---
    budget_error = _check_budget_guards(state, current_role)
    if budget_error:
        return budget_error

    # --- Build messages ---
    system_prompt = agent_config["system_prompt"]
    messages = _build_agent_messages(state, system_prompt, agent_config, current_role)

    # --- Resolve tool definitions ---
    tool_defs = _resolve_tool_definitions(agent_config, current_role)

    # --- Create ToolExecutor ---
    project_root = Path(state.get("project_root", "."))
    tool_executor = ToolExecutor(project_root)

    # --- LLM setup ---
    llm_model = agent_config.get("llm_model", DEFAULT_LLM_MODEL)
    llm: LLMProvider = llm_factory(llm_model)
    batch_timeout = agent_config.get("timeout_seconds", DEFAULT_BATCH_TIMEOUT)

    # Emit agent_started event
    events = list(state.get("events", []))
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
            final_text, input_tokens, output_tokens, files_changed = await _run_agentic_loop(
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
    }

    events.append({
        "type": "agent_complete",
        "role": current_role,
        "name": agent_config["name"],
        "tokens": total_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
        "files_changed": files_changed,
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
) -> dict[str, Any]:
    """
    Execute multiple independent agents in parallel (item 8).

    Only used for agents that have no dependencies on each other's output.
    Each agent sees the SAME state — they don't see each other's results.
    """
    tasks = []
    for role in roles:
        role_state = dict(state)
        role_state["current_agent_role"] = role
        tasks.append(
            execute_agent_node(role_state, llm_factory, cost_calculator, stream_callback)
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge results
    merged_outputs = dict(state.get("agent_outputs", {}))
    merged_costs = dict(state.get("cost_accumulator", {}))
    merged_events = list(state.get("events", []))
    total_new_tokens = 0
    total_new_cost = 0.0

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Parallel agent %s failed: %s", roles[i], result)
            merged_events.append({
                "type": "agent_timeout",
                "role": roles[i],
                "error": str(result),
            })
            continue
        if isinstance(result, dict):
            for role, output in result.get("agent_outputs", {}).items():
                merged_outputs[role] = output
                total_new_tokens += output.get("tokens", 0)
                total_new_cost += output.get("cost", 0.0)
            merged_costs.update(result.get("cost_accumulator", {}))
            merged_events.extend(result.get("events", []))

    return {
        "agent_outputs": merged_outputs,
        "cost_accumulator": merged_costs,
        "events": merged_events,
        "status": "parallel_complete",
    }
