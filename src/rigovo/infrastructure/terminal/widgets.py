"""TUI dashboard widgets — the building blocks of the live dashboard.

Each widget is a focused, composable Textual widget that displays
one aspect of the agent pipeline execution.

Full-featured replacement for Rich Live panels.
"""

from __future__ import annotations

import time
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

# --- Role icons (mirrors rich_output.py) ---
ROLE_ICONS: dict[str, str] = {
    "planner": "\U0001f4cb",
    "lead": "\U0001f454",
    "coder": "\U0001f4bb",
    "reviewer": "\U0001f50d",
    "qa": "\U0001f9ea",
    "security": "\U0001f512",
    "docs": "\U0001f4dd",
    "devops": "\U0001f680",
}

# --- Stage status indicators ---
STAGE_PENDING = "\u25cb"     # ○
STAGE_ACTIVE = "\u25c9"      # ◉
STAGE_COMPLETE = "\u25cf"    # ●
STAGE_FAILED = "\u2717"      # ✗

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

# --- Status display labels with colors ---
STATUS_LABELS: dict[str, str] = {
    "initializing": "[dim]\u23f3 Initializing...[/dim]",
    "starting": "[dim]\u23f3 Starting...[/dim]",
    "scanning": "[cyan]\U0001f50d Scanning project...[/cyan]",
    "classifying": "[cyan]\U0001f9e0 Classifying task...[/cyan]",
    "assembling": "[cyan]\U0001f527 Assembling team...[/cyan]",
    "classified": "[cyan]\U0001f9e0 Classified[/cyan]",
    "executing": "[bold cyan]\u26a1 Executing agents...[/bold cyan]",
    "executing_parallel": "[bold magenta]\u26a1 Parallel execution...[/bold magenta]",
    "awaiting_approval": "[bold yellow]\u26a0 Awaiting approval...[/bold yellow]",
    "learning": "[magenta]\U0001f4da Extracting learnings...[/magenta]",
    "completed": "[bold green]\u2705 Completed[/bold green]",
    "failed": "[bold red]\u274c Failed[/bold red]",
    "rejected": "[bold yellow]\u26a0 Rejected[/bold yellow]",
    "budget_exceeded": "[bold red]\U0001f4b0 Budget exceeded[/bold red]",
}

COMPLEXITY_STYLE: dict[str, str] = {
    "low": "green",
    "medium": "yellow",
    "high": "red",
    "critical": "bold red",
}

MAX_STREAM_LINES = 8
STREAM_LINE_WIDTH = 100


# ═══════════════════════════════════════════════════════════════════
# TaskHeader — extends Static, uses render() directly
# ═══════════════════════════════════════════════════════════════════


class TaskHeader(Static):
    """Task info header bar with live elapsed time."""

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
        super().__init__("", **kwargs)
        self._description = task_description
        self._project = project_root
        self._status = "initializing"
        self._team = ""
        self._task_type = ""
        self._complexity = ""
        self._reasoning = ""
        self._start_time = time.monotonic()

    def set_status(self, status: str) -> None:
        self._status = status
        self.update(self._build())

    def set_team(self, team: str) -> None:
        self._team = team
        self.update(self._build())

    def set_classification(self, task_type: str, complexity: str, reasoning: str = "") -> None:
        self._task_type = task_type
        self._complexity = complexity
        self._reasoning = reasoning
        self.update(self._build())

    def _build(self) -> str:
        elapsed = time.monotonic() - self._start_time
        desc = self._description[:60] + "..." if len(self._description) > 60 else self._description
        status_text = STATUS_LABELS.get(self._status, f"[dim]{self._status}[/dim]")

        parts = [
            f"[bold]RIGOVO TEAMS[/bold]  \u2502  {desc}  \u2502  {status_text}  "
            f"[dim]{elapsed:.0f}s[/dim]",
        ]
        meta: list[str] = []
        if self._project:
            meta.append(f"Project: {self._project}")
        if self._team:
            meta.append(f"Team: {self._team}")
        if self._task_type:
            cx_style = COMPLEXITY_STYLE.get(self._complexity, "white")
            meta.append(f"Type: {self._task_type}")
            meta.append(f"Complexity: [{cx_style}]{self._complexity}[/{cx_style}]")
        if meta:
            parts.append("  ".join(meta))
        return "\n".join(parts)

    def on_mount(self) -> None:
        self.update(self._build())


