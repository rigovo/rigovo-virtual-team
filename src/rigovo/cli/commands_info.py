"""Info commands — teams, agents, config, status."""

from __future__ import annotations

import shutil
import asyncio
from pathlib import Path
from typing import Any
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
    """Register info commands on the app."""

    @app.command()
    def teams(
        project_dir: str | None = typer.Option(
            None, "--project", "-p", help="Project directory",
        ),
    ) -> None:
        """List configured teams and their agent roles."""
        root = Path(project_dir) if project_dir else Path.cwd()
        container = _load_container(root)

        console.print("[bold blue]Rigovo[/bold blue] — Teams\n")

        yml = container.config.yml

        for domain_id, plugin in container.domains.items():
            roles = plugin.get_agent_roles()
            task_types = plugin.get_task_types()
            team_cfg = yml.teams.get(domain_id)

            table = Table(title=f"{plugin.name} Team ({domain_id})")
            table.add_column("Role", style="cyan")
            table.add_column("Produces Code", justify="center")
            table.add_column("Model")
            table.add_column("Rules", justify="right")

            for role in roles:
                code_marker = (
                    "[green]✓[/green]" if role.produces_code else "[dim]—[/dim]"
                )
                override = (
                    team_cfg.agents.get(role.role_id) if team_cfg else None
                )
                model = (
                    override.model
                    if (override and override.model)
                    else role.default_llm_model
                )
                rule_count = len(override.rules) if override else 0

                table.add_row(
                    role.name,
                    code_marker,
                    model,
                    str(rule_count) if rule_count else "[dim]—[/dim]",
                )

            console.print(table)
            console.print()
            console.print(
                f"  [bold]Task types:[/bold] {', '.join(t.name for t in task_types)}",
            )
            console.print()

        container.close()

    @app.command()
    def agents(
        detail: str | None = typer.Argument(
            None, help="Role ID to inspect (e.g., 'coder')",
        ),
        project_dir: str | None = typer.Option(
            None, "--project", "-p", help="Project directory",
        ),
    ) -> None:
        """Show agent details — model, rules, tools, performance stats."""
        root = Path(project_dir) if project_dir else Path.cwd()
        container = _load_container(root)
        yml = container.config.yml

        console.print("[bold blue]Rigovo[/bold blue] — Agents\n")

        for domain_id, plugin in container.domains.items():
            roles = plugin.get_agent_roles()
            team_cfg = yml.teams.get(domain_id)

            if detail:
                _show_agent_detail(plugin, roles, team_cfg, detail)
            else:
                _show_agents_table(plugin, roles, team_cfg)

        container.close()

    @app.command("config")
    def config_cmd(
        key: str | None = typer.Argument(
            None, help="Config key to get/set (dot notation)",
        ),
        value: str | None = typer.Option(None, "--set", "-s", help="Value to set"),
        project_dir: str | None = typer.Option(
            None, "--project", "-p", help="Project directory",
        ),
    ) -> None:
        """Show or update rigovo.yml configuration."""
        root = Path(project_dir) if project_dir else Path.cwd()

        yml_path = root / "rigovo.yml"
        if not yml_path.is_file():
            console.print(
                "[yellow]No rigovo.yml found.[/yellow] Run: [bold]rigovo init[/bold]",
            )
            raise typer.Exit(1)

        from rigovo.config_schema import load_rigovo_yml, save_rigovo_yml

        yml = load_rigovo_yml(root)

        if key and value:
            _set_config_value(yml, key, value)
            save_rigovo_yml(yml, root)
            console.print(f"  [green]✓[/green] Set {key} = {value}")
            console.print("  Updated rigovo.yml")
        elif key:
            val = _get_config_value(yml, key)
            if val is not None:
                console.print(f"  {key} = {val}")
            else:
                console.print(f"  [red]Key not found:[/red] {key}")
        else:
            import yaml

            console.print("[bold blue]Rigovo[/bold blue] — Configuration\n")
            data = yml.model_dump(exclude_defaults=False)
            yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
            console.print(yaml_str)

    @app.command()
    def status(
        project_dir: str | None = typer.Option(
            None, "--project", "-p", help="Project directory",
        ),
    ) -> None:
        """Show current project status — config, health, and stats."""
        root = Path(project_dir) if project_dir else Path.cwd()

        console.print("[bold blue]Rigovo[/bold blue] — Status\n")

        rigovo_dir = root / ".rigovo"
        if not rigovo_dir.exists():
            console.print(
                "  [yellow]Not initialized.[/yellow] Run: [bold]rigovo init[/bold]",
            )
            return

        container = _load_container(root)
        yml = container.config.yml

        console.print(f"  [bold]Project:[/bold]    {yml.project.name or root.name}")
        console.print(f"  [bold]Path:[/bold]       {root}")
        if yml.project.language:
            lang_fw = f"{yml.project.language}/{yml.project.framework or 'generic'}"
            console.print(f"  [bold]Stack:[/bold]      {lang_fw}")

        has_key = bool(container.config.llm.api_key)
        model = container.config.llm.model
        provider = container.config.llm.provider
        console.print(f"  [bold]Provider:[/bold]   {provider}")
        console.print(f"  [bold]Model:[/bold]      {model}")
        key_status = (
            "[green]configured[/green]" if has_key else "[red]missing[/red]"
        )
        console.print(f"  [bold]API Key:[/bold]    {key_status}")

        cloud_key = bool(container.config.cloud.api_key)
        cloud_status = (
            "[green]enabled[/green]" if cloud_key else "[dim]disabled[/dim]"
        )
        console.print(f"  [bold]Cloud sync:[/bold] {cloud_status}")

        rigour_path = shutil.which("rigour")
        rigour_display = (
            f"[green]{rigour_path}[/green]"
            if rigour_path
            else "[dim]fallback (built-in checks)[/dim]"
        )
        console.print(f"  [bold]Rigour CLI:[/bold] {rigour_display}")

        db = container.get_db()
        from rigovo.infrastructure.persistence.sqlite_task_repo import (
            SqliteTaskRepository,
        )

        task_repo = SqliteTaskRepository(db)
        workspace_id = (
            UUID(container.config.workspace_id)
            if container.config.workspace_id
            else UUID(int=0)
        )
        tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=1000))
        completed = sum(1 for t in tasks if t.status.value == "completed")
        failed = sum(1 for t in tasks if t.status.value == "failed")
        console.print(
            f"  [bold]Tasks:[/bold]      {len(tasks)} total "
            f"({completed} completed, {failed} failed)",
        )

        budget = yml.orchestration.budget
        console.print(
            f"  [bold]Budget:[/bold]     "
            f"${budget.max_cost_per_task:.2f}/task, "
            f"${budget.monthly_budget:.2f}/month",
        )

        container.close()
        console.print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _show_agent_detail(plugin, roles, team_cfg, detail: str) -> None:
    """Deep inspect a single agent."""
    role = next((r for r in roles if r.role_id == detail), None)
    if not role:
        console.print(f"[red]Unknown role:[/red] {detail}")
        console.print(f"Available: {', '.join(r.role_id for r in roles)}")
        raise typer.Exit(1)

    override = team_cfg.agents.get(role.role_id) if team_cfg else None
    model = (
        override.model if (override and override.model) else role.default_llm_model
    )

    console.print(f"  [bold cyan]{role.name}[/bold cyan] ({role.role_id})")
    console.print(f"  {role.description}")
    console.print()
    console.print(f"  [bold]Model:[/bold]          {model}")
    console.print(
        f"  [bold]Produces code:[/bold]  {'Yes' if role.produces_code else 'No'}",
    )
    console.print(f"  [bold]Pipeline order:[/bold] {role.pipeline_order}")

    tools = plugin.get_tools(role.role_id)
    if tools:
        tool_names = [t.get("name", "?") for t in tools]
        console.print(f"  [bold]Tools:[/bold]          {', '.join(tool_names)}")

    if override and override.rules:
        console.print(f"\n  [bold]Custom rules ({len(override.rules)}):[/bold]")
        for rule in override.rules:
            console.print(f"    • {rule}")

    if override:
        console.print("\n  [bold]Configuration:[/bold]")
        console.print(f"    Temperature:      {override.temperature}")
        console.print(f"    Max tokens:       {override.max_tokens:,}")
        console.print(f"    Max retries:      {override.max_retries}")
        console.print(f"    Timeout:          {override.timeout_seconds}s")
        approval = "Yes" if override.approval_required else "No"
        console.print(f"    Approval needed:  {approval}")

    console.print()


