"""Rich terminal output — real-time agent status display."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class TerminalUI:
    """Rich terminal interface for displaying task execution status."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def show_classification(self, event: dict[str, Any]) -> None:
        """Display task classification result."""
        task_type = event.get("task_type", "unknown")
        complexity = event.get("complexity", "unknown")
        reasoning = event.get("reasoning", "")

        color_map = {"low": "green", "medium": "yellow", "high": "red", "critical": "bold red"}
        color = color_map.get(complexity, "white")

        self.console.print()
        self.console.print(f"  [bold]Task type:[/bold] {task_type}")
        self.console.print(f"  [bold]Complexity:[/bold] [{color}]{complexity}[/{color}]")
        if reasoning:
            self.console.print(f"  [dim]{reasoning}[/dim]")

    def show_pipeline(self, event: dict[str, Any]) -> None:
        """Display the assembled pipeline."""
        roles = event.get("roles", [])
        gates_after = event.get("gates_after", [])

        self.console.print()
        self.console.print("[bold]Pipeline:[/bold]")
        for i, role in enumerate(roles):
            gate_marker = " [dim](+ quality gates)[/dim]" if role in gates_after else ""
            arrow = "  " if i == 0 else "  → "
            self.console.print(f"{arrow}[cyan]{role}[/cyan]{gate_marker}")

    def show_agent_complete(self, event: dict[str, Any]) -> None:
        """Display an agent's completion status."""
        role = event.get("role", "?")
        name = event.get("name", "")
        tokens = event.get("tokens", 0)
        cost = event.get("cost", 0.0)
        duration_ms = event.get("duration_ms", 0)

        duration_s = duration_ms / 1000 if duration_ms else 0
        self.console.print(
            f"  [green]✓[/green] [bold]{role}[/bold]"
            f" ({name}) — {tokens:,} tokens, ${cost:.4f}, {duration_s:.1f}s"
        )

    def show_gate_results(self, event: dict[str, Any]) -> None:
        """Display quality gate results."""
        passed = event.get("passed", False)
        violations = event.get("violations", 0)
        role = event.get("role", "")

        if event.get("status") == "skipped":
            self.console.print(f"  [dim]⊘ Gates skipped for {role}[/dim]")
        elif passed:
            self.console.print(f"  [green]✓ Gates passed[/green] for {role}")
        else:
            self.console.print(
                f"  [red]✗ Gates failed[/red] for {role} — {violations} violation(s)"
            )

    def show_approval_request(self, event: dict[str, Any]) -> None:
        """Display approval request."""
        checkpoint = event.get("checkpoint", "")
        summary = event.get("summary", {})

        panel_content = []
        if checkpoint == "plan_ready":
            panel_content.append(f"Task type: {summary.get('task_type', '?')}")
            panel_content.append(f"Complexity: {summary.get('complexity', '?')}")
            panel_content.append(f"Team: {summary.get('team', '?')}")
            pipeline = summary.get("pipeline", [])
            panel_content.append(f"Pipeline: {' → '.join(pipeline)}")
        elif checkpoint == "commit_ready":
            agents = summary.get("agents_completed", [])
            panel_content.append(f"Agents: {', '.join(agents)}")
            panel_content.append(f"Total cost: ${summary.get('total_cost', 0):.4f}")
            files = summary.get("files_changed", [])
            if files:
                panel_content.append(f"Files changed: {len(files)}")

        self.console.print()
        self.console.print(Panel(
            "\n".join(panel_content),
            title=f"[bold yellow]Approval Required: {checkpoint}[/bold yellow]",
            border_style="yellow",
        ))

    def show_task_complete(self, event: dict[str, Any]) -> None:
        """Display task completion summary."""
        status = event.get("status", "?")
        total_cost = event.get("total_cost", 0)
        total_tokens = event.get("total_tokens", 0)
        agents_run = event.get("agents_run", [])
        retries = event.get("retries", 0)
        memories = event.get("memories_stored", 0)

        status_colors = {
            "completed": "green",
            "failed": "red",
            "rejected": "yellow",
        }
        color = status_colors.get(status, "white")

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        table.add_row("Status", f"[{color}]{status}[/{color}]")
        table.add_row("Agents", ", ".join(agents_run))
        table.add_row("Tokens", f"{total_tokens:,}")
        table.add_row("Cost", f"${total_cost:.4f}")
        if retries:
            table.add_row("Retries", str(retries))
        if memories:
            table.add_row("Memories stored", str(memories))

        self.console.print()
        self.console.print(Panel(table, title="[bold]Task Complete[/bold]"))

    def handle_event(self, event: dict[str, Any]) -> None:
        """Route an event to the appropriate display method."""
        handlers = {
            "task_classified": self.show_classification,
            "pipeline_assembled": self.show_pipeline,
            "agent_complete": self.show_agent_complete,
            "gate_results": self.show_gate_results,
            "approval_requested": self.show_approval_request,
            "task_finalized": self.show_task_complete,
        }
        event_type = event.get("type", "")
        handler = handlers.get(event_type)
        if handler:
            handler(event)
