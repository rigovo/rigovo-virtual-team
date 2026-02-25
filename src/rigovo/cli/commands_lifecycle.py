"""Lifecycle commands — dashboard, replay, resume, upgrade."""

from __future__ import annotations

import asyncio
import subprocess
import webbrowser
from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()


def _load_container(project_root: Path | None = None):
    """Load config and build DI container."""
    from rigovo.config import load_config
    from rigovo.container import Container

    config = load_config(project_root)
    return Container(config)


def register(app: typer.Typer) -> None:
    """Register lifecycle commands on the app."""

    @app.command()
    def dashboard() -> None:
        """Open the Rigovo cloud dashboard in your browser."""
        url = "https://app.rigovo.com"
        console.print(f"  Opening {url} ...")
        webbrowser.open(url)

    @app.command()
    def replay(
        task_id: str = typer.Argument(..., help="Task ID to replay"),
        diff: bool = typer.Option(
            False, "--diff", "-d",
            help="Show git diff before and after replay",
        ),
        project_dir: str | None = typer.Option(
            None, "--project", "-p", help="Project directory",
        ),
        verbose: bool = typer.Option(
            False, "--verbose", "-v", help="Verbose logging",
        ),
    ) -> None:
        """Re-run a previously failed task and optionally show diff."""
        from rigovo.main import _setup_logging

        root = Path(project_dir) if project_dir else Path.cwd()
        container = _load_container(root)

        db = container.get_db()
        from rigovo.infrastructure.persistence.sqlite_task_repo import (
            SqliteTaskRepository,
        )

        task_repo = SqliteTaskRepository(db)

        task = asyncio.run(task_repo.get(UUID(task_id)))
        if not task:
            console.print(f"[red]Task not found:[/red] {task_id}")
            raise typer.Exit(1)

        console.print("[bold blue]Rigovo[/bold blue] \u2014 Replaying task\n")
        console.print(f"  [dim]Original:[/dim] {task.description}")
        console.print(f"  [dim]Status:[/dim]   {task.status.value}")
        console.print()

        # --- Item 6: Capture git state before replay ---
        pre_diff = None
        if diff:
            try:
                pre_diff = subprocess.run(
                    ["git", "diff", "--stat", "HEAD"],
                    capture_output=True, text=True, cwd=str(root),
                    timeout=10,
                ).stdout
                console.print(
                    Panel(
                        pre_diff or "[dim]No changes[/dim]",
                        title="[bold]Before Replay[/bold]",
                        border_style="dim",
                    )
                )
            except Exception:
                console.print("  [dim]Could not capture pre-replay diff[/dim]")

        _setup_logging(verbose)
        try:
            cmd = container.build_run_task_command(offline=False)
            result = asyncio.run(cmd.execute(description=task.description))

            if result["status"] == "failed":
                console.print(
                    f"\n[red]Replay failed:[/red] "
                    f"{result.get('error', 'Unknown error')}",
                )
            else:
                cost = result.get("total_cost_usd", 0)
                console.print(f"\n[green]Replay completed:[/green] ${cost:.4f}")

            # --- Item 6: Show diff after replay ---
            if diff:
                try:
                    post_diff = subprocess.run(
                        ["git", "diff", "--stat", "HEAD"],
                        capture_output=True, text=True, cwd=str(root),
                        timeout=10,
                    ).stdout
                    console.print(
                        Panel(
                            post_diff or "[dim]No changes[/dim]",
                            title="[bold]After Replay[/bold]",
                            border_style="green",
                        )
                    )

                    # Show detailed diff
                    detailed = subprocess.run(
                        ["git", "diff", "HEAD"],
                        capture_output=True, text=True, cwd=str(root),
                        timeout=30,
                    ).stdout
                    if detailed:
                        # Truncate if too long
                        lines = detailed.split("\n")
                        if len(lines) > 50:
                            detailed = "\n".join(lines[:50]) + f"\n... ({len(lines) - 50} more lines)"
                        console.print(
                            Panel(
                                detailed,
                                title="[bold]Detailed Diff[/bold]",
                                border_style="cyan",
                            )
                        )
                except Exception:
                    console.print("  [dim]Could not capture post-replay diff[/dim]")

        finally:
            container.close()

    @app.command(name="resume")
    def resume_cmd(
        task_id: str = typer.Argument(
            ..., help="Task ID to resume from last checkpoint",
        ),
        project_dir: str | None = typer.Option(
            None, "--project", "-p", help="Project directory",
        ),
        verbose: bool = typer.Option(
            False, "--verbose", "-v", help="Verbose logging",
        ),
    ) -> None:
        """Resume a previously interrupted or crashed task from its last checkpoint."""
        from rigovo.main import _setup_logging

        root = Path(project_dir) if project_dir else Path.cwd()
        container = _load_container(root)

        db = container.get_db()
        from rigovo.infrastructure.persistence.sqlite_task_repo import (
            SqliteTaskRepository,
        )

        task_repo = SqliteTaskRepository(db)

        task = asyncio.run(task_repo.get(UUID(task_id)))
        if not task:
            console.print(f"[red]Task not found:[/red] {task_id}")
            raise typer.Exit(1)

        # Check if checkpoint DB exists
        checkpoint_db = root / ".rigovo" / "checkpoints.db"
        if not checkpoint_db.exists():
            console.print("[red]No checkpoints found.[/red]")
            console.print("  Checkpoints are only available for tasks run with LangGraph.")
            console.print("  Consider using [bold]rigovo replay[/bold] instead.")
            raise typer.Exit(1)

        console.print("[bold blue]Rigovo[/bold blue] \u2014 Resuming task\n")
        console.print(f"  [dim]Task:[/dim]       {task.description}")
        console.print(f"  [dim]Status:[/dim]     {task.status.value}")
        console.print(f"  [dim]Checkpoint:[/dim] {task_id}")
        console.print()

        _setup_logging(verbose)
        ui = None
        try:
            from rigovo.infrastructure.terminal.rich_output import TerminalUI

            ui = TerminalUI(console)
            emitter = container.get_event_emitter()

            for event_type in [
                "task_started", "project_scanned", "task_classified",
                "pipeline_assembled", "agent_started", "agent_streaming",
                "agent_complete", "agent_timeout", "gate_results",
                "approval_requested", "enrichment_extracted",
                "memories_stored", "budget_exceeded",
                "task_finalized", "task_failed",
            ]:
                emitter.on(
                    event_type,
                    lambda data, _et=event_type: ui.handle_event(
                        {**data, "type": _et}
                    ),
                )

            ui.start(description=task.description)

            cmd = container.build_run_task_command(offline=False)
            result = asyncio.run(
                cmd.execute(
                    description=task.description,
                    resume_thread_id=task_id,
                )
            )

            if result["status"] == "failed":
                console.print(
                    f"\n[red]Resume failed:[/red] "
                    f"{result.get('error', 'Unknown error')}",
                )
            else:
                cost = result.get("total_cost_usd", 0)
                console.print(f"\n[green]Resume completed:[/green] ${cost:.4f}")

        finally:
            if ui:
                ui.stop()
            container.close()

    @app.command()
    def upgrade() -> None:
        """Check for Rigovo CLI updates."""
        from rigovo import __version__

        console.print("[bold blue]Rigovo[/bold blue] \u2014 Upgrade Check\n")
        console.print(f"  Current version: {__version__}")
        console.print("  Checking PyPI...")

        try:
            import httpx

            resp = httpx.get("https://pypi.org/pypi/rigovo/json", timeout=10)
            if resp.status_code == 200:
                latest = resp.json()["info"]["version"]
                if latest != __version__:
                    console.print(f"  [yellow]Update available:[/yellow] {latest}")
                    console.print(
                        "  Run: [bold]pip install --upgrade rigovo[/bold]",
                    )
                else:
                    console.print(
                        "  [green]\u2713[/green] You're on the latest version",
                    )
            else:
                console.print("  [dim]Package not yet published to PyPI[/dim]")
        except Exception:
            console.print("  [dim]Could not check for updates[/dim]")
        console.print()