def _show_agents_table(plugin, roles, team_cfg) -> None:
    """Summary table for all agents."""
    table = Table(title=f"{plugin.name} Agents")
    table.add_column("Role ID", style="cyan")
    table.add_column("Name")
    table.add_column("Model")
    table.add_column("Code", justify="center")
    table.add_column("Rules", justify="right")
    table.add_column("Tools", justify="right")

    for role in roles:
        override = team_cfg.agents.get(role.role_id) if team_cfg else None
        model = (
            override.model
            if (override and override.model)
            else role.default_llm_model
        )
        rule_count = len(override.rules) if override else 0
        tool_count = len(plugin.get_tools(role.role_id))

        short_model = (
            model.replace("claude-opus-4-6", "opus-4.6")
            .replace("claude-sonnet-4-6", "sonnet-4.6")
            .replace("claude-opus-4-5-20250624", "opus-4.5")
            .replace("claude-sonnet-4-5-20250929", "sonnet-4.5")
            .replace("claude-haiku-4-5-20251001", "haiku-4.5")
        )

        table.add_row(
            role.role_id,
            role.name,
            short_model,
            "[green]✓[/green]" if role.produces_code else "[dim]—[/dim]",
            str(rule_count) if rule_count else "[dim]—[/dim]",
            str(tool_count),
        )

    console.print(table)
    console.print("\n  [dim]Inspect a specific agent: rigovo agents <role_id>[/dim]\n")


def _set_config_value(yml: Any, key: str, value: str) -> None:
    """Set a config value using dot notation."""
    import yaml as _yaml

    parts = key.split(".")
    obj: Any = yml
    for part in parts[:-1]:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict):
            obj = obj[part]
        else:
            raise typer.BadParameter(f"Invalid config path: {key}")

    final_key = parts[-1]

    try:
        parsed = _yaml.safe_load(value)
    except Exception:
        parsed = value

    if hasattr(obj, final_key):
        setattr(obj, final_key, parsed)
    elif isinstance(obj, dict):
        obj[final_key] = parsed
    else:
        raise typer.BadParameter(f"Cannot set: {key}")


def _get_config_value(yml: Any, key: str) -> Any:
    """Get a config value using dot notation."""
    parts = key.split(".")
    obj: Any = yml
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return obj
