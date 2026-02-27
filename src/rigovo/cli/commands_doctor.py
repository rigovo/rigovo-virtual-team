"""Doctor command — diagnose Rigovo setup."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console

console = Console()


def register(app: typer.Typer) -> None:
    """Register the doctor command."""
    app.command()(doctor)


def doctor(
    project_dir: str | None = typer.Option(
        None,
        "--project",
        "-p",
        help="Project directory",
    ),
) -> None:
    """Diagnose your Rigovo setup — checks dependencies and configuration."""
    root = Path(project_dir) if project_dir else Path.cwd()

    console.print("[bold blue]Rigovo[/bold blue] — Doctor\n")

    passed = 0
    failed = 0
    warned = 0

    def ok(msg: str) -> None:
        nonlocal passed
        passed += 1
        console.print(f"  [green]✓[/green] {msg}")

    def fail(msg: str) -> None:
        nonlocal failed
        failed += 1
        console.print(f"  [red]✗[/red] {msg}")

    def warn(msg: str) -> None:
        nonlocal warned
        warned += 1
        console.print(f"  [yellow]![/yellow] {msg}")

    # Python version
    py_ver = sys.version_info
    if py_ver >= (3, 10):
        ok(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    else:
        fail(f"Python {py_ver.major}.{py_ver.minor} — requires 3.10+")

    ok(f"Platform: {platform.system()} {platform.machine()}")

    _check_config(root, ok, fail, warn)
    _check_packages(root, ok, fail, warn)
    _check_tools(ok, warn)
    _check_api_keys(root, ok, fail, warn)
    _check_disk(root, ok, warn)

    # Summary
    console.print()
    if failed == 0:
        console.print(
            f"  [bold green]All clear![/bold green] {passed} checks passed",
            end="",
        )
        if warned > 0:
            console.print(f", {warned} warnings")
        else:
            console.print()
    else:
        console.print(
            f"  [bold red]{failed} issue(s)[/bold red] found, {passed} passed, {warned} warnings",
        )
    console.print()


def _check_config(root: Path, ok, fail, warn) -> None:
    """Check rigovo.yml, .env, .rigovo directory."""
    if (root / "rigovo.yml").is_file():
        ok("rigovo.yml found")
        try:
            from rigovo.config_schema import load_rigovo_yml

            yml = load_rigovo_yml(root)
            ok(f"rigovo.yml valid (version {yml.version})")
            if yml.project.language:
                fw = yml.project.framework or "generic"
                ok(f"Project: {yml.project.language}/{fw}")
        except Exception as e:
            fail(f"rigovo.yml parse error: {e}")
    else:
        warn("rigovo.yml not found — run `rigovo init`")

    if (root / ".env").is_file():
        ok(".env found")
    else:
        warn(".env not found — API keys need to be set in environment")

    if (root / ".rigovo").is_dir():
        ok(".rigovo/ directory exists")
    else:
        warn(".rigovo/ not found — run `rigovo init`")

    # DB backend diagnostics
    try:
        from rigovo.config import load_config

        cfg = load_config(root)
        backend = str(cfg.db_backend).strip().lower()
        ok(f"Database backend: {backend}")
        if backend == "postgres":
            if cfg.db_url:
                ok("RIGOVO_DB_URL configured")
            else:
                fail("RIGOVO_DB_URL missing for postgres backend")
        else:
            db_path = root / ".rigovo" / "local.db"
            if db_path.is_file():
                size_kb = db_path.stat().st_size / 1024
                ok(f"Local database exists ({size_kb:.1f} KB)")
            else:
                warn("Local database not initialized — run `rigovo init`")
    except Exception as e:
        fail(f"Database config check failed: {e}")


def _check_packages(root: Path, ok, fail, warn) -> None:
    """Check required and optional packages."""
    for pkg_name, desc in [
        ("typer", "CLI framework"),
        ("rich", "Terminal UI"),
        ("pydantic", "Configuration"),
        ("yaml", "YAML parsing"),
        ("httpx", "HTTP client"),
    ]:
        try:
            __import__(pkg_name)
            ok(f"{pkg_name} installed ({desc})")
        except ImportError:
            fail(f"{pkg_name} not installed ({desc})")

    for pkg_name, desc in [
        ("anthropic", "Anthropic SDK"),
        ("openai", "OpenAI SDK"),
        ("langgraph", "LangGraph orchestration"),
    ]:
        try:
            __import__(pkg_name)
            ok(f"{pkg_name} installed ({desc})")
        except ImportError:
            warn(f"{pkg_name} not installed ({desc})")

    try:
        from rigovo.config import load_config

        cfg = load_config(root)
        if str(cfg.db_backend).strip().lower() == "postgres":
            try:
                __import__("psycopg")
                ok("psycopg installed (Postgres driver)")
            except ImportError:
                fail("psycopg not installed (required for postgres backend)")
    except Exception:
        # Keep doctor resilient; backend check already runs in _check_config.
        pass


def _check_tools(ok, warn) -> None:
    """Check external tools."""
    rigour_path = shutil.which("rigour")
    if rigour_path:
        ok(f"Rigour CLI found: {rigour_path}")
    else:
        warn("Rigour CLI not found — using built-in AST checks as fallback")

    git_path = shutil.which("git")
    if git_path:
        ok(f"git found: {git_path}")
    else:
        warn("git not found — version control features disabled")


def _check_api_keys(root, ok, fail, warn) -> None:
    """Check API key configuration."""
    from rigovo.config import load_config
    from rigovo.container import Container

    try:
        config = load_config(root)
        container = Container(config)
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


def _check_disk(root, ok, warn) -> None:
    """Check disk space."""
    usage = shutil.disk_usage(str(root))
    free_gb = usage.free / (1024**3)
    if free_gb > 1:
        ok(f"Disk space: {free_gb:.1f} GB free")
    else:
        warn(f"Low disk space: {free_gb:.2f} GB free")
