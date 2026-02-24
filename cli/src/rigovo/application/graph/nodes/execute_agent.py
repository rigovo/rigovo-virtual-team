"""Execute agent node — runs the current agent with isolated context."""

from __future__ import annotations

import time
from typing import Any

from rigovo.application.graph.state import TaskState, AgentOutput
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.services.cost_calculator import CostCalculator


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
    """
    team_config = state["team_config"]
    current_role = state["current_agent_role"]
    agent_config = team_config["agents"][current_role]

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

    # 3. Call LLM
    llm_model = agent_config.get("llm_model", "claude-sonnet-4-5-20250929")
    llm: LLMProvider = llm_factory(llm_model)

    start_time = time.monotonic()
    response = await llm.invoke(
        messages=messages,
        temperature=0.0,
        max_tokens=8192,
    )
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
