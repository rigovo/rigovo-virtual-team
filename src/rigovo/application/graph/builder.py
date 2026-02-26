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

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

from rigovo.application.graph.state import TaskState
from rigovo.application.graph.edges import (
    check_approval,
    check_gates_and_route,
    check_replan_result,
    check_pipeline_complete,
    check_parallel_postprocess,
    advance_to_next_agent,
    prepare_debate_round,
)
from rigovo.application.graph.nodes.scan_project import scan_project_node
from rigovo.application.graph.nodes.classify import classify_node
from rigovo.application.graph.nodes.route_team import route_team_node
from rigovo.application.graph.nodes.assemble import assemble_node
from rigovo.application.graph.nodes.execute_agent import (
    execute_agent_node,
    execute_agents_parallel,
)
from rigovo.application.graph.nodes.quality_check import quality_check_node
from rigovo.application.graph.nodes.approval import plan_approval_node, commit_approval_node
from rigovo.application.graph.nodes.enrich import enrich_node
from rigovo.application.graph.nodes.replan import replan_node
from rigovo.application.graph.nodes.store_memory import store_memory_node
from rigovo.application.context.memory_retriever import MemoryRetriever
from rigovo.application.master.classifier import TaskClassifier
from rigovo.application.master.router import TeamRouter
from rigovo.application.master.enricher import ContextEnricher
from rigovo.application.master.evaluator import AgentEvaluator
from rigovo.application.graph.nodes.finalize import finalize_node
from rigovo.domain.entities.agent import Agent
from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider
from rigovo.domain.interfaces.llm_provider import LLMProvider
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.domain.interfaces.repositories import MemoryRepository
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
        team_agents_by_id: dict[str, list[Agent]] | None = None,
        available_teams: list[dict[str, Any]] | None = None,
        approval_handler: Callable[[TaskState], dict[str, Any]] | None = None,
        auto_approve: bool = True,
        enable_parallel: bool = True,   # ON by default — the magic
        stream_callback: Any | None = None,
        memory_repo: MemoryRepository | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        memory_retriever: MemoryRetriever | None = None,
        classifier: TaskClassifier | None = None,
        router: TeamRouter | None = None,
        enricher: ContextEnricher | None = None,
        evaluator: AgentEvaluator | None = None,
    ) -> None:
        self._llm_factory = llm_factory
        self._master_llm = master_llm
        self._cost_calculator = cost_calculator
        self._quality_gates = quality_gates
        self._agents = agents or []
        self._team_agents_by_id = team_agents_by_id or {}
        self._available_teams = available_teams or []
        self._approval_handler = approval_handler
        self._auto_approve = auto_approve
        self._enable_parallel = enable_parallel
        self._stream_callback = stream_callback
        self._memory_repo = memory_repo
        self._embedding_provider = embedding_provider
        self._memory_retriever = memory_retriever
        self._classifier = classifier
        self._router = router
        self._enricher = enricher
        self._evaluator = evaluator

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
        team_agents_by_id = self._team_agents_by_id
        available_teams = self._available_teams
        auto_approve = self._auto_approve
        approval_handler = self._approval_handler
        stream_cb = self._stream_callback
        memory_repo = self._memory_repo
        embedding_provider = self._embedding_provider
        memory_retriever = self._memory_retriever
        classifier = self._classifier
        router = self._router
        enricher = self._enricher
        evaluator = self._evaluator

        # --- Node wrappers (bind injected deps) ---

        async def _scan_project(state: TaskState) -> dict:
            return await scan_project_node(state)

        async def _classify(state: TaskState) -> dict:
            return await classify_node(state, master_llm, classifier=classifier)

        async def _route_team(state: TaskState) -> dict:
            if not available_teams:
                return {
                    "status": "routed",
                    "events": state.get("events", []) + [{
                        "type": "team_routed",
                        "team_name": "engineering",
                        "reasoning": "No team config provided; using default engineering team.",
                    }],
                }
            return await route_team_node(state, master_llm, available_teams, router=router)

        async def _assemble(state: TaskState) -> dict:
            selected_team_id = str(state.get("team_config", {}).get("team_id", "")).strip()
            selected_agents = team_agents_by_id.get(selected_team_id, agents)
            return await assemble_node(state, agents=selected_agents)

        async def _plan_approval(state: TaskState) -> dict:
            result = await plan_approval_node(state)
            if auto_approve:
                result["approval_status"] = "approved"
            elif approval_handler:
                # Call the approval handler (blocking I/O) in a thread
                handler_result = await asyncio.to_thread(approval_handler, {**state, **result})
                result["approval_status"] = handler_result.get("approval_status", "approved")
                result["approval_feedback"] = handler_result.get("approval_feedback", "")
            return result

        async def _execute_agent(state: TaskState) -> dict:
            return await execute_agent_node(
                state,
                llm_factory,
                cost_calc,
                stream_callback=stream_cb,
                memory_repo=memory_repo,
                embedding_provider=embedding_provider,
                memory_retriever=memory_retriever,
            )

        async def _quality_check(state: TaskState) -> dict:
            return await quality_check_node(state, gates)

        async def _route_next(state: TaskState) -> dict:
            return advance_to_next_agent(state)

        async def _commit_approval(state: TaskState) -> dict:
            result = await commit_approval_node(state)
            if auto_approve:
                result["approval_status"] = "approved"
            elif approval_handler:
                handler_result = await asyncio.to_thread(approval_handler, {**state, **result})
                result["approval_status"] = handler_result.get("approval_status", "approved")
                result["approval_feedback"] = handler_result.get("approval_feedback", "")
            return result

        async def _enrich(state: TaskState) -> dict:
            return await enrich_node(state, enricher=enricher, evaluator=evaluator)

        async def _replan(state: TaskState) -> dict:
            return await replan_node(state, master_llm)

        async def _store_memory(state: TaskState) -> dict:
            return await store_memory_node(
                state,
                master_llm,
                memory_repo=memory_repo,
                embedding_provider=embedding_provider,
            )

        async def _finalize(state: TaskState) -> dict:
            return await finalize_node(state)

        async def _parallel_fan_out(state: TaskState) -> dict:
            """Execute all currently ready parallelizable agents simultaneously."""
            team_config = state.get("team_config", {})
            pipeline_order = team_config.get("pipeline_order", [])
            ready_roles = state.get("ready_roles", [])
            if ready_roles:
                remaining_roles = list(ready_roles)
            else:
                current_index = state.get("current_agent_index", 0)
                remaining_roles = pipeline_order[current_index + 1:]

            # Emit parallel_started event
            events = list(state.get("events", []))
            events.append({
                "type": "parallel_started",
                "roles": remaining_roles,
            })

            result = await execute_agents_parallel(
                {**state, "events": events},
                remaining_roles,
                llm_factory,
                cost_calc,
                stream_cb,
                memory_repo=memory_repo,
                embedding_provider=embedding_provider,
                memory_retriever=memory_retriever,
            )

            # Add parallel_complete event and advance index to end of pipeline
            result_events = list(result.get("events", []))
            result_events.append({"type": "parallel_complete"})
            result["events"] = result_events
            completed_roles = set(state.get("completed_roles", []))
            completed_roles.update(remaining_roles)
            result["completed_roles"] = sorted(completed_roles)

            # Recompute DAG-ready roles after this parallel wave.
            next_update = advance_to_next_agent(
                {
                    **state,
                    **result,
                    "current_agent_role": "",
                    "completed_roles": sorted(completed_roles),
                }
            )
            result.update(next_update)
            return result

        async def _prepare_debate(state: TaskState) -> dict:
            return prepare_debate_round(state)

        # --- Register nodes ---
        graph.add_node("scan_project", _scan_project)
        graph.add_node("classify", _classify)
        graph.add_node("route_team", _route_team)
        graph.add_node("assemble", _assemble)
        graph.add_node("plan_approval", _plan_approval)
        graph.add_node("execute_agent", _execute_agent)
        graph.add_node("quality_check", _quality_check)
        graph.add_node("route_next", _route_next)
        graph.add_node("parallel_fan_out", _parallel_fan_out)
        graph.add_node("debate_check", _prepare_debate)  # Debate prep node
        graph.add_node("commit_approval", _commit_approval)
        graph.add_node("replan", _replan)
        graph.add_node("enrich", _enrich)
        graph.add_node("store_memory", _store_memory)
        graph.add_node("finalize", _finalize)

        # --- Edges ---
        # Pipeline: scan → classify → assemble → plan_approval
        graph.add_edge(START, "scan_project")
        graph.add_edge("scan_project", "classify")
        graph.add_edge("classify", "route_team")
        graph.add_edge("route_team", "assemble")
        graph.add_edge("assemble", "plan_approval")

        graph.add_conditional_edges("plan_approval", check_approval, {
            "approved": "execute_agent",
            "rejected": "finalize",
        })

        # Agent execution → quality gates
        graph.add_edge("execute_agent", "quality_check")

        graph.add_conditional_edges("quality_check", check_gates_and_route, {
            "pass_next_agent": "route_next",
            "fail_fix_loop": "execute_agent",
            "trigger_replan": "replan",
            "fail_max_retries": "finalize",
        })

        graph.add_conditional_edges("replan", check_replan_result, {
            "replan_continue": "execute_agent",
            "replan_failed": "finalize",
        })

        # After routing: sequential, parallel fan-out, debate loop, or done
        graph.add_conditional_edges("route_next", check_parallel_postprocess, {
            "more_agents": "execute_agent",
            "parallel_fan_out": "parallel_fan_out",
            "debate_needed": "debate_check",
            "pipeline_done": "commit_approval",
            "pipeline_failed": "finalize",
        })

        # After parallel fan-out: continue DAG scheduling, or trigger debate loop.
        graph.add_conditional_edges("parallel_fan_out", check_parallel_postprocess, {
            "more_agents": "execute_agent",
            "parallel_fan_out": "parallel_fan_out",
            "pipeline_done": "commit_approval",
            "pipeline_failed": "finalize",
            "debate_needed": "debate_check",
        })

        # Debate check preps coder re-execution with reviewer feedback
        graph.add_edge("debate_check", "execute_agent")

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
        if self._classifier is not None:
            update = await classify_node(state, self._master_llm, classifier=self._classifier)
        else:
            update = await classify_node(state, self._master_llm)
        state.update(update)

        # 2. Route team
        available_teams = available_teams if available_teams is not None else self._available_teams
        if available_teams:
            update = await route_team_node(
                state,
                self._master_llm,
                available_teams,
                router=self._router,
            )
            state.update(update)

        # 3. Assemble pipeline
        selected_team_id = str(state.get("team_config", {}).get("team_id", "")).strip()
        selected_agents = self._team_agents_by_id.get(selected_team_id, self._agents)
        update = await assemble_node(state, selected_agents)
        state.update(update)

        # 4. Plan approval
        update = await plan_approval_node(state)
        state.update(update)
        if self._auto_approve:
            state["approval_status"] = "approved"
        elif self._approval_handler:
            handler_result = await asyncio.to_thread(self._approval_handler, state)
            state["approval_status"] = handler_result.get("approval_status", "approved")
            state["approval_feedback"] = handler_result.get("approval_feedback", "")
        else:
            state["approval_status"] = "approved"

        if state["approval_status"] == "rejected":
            state["status"] = "rejected"
            update = await finalize_node(state)
            state.update(update)
            return state

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
                    memory_repo=self._memory_repo,
                    embedding_provider=self._embedding_provider,
                    memory_retriever=self._memory_retriever,
                )
                state.update(update)
        else:
            await self._run_sequential_agents(state, pipeline_order)

        # 5. Commit approval
        update = await commit_approval_node(state)
        state.update(update)
        if self._auto_approve:
            state["approval_status"] = "approved"
        elif self._approval_handler:
            handler_result = await asyncio.to_thread(self._approval_handler, state)
            state["approval_status"] = handler_result.get("approval_status", "approved")
            state["approval_feedback"] = handler_result.get("approval_feedback", "")
        else:
            state["approval_status"] = "approved"

        if state["approval_status"] == "rejected":
            state["status"] = "rejected"
            update = await finalize_node(state)
            state.update(update)
            return state

        # 6. Enrich
        update = await enrich_node(state, enricher=self._enricher, evaluator=self._evaluator)
        state.update(update)

        # 7. Store memory
        update = await store_memory_node(
            state,
            self._master_llm,
            memory_repo=self._memory_repo,
            embedding_provider=self._embedding_provider,
        )
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
                memory_repo=self._memory_repo,
                embedding_provider=self._embedding_provider,
                memory_retriever=self._memory_retriever,
            )
            state.update(update)

            update = await quality_check_node(state, self._quality_gates)
            state.update(update)

            gate_results = state.get("gate_results", {})
            if not gate_results.get("passed", True):
                retry_count = state.get("retry_count", 0)
                max_retries = state.get("max_retries", 5)

                while retry_count < max_retries and not gate_results.get("passed", True):
                    update = await execute_agent_node(
                        state, self._llm_factory, self._cost_calculator,
                        stream_callback=self._stream_callback,
                        memory_repo=self._memory_repo,
                        embedding_provider=self._embedding_provider,
                        memory_retriever=self._memory_retriever,
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
