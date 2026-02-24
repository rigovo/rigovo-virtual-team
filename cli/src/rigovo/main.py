"""CLI entry point — rigovo command.

All CLI commands:
  P0: run, init, version, doctor
  P1: teams, agents, config, history, costs, status, login
  P2: export, dashboard
  P3: replay, upgrade
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import shutil
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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
    for name in ("httpx", "httpcore", "anthropic", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _load_container(project_root: Path | None = None):
    """Load config and build DI container."""
    from rigovo.config import load_config
    from rigovo.container import Container

    config = load_config(project_root)
    return Container(config)


# ═══════════════════════════════════════════════════════════════════════════
# P0 Commands
# ═══════════════════════════════════════════════════════════════════════════


@app.command()
def run(
    description: str = typer.Argument(..., help="Task description (what you want done)"),
    team: str | None = typer.Option(None, "--team", "-t", help="Target team name"),
    offline: bool = typer.Option(False, "--offline", help="Run without cloud sync"),
    ci: bool = typer.Option(False, "--ci", help="CI mode: non-interactive, JSON output"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Run a task through your virtual engineering team."""
    _setup_logging(verbose)

    project_root = Path(project_dir) if project_dir else Path.cwd()
    container = _load_container(project_root)

    # Check for API key
    if not container.config.llm.api_key:
        if ci:
            print(json.dumps({"status": "error", "error": "No API key configured"}))
            raise typer.Exit(1)
        console.print("[red]Error:[/red] No API key configured.")
        console.print("  Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env or environment.")
        console.print("  Or run: [bold]rigovo init[/bold]")
        raise typer.Exit(1)

    # Budget guard
    budget = container.config.yml.orchestration.budget
    if budget.max_cost_per_task > 0:
        # Pre-flight budget check will be enforced during execution
        pass

    if not ci:
        # Wire terminal UI to event emitter
        from rigovo.infrastructure.terminal.rich_output import TerminalUI

        ui = TerminalUI(console)
        emitter = container.get_event_emitter()

        for event_type in [
            "task_started", "task_classified", "pipeline_assembled",
            "agent_complete", "gate_results", "approval_requested",
            "task_finalized", "task_failed",
        ]:
            emitter.on(event_type, lambda data, _et=event_type: ui.handle_event({**data, "type": _et}))

        console.print(f"\n[bold blue]Rigovo[/bold blue] — Starting task...\n")
        console.print(f"  [dim]Description:[/dim] {description}")
        if team:
            console.print(f"  [dim]Team:[/dim] {team}")
        console.print()

    # Build and run task command
    try:
        cmd = container.build_run_task_command(offline=offline)
        result = asyncio.run(cmd.execute(description=description, team_name=team))

        if ci:
            print(json.dumps(result, default=str))
        elif result["status"] == "failed":
            console.print(f"\n[red]Task failed:[/red] {result.get('error', 'Unknown error')}")
            raise typer.Exit(1)

    except KeyboardInterrupt:
        if ci:
            print(json.dumps({"status": "interrupted"}))
        else:
            console.print("\n[yellow]Interrupted by user.[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        if ci:
            print(json.dumps({"status": "error", "error": str(e)}))
        elif verbose:
            console.print_exception()
        else:
            console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        container.close()


@app.command()
def init(
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing rigovo.yml"),
) -> None:
    """Initialise a Rigovo project — auto-detects your stack and writes rigovo.yml."""
    root = Path(project_dir) if project_dir else Path.cwd()

    console.print("[bold blue]Rigovo[/bold blue] — Initialising project...\n")

    # 1. Create .rigovo directory
    rigovo_dir = root / ".rigovo"
    rigovo_dir.mkdir(parents=True, exist_ok=True)
    console.print("  [green]✓[/green] Created .rigovo/ directory")

    # 2. Auto-detect project and generate rigovo.yml
    yml_path = root / "rigovo.yml"
    if yml_path.exists() and not force:
        console.print("  [dim]⊘ rigovo.yml already exists (use --force to overwrite)[/dim]")
    else:
        from rigovo.config_schema import detect_project_config, save_rigovo_yml

        detected = detect_project_config(root)
        save_rigovo_yml(detected, root)

        proj = detected.project
        console.print(f"  [green]✓[/green] Generated rigovo.yml")
        if proj.language:
            console.print(f"    [dim]Language:[/dim]   {proj.language}")
        if proj.framework:
            console.print(f"    [dim]Framework:[/dim]  {proj.framework}")
        if proj.test_framework:
            console.print(f"    [dim]Tests:[/dim]      {proj.test_framework}")
        if proj.package_manager:
            console.print(f"    [dim]Pkg mgr:[/dim]    {proj.package_manager}")

        # Show auto-generated agent rules
        eng_team = detected.teams.get("engineering")
        if eng_team:
            coder = eng_team.agents.get("coder")
            if coder and coder.rules:
                console.print(f"    [dim]Coder rules:[/dim] {len(coder.rules)} auto-configured")

    # 3. Create .env template if not exists
    env_file = root / ".env"
    if not env_file.exists():
        env_file.write_text(
            "# ═══════════════════════════════════════════════════\n"
            "# Rigovo secrets — DO NOT commit this file\n"
            "# ═══════════════════════════════════════════════════\n"
            "\n"
            "# LLM Provider (uncomment one)\n"
            "# ANTHROPIC_API_KEY=sk-ant-...\n"
            "# OPENAI_API_KEY=sk-...\n"
            "\n"
            "# Model override (optional)\n"
            "# LLM_MODEL=claude-sonnet-4-5-20250929\n"
            "\n"
            "# Cloud sync (optional — get key at app.rigovo.com)\n"
            "# RIGOVO_API_KEY=\n"
            "# RIGOVO_WORKSPACE_ID=\n"
        )
        console.print("  [green]✓[/green] Created .env template")
    else:
        console.print("  [dim]⊘ .env already exists[/dim]")

    # 4. Initialize local database
    container = _load_container(root)
    db = container.get_db()
    db.initialize()
    console.print("  [green]✓[/green] Initialized local database")

    # 5. Update .gitignore
    gitignore = root / ".gitignore"
    entries_to_add = [".rigovo/", ".env"]
    if gitignore.exists():
        content = gitignore.read_text()
        added = []
        for entry in entries_to_add:
            if entry not in content:
                added.append(entry)
        if added:
            with open(gitignore, "a") as f:
                f.write(f"\n# Rigovo\n")
                for entry in added:
                    f.write(f"{entry}\n")
            console.print(f"  [green]✓[/green] Updated .gitignore (+{', '.join(added)})")
    else:
        gitignore.write_text("# Rigovo\n.rigovo/\n.env\n")
        console.print("  [green]✓[/green] Created .gitignore")

    container.close()
    console.print("\n[bold green]Project initialized.[/bold green]")
    console.print("  1. Set your API key in [bold].env[/bold]")
    console.print("  2. Review [bold]rigovo.yml[/bold] — tweak agent rules, quality gates, budget")
    console.print("  3. Run: [bold]rigovo run \"your task description\"[/bold]\n")


@app.command()
def doctor(
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Diagnose your Rigovo setup — checks all dependencies and configuration."""
    root = Path(project_dir) if project_dir else Path.cwd()

    console.print("[bold blue]Rigovo[/bold blue] — Doctor\n")

    checks_passed = 0
    checks_failed = 0
    checks_warned = 0

    def ok(msg: str) -> None:
        nonlocal checks_passed
        checks_passed += 1
        console.print(f"  [green]✓[/green] {msg}")

    def fail(msg: str) -> None:
        nonlocal checks_failed
        checks_failed += 1
        console.print(f"  [red]✗[/red] {msg}")

    def warn(msg: str) -> None:
        nonlocal checks_warned
        checks_warned += 1
        console.print(f"  [yellow]![/yellow] {msg}")

    # --- Python version ---
    py_ver = sys.version_info
    if py_ver >= (3, 10):
        ok(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    else:
        fail(f"Python {py_ver.major}.{py_ver.minor} — requires 3.10+")

    # --- Platform ---
    ok(f"Platform: {platform.system()} {platform.machine()}")

    # --- rigovo.yml ---
    if (root / "rigovo.yml").is_file():
        ok("rigovo.yml found")
        try:
            from rigovo.config_schema import load_rigovo_yml
            yml = load_rigovo_yml(root)
            ok(f"rigovo.yml valid (version {yml.version})")
            if yml.project.language:
                ok(f"Project: {yml.project.language}/{yml.project.framework or 'generic'}")
        except Exception as e:
            fail(f"rigovo.yml parse error: {e}")
    else:
        warn("rigovo.yml not found — run `rigovo init`")

    # --- .env ---
    if (root / ".env").is_file():
        ok(".env found")
    else:
        warn(".env not found — API keys need to be set in environment")

    # --- .rigovo directory ---
    if (root / ".rigovo").is_dir():
        ok(".rigovo/ directory exists")
        db_path = root / ".rigovo" / "local.db"
        if db_path.is_file():
            size_kb = db_path.stat().st_size / 1024
            ok(f"Local database exists ({size_kb:.1f} KB)")
        else:
            warn("Local database not initialized — run `rigovo init`")
    else:
        warn(".rigovo/ not found — run `rigovo init`")

    # --- API keys ---
    try:
        container = _load_container(root)
        if container.config.llm.anthropic_api_key:
            key = container.config.llm.anthropic_api_key
            ok(f"ANTHROPIC_API_KEY configured (***{key[-4:]})")
        elif container.config.llm.openai_api_key:
            key = container.config.llm.openai_api_key
            ok(f"OPENAI_API_KEY configured (***{key[-4:]})")
        else:
            fail("No LLM API key configured (ANTHROPIC_API_KEY or OPENAI_API_KEY)")

        if container.config.cloud.api_key:
            ok("RIGOVO_API_KEY configured (cloud sync enabled)")
        else:
            warn("RIGOVO_API_KEY not set — cloud sync disabled")

        container.close()
    except Exception as e:
        fail(f"Config load error: {e}")

    # --- Required packages ---
    required_pkgs = [
        ("typer", "CLI framework"),
        ("rich", "Terminal UI"),
        ("pydantic", "Configuration"),
        ("yaml", "YAML parsing"),
        ("httpx", "HTTP client"),
    ]
    for pkg_name, desc in required_pkgs:
        try:
            __import__(pkg_name)
            ok(f"{pkg_name} installed ({desc})")
        except ImportError:
            fail(f"{pkg_name} not installed ({desc})")

    # --- Optional packages ---
    optional_pkgs = [
        ("anthropic", "Anthropic SDK"),
        ("openai", "OpenAI SDK"),
        ("langgraph", "LangGraph orchestration"),
    ]
    for pkg_name, desc in optional_pkgs:
        try:
            __import__(pkg_name)
            ok(f"{pkg_name} installed ({desc})")
        except ImportError:
            warn(f"{pkg_name} not installed ({desc})")

    # --- Rigour CLI ---
    rigour_path = shutil.which("rigour")
    if rigour_path:
        ok(f"Rigour CLI found: {rigour_path}")
    else:
        warn("Rigour CLI not found — using built-in AST checks as fallback")

    # --- Git ---
    git_path = shutil.which("git")
    if git_path:
        ok(f"git found: {git_path}")
    else:
        warn("git not found — version control features disabled")

    # --- Disk space ---
    usage = shutil.disk_usage(str(root))
    free_gb = usage.free / (1024**3)
    if free_gb > 1:
        ok(f"Disk space: {free_gb:.1f} GB free")
    else:
        warn(f"Low disk space: {free_gb:.2f} GB free")

    # --- Summary ---
    console.print()
    if checks_failed == 0:
        console.print(f"  [bold green]All clear![/bold green] {checks_passed} checks passed", end="")
        if checks_warned > 0:
            console.print(f", {checks_warned} warnings")
        else:
            console.print()
    else:
        console.print(
            f"  [bold red]{checks_failed} issue(s)[/bold red] found, "
            f"{checks_passed} passed, {checks_warned} warnings"
        )
    console.print()


@app.command()
def version() -> None:
    """Show Rigovo CLI version."""
    from rigovo import __version__
    console.print(f"rigovo {__version__}")


# ═══════════════════════════════════════════════════════════════════════════
# P1 Commands
# ═══════════════════════════════════════════════════════════════════════════


@app.command()
def teams(
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
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
            code_marker = "[green]✓[/green]" if role.produces_code else "[dim]—[/dim]"

            # Check for agent override in rigovo.yml
            override = team_cfg.agents.get(role.role_id) if team_cfg else None
            model = override.model if (override and override.model) else role.default_llm_model
            rule_count = len(override.rules) if override else 0

            table.add_row(
                role.name,
                code_marker,
                model,
                str(rule_count) if rule_count else "[dim]—[/dim]",
            )

        console.print(table)
        console.print()

        console.print(f"  [bold]Task types:[/bold] {', '.join(t.name for t in task_types)}")
        console.print()

    container.close()


@app.command()
def agents(
    detail: str | None = typer.Argument(None, help="Role ID to inspect (e.g., 'coder')"),
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
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
            # Deep inspect a single agent
            role = next((r for r in roles if r.role_id == detail), None)
            if not role:
                console.print(f"[red]Unknown role:[/red] {detail}")
                console.print(f"Available: {', '.join(r.role_id for r in roles)}")
                raise typer.Exit(1)

            override = team_cfg.agents.get(role.role_id) if team_cfg else None
            model = override.model if (override and override.model) else role.default_llm_model

            console.print(f"  [bold cyan]{role.name}[/bold cyan] ({role.role_id})")
            console.print(f"  {role.description}")
            console.print()
            console.print(f"  [bold]Model:[/bold]          {model}")
            console.print(f"  [bold]Produces code:[/bold]  {'Yes' if role.produces_code else 'No'}")
            console.print(f"  [bold]Pipeline order:[/bold] {role.pipeline_order}")

            # Tools
            tools = plugin.get_tools(role.role_id)
            if tools:
                tool_names = [t.get("name", "?") for t in tools]
                console.print(f"  [bold]Tools:[/bold]          {', '.join(tool_names)}")

            # Rules from rigovo.yml
            if override and override.rules:
                console.print(f"\n  [bold]Custom rules ({len(override.rules)}):[/bold]")
                for rule in override.rules:
                    console.print(f"    • {rule}")

            # Agent config overrides
            if override:
                console.print(f"\n  [bold]Configuration:[/bold]")
                console.print(f"    Temperature:      {override.temperature}")
                console.print(f"    Max tokens:       {override.max_tokens:,}")
                console.print(f"    Max retries:      {override.max_retries}")
                console.print(f"    Timeout:          {override.timeout_seconds}s")
                console.print(f"    Approval needed:  {'Yes' if override.approval_required else 'No'}")

            console.print()
        else:
            # Summary table for all agents
            table = Table(title=f"{plugin.name} Agents")
            table.add_column("Role ID", style="cyan")
            table.add_column("Name")
            table.add_column("Model")
            table.add_column("Code", justify="center")
            table.add_column("Rules", justify="right")
            table.add_column("Tools", justify="right")

            for role in roles:
                override = team_cfg.agents.get(role.role_id) if team_cfg else None
                model = override.model if (override and override.model) else role.default_llm_model
                rule_count = len(override.rules) if override else 0
                tool_count = len(plugin.get_tools(role.role_id))

                # Shorten model name for display
                short_model = model.replace("claude-sonnet-4-5-20250929", "sonnet-4.5") \
                    .replace("claude-opus-4-5-20251101", "opus-4.5") \
                    .replace("claude-haiku-4-5-20251001", "haiku-4.5")

                table.add_row(
                    role.role_id,
                    role.name,
                    short_model,
                    "[green]✓[/green]" if role.produces_code else "[dim]—[/dim]",
                    str(rule_count) if rule_count else "[dim]—[/dim]",
                    str(tool_count),
                )

            console.print(table)
            console.print(f"\n  [dim]Inspect a specific agent: rigovo agents <role_id>[/dim]\n")

    container.close()


@app.command("config")
def config_cmd(
    key: str | None = typer.Argument(None, help="Config key to get/set (dot notation)"),
    value: str | None = typer.Option(None, "--set", "-s", help="Value to set"),
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Show or update rigovo.yml configuration."""
    root = Path(project_dir) if project_dir else Path.cwd()

    yml_path = root / "rigovo.yml"
    if not yml_path.is_file():
        console.print("[yellow]No rigovo.yml found.[/yellow] Run: [bold]rigovo init[/bold]")
        raise typer.Exit(1)

    from rigovo.config_schema import load_rigovo_yml, save_rigovo_yml

    yml = load_rigovo_yml(root)

    if key and value:
        # SET mode: update a config value
        _set_config_value(yml, key, value)
        save_rigovo_yml(yml, root)
        console.print(f"  [green]✓[/green] Set {key} = {value}")
        console.print(f"  Updated rigovo.yml")
    elif key:
        # GET mode: show a specific key
        val = _get_config_value(yml, key)
        if val is not None:
            console.print(f"  {key} = {val}")
        else:
            console.print(f"  [red]Key not found:[/red] {key}")
    else:
        # SHOW mode: display full config
        console.print("[bold blue]Rigovo[/bold blue] — Configuration\n")

        import yaml
        data = yml.model_dump(exclude_defaults=False)
        yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
        console.print(yaml_str)


@app.command()
def history(
    task_id: str | None = typer.Argument(None, help="Task ID to inspect"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of tasks to show"),
    status_filter: str | None = typer.Option(None, "--status", help="Filter by status"),
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Show task history — past runs with outcomes, costs, and durations."""
    root = Path(project_dir) if project_dir else Path.cwd()
    container = _load_container(root)

    console.print("[bold blue]Rigovo[/bold blue] — History\n")

    db = container.get_db()
    from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
    from rigovo.infrastructure.persistence.sqlite_audit_repo import SqliteAuditRepository

    task_repo = SqliteTaskRepository(db)
    audit_repo = SqliteAuditRepository(db)
    workspace_id = UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)

    if task_id:
        # Show single task detail
        task = asyncio.run(task_repo.get(UUID(task_id)))
        if not task:
            console.print(f"  [red]Task not found:[/red] {task_id}")
            raise typer.Exit(1)

        status_colors = {"completed": "green", "failed": "red", "rejected": "yellow", "running": "blue"}
        color = status_colors.get(task.status.value, "white")

        console.print(f"  [bold]Task ID:[/bold]     {task.id}")
        console.print(f"  [bold]Status:[/bold]      [{color}]{task.status.value}[/{color}]")
        console.print(f"  [bold]Description:[/bold] {task.description}")
        console.print(f"  [bold]Created:[/bold]     {task.created_at}")
        console.print(f"  [bold]Duration:[/bold]    {(task.duration_ms or 0) / 1000:.1f}s")
        console.print(f"  [bold]Tokens:[/bold]      {task.total_tokens:,}")
        console.print(f"  [bold]Cost:[/bold]        ${task.total_cost_usd:.4f}")

        # Audit trail
        audit_entries = asyncio.run(audit_repo.list_by_task(task.id))
        if audit_entries:
            console.print(f"\n  [bold]Audit trail ({len(audit_entries)} entries):[/bold]")
            for entry in audit_entries:
                console.print(f"    [{entry.action.value}] {entry.agent_role}: {entry.summary}")
    else:
        # Show task list
        tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=limit))

        if not tasks:
            console.print("  [dim]No tasks yet. Run: rigovo run \"your task\"[/dim]")
            container.close()
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
            status_colors = {"completed": "green", "failed": "red", "rejected": "yellow"}
            color = status_colors.get(task.status.value, "white")
            duration_s = (task.duration_ms or 0) / 1000

            table.add_row(
                str(task.id)[:8],
                task.description[:50],
                f"[{color}]{task.status.value}[/{color}]",
                f"{task.total_tokens:,}",
                f"${task.total_cost_usd:.4f}",
                f"{duration_s:.1f}s",
                task.created_at.strftime("%Y-%m-%d %H:%M") if task.created_at else "",
            )

        console.print(table)
        console.print(f"\n  [dim]Inspect a task: rigovo history <task-id>[/dim]")

    console.print()
    container.close()


@app.command()
def costs(
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Show cost breakdown — per-task, per-agent, and totals."""
    root = Path(project_dir) if project_dir else Path.cwd()
    container = _load_container(root)

    console.print("[bold blue]Rigovo[/bold blue] — Cost Report\n")

    db = container.get_db()
    from rigovo.infrastructure.persistence.sqlite_cost_repo import SqliteCostRepository
    from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository

    cost_repo = SqliteCostRepository(db)
    task_repo = SqliteTaskRepository(db)

    workspace_id = UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)
    total = asyncio.run(cost_repo.total_by_workspace(workspace_id))
    tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=20))

    if not tasks and total == 0:
        console.print("  [dim]No tasks run yet. Run: rigovo run \"your task\"[/dim]\n")
        container.close()
        return

    table = Table(title="Recent Tasks")
    table.add_column("Task", max_width=50)
    table.add_column("Status")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Duration", justify="right")

    for task in tasks:
        status_colors = {"completed": "green", "failed": "red", "rejected": "yellow"}
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

    # Budget status
    budget = container.config.yml.orchestration.budget
    console.print(f"\n  [bold]Total spend:[/bold]    ${total:.4f}")
    if budget.monthly_budget > 0:
        pct = (total / budget.monthly_budget) * 100
        color = "green" if pct < 80 else "yellow" if pct < 100 else "red"
        console.print(f"  [bold]Monthly budget:[/bold] ${budget.monthly_budget:.2f} ([{color}]{pct:.0f}% used[/{color}])")
    console.print()

    container.close()


@app.command()
def status(
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Show current project status — config, health, and stats."""
    root = Path(project_dir) if project_dir else Path.cwd()

    console.print("[bold blue]Rigovo[/bold blue] — Status\n")

    rigovo_dir = root / ".rigovo"
    if not rigovo_dir.exists():
        console.print("  [yellow]Not initialized.[/yellow] Run: [bold]rigovo init[/bold]")
        return

    container = _load_container(root)
    yml = container.config.yml

    console.print(f"  [bold]Project:[/bold]    {yml.project.name or root.name}")
    console.print(f"  [bold]Path:[/bold]       {root}")
    if yml.project.language:
        console.print(f"  [bold]Stack:[/bold]      {yml.project.language}/{yml.project.framework or 'generic'}")

    # LLM
    has_key = bool(container.config.llm.api_key)
    model = container.config.llm.model
    provider = container.config.llm.provider
    console.print(f"  [bold]Provider:[/bold]   {provider}")
    console.print(f"  [bold]Model:[/bold]      {model}")
    console.print(f"  [bold]API Key:[/bold]    {'[green]configured[/green]' if has_key else '[red]missing[/red]'}")

    # Cloud
    cloud_key = bool(container.config.cloud.api_key)
    console.print(f"  [bold]Cloud sync:[/bold] {'[green]enabled[/green]' if cloud_key else '[dim]disabled[/dim]'}")

    # Quality
    rigour_path = shutil.which("rigour")
    console.print(f"  [bold]Rigour CLI:[/bold] {'[green]' + rigour_path + '[/green]' if rigour_path else '[dim]fallback (built-in checks)[/dim]'}")

    # DB stats
    db = container.get_db()
    from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
    task_repo = SqliteTaskRepository(db)
    workspace_id = UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)
    tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=1000))
    completed = sum(1 for t in tasks if t.status.value == "completed")
    failed = sum(1 for t in tasks if t.status.value == "failed")
    console.print(f"  [bold]Tasks:[/bold]      {len(tasks)} total ({completed} completed, {failed} failed)")

    # Budget
    budget = yml.orchestration.budget
    console.print(f"  [bold]Budget:[/bold]     ${budget.max_cost_per_task:.2f}/task, ${budget.monthly_budget:.2f}/month")

    container.close()
    console.print()


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
        console.print(f"  [green]✓[/green] Authenticated — workspace: {workspace_id}")
        console.print(f"\n  Add to your .env:")
        console.print(f"    RIGOVO_API_KEY={api_key}")
        console.print(f"    RIGOVO_WORKSPACE_ID={workspace_id}\n")
    else:
        console.print("  [red]✗ Authentication failed.[/red]")
        console.print("  Check your API key at https://app.rigovo.com/settings\n")

    asyncio.run(client.close())


# ═══════════════════════════════════════════════════════════════════════════
# P2 Commands
# ═══════════════════════════════════════════════════════════════════════════


@app.command("export")
def export_cmd(
    format: str = typer.Option("json", "--format", "-f", help="Output format: json, csv"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path"),
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    """Export task history, costs, and agent stats as JSON or CSV."""
    root = Path(project_dir) if project_dir else Path.cwd()
    container = _load_container(root)

    db = container.get_db()
    from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
    from rigovo.infrastructure.persistence.sqlite_cost_repo import SqliteCostRepository
    from rigovo.infrastructure.persistence.sqlite_audit_repo import SqliteAuditRepository

    task_repo = SqliteTaskRepository(db)
    cost_repo = SqliteCostRepository(db)
    audit_repo = SqliteAuditRepository(db)
    workspace_id = UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)

    tasks = asyncio.run(task_repo.list_by_workspace(workspace_id, limit=10000))
    total_cost = asyncio.run(cost_repo.total_by_workspace(workspace_id))

    if format == "json":
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
                    "created_at": t.created_at.isoformat() if t.created_at else None,
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

    elif format == "csv":
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "description", "status", "tokens", "cost_usd", "duration_ms", "created_at"])
        for t in tasks:
            writer.writerow([
                str(t.id), t.description, t.status.value,
                t.total_tokens, f"{t.total_cost_usd:.6f}",
                t.duration_ms, t.created_at.isoformat() if t.created_at else "",
            ])

        csv_str = buf.getvalue()
        if output:
            Path(output).write_text(csv_str)
            console.print(f"  [green]✓[/green] Exported {len(tasks)} tasks to {output}")
        else:
            print(csv_str)
    else:
        console.print(f"[red]Unknown format:[/red] {format}. Use json or csv.")
        raise typer.Exit(1)

    container.close()


# ═══════════════════════════════════════════════════════════════════════════
# P3 Commands
# ═══════════════════════════════════════════════════════════════════════════


@app.command()
def dashboard() -> None:
    """Open the Rigovo cloud dashboard in your browser."""
    url = "https://app.rigovo.com"
    console.print(f"  Opening {url} ...")
    webbrowser.open(url)


@app.command()
def replay(
    task_id: str = typer.Argument(..., help="Task ID to replay"),
    project_dir: str | None = typer.Option(None, "--project", "-p", help="Project directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
) -> None:
    """Re-run a previously failed task with the same context."""
    root = Path(project_dir) if project_dir else Path.cwd()
    container = _load_container(root)

    db = container.get_db()
    from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
    task_repo = SqliteTaskRepository(db)

    task = asyncio.run(task_repo.get(UUID(task_id)))
    if not task:
        console.print(f"[red]Task not found:[/red] {task_id}")
        raise typer.Exit(1)

    console.print(f"[bold blue]Rigovo[/bold blue] — Replaying task\n")
    console.print(f"  [dim]Original:[/dim] {task.description}")
    console.print(f"  [dim]Status:[/dim]   {task.status.value}")
    console.print()

    # Re-run with the same description
    _setup_logging(verbose)
    try:
        cmd = container.build_run_task_command(offline=False)
        result = asyncio.run(cmd.execute(description=task.description))

        if result["status"] == "failed":
            console.print(f"\n[red]Replay failed:[/red] {result.get('error', 'Unknown error')}")
        else:
            console.print(f"\n[green]Replay completed:[/green] ${result.get('total_cost_usd', 0):.4f}")
    finally:
        container.close()


@app.command()
def upgrade() -> None:
    """Check for Rigovo CLI updates."""
    from rigovo import __version__

    console.print(f"[bold blue]Rigovo[/bold blue] — Upgrade Check\n")
    console.print(f"  Current version: {__version__}")
    console.print(f"  Checking PyPI...")

    try:
        import httpx
        resp = httpx.get("https://pypi.org/pypi/rigovo/json", timeout=10)
        if resp.status_code == 200:
            latest = resp.json()["info"]["version"]
            if latest != __version__:
                console.print(f"  [yellow]Update available:[/yellow] {latest}")
                console.print(f"  Run: [bold]pip install --upgrade rigovo[/bold]")
            else:
                console.print(f"  [green]✓[/green] You're on the latest version")
        else:
            console.print(f"  [dim]Package not yet published to PyPI[/dim]")
    except Exception:
        console.print(f"  [dim]Could not check for updates[/dim]")
    console.print()


# ═══════════════════════════════════════════════════════════════════════════
# Config helpers
# ═══════════════════════════════════════════════════════════════════════════


def _set_config_value(yml: "RigovoConfig", key: str, value: str) -> None:
    """Set a config value using dot notation (e.g., 'orchestration.max_retries')."""
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

    # Try to coerce value to the right type
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


def _get_config_value(yml: "RigovoConfig", key: str) -> Any:
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


if __name__ == "__main__":
    app()
