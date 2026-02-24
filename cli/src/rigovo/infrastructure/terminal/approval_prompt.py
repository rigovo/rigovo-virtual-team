"""Terminal approval prompt — interactive human-in-the-loop."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.prompt import Confirm


class TerminalApprovalHandler:
    """
    Handles approval gates via terminal prompts.

    This is the CLI's implementation of human-in-the-loop.
    The user sees a summary and types Y/N.
    """

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def request_approval(
        self,
        checkpoint: str,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Show approval prompt and wait for user input.

        Returns:
            {"approved": bool, "feedback": str}
        """
        self.console.print()

        if checkpoint == "plan_ready":
            self.console.print("[bold yellow]Plan ready for approval:[/bold yellow]")
            self._show_plan_summary(summary)
        elif checkpoint == "commit_ready":
            self.console.print("[bold yellow]Work complete — ready to commit:[/bold yellow]")
            self._show_commit_summary(summary)
        else:
            self.console.print(f"[bold yellow]Checkpoint: {checkpoint}[/bold yellow]")

        approved = Confirm.ask("\n  Approve?", default=True)

        feedback = ""
        if not approved:
            feedback = self.console.input("  [dim]Feedback (optional):[/dim] ").strip()

        return {"approved": approved, "feedback": feedback}

    def _show_plan_summary(self, summary: dict[str, Any]) -> None:
        task_type = summary.get("task_type", "?")
        complexity = summary.get("complexity", "?")
        team = summary.get("team", "?")
        pipeline = summary.get("pipeline", [])

        self.console.print(f"  Task type: [bold]{task_type}[/bold]")
        self.console.print(f"  Complexity: [bold]{complexity}[/bold]")
        self.console.print(f"  Team: [bold]{team}[/bold]")
        self.console.print(f"  Pipeline: {' → '.join(pipeline)}")

    def _show_commit_summary(self, summary: dict[str, Any]) -> None:
        agents = summary.get("agents_completed", [])
        total_cost = summary.get("total_cost", 0)
        files = summary.get("files_changed", [])

        self.console.print(f"  Agents: {', '.join(agents)}")
        self.console.print(f"  Cost: [bold]${total_cost:.4f}[/bold]")
        if files:
            self.console.print(f"  Files: {len(files)} changed")
            for f in files[:10]:
                self.console.print(f"    {f}")
            if len(files) > 10:
                self.console.print(f"    ... and {len(files) - 10} more")
