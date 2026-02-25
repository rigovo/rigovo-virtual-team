"""TUI Dashboard — live terminal interface for Rigovo Teams.

Provides a real-time, interactive terminal dashboard that shows:
- Pipeline progress (which stage is active)
- Agent execution logs (output, tokens, cost per agent)
- Quality gate results (pass/fail, violations)
- Cost tracking (running total, budget usage)

Built with Textual for a rich, interactive TUI experience.
The dashboard receives events from the graph execution pipeline
and updates widgets in real-time.
"""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static

from rigovo.infrastructure.terminal.widgets import (
    TaskHeader,
    PipelineView,
    AgentPanel,
    CostTracker,
)

# Map graph events to pipeline stages
EVENT_TO_STAGE: dict[str, str] = {
    "project_scanned": "scan_project",
    "task_classified": "classify",
    "pipeline_assembled": "assemble",
    "approval_requested": "plan_approval",
    "agent_complete": "execute_agent",
    "gate_results": "quality_check",
    "enrichment_extracted": "enrich",
    "memories_stored": "store_memory",
    "task_finalized": "finalize",
}


class RigovoDashboard(App[dict[str, Any]]):
    """Live TUI dashboard for monitoring agent pipeline execution.

    This is the main application class. It receives events from
    the graph execution pipeline and routes them to the appropriate
    widgets for real-time display.
    """

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-area {
        layout: horizontal;
        height: 1fr;
    }
    #left-panel {
        width: 1fr;
    }
    #status-bar {
        height: 1;
        background: $surface;
        padding: 0 2;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "toggle_dark", "Toggle Dark"),
    ]

    def __init__(
        self,
        task_description: str = "",
        project_root: str = "",
        budget: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._task_description = task_description
        self._project_root = project_root
        self._budget = budget
        self._final_result: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield TaskHeader(
            task_description=self._task_description,
            project_root=self._project_root,
            id="task-header",
        )
        yield PipelineView(id="pipeline")

        with Horizontal(id="main-area"):
            with Vertical(id="left-panel"):
                yield AgentPanel(id="agents")
            yield CostTracker(budget=self._budget, id="costs")

        yield Static(
            "[dim]q[/dim] Quit  [dim]d[/dim] Dark mode",
            id="status-bar",
        )

    def on_mount(self) -> None:
        """Set initial state when app mounts."""
        header = self.query_one("#task-header", TaskHeader)
        header.set_status("starting")

    # --- Event handlers called by the graph pipeline ---

    def handle_event(self, event: dict[str, Any]) -> None:
        """Route a pipeline event to the appropriate widget update.

        This is the main entry point for the dashboard. The graph
        execution pipeline calls this with events as they occur.
        """
        event_type = event.get("type", "")

        # Update pipeline stage
        stage = EVENT_TO_STAGE.get(event_type)
        if stage:
            pipeline = self.query_one("#pipeline", PipelineView)
            pipeline.set_active(stage)

        # Route to specific handler
        handlers = {
            "project_scanned": self._on_project_scanned,
            "task_classified": self._on_classified,
            "pipeline_assembled": self._on_pipeline_assembled,
            "agent_started": self._on_agent_started,
            "agent_complete": self._on_agent_complete,
            "agent_timeout": self._on_agent_timeout,
            "gate_results": self._on_gate_results,
            "enrichment_extracted": self._on_enrichment,
            "memories_stored": self._on_memories,
            "budget_exceeded": self._on_budget_exceeded,
            "task_finalized": self._on_task_finalized,
            "task_failed": self._on_task_failed,
        }
        handler = handlers.get(event_type)
        if handler:
            handler(event)

    def _on_project_scanned(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        stack = ", ".join(event.get("tech_stack", []))
        files = event.get("source_files", 0)
        agents.add_info(f"Project scanned: {files} source files, stack: {stack}")

        header = self.query_one("#task-header", TaskHeader)
        header.set_status("scanning")

    def _on_classified(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        task_type = event.get("task_type", "?")
        complexity = event.get("complexity", "?")
        agents.add_info(f"Classified: {task_type} / {complexity}")

        header = self.query_one("#task-header", TaskHeader)
        header.set_status("classified")

    def _on_pipeline_assembled(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        roles = event.get("roles", [])
        agents.add_info(f"Pipeline: {' → '.join(roles)}")

        header = self.query_one("#task-header", TaskHeader)
        header.set_status("executing")
        header.set_team(", ".join(roles))

    def _on_agent_started(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        agents.add_agent_start(
            role=event.get("role", "?"),
            name=event.get("name", ""),
        )

    def _on_agent_complete(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        agents.add_agent_complete(
            role=event.get("role", "?"),
            name=event.get("name", ""),
            tokens=event.get("tokens", 0),
            cost=event.get("cost", 0.0),
            duration_ms=event.get("duration_ms", 0),
        )

        costs = self.query_one("#costs", CostTracker)
        costs.update_cost(
            cost=event.get("cost", 0.0),
            tokens=event.get("tokens", 0),
            duration_ms=event.get("duration_ms", 0),
        )

        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_complete("execute_agent")

    def _on_agent_timeout(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        role = event.get("role", "?")
        timeout = event.get("timeout_seconds", 0)
        agents.add_error(f"Agent '{role}' timed out after {timeout}s")

    def _on_gate_results(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        passed = event.get("passed", False)
        role = event.get("role", "?")
        violations = event.get("violations", 0)
        agents.add_gate_result(role, passed, violations)

        if not passed:
            costs = self.query_one("#costs", CostTracker)
            costs.add_retry()

        pipeline = self.query_one("#pipeline", PipelineView)
        if passed:
            pipeline.set_complete("quality_check")
        else:
            pipeline.set_failed("quality_check")

    def _on_enrichment(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        agents.add_enrichment(
            pitfalls=event.get("pitfall_count", 0),
            patterns=event.get("pattern_count", 0),
        )

        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_complete("enrich")

    def _on_memories(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        agents.add_memory(event.get("count", 0))

        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_complete("store_memory")

    def _on_budget_exceeded(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        agents.add_error(
            f"Budget exceeded: {event.get('tokens_used', 0):,} tokens "
            f"(limit: {event.get('token_limit', 0):,})"
        )

    def _on_task_finalized(self, event: dict[str, Any]) -> None:
        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_complete("finalize")

        header = self.query_one("#task-header", TaskHeader)
        status = event.get("status", "completed")
        header.set_status(status)

        agents = self.query_one("#agents", AgentPanel)
        total_cost = event.get("total_cost", 0)
        total_tokens = event.get("total_tokens", 0)
        agents.add_info(
            f"[bold green]Task complete:[/bold green] "
            f"${total_cost:.4f}, {total_tokens:,} tokens"
        )

        self._final_result = event

    def _on_task_failed(self, event: dict[str, Any]) -> None:
        header = self.query_one("#task-header", TaskHeader)
        header.set_status("failed")

        agents = self.query_one("#agents", AgentPanel)
        agents.add_error(event.get("error", "Task failed"))

        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_failed("finalize")

    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.dark = not self.dark


def run_dashboard(
    task_description: str,
    project_root: str = ".",
    budget: float = 0.0,
) -> RigovoDashboard:
    """Create and return a dashboard instance.

    The caller is responsible for:
    1. Starting the dashboard with `app.run()`
    2. Feeding events via `app.handle_event(event)`
    """
    return RigovoDashboard(
        task_description=task_description,
        project_root=project_root,
        budget=budget,
    )
