"""Graph builder — constructs the LangGraph orchestration graph.

This module assembles the complete task execution graph from individual nodes
and edges. It's the "main" of the orchestration layer.

When LangGraph is available, this builds a real StateGraph with checkpointing.
When running without LangGraph (tests, lightweight mode), it provides a
simple sequential executor.
"""

from __future__ import annotations

from typing import Any, Callable

from rigovo.application.graph.state import TaskState
from rigovo.application.graph.edges import (
    check_approval,
    check_gates_and_route,
    check_pipeline_complete,
    advance_to_next_agent,
)
from rigovo.application.graph.nodes.classify import classify_node
from rigovo.application.graph.nodes.assemble import assemble_node
from rigovo.application.graph.nodes.execute_agent import execute_agent_node
from rigovo.application.graph.nodes.quality_check import quality_check_node
from rigovo.application.graph.nodes.approval import plan_approval_node, commit_approval_node
from rigovo.application.graph.nodes.store_memory import store_memory_node
from rigovo.application.graph.nodes.finalize import finalize_node
from rigovo.domain.entities.agent import Agent
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.services.cost_calculator import CostCalculator


class GraphBuilder:
    """
    Builds the orchestration graph.

    Dependencies are injected at construction time — the graph builder
    doesn't know about concrete LLM providers, databases, or gate
    implementations.
    """

    def __init__(
        self,
        llm_factory: Callable[[str], LLMProvider],
        master_llm: LLMProvider,
        cost_calculator: CostCalculator,
        quality_gates: list[QualityGate],
        approval_handler: Callable[[TaskState], dict[str, Any]] | None = None,
    ) -> None:
        self._llm_factory = llm_factory
        self._master_llm = master_llm
        self._cost_calculator = cost_calculator
        self._quality_gates = quality_gates
        self._approval_handler = approval_handler

    def build_langgraph(self, checkpointer: Any = None) -> Any:
        """
        Build a real LangGraph StateGraph.

        Requires langgraph to be installed. Returns compiled graph.
        """
        try:
            from langgraph.graph import StateGraph, START, END
        except ImportError:
            raise ImportError(
                "langgraph is required for full orchestration. "
                "Install with: pip install langgraph"
            )

        graph = StateGraph(TaskState)

        # Bind dependencies into node closures
        master_llm = self._master_llm
        llm_factory = self._llm_factory
        cost_calc = self._cost_calculator
        gates = self._quality_gates

        async def _classify(state: TaskState) -> dict:
            return await classify_node(state, master_llm)

        async def _assemble(state: TaskState) -> dict:
            # In real usage, agents come from DB. For now, use state.
            return await assemble_node(state, agents=[])

        async def _plan_approval(state: TaskState) -> dict:
            return await plan_approval_node(state)

        async def _execute_agent(state: TaskState) -> dict:
            return await execute_agent_node(state, llm_factory, cost_calc)

        async def _quality_check(state: TaskState) -> dict:
            return await quality_check_node(state, gates)

        async def _route_next(state: TaskState) -> dict:
            return advance_to_next_agent(state)

        async def _commit_approval(state: TaskState) -> dict:
            return await commit_approval_node(state)

        async def _store_memory(state: TaskState) -> dict:
            return await store_memory_node(state, master_llm)

        async def _finalize(state: TaskState) -> dict:
            return await finalize_node(state)

        # Add nodes
        graph.add_node("classify", _classify)
        graph.add_node("assemble", _assemble)
        graph.add_node("plan_approval", _plan_approval)
        graph.add_node("execute_agent", _execute_agent)
        graph.add_node("quality_check", _quality_check)
        graph.add_node("route_next", _route_next)
        graph.add_node("commit_approval", _commit_approval)
        graph.add_node("store_memory", _store_memory)
        graph.add_node("finalize", _finalize)

        # Edges
        graph.add_edge(START, "classify")
        graph.add_edge("classify", "assemble")
        graph.add_edge("assemble", "plan_approval")

        graph.add_conditional_edges("plan_approval", check_approval, {
            "approved": "execute_agent",
            "rejected": "finalize",
        })

        graph.add_edge("execute_agent", "quality_check")

        graph.add_conditional_edges("quality_check", check_gates_and_route, {
            "pass_next_agent": "route_next",
            "fail_fix_loop": "execute_agent",
            "fail_max_retries": "finalize",
        })

        graph.add_conditional_edges("route_next", check_pipeline_complete, {
            "more_agents": "execute_agent",
            "pipeline_done": "commit_approval",
        })

        graph.add_conditional_edges("commit_approval", check_approval, {
            "approved": "store_memory",
            "rejected": "finalize",
        })

        graph.add_edge("store_memory", "finalize")
        graph.add_edge("finalize", END)

        # Compile
        if checkpointer:
            return graph.compile(checkpointer=checkpointer)
        return graph.compile()

    async def run_sequential(
        self,
        initial_state: TaskState,
        agents: list[Agent],
        available_teams: list[dict[str, Any]] | None = None,
    ) -> TaskState:
        """
        Run the graph sequentially without LangGraph (for tests or simple mode).

        No checkpointing, no interrupt(). Useful for unit tests and
        when langgraph is not installed.
        """
        state = dict(initial_state)

        # 1. Classify
        update = await classify_node(state, self._master_llm)
        state.update(update)

        # 2. Assemble pipeline
        update = await assemble_node(state, agents)
        state.update(update)

        # 3. Plan approval (auto-approve in sequential mode)
        update = await plan_approval_node(state)
        state.update(update)
        state["approval_status"] = "approved"

        # 4. Execute agents sequentially
        pipeline_order = state.get("team_config", {}).get("pipeline_order", [])

        for i, role in enumerate(pipeline_order):
            state["current_agent_index"] = i
            state["current_agent_role"] = role

            # Execute
            update = await execute_agent_node(state, self._llm_factory, self._cost_calculator)
            state.update(update)

            # Quality check
            update = await quality_check_node(state, self._quality_gates)
            state.update(update)

            # Handle gate failure
            gate_results = state.get("gate_results", {})
            if not gate_results.get("passed", True):
                retry_count = state.get("retry_count", 0)
                max_retries = state.get("max_retries", 3)

                while retry_count < max_retries and not gate_results.get("passed", True):
                    update = await execute_agent_node(
                        state, self._llm_factory, self._cost_calculator,
                    )
                    state.update(update)
                    update = await quality_check_node(state, self._quality_gates)
                    state.update(update)
                    gate_results = state.get("gate_results", {})
                    retry_count = state.get("retry_count", 0)

                if not gate_results.get("passed", True):
                    break

        # 5. Commit approval (auto-approve in sequential mode)
        update = await commit_approval_node(state)
        state.update(update)
        state["approval_status"] = "approved"

        # 6. Store memory
        update = await store_memory_node(state, self._master_llm)
        state.update(update)

        # 7. Finalize
        update = await finalize_node(state)
        state.update(update)

        return state  # type: ignore[return-value]
