"""CLI entry point — rigovo command.

P0 commands (run, init, version) live here.
P1/P2/P3 commands are in rigovo.cli.commands_*.py modules.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import typer
from rich.console import Console

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
# P0 Commands — run, init, version
# ═══════════════════════════════════════════════════════════════════════════


@app.command()
def run(
    description: str = typer.Argument(
        ..., help="Task description (what you want done)",
    ),
    team: str | None = typer.Option(None, "--team", "-t", help="Target team"),
    offline: bool = typer.Option(False, "--offline", help="No cloud sync"),
    ci: bool = typer.Option(False, "--ci", help="CI mode: non-interactive"),
    plain: bool = typer.Option(
        False, "--plain", help="Plain output (no live dashboard)",
    ),
    approve: bool = typer.Option(
        False, "--approve", "-a",
        help="Interactive approval mode — pause for human approval at checkpoints",
    ),
    parallel: bool = typer.Option(
        False, "--parallel",
        help="Enable parallel execution for independent agents",
    ),
    resume: str | None = typer.Option(
        None, "--resume", "-r",
        help="Resume from checkpoint (task ID from a previous crashed run)",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose"),
    project_dir: str | None = typer.Option(
        None, "--project", "-p", help="Project directory",
    ),
) -> None:
    """Run a task through your virtual engineering team."""
    _setup_logging(verbose)

    project_root = Path(project_dir) if project_dir else Path.cwd()
    container = _load_container(project_root)

    if not container.config.llm.api_key:
        if ci:
            print(json.dumps({"status": "error", "error": "No API key configured"}))
            raise typer.Exit(1)
        console.print("[red]Error:[/red] No API key configured.")
        console.print("  Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env")
        console.print("  Or run: [bold]rigovo init[/bold]")
        raise typer.Exit(1)

    # --- Read parallel setting from config ---
    enable_parallel = parallel or container.config.yml.orchestration.parallel_agents

    # ╔═══════════════════════════════════════════════════════════════╗
    # ║  Rich Live / plain / CI path — original flow                ║
    # ╚═══════════════════════════════════════════════════════════════╝

    ui = None
    approval_handler = None

    if not ci and not plain:
        from rigovo.infrastructure.terminal.rich_output import TerminalUI

        ui = TerminalUI(console)
        emitter = container.get_event_emitter()

        # Subscribe to ALL pipeline events for real-time display
        for event_type in [
            "task_started", "project_scanned", "task_classified",
            "pipeline_assembled", "agent_started", "agent_streaming",
            "agent_complete", "agent_timeout", "gate_results",
            "approval_requested", "enrichment_extracted",
            "memories_stored", "budget_exceeded",
            "task_finalized", "task_failed",
            "parallel_started", "parallel_complete",
        ]:
            emitter.on(
                event_type,
                lambda data, _et=event_type: ui.handle_event({**data, "type": _et}),
            )

        ui.start(description=description, team=team)

        # --- Interactive approval handler ---
        if approve:
            def approval_handler(state):
                status = state.get("status", "")
                if "plan" in status:
                    checkpoint = "plan_ready"
                    tc = state.get("team_config", {})
                    roles = tc.get("pipeline_order", [])
                    arrow = " \u2192 "
                    details = f"Pipeline: {arrow.join(roles)}"
                else:
                    checkpoint = "commit_ready"
                    agent_outputs = state.get("agent_outputs", {})
                    agents_done = list(agent_outputs.keys()) if isinstance(agent_outputs, dict) else []
                    details = f"Agents completed: {', '.join(agents_done)}" if agents_done else ""
                approved = ui.prompt_approval(checkpoint, details)
                return {
                    "approval_status": "approved" if approved else "rejected",
                    "approval_feedback": "" if approved else "User rejected",
                }
    elif not ci:
        console.print("\n[bold blue]Rigovo[/bold blue] — Starting task...\n")
        console.print(f"  [dim]Description:[/dim] {description}")
        if team:
            console.print(f"  [dim]Team:[/dim] {team}")
        if resume:
            console.print(f"  [dim]Resuming from:[/dim] {resume}")
        if parallel:
            console.print("  [dim]Parallel execution:[/dim] enabled")
        console.print()

    try:
        cmd = container.build_run_task_command(
            offline=offline,
            approval_handler=approval_handler,
            enable_streaming=not plain and not ci,
            enable_parallel=enable_parallel,
            auto_approve=not approve,
        )
        result = asyncio.run(
            cmd.execute(
                description=description,
                team_name=team,
                resume_thread_id=resume,
            )
        )

        if ci:
            print(json.dumps(result, default=str))
        elif result["status"] == "failed" and not ui:
            console.print(
                f"\n[red]Task failed:[/red] {result.get('error', 'Unknown error')}",
            )
            raise typer.Exit(1)

    except KeyboardInterrupt:
        if ui:
            ui.stop()
        if ci:
            print(json.dumps({"status": "interrupted"}))
        else:
            console.print("\n[yellow]Interrupted by user.[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        if ui:
            ui.stop()
        if ci:
            print(json.dumps({"status": "error", "error": str(e)}))
        elif verbose:
            console.print_exception()
        else:
            console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        if ui:
            ui.stop()
        container.close()


@app.command()
def init(
    project_dir: str | None = typer.Option(
        None, "--project", "-p", help="Project directory",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing rigovo.yml",
    ),
) -> None:
    """Initialise a Rigovo project — auto-detects stack, writes rigovo.yml."""
    root = Path(project_dir) if project_dir else Path.cwd()

    console.print("[bold blue]Rigovo[/bold blue] — Initialising project...\n")

    # 1. Create .rigovo directory
    rigovo_dir = root / ".rigovo"
    rigovo_dir.mkdir(parents=True, exist_ok=True)
    console.print("  [green]\u2713[/green] Created .rigovo/ directory")

    # 2. Auto-detect project and generate rigovo.yml
    yml_path = root / "rigovo.yml"
    if yml_path.exists() and not force:
        console.print(
            "  [dim]\u2298 rigovo.yml already exists (use --force to overwrite)[/dim]",
        )
    else:
        from rigovo.config_schema import detect_project_config, save_rigovo_yml

        detected = detect_project_config(root)
        save_rigovo_yml(detected, root)

        proj = detected.project
        console.print("  [green]\u2713[/green] Generated rigovo.yml")
        if proj.language:
            console.print(f"    [dim]Language:[/dim]   {proj.language}")
        if proj.framework:
            console.print(f"    [dim]Framework:[/dim]  {proj.framework}")
        if proj.test_framework:
            console.print(f"    [dim]Tests:[/dim]      {proj.test_framework}")
        if proj.package_manager:
            console.print(f"    [dim]Pkg mgr:[/dim]    {proj.package_manager}")

        eng_team = detected.teams.get("engineering")
        if eng_team:
            coder = eng_team.agents.get("coder")
            if coder and coder.rules:
                console.print(
                    f"    [dim]Coder rules:[/dim] "
                    f"{len(coder.rules)} auto-configured",
                )

    # 3. Create .env template if not exists
    env_file = root / ".env"
    if not env_file.exists():
        env_file.write_text(
            "# Rigovo secrets — DO NOT commit this file\n"
            "# LLM Provider (uncomment one)\n"
            "# ANTHROPIC_API_KEY=sk-ant-...\n"
            "# OPENAI_API_KEY=sk-...\n"
            "# Model override (optional)\n"
            "# LLM_MODEL=claude-sonnet-4-5-20250929\n"
            "# Cloud sync (optional — get key at app.rigovo.com)\n"
            "# RIGOVO_API_KEY=\n"
            "# RIGOVO_WORKSPACE_ID=\n"
        )
        console.print("  [green]\u2713[/green] Created .env template")
    else:
        console.print("  [dim]\u2298 .env already exists[/dim]")

    # 4. Initialize local database
    container = _load_container(root)
    db = container.get_db()
    db.initialize()
    console.print("  [green]\u2713[/green] Initialized local database")

    # 5. Update .gitignore
    _update_gitignore(root)

    container.close()
    console.print("\n[bold green]Project initialized.[/bold green]")
    console.print("  1. Set your API key in [bold].env[/bold]")
    console.print("  2. Review [bold]rigovo.yml[/bold]")
    console.print("  3. Run: [bold]rigovo run \"your task description\"[/bold]\n")


@app.command()
def version() -> None:
    """Show Rigovo CLI version."""
    from rigovo import __version__

    console.print(f"rigovo {__version__}")


# ═══════════════════════════════════════════════════════════════════════════
# Register P1/P2/P3 commands from sub-modules
# ═══════════════════════════════════════════════════════════════════════════

from rigovo.cli import (  # noqa: E402
    commands_data,
    commands_doctor,
    commands_info,
    commands_lifecycle,
)

commands_doctor.register(app)
commands_info.register(app)
commands_data.register(app)
commands_lifecycle.register(app)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _update_gitignore(root: Path) -> None:
    """Add Rigovo entries to .gitignore."""
    gitignore = root / ".gitignore"
    entries_to_add = [".rigovo/", ".env"]
    if gitignore.exists():
        content = gitignore.read_text()
        added = [e for e in entries_to_add if e not in content]
        if added:
            with open(gitignore, "a") as f:
                f.write("\n# Rigovo\n")
                for entry in added:
                    f.write(f"{entry}\n")
            console.print(
                f"  [green]\u2713[/green] Updated .gitignore (+{', '.join(added)})",
            )
    else:
        gitignore.write_text("# Rigovo\n.rigovo/\n.env\n")
        console.print("  [green]\u2713[/green] Created .gitignore")


if __name__ == "__main__":
    app()
