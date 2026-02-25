"""Execute agent node — runs the current agent with context engineering.

Each agent execution follows the INTELLIGENT AGENT pattern:
1. PERCEIVE — project snapshot injected (scanned at task start)
2. REMEMBER — relevant memories from past tasks injected
3. REASON — system prompt + enrichment + quality contract
4. ACT — LLM generates response (streaming or batch)
5. VERIFY — Rigour gates check output (separate node)

Supports two modes:
- **Batch**: llm.invoke() — single response, simpler
- **Streaming**: llm.stream() — token-by-token, emits agent_streaming events
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from rigovo.application.context.context_builder import ContextBuilder
from rigovo.application.graph.state import TaskState, AgentOutput
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.services.cost_calculator import CostCalculator

logger = logging.getLogger(__name__)

# --- Named constants for agent execution defaults ---
DEFAULT_LLM_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 8192
MS_PER_SECOND = 1000
STREAM_CHUNK_MIN_SIZE = 4  # Minimum chars before emitting stream event


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
) -> list[dict[str, str]]:
    """Build the message list for an agent execution."""
    # Context engineering: assemble rich per-agent context
    context_builder = ContextBuilder()
    agent_context = context_builder.build(
        role=current_role,
        project_snapshot=state.get("project_snapshot"),
        enrichment_text=agent_config.get("enrichment_context", ""),
        previous_outputs=state.get("agent_outputs"),
    )
    full_context = agent_context.to_full_context()
    if full_context:
        system_prompt += f"\n\n{full_context}"

    messages: list[dict[str, str]] = [
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


async def execute_agent_node(
    state: TaskState,
    llm_factory: Any,
    cost_calculator: CostCalculator,
    stream_callback: Any | None = None,
) -> dict[str, Any]:
    """
    Execute the current agent with context isolation.

    Args:
        state: Current graph state.
        llm_factory: Creates LLM providers for given model names.
        cost_calculator: Calculates token costs.
        stream_callback: Optional callback(role, chunk) for streaming tokens.
            When provided, uses llm.stream() for real-time output.
    """
    team_config = state["team_config"]
    current_role = state["current_agent_role"]
    agent_config = team_config["agents"][current_role]

    # --- Budget guards ---
    budget_error = _check_budget_guards(state, current_role)
    if budget_error:
        return budget_error

    # --- Build messages ---
    system_prompt = agent_config["system_prompt"]
    messages = _build_agent_messages(state, system_prompt, agent_config, current_role)

    # --- LLM setup ---
    llm_model = agent_config.get("llm_model", DEFAULT_LLM_MODEL)
    llm: LLMProvider = llm_factory(llm_model)
    timeout_seconds = agent_config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)

    # Emit agent_started event
    events = list(state.get("events", []))
    events.append({
        "type": "agent_started",
        "role": current_role,
        "name": agent_config["name"],
    })

    start_time = time.monotonic()

    try:
        if stream_callback:
            # --- Streaming mode (item 2) ---
            response = await _execute_streaming(
                llm, messages, agent_config, timeout_seconds,
                current_role, stream_callback,
            )
        else:
            # --- Batch mode ---
            response = await asyncio.wait_for(
                llm.invoke(
                    messages=messages,
                    temperature=agent_config.get("temperature", DEFAULT_TEMPERATURE),
                    max_tokens=agent_config.get("max_tokens", DEFAULT_MAX_TOKENS),
                ),
                timeout=timeout_seconds,
            )
    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start_time) * MS_PER_SECOND)
        logger.warning("Agent %s timed out after %ds", current_role, timeout_seconds)
        events.append({
            "type": "agent_timeout",
            "role": current_role,
            "timeout_seconds": timeout_seconds,
            "duration_ms": duration_ms,
        })
        return {
            "status": f"agent_{current_role}_timeout",
            "error": f"Agent '{current_role}' timed out after {timeout_seconds}s",
            "events": events,
        }

    duration_ms = int((time.monotonic() - start_time) * MS_PER_SECOND)

    # --- Calculate cost ---
    cost = cost_calculator.calculate(
        model=llm_model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    # --- Build output ---
    agent_output: AgentOutput = {
        "summary": response.content,
        "files_changed": [],
        "tokens": response.usage.total_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
    }

    events.append({
        "type": "agent_complete",
        "role": current_role,
        "name": agent_config["name"],
        "tokens": response.usage.total_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
    })

    return {
        "agent_outputs": {
            **state.get("agent_outputs", {}),
            current_role: agent_output,
        },
        "cost_accumulator": {
            **state.get("cost_accumulator", {}),
            agent_config["id"]: {
                "tokens": response.usage.total_tokens,
                "cost": cost,
            },
        },
        "status": f"agent_{current_role}_complete",
        "events": events,
    }


async def _execute_streaming(
    llm: LLMProvider,
    messages: list[dict[str, str]],
    agent_config: dict[str, Any],
    timeout_seconds: int,
    role: str,
    stream_callback: Any,
) -> Any:
    """Execute agent with streaming, calling stream_callback for each chunk."""
    from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage

    collected_text = ""

    async def _stream_inner():
        nonlocal collected_text
        async for chunk in llm.stream(
            messages=messages,
            temperature=agent_config.get("temperature", DEFAULT_TEMPERATURE),
            max_tokens=agent_config.get("max_tokens", DEFAULT_MAX_TOKENS),
        ):
            collected_text += chunk
            try:
                stream_callback(role, chunk)
            except Exception:
                logger.debug("Stream callback error for %s", role)

    await asyncio.wait_for(_stream_inner(), timeout=timeout_seconds)

    # Build a synthetic LLMResponse from streamed content
    # Note: token counts are estimates for streaming mode
    estimated_input = sum(len(m.get("content", "")) // 4 for m in messages)
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
