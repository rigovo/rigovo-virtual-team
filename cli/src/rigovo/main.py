"""CLI entry point — rigovo command."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="rigovo",
    help="Rigovo — Virtual Engineering Team as a Service",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool = False) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def _load_container(project_root: Path | None = None):
    """Load config and build DI container."""
    from rigovo.config import load_config
    from rigovo.container import Container

    config = load_config(project_root)
    return Container(config)


@app.command()
def run(
    description: str = typer.Argument(..., help="Task description (what you want done)"),
    team: Optional[str] = typer.Option(None, "--team", "-t", help="Target team name"),
    offline: bool = typer.Option(False, "--offline", help="Run without cloud sync"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
    project_dir: Optional[str] = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Run a task through your virtual engineering team."""
    _setup_logging(verbose)

    project_root = Path(project_dir) if project_dir else Path.cwd()
    container = _load_container(project_root)

    # Wire terminal UI to event emitter
    from rigovo.infrastructure.terminal.rich_output import TerminalUI
    from rigovo.infrastructure.terminal.approval_prompt import TerminalApprovalHandler

    ui = TerminalUI(console)
    emitter = container.get_event_emitter()

    # Subscribe UI to all events
    for event_type in [
        "task_classified", "pipeline_assembled", "agent_complete",
        "gate_results", "approval_requested", "task_finalized",
    ]:
        emitter.on(event_type, lambda data, _et=event_type: ui.handle_event({**data, "type": _et}))

    console.print(f"\n[bold blue]Rigovo[/bold blue] — Starting task...\n")
    console.print(f"  [dim]Description:[/dim] {description}")
    if team:
        console.print(f"  [dim]Team:[/dim] {team}")
    console.print()

    # Check for API key
    if not container.config.llm.api_key:
        console.print("[red]Error:[/red] No API key configured.")
        console.print("  Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env or environment.")
        console.print("  Or run: [bold]rigovo init[/bold]")
        raise typer.Exit(1)

    # Build and run task command
    try:
        cmd = container.build_run_task_command(offline=offline)
        result = asyncio.run(cmd.execute(description=description, team_name=team))

        if result["status"] == "failed":
            console.print(f"\n[red]Task failed:[/red] {result.get('error', 'Unknown error')}")
            raise typer.Exit(1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        if verbose:
            console.print_exception()
        else:
            console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        container.close()


@app.command()
def init(
    project_dir: Optional[str] = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Initialise a Rigovo project in the current directory."""
    root = Path(project_dir) if project_dir else Path.cwd()

    console.print("[bold blue]Rigovo[/bold blue] — Initialising project...\n")

    # Create .rigovo directory
    rigovo_dir = root / ".rigovo"
    rigovo_dir.mkdir(parents=True, exist_ok=True)

    # Create .env template if not exists
    env_file = root / ".env"
    if not env_file.exists():
        env_file.write_text(
            "# Rigovo Configuration\n"
            "# Uncomment and set your API key:\n"
            "\n"
            "# ANTHROPIC_API_KEY=sk-ant-...\n"
            "# OPENAI_API_KEY=sk-...\n"
            "\n"
            "# LLM_MODEL=claude-sonnet-4-5-20250929\n"
            "\n"
            "# Cloud sync (optional)\n"
            "# RIGOVO_API_KEY=\n"
            "# RIGOVO_WORKSPACE_ID=\n"
        )
        console.print("  [green]✓[/green] Created .env template")
    else:
        console.print("  [dim]⊘ .env already exists[/dim]")

    # Initialize local database
    container = _load_container(root)
    container.get_db()
    console.print("  [green]✓[/green] Initialized local database")

    # Add .rigovo to .gitignore if not already there
    gitignore = root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".rigovo/" not in content:
            with open(gitignore, "a") as f:
                f.write("\n# Rigovo local data\n.rigovo/\n")
            console.print("  [green]✓[/green] Updated .gitignore")
    else:
        gitignore.write_text("# Rigovo local data\n.rigovo/\n")
        console.print("  [green]✓[/green] Created .gitignore")

    container.close()
    console.print("\n[bold green]Project initialized.[/bold green]")
    console.print("  Next: Set your API key in .env, then run:")
    console.print("  [bold]rigovo run \"your task description\"[/bold]\n")


@app.command()
def teams(
    project_dir: Optional[str] = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """List configured teams and their agent roles."""
    root = Path(project_dir) if project_dir else Path.cwd()
    container = _load_container(root)

    console.print("[bold blue]Rigovo[/bold blue] — Teams\n")

    for domain_id, plugin in container.domains.items():
        roles = plugin.get_agent_roles()
        task_types = plugin.get_task_types()

        table = Table(title=f"{plugin.name} Team ({domain_id})")
        table.add_column("Role", style="cyan")
        table.add_column("Produces Code", justify="center")
        table.add_column("Model Tier")

        for role in roles:
            code_marker = "[green]✓[/green]" if role.produces_code else "[dim]—[/dim]"
            table.add_row(role.name, code_marker, role.default_llm_model or "default")

        console.print(table)
        console.print()

        # Task types
        console.print(f"  [bold]Task types:[/bold] {', '.join(t.name for t in task_types)}")
        console.print()

    container.close()


@app.command()
def costs(
    project_dir: Optional[str] = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Show cost breakdown for this workspace."""
    root = Path(project_dir) if project_dir else Path.cwd()
    container = _load_container(root)

    console.print("[bold blue]Rigovo[/bold blue] — Cost Report\n")

    db = container.get_db()
    from rigovo.infrastructure.persistence.sqlite_cost_repo import SqliteCostRepository
    from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository

    cost_repo = SqliteCostRepository(db)
    task_repo = SqliteTaskRepository(db)

    # Get workspace total
    workspace_id = UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)

    total = asyncio.run(cost_repo.total_by_workspace(workspace_id))

    # Get recent tasks
    tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=20))

    if not tasks and total == 0:
        console.print("  [dim]No tasks run yet. Run your first task with:[/dim]")
        console.print("  [bold]rigovo run \"your task description\"[/bold]\n")
        container.close()
        return

    table = Table(title="Recent Tasks")
    table.add_column("Task", max_width=50)
    table.add_column("Status")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Duration", justify="right")

    for task in tasks:
        status_colors = {
            "completed": "green", "failed": "red", "rejected": "yellow",
        }
        color = status_colors.get(task.status.value, "white")
        duration_s = (task.duration_ms or 0) / 1000

        table.add_row(
            task.description[:50],
            f"[{color}]{task.status.value}[/{color}]",
            f"{task.total_tokens:,}",
            f"${task.total_cost_usd:.4f}",
            f"{duration_s:.1f}s",
        )

    console.print(table)
    console.print(f"\n  [bold]Total spend:[/bold] ${total:.4f}\n")

    container.close()