# ═══════════════════════════════════════════════════════════════════
# PipelineStage + PipelineView — horizontal pipeline progress
# ═══════════════════════════════════════════════════════════════════


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
        if self.status == "active":
            return f"{icon} [bold]{self.label}[/bold]"
        elif self.status == "pending":
            return f"{icon} [dim]{self.label}[/dim]"
        elif self.status == "failed":
            return f"{icon} [red]{self.label}[/red]"
        else:
            return f"{icon} {self.label}"


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
            for i, stage_id in enumerate(self._stages):
                label = STAGE_LABELS.get(stage_id, stage_id)
                widget = PipelineStage(id=f"stage-{stage_id}")
                widget.label = label
                self._stage_widgets[stage_id] = widget
                yield widget
                if i < len(self._stages) - 1:
                    yield Static(" [dim]\u2192[/dim] ")

    def set_active(self, stage_id: str) -> None:
        """Set a stage as active and mark previous stages complete."""
        found = False
        for sid, widget in self._stage_widgets.items():
            if sid == stage_id:
                widget.status = "active"
                found = True
            elif not found:
                if widget.status != "failed":
                    widget.status = "complete"

    def set_complete(self, stage_id: str) -> None:
        widget = self._stage_widgets.get(stage_id)
        if widget:
            widget.status = "complete"

    def set_failed(self, stage_id: str) -> None:
        widget = self._stage_widgets.get(stage_id)
        if widget:
            widget.status = "failed"


# ═══════════════════════════════════════════════════════════════════
# StreamingPanel — extends Static, uses update() directly
# ═══════════════════════════════════════════════════════════════════


