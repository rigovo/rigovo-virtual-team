"""Data commands — history, costs, export, login."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def _load_container(project_root: Path | None = None):
    """Load config and build DI container."""
    from rigovo.config import load_config
    from rigovo.container import Container

    config = load_config(project_root)
    return Container(config)


def register(app: typer.Typer) -> None:
    """Register data commands on the app."""

    @app.command()
    def history(
        task_id: str | None = typer.Argument(None, help="Task ID to inspect"),
        limit: int = typer.Option(20, "--limit", "-n", help="Number of tasks"),
        status_filter: str | None = typer.Option(
            None,
            "--status",
            help="Filter by status",
        ),
        project_dir: str | None = typer.Option(
            None,
            "--project",
            "-p",
            help="Project directory",
        ),
    ) -> None:
        """Show task history — past runs with outcomes, costs, durations."""
        root = Path(project_dir) if project_dir else Path.cwd()
        container = _load_container(root)

        console.print("[bold blue]Rigovo[/bold blue] — History\n")

        db = container.get_db()
        from rigovo.infrastructure.persistence.sqlite_audit_repo import (
            SqliteAuditRepository,
        )
        from rigovo.infrastructure.persistence.sqlite_task_repo import (
            SqliteTaskRepository,
        )

        task_repo = SqliteTaskRepository(db)
        audit_repo = SqliteAuditRepository(db)
        workspace_id = (
            UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)
        )

        if task_id:
            _show_task_detail(task_repo, audit_repo, task_id)
        else:
            _show_task_list(task_repo, workspace_id, limit)

        console.print()
        container.close()

    @app.command()
    def costs(
        project_dir: str | None = typer.Option(
            None,
            "--project",
            "-p",
            help="Project directory",
        ),
    ) -> None:
        """Show cost breakdown — per-task, per-agent, and totals."""
        root = Path(project_dir) if project_dir else Path.cwd()
        container = _load_container(root)

        console.print("[bold blue]Rigovo[/bold blue] — Cost Report\n")

        db = container.get_db()
        from rigovo.infrastructure.persistence.sqlite_cost_repo import (
            SqliteCostRepository,
        )
        from rigovo.infrastructure.persistence.sqlite_task_repo import (
            SqliteTaskRepository,
        )

        cost_repo = SqliteCostRepository(db)
        task_repo = SqliteTaskRepository(db)

        workspace_id = (
            UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)
        )
        total = asyncio.run(cost_repo.total_by_workspace(workspace_id))
        tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=20))

        if not tasks and total == 0:
            console.print(
                '  [dim]No tasks run yet. Run: rigovo run "your task"[/dim]\n',
            )
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
                "completed": "green",
                "failed": "red",
                "rejected": "yellow",
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

        budget = container.config.yml.orchestration.budget
        console.print(f"\n  [bold]Total spend:[/bold]    ${total:.4f}")
        if budget.monthly_budget > 0:
            pct = (total / budget.monthly_budget) * 100
            color = "green" if pct < 80 else "yellow" if pct < 100 else "red"
            console.print(
                f"  [bold]Monthly budget:[/bold] ${budget.monthly_budget:.2f} "
                f"([{color}]{pct:.0f}% used[/{color}])",
            )
        console.print()

        container.close()

    @app.command()
    def audit(
        limit: int = typer.Option(100, "--limit", "-n", help="Number of audit entries"),
        project_dir: str | None = typer.Option(
            None,
            "--project",
            "-p",
            help="Project directory",
        ),
    ) -> None:
        """Show audit trail for monitoring and governance."""
        root = Path(project_dir) if project_dir else Path.cwd()
        container = _load_container(root)
        db = container.get_db()
        from rigovo.infrastructure.persistence.sqlite_audit_repo import SqliteAuditRepository

        audit_repo = SqliteAuditRepository(db)
        workspace_id = (
            UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)
        )
        entries = asyncio.run(audit_repo.list_by_workspace(workspace_id, limit=limit))

        console.print("[bold blue]Rigovo[/bold blue] — Audit Trail\n")
        if not entries:
            console.print("  [dim]No audit entries yet.[/dim]\n")
            container.close()
            return

        table = Table(title=f"Audit Entries ({len(entries)})")
        table.add_column("When", style="dim")
        table.add_column("Action", style="cyan")
        table.add_column("Role")
        table.add_column("Summary", max_width=70)
        table.add_column("Task", style="dim")

        for e in entries:
            table.add_row(
                e.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                e.action.value,
                e.agent_role or "system",
                e.summary,
                str(e.task_id)[:8] if e.task_id else "—",
            )

        console.print(table)
        console.print()
        container.close()

    @app.command("export")
    def export_cmd(
        format: str = typer.Option(
            "json",
            "--format",
            "-f",
            help="Output format: json, csv",
        ),
        output: str | None = typer.Option(
            None,
            "--output",
            "-o",
            help="Output file path",
        ),
        project_dir: str | None = typer.Option(
            None,
            "--project",
            "-p",
            help="Project directory",
        ),
    ) -> None:
        """Export task history, costs, and agent stats as JSON or CSV."""
        root = Path(project_dir) if project_dir else Path.cwd()
        container = _load_container(root)

        db = container.get_db()
        from rigovo.infrastructure.persistence.sqlite_cost_repo import (
            SqliteCostRepository,
        )
        from rigovo.infrastructure.persistence.sqlite_task_repo import (
            SqliteTaskRepository,
        )

        task_repo = SqliteTaskRepository(db)
        cost_repo = SqliteCostRepository(db)
        workspace_id = (
            UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)
        )

        tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=10000))
        total_cost = asyncio.run(cost_repo.total_by_workspace(workspace_id))

        if format == "json":
            _export_json(tasks, total_cost, workspace_id, output)
        elif format == "csv":
            _export_csv(tasks, output)
        else:
            console.print(f"[red]Unknown format:[/red] {format}. Use json or csv.")
            raise typer.Exit(1)

        container.close()

    @app.command()
    def login() -> None:
        """Authenticate with Rigovo cloud."""
        console.print("[bold blue]Rigovo[/bold blue] — Login\n")

        api_key = typer.prompt("  Enter your Rigovo API key", hide_input=True)
        if not api_key.strip():
            console.print("  [red]No API key provided.[/red]")
            raise typer.Exit(1)

        from rigovo.infrastructure.cloud.sync_client import CloudSyncClient

        client = CloudSyncClient(api_key=api_key)
        console.print("  Validating...")
        result = asyncio.run(client.authenticate(api_key))

        if result:
            workspace_id = result.get("workspace_id", "")
            console.print(
                f"  [green]✓[/green] Authenticated — workspace: {workspace_id}",
            )
            console.print("\n  Add to your .env:")
            console.print(f"    RIGOVO_API_KEY={api_key}")
            console.print(f"    RIGOVO_WORKSPACE_ID={workspace_id}\n")
        else:
            console.print("  [red]✗ Authentication failed.[/red]")
            console.print(
                "  Check your API key in the desktop app Settings → Identity.\n",
            )

        asyncio.run(client.close())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _show_task_detail(task_repo, audit_repo, task_id: str) -> None:
    """Show single task detail."""
    task = asyncio.run(task_repo.get(UUID(task_id)))
    if not task:
        console.print(f"  [red]Task not found:[/red] {task_id}")
        raise typer.Exit(1)

    status_colors = {
        "completed": "green",
        "failed": "red",
        "rejected": "yellow",
        "running": "blue",
    }
    color = status_colors.get(task.status.value, "white")

    console.print(f"  [bold]Task ID:[/bold]     {task.id}")
    console.print(f"  [bold]Status:[/bold]      [{color}]{task.status.value}[/{color}]")
    console.print(f"  [bold]Description:[/bold] {task.description}")
    console.print(f"  [bold]Created:[/bold]     {task.created_at}")
    console.print(f"  [bold]Duration:[/bold]    {(task.duration_ms or 0) / 1000:.1f}s")
    console.print(f"  [bold]Tokens:[/bold]      {task.total_tokens:,}")
    console.print(f"  [bold]Cost:[/bold]        ${task.total_cost_usd:.4f}")

    audit_entries = asyncio.run(audit_repo.list_by_task(task.id))
    if audit_entries:
        console.print(f"\n  [bold]Audit trail ({len(audit_entries)} entries):[/bold]")
        for entry in audit_entries:
            console.print(
                f"    [{entry.action.value}] {entry.agent_role}: {entry.summary}",
            )


def _show_task_list(task_repo, workspace_id: UUID, limit: int) -> None:
    """Show task list table."""
    tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=limit))

    if not tasks:
        console.print('  [dim]No tasks yet. Run: rigovo run "your task"[/dim]')
        return

    table = Table(title=f"Recent Tasks ({len(tasks)})")
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Description", max_width=50)
    table.add_column("Status")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("When")

    for task in tasks:
        status_colors = {
            "completed": "green",
            "failed": "red",
            "rejected": "yellow",
        }
        color = status_colors.get(task.status.value, "white")
        duration_s = (task.duration_ms or 0) / 1000

        table.add_row(
            str(task.id)[:8],
            task.description[:50],
            f"[{color}]{task.status.value}[/{color}]",
            f"{task.total_tokens:,}",
            f"${task.total_cost_usd:.4f}",
            f"{duration_s:.1f}s",
            (task.created_at.strftime("%Y-%m-%d %H:%M") if task.created_at else ""),
        )

    console.print(table)
    console.print("\n  [dim]Inspect a task: rigovo history <task-id>[/dim]")


def _export_json(tasks, total_cost: float, workspace_id: UUID, output) -> None:
    """Export as JSON."""
    export_data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "workspace_id": str(workspace_id),
        "summary": {
            "total_tasks": len(tasks),
            "total_cost_usd": total_cost,
            "completed": sum(1 for t in tasks if t.status.value == "completed"),
            "failed": sum(1 for t in tasks if t.status.value == "failed"),
        },
        "tasks": [
            {
                "id": str(t.id),
                "description": t.description,
                "status": t.status.value,
                "total_tokens": t.total_tokens,
                "total_cost_usd": t.total_cost_usd,
                "duration_ms": t.duration_ms,
                "created_at": (t.created_at.isoformat() if t.created_at else None),
            }
            for t in tasks
        ],
    }

    json_str = json.dumps(export_data, indent=2, default=str)
    if output:
        Path(output).write_text(json_str)
        console.print(f"  [green]✓[/green] Exported {len(tasks)} tasks to {output}")
    else:
        print(json_str)


def _export_csv(tasks, output) -> None:
    """Export as CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "description",
            "status",
            "tokens",
            "cost_usd",
            "duration_ms",
            "created_at",
        ]
    )
    for t in tasks:
        writer.writerow(
            [
                str(t.id),
                t.description,
                t.status.value,
                t.total_tokens,
                f"{t.total_cost_usd:.6f}",
                t.duration_ms,
                t.created_at.isoformat() if t.created_at else "",
            ]
        )

    csv_str = buf.getvalue()
    if output:
        Path(output).write_text(csv_str)
        console.print(f"  [green]✓[/green] Exported {len(tasks)} tasks to {output}")
    else:
        print(csv_str)
