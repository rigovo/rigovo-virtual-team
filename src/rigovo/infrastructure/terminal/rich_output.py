"""Rich terminal output — real-time live dashboard for agent execution.

Features:
- Live pipeline progress with per-agent status icons
- Real-time streaming text from active agent
- Interactive approval prompts (--approve mode)
- Parallel agent execution display
- Agent results table with tokens, cost, duration
- Quality gate log
- Cost summary bar
"""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# --- Display constants ---
ROLE_ICONS = {
    "planner": "\U0001f4cb", "lead": "\U0001f454", "coder": "\U0001f4bb",
    "reviewer": "\U0001f50d", "qa": "\U0001f9ea", "security": "\U0001f512",
    "docs": "\U0001f4dd", "devops": "\U0001f680",
}
COMPLEXITY_STYLE = {
    "low": "green", "medium": "yellow",
    "high": "red", "critical": "bold red",
}
BORDER_STYLE = "blue"
MAX_LOG_LINES = 12
MAX_STREAM_LINES = 8
STREAM_LINE_WIDTH = 100


class TerminalUI:
    """Live Rich dashboard for Rigovo task execution."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self._live: Live | None = None
        self._start_time = time.monotonic()

        # State
        self._description = ""
        self._task_type = ""
        self._complexity = ""
        self._reasoning = ""
        self._pipeline_roles: list[str] = []
        self._gates_after: list[str] = []
        self._active_role = ""
        self._agent_results: list[dict[str, Any]] = []
        self._gate_log: list[str] = []
        self._total_tokens = 0
        self._total_cost = 0.0
        self._status = "initializing"
        self._final_event: dict[str, Any] | None = None
        self._memories_stored = 0
        self._retries = 0

        # Streaming text buffer (item 2 + 7)
        self._stream_buffer = ""
        self._stream_lines: list[str] = []

        # Parallel agent tracking (item 8)
        self._parallel_active: list[str] = []

        # Approval state (item 4)
        self._approval_pending = False
        self._approval_checkpoint = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, description: str, team: str | None = None) -> None:
        """Start the live display."""
        self._description = description
        self._start_time = time.monotonic()
        self._status = "scanning"
        self._live = Live(
            self._build_layout(),
            console=self.console,
            refresh_per_second=8,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the live display and print final summary."""
        if self._live:
            self._live.stop()
            self._live = None
        if self._final_event:
            self._print_final_summary(self._final_event)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_event(self, event: dict[str, Any]) -> None:
        """Route event and refresh the live display."""
        event_type = event.get("type", "")
        handler = {
            "project_scanned": self._on_scanned,
            "task_classified": self._on_classified,
            "pipeline_assembled": self._on_assembled,
            "agent_started": self._on_agent_started,
            "agent_streaming": self._on_agent_streaming,
            "agent_complete": self._on_agent_complete,
            "agent_timeout": self._on_agent_timeout,
            "gate_results": self._on_gate_results,
            "approval_requested": self._on_approval,
            "enrichment_extracted": self._on_enrichment,
            "memories_stored": self._on_memories,
            "budget_exceeded": self._on_budget_exceeded,
            "task_finalized": self._on_finalized,
            "task_failed": self._on_failed,
            "parallel_started": self._on_parallel_started,
            "parallel_complete": self._on_parallel_complete,
        }.get(event_type)

        if handler:
            handler(event)
        self._refresh()

    def _on_scanned(self, e: dict) -> None:
        self._status = "classifying"

    def _on_classified(self, e: dict) -> None:
        self._task_type = e.get("task_type", "")
        self._complexity = e.get("complexity", "")
        self._reasoning = e.get("reasoning", "")
        self._status = "assembling"

    def _on_assembled(self, e: dict) -> None:
        self._pipeline_roles = e.get("roles", [])
        self._gates_after = e.get("gates_after", [])
        self._status = "executing"

    def _on_agent_started(self, e: dict) -> None:
        self._active_role = e.get("role", "")
        self._stream_buffer = ""
        self._stream_lines = []

    def _on_agent_streaming(self, e: dict) -> None:
        """Handle streaming token chunks from active agent."""
        chunk = e.get("chunk", "")
        self._stream_buffer += chunk
        # Split into lines for display, keeping last N
        all_lines = self._stream_buffer.split("\n")
        self._stream_lines = all_lines[-MAX_STREAM_LINES:]

    def _on_agent_complete(self, e: dict) -> None:
        self._agent_results.append(e)
        self._total_tokens += e.get("tokens", 0)
        self._total_cost += e.get("cost", 0.0)
        self._active_role = ""
        self._stream_buffer = ""
        self._stream_lines = []

    def _on_agent_timeout(self, e: dict) -> None:
        self._agent_results.append({**e, "_timed_out": True})
        self._active_role = ""
        self._stream_buffer = ""
        self._stream_lines = []

    def _on_gate_results(self, e: dict) -> None:
        role = e.get("role", "")
        if e.get("status") == "skipped":
            self._gate_log.append(f"[dim]\u2298 {role}: skipped[/dim]")
        elif e.get("passed"):
            self._gate_log.append(f"[green]\u2713 {role}: passed[/green]")
        else:
            self._gate_log.append(
                f"[red]\u2717 {role}: {e.get('violations', 0)} violations[/red]"
            )
            self._retries += 1

    def _on_approval(self, e: dict) -> None:
        self._approval_pending = True
        self._approval_checkpoint = e.get("checkpoint", "")
        self._status = "awaiting_approval"

    def _on_enrichment(self, e: dict) -> None:
        self._status = "learning"

    def _on_memories(self, e: dict) -> None:
        self._memories_stored = e.get("count", 0)

    def _on_budget_exceeded(self, e: dict) -> None:
        self._status = "budget_exceeded"

    def _on_finalized(self, e: dict) -> None:
        self._status = e.get("status", "completed")
        self._final_event = e

    def _on_failed(self, e: dict) -> None:
        self._status = "failed"
        self._final_event = e

    def _on_parallel_started(self, e: dict) -> None:
        self._parallel_active = e.get("roles", [])
        self._status = "executing_parallel"

    def _on_parallel_complete(self, e: dict) -> None:
        self._parallel_active = []

    # ------------------------------------------------------------------
    # Layout builder
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._build_layout())

    def _build_layout(self) -> Group:
        """Build the full dashboard layout."""
        parts: list[Any] = []

        # Header
        parts.append(self._build_header())

        # Pipeline progress (once assembled)
        if self._pipeline_roles:
            parts.append(self._build_pipeline_panel())

        # Streaming text from active agent (items 2+7)
        if self._stream_lines and self._active_role:
            parts.append(self._build_streaming_panel())

        # Agent results + gates side-by-side
        if self._agent_results or self._gate_log:
            parts.append(self._build_agents_panel())

        # Approval prompt (item 4)
        if self._approval_pending:
            parts.append(self._build_approval_panel())

        # Cost bar
        if self._total_tokens > 0:
            parts.append(self._build_cost_bar())

        return Group(*parts)

    def _build_header(self) -> Panel:
        """Task header with classification info."""
        elapsed = time.monotonic() - self._start_time
        status_text = self._status_label()

        header = Table.grid(padding=(0, 2))
        header.add_column(ratio=3)
        header.add_column(ratio=1, justify="right")

        left_parts = [f"[bold]{self._description}[/bold]"]
        if self._task_type:
            cx_style = COMPLEXITY_STYLE.get(self._complexity, "white")
            left_parts.append(
                f"[dim]Type:[/dim] {self._task_type}  "
                f"[dim]Complexity:[/dim] [{cx_style}]{self._complexity}[/{cx_style}]"
            )
        if self._reasoning:
            left_parts.append(f"[dim italic]{self._reasoning}[/dim italic]")

        right_parts = [status_text, f"[dim]{elapsed:.0f}s elapsed[/dim]"]
        header.add_row("\n".join(left_parts), "\n".join(right_parts))

        return Panel(
            header,
            title="[bold blue]  RIGOVO  [/bold blue]",
            border_style=BORDER_STYLE,
            padding=(0, 1),
        )

    def _build_pipeline_panel(self) -> Panel:
        """Horizontal pipeline with per-agent status."""
        completed_roles = {r.get("role") for r in self._agent_results}
        parts: list[str] = []

        for i, role in enumerate(self._pipeline_roles):
            icon = ROLE_ICONS.get(role, "\u2699")
            if role in completed_roles:
                result = next(
                    (r for r in self._agent_results if r.get("role") == role), {}
                )
                if result.get("_timed_out"):
                    badge = f"[red]{icon} {role} \u2717[/red]"
                else:
                    badge = f"[green]{icon} {role} \u2713[/green]"
            elif role == self._active_role:
                badge = f"[bold cyan]{icon} {role} \u25cf[/bold cyan]"
            elif role in self._parallel_active:
                badge = f"[bold magenta]{icon} {role} \u25cb[/bold magenta]"
            else:
                badge = f"[dim]{icon} {role}[/dim]"

            parts.append(badge)
            if i < len(self._pipeline_roles) - 1:
                parts.append("[dim]\u2192[/dim]")

        pipeline_text = "  ".join(parts)
        done = len(completed_roles)
        total = len(self._pipeline_roles)
        pct = f"[dim]{done}/{total} agents[/dim]"

        return Panel(
            f"{pipeline_text}   {pct}",
            title="[bold]Pipeline[/bold]",
            border_style="cyan",
            padding=(0, 1),
        )

    def _build_streaming_panel(self) -> Panel:
        """Live streaming output from the active agent."""
        icon = ROLE_ICONS.get(self._active_role, "\u2699")
        lines = []
        for line in self._stream_lines:
            truncated = line[:STREAM_LINE_WIDTH]
            if len(line) > STREAM_LINE_WIDTH:
                truncated += "\u2026"
            lines.append(truncated)
        stream_text = "\n".join(lines)
        return Panel(
            f"[dim]{stream_text}[/dim]",
            title=f"[bold cyan]{icon} {self._active_role}[/bold cyan] [dim]streaming...[/dim]",
            border_style="cyan",
            padding=(0, 1),
        )

    def _build_agents_panel(self) -> Panel:
        """Agent execution results table + gate log."""
        grid = Table.grid(padding=(0, 2))
        grid.add_column(ratio=3)
        grid.add_column(ratio=1)

        agent_table = Table(
            show_header=True, header_style="bold",
            box=None, padding=(0, 1), expand=True,
        )
        agent_table.add_column("Agent", style="cyan")
        agent_table.add_column("Tokens", justify="right")
        agent_table.add_column("Cost", justify="right")
        agent_table.add_column("Time", justify="right")
        agent_table.add_column("", width=3)

        for result in self._agent_results:
            role = result.get("role", "?")
            icon = ROLE_ICONS.get(role, "\u2699")
            tokens = result.get("tokens", 0)
            cost = result.get("cost", 0.0)
            duration_ms = result.get("duration_ms", 0)
            duration_s = duration_ms / 1000 if duration_ms else 0

            if result.get("_timed_out"):
                agent_table.add_row(
                    f"{icon} {role}", "\u2014", "\u2014",
                    "[red]timeout[/red]", "[red]\u2717[/red]",
                )
            else:
                agent_table.add_row(
                    f"{icon} {role}",
                    f"{tokens:,}",
                    f"${cost:.4f}",
                    f"{duration_s:.1f}s",
                    "[green]\u2713[/green]",
                )

        # Show active agent with spinner
        if self._active_role:
            icon = ROLE_ICONS.get(self._active_role, "\u2699")
            agent_table.add_row(
                f"[bold cyan]{icon} {self._active_role}[/bold cyan]",
                "[cyan]...[/cyan]", "", "",
                "[cyan]\u25cf[/cyan]",
            )

        # Show parallel agents
        for role in self._parallel_active:
            if role != self._active_role:
                icon = ROLE_ICONS.get(role, "\u2699")
                agent_table.add_row(
                    f"[bold magenta]{icon} {role}[/bold magenta]",
                    "[magenta]...[/magenta]", "", "",
                    "[magenta]\u25cb[/magenta]",
                )

        gate_text = (
            "\n".join(self._gate_log[-MAX_LOG_LINES:])
            if self._gate_log
            else "[dim]No gates run yet[/dim]"
        )
        grid.add_row(agent_table, gate_text)

        return Panel(
            grid,
            title="[bold]Agents[/bold]  \u2502  [bold]Quality Gates[/bold]",
            border_style="green",
            padding=(0, 1),
        )

    def _build_approval_panel(self) -> Panel:
        """Show pending approval prompt."""
        return Panel(
            f"[bold yellow]Waiting for approval at checkpoint: "
            f"{self._approval_checkpoint}[/bold yellow]\n"
            "[dim]Press Enter to approve, or type 'reject' to reject[/dim]",
            title="[bold yellow]\u26a0 Approval Required[/bold yellow]",
            border_style="yellow",
            padding=(0, 1),
        )

    def _build_cost_bar(self) -> Text:
        """Compact cost summary line."""
        return Text.from_markup(
            f"  [dim]Tokens:[/dim] [bold]{self._total_tokens:,}[/bold]"
            f"  [dim]Cost:[/dim] [bold]${self._total_cost:.4f}[/bold]"
            f"  [dim]Retries:[/dim] {self._retries}"
            f"  [dim]Memories:[/dim] {self._memories_stored}"
        )

    def _status_label(self) -> str:
        """Current status with color."""
        labels = {
            "initializing": "[dim]\u23f3 Initializing...[/dim]",
            "scanning": "[cyan]\U0001f50d Scanning project...[/cyan]",
            "classifying": "[cyan]\U0001f9e0 Classifying task...[/cyan]",
            "assembling": "[cyan]\U0001f527 Assembling team...[/cyan]",
            "executing": "[bold cyan]\u26a1 Executing agents...[/bold cyan]",
            "executing_parallel": "[bold magenta]\u26a1 Parallel execution...[/bold magenta]",
            "awaiting_approval": "[bold yellow]\u26a0 Awaiting approval...[/bold yellow]",
            "learning": "[magenta]\U0001f4da Extracting learnings...[/magenta]",
            "completed": "[bold green]\u2705 Completed[/bold green]",
            "failed": "[bold red]\u274c Failed[/bold red]",
            "rejected": "[bold yellow]\u26a0 Rejected[/bold yellow]",
            "budget_exceeded": "[bold red]\U0001f4b0 Budget exceeded[/bold red]",
        }
        return labels.get(self._status, f"[dim]{self._status}[/dim]")

    # ------------------------------------------------------------------
    # Interactive approval (item 4)
    # ------------------------------------------------------------------

    def prompt_approval(self, checkpoint: str, details: str = "") -> bool:
        """Pause live display and prompt user for approval. Returns True if approved."""
        if self._live:
            self._live.stop()

        self.console.print()
        self.console.print(
            Panel(
                f"[bold]Checkpoint:[/bold] {checkpoint}\n"
                + (f"\n{details}\n" if details else "")
                + "\n[dim]Type 'approve' or press Enter to approve, 'reject' to reject[/dim]",
                title="[bold yellow]\u26a0 Approval Required[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            )
        )
        try:
            response = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            response = "reject"

        approved = response in ("", "approve", "yes", "y", "ok")
        status = "approved" if approved else "rejected"
        color = "green" if approved else "red"
        self.console.print(f"  [{color}]{status.upper()}[/{color}]\n")

        self._approval_pending = False
        if self._live is None and approved:
            self._live = Live(
                self._build_layout(),
                console=self.console,
                refresh_per_second=8,
                transient=False,
            )
            self._live.start()

        return approved

    # ------------------------------------------------------------------
    # Final summary (printed after live display stops)
    # ------------------------------------------------------------------

    def _print_final_summary(self, event: dict[str, Any]) -> None:
        """Print the final task summary after live display ends."""
        status = event.get("status", "?")
        cost = event.get("total_cost", self._total_cost)
        tokens = event.get("total_tokens", self._total_tokens)
        agents = event.get("agents_run", [])
        elapsed = time.monotonic() - self._start_time
        color = {"completed": "green", "failed": "red", "rejected": "yellow"}.get(
            status, "white"
        )

        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column("Key", style="bold")
        t.add_column("Value")
        t.add_row("Status", f"[{color}]{status.upper()}[/{color}]")
        t.add_row("Duration", f"{elapsed:.1f}s")
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
        if self._retries:
            t.add_row("Retries", str(self._retries))
        if self._memories_stored:
            t.add_row("Memories", f"{self._memories_stored} stored")

        self.console.print()
        self.console.print(
            Panel(
                t,
                title="[bold] Task Complete [/bold]",
                border_style=color,
                padding=(0, 1),
            )
        )