class StreamingPanel(Static):
    """Live streaming output from the active agent."""

    DEFAULT_CSS = """
    StreamingPanel {
        height: auto;
        max-height: 12;
        border: solid cyan;
        padding: 0 1;
        display: none;
    }
    StreamingPanel.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._active_role = ""
        self._stream_buffer = ""
        self._stream_lines: list[str] = []

    def start_streaming(self, role: str) -> None:
        self._active_role = role
        self._stream_buffer = ""
        self._stream_lines = []
        self.add_class("visible")
        self._update_content()

    def add_chunk(self, chunk: str) -> None:
        self._stream_buffer += chunk
        all_lines = self._stream_buffer.split("\n")
        self._stream_lines = all_lines[-MAX_STREAM_LINES:]
        self._update_content()

    def stop_streaming(self) -> None:
        self._active_role = ""
        self._stream_buffer = ""
        self._stream_lines = []
        self.remove_class("visible")

    def _update_content(self) -> None:
        icon = ROLE_ICONS.get(self._active_role, "\u2699")
        lines: list[str] = []
        for line in self._stream_lines:
            truncated = line[:STREAM_LINE_WIDTH]
            if len(line) > STREAM_LINE_WIDTH:
                truncated += "\u2026"
            lines.append(truncated)
        title = f"[bold cyan]{icon} {self._active_role}[/bold cyan] [dim]streaming...[/dim]"
        text = "\n".join(lines) if lines else "[dim]waiting for output...[/dim]"
        self.update(f"{title}\n[dim]{text}[/dim]")


# ═══════════════════════════════════════════════════════════════════
# AgentPanel — extends Static, uses update() directly
# ═══════════════════════════════════════════════════════════════════


class AgentPanel(Static):
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
        super().__init__("Waiting for agents...", **kwargs)
        self._log_lines: list[str] = []

    def add_agent_start(self, role: str, name: str) -> None:
        icon = ROLE_ICONS.get(role, "\u2699")
        self._log_lines.append(f"[bold cyan]\u25b6 {icon} {role}[/bold cyan] ({name}) executing...")
        self._update_log()

    def add_agent_complete(
        self, role: str, name: str, tokens: int, cost: float, duration_ms: int,
    ) -> None:
        icon = ROLE_ICONS.get(role, "\u2699")
        duration_s = duration_ms / 1000
        self._log_lines.append(
            f"[green]\u2713 {icon} {role}[/green] ({name}) \u2014 "
            f"{tokens:,} tok, ${cost:.4f}, {duration_s:.1f}s"
        )
        self._update_log()

    def add_agent_timeout(self, role: str, timeout_seconds: int) -> None:
        icon = ROLE_ICONS.get(role, "\u2699")
        self._log_lines.append(
            f"[red]\u2717 {icon} {role}[/red] timed out after {timeout_seconds}s"
        )
        self._update_log()

    def add_gate_result(self, role: str, passed: bool, violations: int = 0) -> None:
        if passed:
            self._log_lines.append(f"  [green]\u2713 Gates passed[/green] for {role}")
        else:
            self._log_lines.append(
                f"  [red]\u2717 Gates failed[/red] for {role} \u2014 {violations} violation(s)"
            )
        self._update_log()

    def add_gate_skipped(self, role: str) -> None:
        self._log_lines.append(f"  [dim]\u2298 Gates skipped[/dim] for {role}")
        self._update_log()

    def add_enrichment(self, pitfalls: int, patterns: int) -> None:
        self._log_lines.append(
            f"  [magenta]\u25c6 Enrichment:[/magenta] {pitfalls} pitfalls, {patterns} patterns"
        )
        self._update_log()

    def add_memory(self, count: int) -> None:
        self._log_lines.append(f"  [blue]\u25c6 Stored {count} memories[/blue]")
        self._update_log()

    def add_parallel_start(self, roles: list[str]) -> None:
        icons = " ".join(
            f"{ROLE_ICONS.get(r, chr(0x2699))} {r}" for r in roles
        )
        self._log_lines.append(
            f"[bold magenta]\u26a1 Parallel:[/bold magenta] {icons}"
        )
        self._update_log()

    def add_parallel_complete(self) -> None:
        self._log_lines.append("[magenta]\u2713 Parallel execution complete[/magenta]")
        self._update_log()

    def add_info(self, message: str) -> None:
        self._log_lines.append(f"[dim]{message}[/dim]")
        self._update_log()

    def add_error(self, message: str) -> None:
        self._log_lines.append(f"[red bold]\u2717 {message}[/red bold]")
        self._update_log()

    def _update_log(self) -> None:
        self.update("\n".join(self._log_lines[-50:]))


# ═══════════════════════════════════════════════════════════════════
# CostTracker — extends Static, uses update() directly
# ═══════════════════════════════════════════════════════════════════


class CostTracker(Static):
    """Real-time cost and token tracking panel."""

    DEFAULT_CSS = """
    CostTracker {
        width: 28;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def __init__(self, budget: float = 0.0, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._budget = budget
        self._total_cost: float = 0.0
        self._total_tokens: int = 0
        self._agent_count: int = 0
        self._retry_count: int = 0
        self._elapsed_s: float = 0.0
        self._memories: int = 0

    def on_mount(self) -> None:
        self.update(self._build())

    def update_cost(self, cost: float, tokens: int, duration_ms: int = 0) -> None:
        self._total_cost += cost
        self._total_tokens += tokens
        self._agent_count += 1
        self._elapsed_s += duration_ms / 1000
        self.update(self._build())

    def add_retry(self) -> None:
        self._retry_count += 1
        self.update(self._build())

    def set_memories(self, count: int) -> None:
        self._memories = count
        self.update(self._build())

    def _build(self) -> str:
        lines = [
            "[bold]Cost Tracker[/bold]",
            "",
            f"  Cost:     [bold]${self._total_cost:.4f}[/bold]",
            f"  Tokens:   {self._total_tokens:,}",
            f"  Agents:   {self._agent_count}",
            f"  Retries:  {self._retry_count}",
            f"  Memories: {self._memories}",
            f"  Time:     {self._elapsed_s:.1f}s",
        ]

        if self._budget > 0:
            pct = min((self._total_cost / self._budget) * 100, 100)
            filled = int(pct / 5)
            bar = "\u2588" * filled + "\u2591" * (20 - filled)
            color = "green" if pct < 70 else "yellow" if pct < 90 else "red"
            lines.extend([
                "",
                f"  Budget: ${self._budget:.2f}",
                f"  [{color}][{bar}] {pct:.0f}%[/{color}]",
            ])

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# ApprovalPanel — extends Static, uses update() directly
# ═══════════════════════════════════════════════════════════════════


class ApprovalPanel(Static):
    """Inline approval prompt shown when a checkpoint requires human input."""

    DEFAULT_CSS = """
    ApprovalPanel {
        height: auto;
        border: solid yellow;
        padding: 1 2;
        display: none;
    }
    ApprovalPanel.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._checkpoint = ""
        self._details = ""

    def show_approval(self, checkpoint: str, details: str = "") -> None:
        self._checkpoint = checkpoint
        self._details = details
        self.add_class("visible")
        text = (
            f"[bold yellow]\u26a0 Approval Required[/bold yellow]\n"
            f"[bold]Checkpoint:[/bold] {self._checkpoint}\n"
        )
        if self._details:
            text += f"\n{self._details}\n"
        text += "\n[dim]Press Enter to approve, or type 'reject' to reject[/dim]"
        self.update(text)

    def hide_approval(self) -> None:
        self.remove_class("visible")
