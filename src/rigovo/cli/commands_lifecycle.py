"""Lifecycle commands — dashboard, replay, upgrade."""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console

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
        project_dir: str | None = typer.Option(
            None, "--project", "-p", help="Project directory",
        ),
        verbose: bool = typer.Option(
            False, "--verbose", "-v", help="Verbose logging",
        ),
    ) -> None:
        """Re-run a previously failed task with the same context."""
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

        console.print("[bold blue]Rigovo[/bold blue] — Replaying task\n")
        console.print(f"  [dim]Original:[/dim] {task.description}")
        console.print(f"  [dim]Status:[/dim]   {task.status.value}")
        console.print()

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
        finally:
            container.close()

    @app.command()
    def upgrade() -> None:
        """Check for Rigovo CLI updates."""
        from rigovo import __version__

        console.print("[bold blue]Rigovo[/bold blue] — Upgrade Check\n")
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
                        "  [green]✓[/green] You're on the latest version",
                    )
            else:
                console.print("  [dim]Package not yet published to PyPI[/dim]")
        except Exception:
            console.print("  [dim]Could not check for updates[/dim]")
        console.print()
