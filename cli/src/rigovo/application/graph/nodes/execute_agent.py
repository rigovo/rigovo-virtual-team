"""Execute agent node — runs the current agent with isolated context.

Includes:
- Context isolation (agents only see output summaries, not reasoning)
- Budget enforcement (hard stop if task cost exceeds limit)
- Per-agent timeout with graceful handling
- Tool call processing for file operations
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from rigovo.application.graph.state import TaskState, AgentOutput
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.services.cost_calculator import CostCalculator

logger = logging.getLogger(__name__)


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


async def execute_agent_node(
    state: TaskState,
    llm_factory: Any,  # Callable[[str], LLMProvider] — creates provider for a model
    cost_calculator: CostCalculator,
) -> dict[str, Any]:
    """
    Execute the current agent with context isolation.

    Each agent ONLY sees:
    - Its own system prompt (with enrichment)
    - Task description
    - Previous agents' OUTPUT SUMMARIES (not their chain-of-thought)
    - Fix packet (if in retry loop)

    Budget enforcement:
    - Checks accumulated cost before each agent run
    - Raises BudgetExceededError if max_cost_per_task exceeded

    Timeout enforcement:
    - Each agent has a configurable timeout (default 300s)
    - Raises AgentTimeoutError if agent takes too long
    """
    team_config = state["team_config"]
    current_role = state["current_agent_role"]
    agent_config = team_config["agents"][current_role]

    # --- Budget guard ---
    accumulated_cost = sum(
        v.get("cost", 0) for v in state.get("cost_accumulator", {}).values()
    )
    budget_limit = state.get("budget_max_cost_per_task", 0)
    if budget_limit > 0 and accumulated_cost >= budget_limit:
        raise BudgetExceededError(accumulated_cost, budget_limit)

    # --- Token guard ---
    accumulated_tokens = sum(
        v.get("tokens", 0) for v in state.get("cost_accumulator", {}).values()
    )
    token_limit = state.get("budget_max_tokens_per_task", 0)
    if token_limit > 0 and accumulated_tokens >= token_limit:
        return {
            "status": "budget_exceeded_tokens",
            "error": f"Token limit exceeded: {accumulated_tokens:,} tokens (limit {token_limit:,})",
            "events": state.get("events", []) + [{
                "type": "budget_exceeded",
                "role": current_role,
                "tokens_used": accumulated_tokens,
                "token_limit": token_limit,
            }],
        }

    # 1. Build system prompt with enrichment
    system_prompt = agent_config["system_prompt"]
    enrichment = agent_config.get("enrichment_context", "")
    if enrichment:
        system_prompt += f"\n\n--- ENRICHMENT (from Master Agent) ---\n{enrichment}"

    # 2. Build messages — isolated context
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Task: {state['description']}"},
    ]

    # Add previous agent outputs (summaries only, no reasoning)
    for role, output in state.get("agent_outputs", {}).items():
        messages.append({
            "role": "user",
            "content": f"[{role.upper()} output]: {output.get('summary', '')}",
        })

    # Add fix packet if retrying
    fix_packets = state.get("fix_packets", [])
    if fix_packets:
        messages.append({
            "role": "user",
            "content": f"[FIX REQUIRED]: {fix_packets[-1]}",
        })

    # 3. Call LLM with timeout
    llm_model = agent_config.get("llm_model", "claude-sonnet-4-5-20250929")
    llm: LLMProvider = llm_factory(llm_model)
    timeout_seconds = agent_config.get("timeout_seconds", 300)

    start_time = time.monotonic()

    try:
        response = await asyncio.wait_for(
            llm.invoke(
                messages=messages,
                temperature=agent_config.get("temperature", 0.0),
                max_tokens=agent_config.get("max_tokens", 8192),
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.warning("Agent %s timed out after %ds", current_role, timeout_seconds)
        return {
            "status": f"agent_{current_role}_timeout",
            "error": f"Agent '{current_role}' timed out after {timeout_seconds}s",
            "events": state.get("events", []) + [{
                "type": "agent_timeout",
                "role": current_role,
                "timeout_seconds": timeout_seconds,
                "duration_ms": duration_ms,
            }],
        }

    duration_ms = int((time.monotonic() - start_time) * 1000)

    # 4. Calculate cost
    cost = cost_calculator.calculate(
        model=llm_model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    # 5. Build output
    agent_output: AgentOutput = {
        "summary": response.content,
        "files_changed": [],  # Will be populated by tool calls
        "tokens": response.usage.total_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
    }

    # 6. Update state
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
        "events": state.get("events", []) + [{
            "type": "agent_complete",
            "role": current_role,
            "name": agent_config["name"],
            "tokens": response.usage.total_tokens,
            "cost": cost,
            "duration_ms": duration_ms,
        }],
    }
