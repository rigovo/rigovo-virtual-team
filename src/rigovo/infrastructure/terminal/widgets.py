"""TUI dashboard widgets — the building blocks of the live dashboard.

Each widget is a focused, composable Textual widget that displays
one aspect of the agent pipeline execution.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, DataTable, ProgressBar, Label

# --- Stage status indicators ---
STAGE_PENDING = "○"
STAGE_ACTIVE = "◉"
STAGE_COMPLETE = "●"
STAGE_FAILED = "✗"

# --- Pipeline stage display names ---
STAGE_LABELS: dict[str, str] = {
    "scan_project": "Scan",
    "classify": "Classify",
    "assemble": "Assemble",
    "plan_approval": "Approve",
    "execute_agent": "Execute",
    "quality_check": "Gates",
    "enrich": "Enrich",
    "store_memory": "Memory",
    "finalize": "Done",
}


class PipelineStage(Static):
    """Single pipeline stage indicator."""

    status: reactive[str] = reactive("pending")
    label: reactive[str] = reactive("")

    def render(self) -> str:
        icons = {
            "pending": f"[dim]{STAGE_PENDING}[/dim]",
            "active": f"[bold cyan]{STAGE_ACTIVE}[/bold cyan]",
            "complete": f"[green]{STAGE_COMPLETE}[/green]",
            "failed": f"[red]{STAGE_FAILED}[/red]",
        }
        icon = icons.get(self.status, STAGE_PENDING)
        style = "bold" if self.status == "active" else "dim" if self.status == "pending" else ""
        return f"{icon} [{style}]{self.label}[/{style}]" if style else f"{icon} {self.label}"


class PipelineView(Widget):
    """Horizontal pipeline progress view showing all stages."""

    DEFAULT_CSS = """
    PipelineView {
        height: 3;
        padding: 0 1;
        background: $surface;
        border: solid $primary;
    }
    PipelineView Horizontal {
        height: 1;
        align: center middle;
    }
    """

    def __init__(self, stages: list[str] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._stages = stages or list(STAGE_LABELS.keys())
        self._stage_widgets: dict[str, PipelineStage] = {}

    def compose(self) -> ComposeResult:
        with Horizontal():
            for stage_id in self._stages:
                label = STAGE_LABELS.get(stage_id, stage_id)
                widget = PipelineStage(id=f"stage-{stage_id}")
                widget.label = label
                self._stage_widgets[stage_id] = widget
                yield widget

    def set_active(self, stage_id: str) -> None:
        """Set a stage as active and mark previous stages complete."""
        found = False
        for sid, widget in self._stage_widgets.items():
            if sid == stage_id:
                widget.status = "active"
                found = True
            elif not found:
                widget.status = "complete"

    def set_complete(self, stage_id: str) -> None:
        """Mark a specific stage as complete."""
        widget = self._stage_widgets.get(stage_id)
        if widget:
            widget.status = "complete"

    def set_failed(self, stage_id: str) -> None:
        """Mark a specific stage as failed."""
        widget = self._stage_widgets.get(stage_id)
        if widget:
            widget.status = "failed"


class AgentPanel(Widget):
    """Displays current and past agent execution output."""

    DEFAULT_CSS = """
    AgentPanel {
        height: 1fr;
        border: solid $secondary;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("Waiting for agents...", id="agent-log")

    def add_agent_start(self, role: str, name: str) -> None:
        """Log an agent starting execution."""
        self._log_lines.append(f"[bold cyan]▶ {role}[/bold cyan] ({name}) executing...")
        self._refresh_log()

    def add_agent_complete(
        self, role: str, name: str, tokens: int, cost: float, duration_ms: int,
    ) -> None:
        """Log an agent completing execution."""
        duration_s = duration_ms / 1000
        self._log_lines.append(
            f"[green]✓ {role}[/green] ({name}) — "
            f"{tokens:,} tokens, ${cost:.4f}, {duration_s:.1f}s"
        )
        self._refresh_log()

    def add_gate_result(self, role: str, passed: bool, violations: int = 0) -> None:
        """Log quality gate results."""
        if passed:
            self._log_lines.append(f"  [green]✓ Gates passed[/green] for {role}")
        else:
            self._log_lines.append(
                f"  [red]✗ Gates failed[/red] for {role} — {violations} violation(s)"
            )
        self._refresh_log()

    def add_enrichment(self, pitfalls: int, patterns: int) -> None:
        """Log enrichment extraction."""
        self._log_lines.append(
            f"  [magenta]◆ Enrichment:[/magenta] {pitfalls} pitfalls, {patterns} patterns"
        )
        self._refresh_log()

    def add_memory(self, count: int) -> None:
        """Log memory storage."""
        self._log_lines.append(f"  [blue]◆ Stored {count} memories[/blue]")
        self._refresh_log()

    def add_info(self, message: str) -> None:
        """Log a general info message."""
        self._log_lines.append(f"[dim]{message}[/dim]")
        self._refresh_log()

    def add_error(self, message: str) -> None:
        """Log an error message."""
        self._log_lines.append(f"[red bold]✗ {message}[/red bold]")
        self._refresh_log()

    def _refresh_log(self) -> None:
        """Update the display with all log lines."""
        try:
            log_widget = self.query_one("#agent-log", Static)
            log_widget.update("\n".join(self._log_lines[-50:]))  # Keep last 50 lines
        except (LookupError, AttributeError):
            pass  # Widget not yet mounted


class CostTracker(Widget):
    """Real-time cost and token tracking panel."""

    DEFAULT_CSS = """
    CostTracker {
        width: 28;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def __init__(self, budget: float = 0.0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._budget = budget
        self._total_cost: float = 0.0
        self._total_tokens: int = 0
        self._agent_count: int = 0
        self._retry_count: int = 0
        self._elapsed_s: float = 0.0

    def compose(self) -> ComposeResult:
        yield Static(self._render_content(), id="cost-display")

    def update_cost(
        self, cost: float, tokens: int, duration_ms: int = 0,
    ) -> None:
        """Add cost from an agent execution."""
        self._total_cost += cost
        self._total_tokens += tokens
        self._agent_count += 1
        self._elapsed_s += duration_ms / 1000
        self._refresh()

    def add_retry(self) -> None:
        """Record a retry attempt."""
        self._retry_count += 1
        self._refresh()

    def _render_content(self) -> str:
        """Render the cost panel content."""
        lines = [
            "[bold]Cost Tracker[/bold]",
            "",
            f"  Cost:    [bold]${self._total_cost:.4f}[/bold]",
            f"  Tokens:  {self._total_tokens:,}",
            f"  Agents:  {self._agent_count}",
            f"  Retries: {self._retry_count}",
            f"  Time:    {self._elapsed_s:.1f}s",
        ]

        if self._budget > 0:
            pct = (self._total_cost / self._budget) * 100
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            lines.extend([
                "",
                f"  Budget: ${self._budget:.2f}",
                f"  [{bar}] {pct:.0f}%",
            ])

        return "\n".join(lines)

    def _refresh(self) -> None:
        """Update the display."""
        try:
            display = self.query_one("#cost-display", Static)
            display.update(self._render_content())
        except (LookupError, AttributeError):
            pass  # Widget not yet mounted


class TaskHeader(Widget):
    """Task info header bar."""

    DEFAULT_CSS = """
    TaskHeader {
        height: 3;
        background: $primary;
        color: $text;
        padding: 0 2;
    }
    """

    def __init__(
        self,
        task_description: str = "",
        project_root: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._description = task_description
        self._project = project_root
        self._status = "initializing"
        self._team = ""

    def compose(self) -> ComposeResult:
        yield Static(self._render(), id="header-content")

    def set_status(self, status: str) -> None:
        self._status = status
        self._refresh()

    def set_team(self, team: str) -> None:
        self._team = team
        self._refresh()

    def _render(self) -> str:
        desc = self._description[:60] + "..." if len(self._description) > 60 else self._description
        parts = [
            f"[bold]RIGOVO TEAMS[/bold]  │  {desc}  │  "
            f"Status: [bold]{self._status}[/bold]",
        ]
        meta = []
        if self._project:
            meta.append(f"Project: {self._project}")
        if self._team:
            meta.append(f"Team: {self._team}")
        if meta:
            parts.append("  ".join(meta))
        return "\n".join(parts)

    def _refresh(self) -> None:
        try:
            content = self.query_one("#header-content", Static)
            content.update(self._render())
        except (LookupError, AttributeError):
            pass  # Widget not yet mounted
