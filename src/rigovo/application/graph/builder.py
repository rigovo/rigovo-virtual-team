"""Graph builder — constructs the LangGraph orchestration graph.

**Primary path** — ``build_langgraph()`` returns a compiled LangGraph
``StateGraph`` with checkpointing, conditional routing, parallel fan-out,
and the full intelligent-agent pipeline.

**Fallback path** — ``run_sequential()`` provides a lightweight executor
for unit tests or environments where ``langgraph`` is not installed.

Features:
- SQLite checkpointing for crash recovery (item 3)
- Interactive approval with interrupt (item 4)
- Parallel fan-out for independent agents (item 8)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from rigovo.application.graph.state import TaskState
from rigovo.application.graph.edges import (
    check_approval,
    check_gates_and_route,
    check_pipeline_complete,
    advance_to_next_agent,
)
from rigovo.application.graph.nodes.scan_project import scan_project_node
from rigovo.application.graph.nodes.classify import classify_node
from rigovo.application.graph.nodes.assemble import assemble_node
from rigovo.application.graph.nodes.execute_agent import (
    execute_agent_node,
    execute_agents_parallel,
)
from rigovo.application.graph.nodes.quality_check import quality_check_node
from rigovo.application.graph.nodes.approval import plan_approval_node, commit_approval_node
from rigovo.application.graph.nodes.enrich import enrich_node
from rigovo.application.graph.nodes.store_memory import store_memory_node
from rigovo.application.graph.nodes.finalize import finalize_node
from rigovo.domain.entities.agent import Agent
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.services.cost_calculator import CostCalculator

logger = logging.getLogger(__name__)

# Roles that can run in parallel (no inter-dependency)
PARALLELIZABLE_ROLES = {"reviewer", "qa", "security", "docs"}


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
        agents: list[Agent] | None = None,
        approval_handler: Callable[[TaskState], dict[str, Any]] | None = None,
        auto_approve: bool = True,
        enable_parallel: bool = False,
        stream_callback: Any | None = None,
    ) -> None:
        self._llm_factory = llm_factory
        self._master_llm = master_llm
        self._cost_calculator = cost_calculator
        self._quality_gates = quality_gates
        self._agents = agents or []
        self._approval_handler = approval_handler
        self._auto_approve = auto_approve
        self._enable_parallel = enable_parallel
        self._stream_callback = stream_callback

    # ------------------------------------------------------------------
    # Checkpointer factory (item 3)
    # ------------------------------------------------------------------

    @staticmethod
    def create_sqlite_checkpointer(db_path: str | Path | None = None) -> Any:
        """Create a SQLite checkpointer for crash recovery.

        Args:
            db_path: Path to SQLite database. Defaults to .rigovo/checkpoints.db.

        Returns:
            A LangGraph-compatible checkpointer, or None if unavailable.
        """
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError:
            try:
                from langgraph.checkpoint.sqlite import SqliteSaver
                path = str(db_path) if db_path else ".rigovo/checkpoints.db"
                return SqliteSaver.from_conn_string(path)
            except ImportError:
                logger.debug("No SQLite checkpointer available")
                return None

        path = str(db_path) if db_path else ".rigovo/checkpoints.db"
        return AsyncSqliteSaver.from_conn_string(path)

    # ------------------------------------------------------------------
    # Primary path — LangGraph compiled graph
    # ------------------------------------------------------------------

    def build_langgraph(self, checkpointer: Any = None) -> Any:
        """
        Build a compiled LangGraph ``StateGraph``.

        Returns the compiled graph ready for ``await graph.ainvoke(state)``.
        Raises ``ImportError`` when ``langgraph`` is not installed.
        """
        from langgraph.graph import StateGraph, START, END

        graph = StateGraph(TaskState)

        # Capture dependencies in closures
        master_llm = self._master_llm
        llm_factory = self._llm_factory
        cost_calc = self._cost_calculator
        gates = self._quality_gates
        agents = self._agents
        auto_approve = self._auto_approve
        stream_cb = self._stream_callback

        # --- Node wrappers (bind injected deps) ---

        async def _scan_project(state: TaskState) -> dict:
            return await scan_project_node(state)

        async def _classify(state: TaskState) -> dict:
            return await classify_node(state, master_llm)

        async def _assemble(state: TaskState) -> dict:
            return await assemble_node(state, agents=agents)

        async def _plan_approval(state: TaskState) -> dict:
            result = await plan_approval_node(state)
            if auto_approve:
                result["approval_status"] = "approved"
            return result

        async def _execute_agent(state: TaskState) -> dict:
            return await execute_agent_node(
                state, llm_factory, cost_calc, stream_callback=stream_cb,
            )

        async def _quality_check(state: TaskState) -> dict:
            return await quality_check_node(state, gates)

        async def _route_next(state: TaskState) -> dict:
            return advance_to_next_agent(state)

        async def _commit_approval(state: TaskState) -> dict:
            result = await commit_approval_node(state)
            if auto_approve:
                result["approval_status"] = "approved"
            return result

        async def _enrich(state: TaskState) -> dict:
            return await enrich_node(state)

        async def _store_memory(state: TaskState) -> dict:
            return await store_memory_node(state, master_llm)

        async def _finalize(state: TaskState) -> dict:
            return await finalize_node(state)

        # --- Register nodes ---
        graph.add_node("scan_project", _scan_project)
        graph.add_node("classify", _classify)
        graph.add_node("assemble", _assemble)
        graph.add_node("plan_approval", _plan_approval)
        graph.add_node("execute_agent", _execute_agent)
        graph.add_node("quality_check", _quality_check)
        graph.add_node("route_next", _route_next)
        graph.add_node("commit_approval", _commit_approval)
        graph.add_node("enrich", _enrich)
        graph.add_node("store_memory", _store_memory)
        graph.add_node("finalize", _finalize)

        # --- Edges ---
        graph.add_edge(START, "scan_project")
        graph.add_edge("scan_project", "classify")
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
            "approved": "enrich",
            "rejected": "finalize",
        })

        graph.add_edge("enrich", "store_memory")
        graph.add_edge("store_memory", "finalize")
        graph.add_edge("finalize", END)

        if checkpointer:
            return graph.compile(checkpointer=checkpointer)
        return graph.compile()

    # ------------------------------------------------------------------
    # Fallback path — simple sequential executor (no LangGraph needed)
    # ------------------------------------------------------------------

    async def run_sequential(
        self,
        initial_state: TaskState,
        agents: list[Agent] | None = None,
        available_teams: list[dict[str, Any]] | None = None,
    ) -> TaskState:
        """
        Run the pipeline sequentially without LangGraph.

        No checkpointing, no interrupt(). Useful for unit tests and
        environments where ``langgraph`` is not installed.
        """
        resolved_agents = agents if agents is not None else self._agents
        state = dict(initial_state)

        # 0. Scan project — perception BEFORE reasoning
        update = await scan_project_node(state)
        state.update(update)

        # 1. Classify (with project context available)
        update = await classify_node(state, self._master_llm)
        state.update(update)

        # 2. Assemble pipeline
        update = await assemble_node(state, resolved_agents)
        state.update(update)

        # 3. Plan approval (auto-approve in sequential mode)
        update = await plan_approval_node(state)
        state.update(update)
        state["approval_status"] = "approved"

        # 4. Execute agents
        pipeline_order = state.get("team_config", {}).get("pipeline_order", [])

        if self._enable_parallel:
            # Split into sequential and parallel groups
            sequential, parallel = self._split_pipeline(pipeline_order)
            await self._run_sequential_agents(state, sequential)
            if parallel:
                update = await execute_agents_parallel(
                    state, parallel, self._llm_factory,
                    self._cost_calculator, self._stream_callback,
                )
                state.update(update)
        else:
            await self._run_sequential_agents(state, pipeline_order)

        # 5. Commit approval (auto-approve in sequential mode)
        update = await commit_approval_node(state)
        state.update(update)
        state["approval_status"] = "approved"

        # 6. Enrich
        update = await enrich_node(state)
        state.update(update)

        # 7. Store memory
        update = await store_memory_node(state, self._master_llm)
        state.update(update)

        # 8. Finalize
        update = await finalize_node(state)
        state.update(update)

        return state  # type: ignore[return-value]

    async def _run_sequential_agents(
        self, state: dict, pipeline_order: list[str],
    ) -> None:
        """Run agents one-by-one with quality gate retry loops."""
        for i, role in enumerate(pipeline_order):
            state["current_agent_index"] = i
            state["current_agent_role"] = role

            update = await execute_agent_node(
                state, self._llm_factory, self._cost_calculator,
                stream_callback=self._stream_callback,
            )
            state.update(update)

            update = await quality_check_node(state, self._quality_gates)
            state.update(update)

            gate_results = state.get("gate_results", {})
            if not gate_results.get("passed", True):
                retry_count = state.get("retry_count", 0)
                max_retries = state.get("max_retries", 3)

                while retry_count < max_retries and not gate_results.get("passed", True):
                    update = await execute_agent_node(
                        state, self._llm_factory, self._cost_calculator,
                        stream_callback=self._stream_callback,
                    )
                    state.update(update)
                    update = await quality_check_node(state, self._quality_gates)
                    state.update(update)
                    gate_results = state.get("gate_results", {})
                    retry_count = state.get("retry_count", 0)

                if not gate_results.get("passed", True):
                    break

    @staticmethod
    def _split_pipeline(
        pipeline_order: list[str],
    ) -> tuple[list[str], list[str]]:
        """Split pipeline into sequential (must run first) and parallel groups."""
        sequential = []
        parallel = []
        for role in pipeline_order:
            if role in PARALLELIZABLE_ROLES:
                parallel.append(role)
            else:
                sequential.append(role)
        return sequential, parallel
