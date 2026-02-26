"""TUI Dashboard — Textual-based live terminal interface for Rigovo Teams.

Full replacement for Rich Live (rich_output.py). Provides a real-time,
interactive terminal dashboard that shows:
- Pipeline progress (which stage is active)
- Live streaming output from the active agent
- Agent execution logs (output, tokens, cost per agent)
- Parallel agent execution tracking
- Quality gate results (pass/fail, violations)
- Cost tracking (running total, budget usage)
- Approval prompts (human-in-the-loop via keybindings)
- Final summary on completion

Architecture:
    Textual MUST run in the main thread (it registers signal handlers).
    The graph pipeline runs in a background thread and sends events
    to the Textual app via call_from_thread().

    Approval flow:
    1. Pipeline thread calls approval_handler() which calls
       tui_app.request_approval() — this sets an Event and blocks.
    2. Textual shows the ApprovalPanel with keybinding hints.
    3. User presses 'a' (approve) or 'r' (reject).
    4. Textual sets the result and signals the Event.
    5. Pipeline thread wakes up and reads the result.
"""

from __future__ import annotations

import asyncio
import time
import threading
import logging
from typing import Any, Callable

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static

from rigovo.infrastructure.terminal.widgets import (
    TaskHeader,
    PipelineView,
    StreamingPanel,
    AgentPanel,
    ApprovalPanel,
    CostTracker,
    ROLE_ICONS,
    STATUS_LABELS,
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
logger = logging.getLogger(__name__)


class RigovoDashboard(App[dict[str, Any]]):
    """Live TUI dashboard for monitoring agent pipeline execution.

    MUST run in the main thread (Textual uses signal handlers).
    The pipeline thread calls handle_event() which uses
    call_from_thread() to safely update the UI.
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
        ("d", "toggle_dark", "Dark"),
        ("a", "approve", "Approve"),
        ("r", "reject", "Reject"),
    ]

    def __init__(
        self,
        task_description: str = "",
        project_root: str = "",
        budget: float = 0.0,
        pipeline_runner: Callable[[], dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._task_description = task_description
        self._project_root = project_root
        self._budget = budget
        self._final_result: dict[str, Any] = {}
        self._start_time = time.monotonic()
        self._pipeline_runner = pipeline_runner
        self._pipeline_thread: threading.Thread | None = None
        self._pipeline_error: Exception | None = None

        # Approval synchronization (pipeline thread waits on _approval_event)
        self._approval_event = threading.Event()
        self._approval_result: bool = False
        self._approval_pending = False

    def compose(self) -> ComposeResult:
        yield TaskHeader(
            task_description=self._task_description,
            project_root=self._project_root,
            id="task-header",
        )
        yield PipelineView(id="pipeline")
        yield StreamingPanel(id="streaming")
        yield ApprovalPanel(id="approval")

        with Horizontal(id="main-area"):
            with Vertical(id="left-panel"):
                yield AgentPanel(id="agents")
            yield CostTracker(budget=self._budget, id="costs")

        yield Static(
            "[dim]q[/dim] Quit  [dim]d[/dim] Dark  "
            "[dim]a[/dim] Approve  [dim]r[/dim] Reject",
            id="status-bar",
        )

    def on_mount(self) -> None:
        """Set initial state and start pipeline in background thread."""
        header = self.query_one("#task-header", TaskHeader)
        header.set_status("starting")

        if self._pipeline_runner:
            self._pipeline_thread = threading.Thread(
                target=self._run_pipeline,
                daemon=True,
            )
            self._pipeline_thread.start()

    def _run_pipeline(self) -> None:
        """Run the graph pipeline in a background thread."""
        try:
            result = self._pipeline_runner()
            self._final_result = result
        except Exception as exc:
            self._pipeline_error = exc
        finally:
            time.sleep(0.5)
            try:
                self.call_from_thread(self.exit, self._final_result)
            except Exception as exc:
                logger.debug("Failed to exit dashboard from pipeline thread: %s", exc)

    # ── Approval flow (thread-safe) ──────────────────────────────

    def request_approval(self, checkpoint: str, details: str = "") -> bool:
        """Called from the PIPELINE THREAD. Blocks until user presses a/r.

        1. Show approval panel via call_from_thread
        2. Wait on threading.Event
        3. Return True (approved) or False (rejected)
        """
        self._approval_event.clear()
        self._approval_result = False
        self._approval_pending = True

        # Show the panel on Textual's thread
        self.call_from_thread(self._show_approval_ui, checkpoint, details)

        # Block the pipeline thread until user responds
        self._approval_event.wait()
        self._approval_pending = False
        return self._approval_result

    def _show_approval_ui(self, checkpoint: str, details: str) -> None:
        """Show the approval panel (runs on Textual event loop)."""
        header = self.query_one("#task-header", TaskHeader)
        header.set_status("awaiting_approval")

        approval = self.query_one("#approval", ApprovalPanel)
        approval.show_approval(checkpoint, details)

    def action_approve(self) -> None:
        """Keybinding: 'a' — approve the pending checkpoint."""
        if not self._approval_pending:
            return
        self._approval_result = True
        self._approval_pending = False

        approval = self.query_one("#approval", ApprovalPanel)
        approval.hide_approval()

        header = self.query_one("#task-header", TaskHeader)
        header.set_status("executing")

        agents = self.query_one("#agents", AgentPanel)
        agents.add_info("[green]\u2713 Approved[/green]")

        # Unblock the pipeline thread
        self._approval_event.set()

    def action_reject(self) -> None:
        """Keybinding: 'r' — reject the pending checkpoint."""
        if not self._approval_pending:
            return
        self._approval_result = False
        self._approval_pending = False

        approval = self.query_one("#approval", ApprovalPanel)
        approval.hide_approval()

        header = self.query_one("#task-header", TaskHeader)
        header.set_status("rejected")

        agents = self.query_one("#agents", AgentPanel)
        agents.add_error("Rejected by user")

        # Unblock the pipeline thread
        self._approval_event.set()

    # ── Event handlers called from the pipeline thread ───────────

    def handle_event(self, event: dict[str, Any]) -> None:
        """Thread-safe: forwards to Textual event loop."""
        try:
            self.call_from_thread(self._handle_event_internal, event)
        except Exception as exc:
            logger.debug("Failed to forward dashboard event %s: %s", event.get("type"), exc)

    def _handle_event_internal(self, event: dict[str, Any]) -> None:
        event_type = event.get("type", "")

        stage = EVENT_TO_STAGE.get(event_type)
        if stage:
            pipeline = self.query_one("#pipeline", PipelineView)
            pipeline.set_active(stage)

        handlers = {
            "project_scanned": self._on_project_scanned,
            "task_classified": self._on_classified,
            "pipeline_assembled": self._on_pipeline_assembled,
            "agent_started": self._on_agent_started,
            "agent_streaming": self._on_agent_streaming,
            "agent_complete": self._on_agent_complete,
            "agent_timeout": self._on_agent_timeout,
            "gate_results": self._on_gate_results,
            "approval_requested": self._on_approval_requested,
            "enrichment_extracted": self._on_enrichment,
            "memories_stored": self._on_memories,
            "budget_exceeded": self._on_budget_exceeded,
            "task_finalized": self._on_task_finalized,
            "task_failed": self._on_task_failed,
            "parallel_started": self._on_parallel_started,
            "parallel_complete": self._on_parallel_complete,
        }
        handler = handlers.get(event_type)
        if handler:
            handler(event)

    # ── Individual event handlers ────────────────────────────────

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
        reasoning = event.get("reasoning", "")
        agents.add_info(f"Classified: {task_type} / {complexity}")

        header = self.query_one("#task-header", TaskHeader)
        header.set_classification(task_type, complexity, reasoning)
        header.set_status("classified")

    def _on_pipeline_assembled(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        roles = event.get("roles", [])
        icons = " \u2192 ".join(
            f"{ROLE_ICONS.get(r, chr(0x2699))} {r}" for r in roles
        )
        agents.add_info(f"Pipeline: {icons}")

        header = self.query_one("#task-header", TaskHeader)
        header.set_status("executing")
        header.set_team(", ".join(roles))

    def _on_agent_started(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        agents.add_agent_start(
            role=event.get("role", "?"),
            name=event.get("name", ""),
        )

        streaming = self.query_one("#streaming", StreamingPanel)
        streaming.start_streaming(event.get("role", "?"))

    def _on_agent_streaming(self, event: dict[str, Any]) -> None:
        streaming = self.query_one("#streaming", StreamingPanel)
        streaming.add_chunk(event.get("chunk", ""))

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

        streaming = self.query_one("#streaming", StreamingPanel)
        streaming.stop_streaming()

        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_complete("execute_agent")

    def _on_agent_timeout(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        role = event.get("role", "?")
        timeout = event.get("timeout_seconds", 0)
        agents.add_agent_timeout(role, timeout)

        streaming = self.query_one("#streaming", StreamingPanel)
        streaming.stop_streaming()

    def _on_gate_results(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        passed = event.get("passed", False)
        role = event.get("role", "?")
        violations = event.get("violations", 0)

        if event.get("status") == "skipped":
            agents.add_gate_skipped(role)
        else:
            agents.add_gate_result(role, passed, violations)

        if not passed and event.get("status") != "skipped":
            costs = self.query_one("#costs", CostTracker)
            costs.add_retry()

        pipeline = self.query_one("#pipeline", PipelineView)
        if passed or event.get("status") == "skipped":
            pipeline.set_complete("quality_check")
        else:
            pipeline.set_failed("quality_check")

    def _on_approval_requested(self, event: dict[str, Any]) -> None:
        # This just updates the UI. The actual blocking happens in
        # request_approval() which is called by the approval_handler.
        header = self.query_one("#task-header", TaskHeader)
        header.set_status("awaiting_approval")

        approval = self.query_one("#approval", ApprovalPanel)
        checkpoint = event.get("checkpoint", "")
        details = event.get("details", "")
        approval.show_approval(checkpoint, details)

    def _on_enrichment(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        agents.add_enrichment(
            pitfalls=event.get("pitfall_count", 0),
            patterns=event.get("pattern_count", 0),
        )

        header = self.query_one("#task-header", TaskHeader)
        header.set_status("learning")

        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_complete("enrich")

    def _on_memories(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        count = event.get("count", 0)
        agents.add_memory(count)

        costs = self.query_one("#costs", CostTracker)
        costs.set_memories(count)

        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_complete("store_memory")

    def _on_budget_exceeded(self, event: dict[str, Any]) -> None:
        agents = self.query_one("#agents", AgentPanel)
        agents.add_error(
            f"Budget exceeded: {event.get('tokens_used', 0):,} tokens "
            f"(limit: {event.get('token_limit', 0):,})"
        )

        header = self.query_one("#task-header", TaskHeader)
        header.set_status("budget_exceeded")

    def _on_task_finalized(self, event: dict[str, Any]) -> None:
        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_complete("finalize")

        header = self.query_one("#task-header", TaskHeader)
        status = event.get("status", "completed")
        header.set_status(status)

        agents = self.query_one("#agents", AgentPanel)
        total_cost = event.get("total_cost", 0)
        total_tokens = event.get("total_tokens", 0)
        agents_run = event.get("agents_run", [])
        elapsed = time.monotonic() - self._start_time
        agents.add_info(
            f"[bold green]\u2705 Task complete:[/bold green] "
            f"${total_cost:.4f}, {total_tokens:,} tokens, "
            f"{len(agents_run)} agents, {elapsed:.1f}s"
        )

        self._final_result = event

    def _on_task_failed(self, event: dict[str, Any]) -> None:
        header = self.query_one("#task-header", TaskHeader)
        header.set_status("failed")

        agents = self.query_one("#agents", AgentPanel)
        agents.add_error(event.get("error", "Task failed"))

        pipeline = self.query_one("#pipeline", PipelineView)
        pipeline.set_failed("finalize")

        self._final_result = event

    def _on_parallel_started(self, event: dict[str, Any]) -> None:
        header = self.query_one("#task-header", TaskHeader)
        header.set_status("executing_parallel")

        agents = self.query_one("#agents", AgentPanel)
        roles = event.get("roles", [])
        agents.add_parallel_start(roles)

    def _on_parallel_complete(self, event: dict[str, Any]) -> None:
        header = self.query_one("#task-header", TaskHeader)
        header.set_status("executing")

        agents = self.query_one("#agents", AgentPanel)
        agents.add_parallel_complete()

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark


# ── Helpers ──────────────────────────────────────────────────────


def run_dashboard(
    task_description: str,
    project_root: str = ".",
    budget: float = 0.0,
) -> RigovoDashboard:
    """Create and return a dashboard instance (without pipeline runner)."""
    return RigovoDashboard(
        task_description=task_description,
        project_root=project_root,
        budget=budget,
    )


def print_final_summary(event: dict[str, Any]) -> None:
    """Print the final task summary to the terminal (after TUI exits)."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    status = event.get("status", "?")
    cost = event.get("total_cost", 0)
    tokens = event.get("total_tokens", 0)
    agents = event.get("agents_run", [])
    color = {"completed": "green", "failed": "red", "rejected": "yellow"}.get(
        status, "white"
    )

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Key", style="bold")
    t.add_column("Value")
    t.add_row("Status", f"[{color}]{status.upper()}[/{color}]")
    default_icon = "\u2699"
    t.add_row(
        "Agents",
        " \u2192 ".join(
            f"{ROLE_ICONS.get(r, default_icon)} {r}" for r in agents
        )
        or "\u2014",
    )
    t.add_row("Tokens", f"{tokens:,}")
    t.add_row("Cost", f"${cost:.4f}")

    console.print()
    console.print(
        Panel(
            t,
            title="[bold] Task Complete [/bold]",
            border_style=color,
            padding=(0, 1),
        )
    )
