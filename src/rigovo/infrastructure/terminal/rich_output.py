"""Streaming terminal output — REPL-style interface for agent execution.

Inspired by Claude Code CLI and Gemini CLI: no Rich Live dashboard,
no panels-within-panels. Just stream output directly to the terminal
as events happen. The user sees exactly what each agent is doing
in real-time.

Architecture:
    - Events arrive via handle_event() from the pipeline
    - Each event prints immediately to the console (no buffering)
    - Streaming chunks print inline without newlines (like typing)
    - Approval prompts use plain input() — no hacks needed
    - Final summary prints a clean table at the end
"""

from __future__ import annotations

import sys
import time
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
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


class TerminalUI:
    """Streaming terminal UI for Rigovo task execution.

    No Rich Live. No panels refreshing 8x/second. Just print events
    as they happen, stream agent output inline, and show results.
    Like Claude Code and Gemini CLI.
    """

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self._start_time = time.monotonic()
        self._total_tokens = 0
        self._total_cost = 0.0
        self._retries = 0
        self._memories_stored = 0
        self._active_role = ""
        self._streaming = False
        self._final_event: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, description: str, team: str | None = None) -> None:
        """Print the task header and start."""
        self._start_time = time.monotonic()
        self.console.print()
        self.console.print(
            f"[bold blue]RIGOVO[/bold blue] [dim]\u2502[/dim] {description}"
        )
        if team:
            self.console.print(f"  [dim]Team:[/dim] {team}")
        self.console.print()

    def stop(self) -> None:
        """Print final summary."""
        self._end_stream()
        if self._final_event:
            self._print_final_summary(self._final_event)

    # ------------------------------------------------------------------
    # Event router
    # ------------------------------------------------------------------

    def handle_event(self, event: dict[str, Any]) -> None:
        """Route event and print immediately."""
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

    # ------------------------------------------------------------------
    # Individual event handlers — each prints immediately
    # ------------------------------------------------------------------

    def _on_scanned(self, e: dict) -> None:
        stack = ", ".join(e.get("tech_stack", []))
        files = e.get("source_files", 0)
        self.console.print(
            f"  [cyan]\U0001f50d Scanned:[/cyan] {files} files"
            + (f" [dim]({stack})[/dim]" if stack else "")
        )

    def _on_classified(self, e: dict) -> None:
        task_type = e.get("task_type", "?")
        complexity = e.get("complexity", "?")
        reasoning = e.get("reasoning", "")
        cx_style = COMPLEXITY_STYLE.get(complexity, "white")
        self.console.print(
            f"  [cyan]\U0001f9e0 Classified:[/cyan] {task_type} "
            f"[{cx_style}]({complexity})[/{cx_style}]"
        )
        if reasoning:
            self.console.print(f"     [dim italic]{reasoning}[/dim italic]")

    def _on_assembled(self, e: dict) -> None:
        roles = e.get("roles", [])
        pipeline_str = " [dim]\u2192[/dim] ".join(
            f"{ROLE_ICONS.get(r, chr(0x2699))} [bold]{r}[/bold]" for r in roles
        )
        self.console.print(f"  [cyan]\U0001f527 Pipeline:[/cyan] {pipeline_str}")
        self.console.print()

    def _on_agent_started(self, e: dict) -> None:
        self._end_stream()
        role = e.get("role", "?")
        name = e.get("name", "")
        icon = ROLE_ICONS.get(role, "\u2699")
        self._active_role = role
        self._streaming = False

        self.console.print(Rule(
            f"[bold cyan]{icon} {role}[/bold cyan]"
            + (f" [dim]({name})[/dim]" if name else ""),
            style="cyan",
        ))

    def _on_agent_streaming(self, e: dict) -> None:
        """Print streaming chunks directly — like Claude Code typing effect."""
        chunk = e.get("chunk", "")
        if not chunk:
            return

        if not self._streaming:
            self._streaming = True
            # Start with a dim indicator
            sys.stdout.write("  ")

        # Write chunk directly to stdout for real-time streaming
        # No Rich markup here — raw text so it appears immediately
        sys.stdout.write(chunk)
        sys.stdout.flush()

    def _end_stream(self) -> None:
        """End any active streaming output with a newline."""
        if self._streaming:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._streaming = False

    def _on_agent_complete(self, e: dict) -> None:
        self._end_stream()
        role = e.get("role", "?")
        icon = ROLE_ICONS.get(role, "\u2699")
        tokens = e.get("tokens", 0)
        cost = e.get("cost", 0.0)
        duration_ms = e.get("duration_ms", 0)
        duration_s = duration_ms / 1000 if duration_ms else 0

        self._total_tokens += tokens
        self._total_cost += cost
        self._active_role = ""

        self.console.print(
            f"  [green]\u2713 {icon} {role}[/green] "
            f"[dim]{tokens:,} tok \u2502 ${cost:.4f} \u2502 {duration_s:.1f}s[/dim]"
        )
        self.console.print()

    def _on_agent_timeout(self, e: dict) -> None:
        self._end_stream()
        role = e.get("role", "?")
        icon = ROLE_ICONS.get(role, "\u2699")
        timeout = e.get("timeout_seconds", 0)
        self._active_role = ""
        self.console.print(
            f"  [red]\u2717 {icon} {role} timed out[/red] after {timeout}s"
        )
        self.console.print()

    def _on_gate_results(self, e: dict) -> None:
        role = e.get("role", "?")
        if e.get("status") == "skipped":
            self.console.print(f"  [dim]\u2298 Gates skipped for {role}[/dim]")
        elif e.get("passed"):
            self.console.print(f"  [green]\u2713 Gates passed[/green] for {role}")
        else:
            violations = e.get("violations", 0)
            self._retries += 1
            self.console.print(
                f"  [red]\u2717 Gates failed[/red] for {role} "
                f"[dim]({violations} violations, retry {self._retries})[/dim]"
            )

    def _on_approval(self, e: dict) -> None:
        # Just a visual indicator — actual approval happens via approval_handler
        checkpoint = e.get("checkpoint", "")
        self.console.print(
            f"\n  [bold yellow]\u26a0 Approval checkpoint:[/bold yellow] {checkpoint}"
        )

    def _on_enrichment(self, e: dict) -> None:
        pitfalls = e.get("pitfall_count", 0)
        patterns = e.get("pattern_count", 0)
        self.console.print(
            f"  [magenta]\U0001f4da Enrichment:[/magenta] "
            f"{pitfalls} pitfalls, {patterns} patterns"
        )

    def _on_memories(self, e: dict) -> None:
        count = e.get("count", 0)
        self._memories_stored = count
        self.console.print(f"  [blue]\U0001f4be Stored {count} memories[/blue]")

    def _on_budget_exceeded(self, e: dict) -> None:
        tokens_used = e.get("tokens_used", 0)
        token_limit = e.get("token_limit", 0)
        self.console.print(
            f"\n  [bold red]\U0001f4b0 Budget exceeded![/bold red] "
            f"{tokens_used:,} / {token_limit:,} tokens"
        )

    def _on_finalized(self, e: dict) -> None:
        self._final_event = e

    def _on_failed(self, e: dict) -> None:
        error = e.get("error", "Unknown error")
        self.console.print(f"\n  [bold red]\u274c Failed:[/bold red] {error}")
        self._final_event = e

    def _on_parallel_started(self, e: dict) -> None:
        roles = e.get("roles", [])
        icons = " ".join(
            f"{ROLE_ICONS.get(r, chr(0x2699))} {r}" for r in roles
        )
        self.console.print(
            f"  [bold magenta]\u26a1 Parallel execution:[/bold magenta] {icons}"
        )

    def _on_parallel_complete(self, e: dict) -> None:
        self.console.print(
            "  [magenta]\u2713 Parallel execution complete[/magenta]"
        )
        self.console.print()

    # ------------------------------------------------------------------
    # Interactive approval — just input(), no Rich Live stopping
    # ------------------------------------------------------------------

    def prompt_approval(self, checkpoint: str, details: str = "") -> bool:
        """Inline approval prompt. No hacks, no Live restart."""
        self._end_stream()
        self.console.print()
        self.console.print(Panel(
            f"[bold]Checkpoint:[/bold] {checkpoint}"
            + (f"\n{details}" if details else "")
            + "\n\n[dim]Press Enter to approve, type 'reject' to reject[/dim]",
            title="[bold yellow]\u26a0 Approval Required[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        ))

        try:
            response = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            response = "reject"

        approved = response in ("", "approve", "yes", "y", "ok")
        color = "green" if approved else "red"
        status = "APPROVED" if approved else "REJECTED"
        self.console.print(f"  [{color}]{status}[/{color}]")
        self.console.print()
        return approved

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------

    def _print_final_summary(self, event: dict[str, Any]) -> None:
        """Print clean final summary table."""
        status = event.get("status", "?")
        cost = event.get("total_cost", self._total_cost)
        tokens = event.get("total_tokens", self._total_tokens)
        agents = event.get("agents_run", [])
        elapsed = time.monotonic() - self._start_time
        color = {"completed": "green", "failed": "red", "rejected": "yellow"}.get(
            status, "white"
        )

        self.console.print()
        self.console.print(Rule(style=color))

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

        self.console.print(Panel(
            t,
            title="[bold]Task Complete[/bold]",
            border_style=color,
            padding=(0, 1),
        ))