@app.command()
def status(
    project_dir: Optional[str] = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Show current project status."""
    root = Path(project_dir) if project_dir else Path.cwd()

    console.print("[bold blue]Rigovo[/bold blue] — Status\n")

    # Check .rigovo directory
    rigovo_dir = root / ".rigovo"
    if not rigovo_dir.exists():
        console.print("  [yellow]Not initialized.[/yellow] Run: [bold]rigovo init[/bold]")
        return

    console.print(f"  [bold]Project:[/bold] {root.name}")
    console.print(f"  [bold]Path:[/bold] {root}")

    # Check .env
    env_file = root / ".env"
    if env_file.exists():
        container = _load_container(root)
        has_key = bool(container.config.llm.api_key)
        model = container.config.llm.model
        provider = container.config.llm.provider

        console.print(f"  [bold]Provider:[/bold] {provider}")
        console.print(f"  [bold]Model:[/bold] {model}")
        console.print(f"  [bold]API Key:[/bold] {'[green]configured[/green]' if has_key else '[red]missing[/red]'}")

        # Cloud status
        cloud_key = bool(container.config.cloud.api_key)
        console.print(f"  [bold]Cloud sync:[/bold] {'[green]enabled[/green]' if cloud_key else '[dim]disabled[/dim]'}")

        # Database stats
        db = container.get_db()
        from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
        task_repo = SqliteTaskRepository(db)
        workspace_id = UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)
        tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=1000))
        console.print(f"  [bold]Tasks run:[/bold] {len(tasks)}")

        container.close()
    else:
        console.print("  [yellow].env not found.[/yellow] Run: [bold]rigovo init[/bold]")

    console.print()


@app.command()
def login() -> None:
    """Authenticate with Rigovo cloud."""
    console.print("[bold blue]Rigovo[/bold blue] — Login\n")

    api_key = typer.prompt("  Enter your Rigovo API key", hide_input=True)

    if not api_key.strip():
        console.print("  [red]No API key provided.[/red]")
        raise typer.Exit(1)

    # Validate with cloud
    from rigovo.infrastructure.cloud.sync_client import CloudSyncClient

    client = CloudSyncClient(api_key=api_key)

    console.print("  Validating...")
    result = asyncio.run(client.authenticate(api_key))

    if result:
        workspace_id = result.get("workspace_id", "")
        console.print(f"  [green]✓[/green] Authenticated — workspace: {workspace_id}")
        console.print(f"\n  Add to your .env:")
        console.print(f"    RIGOVO_API_KEY={api_key}")
        console.print(f"    RIGOVO_WORKSPACE_ID={workspace_id}\n")
    else:
        console.print("  [red]✗ Authentication failed.[/red]")
        console.print("  Check your API key at https://app.rigovo.com/settings\n")

    asyncio.run(client.close())


@app.command()
def version() -> None:
    """Show Rigovo CLI version."""
    from rigovo import __version__
    console.print(f"rigovo {__version__}")


if __name__ == "__main__":
    app()
