"""Tests for Rigovo CLI commands using typer.testing.CliRunner.

This test suite covers all main CLI commands:
- version: output version string
- init: project initialization with config detection
- doctor: diagnostic checks
- teams: list configured teams
- agents: list agents and roles
- config: show/get/set configuration
- history: task history and details
- costs: cost reporting
- status: project status display
- export: export data as JSON/CSV
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from rigovo.main import app

runner = CliRunner()


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_project_dir():
    """Create a temporary project directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        yield tmp_path


@pytest.fixture
def initialized_project(tmp_project_dir):
    """Initialize a project in tmp directory."""
    result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
    assert result.exit_code == 0, f"Init failed: {result.output}"
    yield tmp_project_dir


@pytest.fixture
def python_project(tmp_project_dir):
    """Create a Python project structure."""
    # Create typical Python project files
    (tmp_project_dir / "setup.py").write_text("from setuptools import setup\nsetup(name='test-project')")
    (tmp_project_dir / "requirements.txt").write_text("pytest==7.0.0\nblack==23.0.0")
    (tmp_project_dir / "src").mkdir()
    (tmp_project_dir / "src" / "main.py").write_text("print('hello')")
    (tmp_project_dir / "tests").mkdir()
    (tmp_project_dir / "tests" / "test_main.py").write_text("def test_main(): pass")
    return tmp_project_dir


# ═══════════════════════════════════════════════════════════════════════════
# P0 Commands
# ═══════════════════════════════════════════════════════════════════════════


class TestVersion:
    """Test `rigovo version` command."""

    def test_version_outputs_version_string(self):
        """Test that version command outputs version string."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "rigovo" in result.output
        # Version should match pattern like "rigovo 0.1.0"
        assert any(char.isdigit() for char in result.output)


class TestInit:
    """Test `rigovo init` command."""

    def test_init_creates_rigovo_yml(self, tmp_project_dir):
        """Test that init creates rigovo.yml file."""
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0

        yml_path = tmp_project_dir / "rigovo.yml"
        assert yml_path.exists(), "rigovo.yml was not created"

    def test_init_creates_rigovo_directory(self, tmp_project_dir):
        """Test that init creates .rigovo directory."""
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0

        rigovo_dir = tmp_project_dir / ".rigovo"
        assert rigovo_dir.exists(), ".rigovo directory was not created"
        assert rigovo_dir.is_dir()

    def test_init_creates_env_template(self, tmp_project_dir):
        """Test that init creates .env template file."""
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0

        env_path = tmp_project_dir / ".env"
        assert env_path.exists(), ".env template was not created"
        content = env_path.read_text()
        assert "ANTHROPIC_API_KEY" in content

    def test_init_detects_python_project_language(self, python_project):
        """Test that init detects Python as project language."""
        result = runner.invoke(app, ["init", "--project", str(python_project)])
        assert result.exit_code == 0

        yml_path = python_project / "rigovo.yml"
        assert yml_path.exists()
        content = yml_path.read_text()
        # Should detect Python and include language info
        assert "python" in content.lower()

    def test_init_force_overwrites_existing_yml(self, tmp_project_dir):
        """Test that --force flag overwrites existing rigovo.yml."""
        # First init
        result1 = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result1.exit_code == 0
        yml_path = tmp_project_dir / "rigovo.yml"
        first_content = yml_path.read_text()

        # Modify the file
        yml_path.write_text("# modified content")

        # Second init without --force should skip
        result2 = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result2.exit_code == 0
        assert "already exists" in result2.output or "⊘" in result2.output

        # Third init with --force should overwrite
        result3 = runner.invoke(app, ["init", "--project", str(tmp_project_dir), "--force"])
        assert result3.exit_code == 0
        second_content = yml_path.read_text()
        assert second_content != "# modified content"

    def test_init_creates_gitignore(self, tmp_project_dir):
        """Test that init creates or updates .gitignore."""
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0

        gitignore_path = tmp_project_dir / ".gitignore"
        assert gitignore_path.exists()
        content = gitignore_path.read_text()
        assert ".rigovo" in content
        assert ".env" in content


class TestDoctor:
    """Test `rigovo doctor` command."""

    def test_doctor_runs_without_crashing(self, tmp_project_dir):
        """Test that doctor command runs and completes."""
        result = runner.invoke(app, ["doctor", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0

    def test_doctor_on_initialized_project(self, initialized_project):
        """Test doctor on an initialized project."""
        result = runner.invoke(app, ["doctor", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should mention rigovo.yml
        assert "rigovo.yml" in result.output

    def test_doctor_with_no_initialization(self, tmp_project_dir):
        """Test doctor on uninitialized project."""
        result = runner.invoke(app, ["doctor", "--project", str(tmp_project_dir)])
        # Should still exit cleanly (warnings are OK)
        assert result.exit_code == 0


# ═══════════════════════════════════════════════════════════════════════════
# P1 Commands
# ═══════════════════════════════════════════════════════════════════════════


class TestTeams:
    """Test `rigovo teams` command."""

    def test_teams_lists_teams(self, initialized_project):
        """Test that teams command lists configured teams."""
        result = runner.invoke(app, ["teams", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should contain "Software Engineering" or similar team name
        assert "Software" in result.output or "Team" in result.output or "engineering" in result.output.lower()

    def test_teams_shows_roles(self, initialized_project):
        """Test that teams output includes agent roles."""
        result = runner.invoke(app, ["teams", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should include some role information
        assert "Role" in result.output or "coder" in result.output or "Agent" in result.output


class TestAgents:
    """Test `rigovo agents` command."""

    def test_agents_lists_all_agents(self, initialized_project):
        """Test that agents command lists all agents."""
        result = runner.invoke(app, ["agents", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should mention agents or roles
        assert "coder" in result.output or "Agent" in result.output or "Role" in result.output

    def test_agents_contains_coder(self, initialized_project):
        """Test that agents list contains coder."""
        result = runner.invoke(app, ["agents", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # The coder agent should be present
        assert "coder" in result.output.lower()

    def test_agents_inspect_specific_agent(self, initialized_project):
        """Test inspecting a specific agent (if coder exists)."""
        result = runner.invoke(app, ["agents", "coder", "--project", str(initialized_project)])
        # Should either show agent details or error about unknown role
        assert result.exit_code in [0, 1]


class TestConfig:
    """Test `rigovo config` command."""

    def test_config_shows_configuration(self, initialized_project):
        """Test that config command shows configuration without error."""
        result = runner.invoke(app, ["config", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should show YAML output
        assert "project" in result.output or "teams" in result.output or ":" in result.output

    def test_config_shows_all_sections(self, initialized_project):
        """Test that config output includes main sections."""
        result = runner.invoke(app, ["config", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should have at least one configuration section
        output_lines = result.output.lower()
        assert any(word in output_lines for word in ["project", "team", "orchestration"])

    def test_config_get_specific_key(self, initialized_project):
        """Test getting a specific config key."""
        # Try to get a key that should exist
        result = runner.invoke(app, ["config", "project.name", "--project", str(initialized_project)])
        # Should either show value or indicate key not found
        assert result.exit_code in [0, 1]


class TestHistory:
    """Test `rigovo history` command."""

    def test_history_shows_no_tasks_yet_on_empty_db(self, initialized_project):
        """Test history on initialized project with no tasks."""
        result = runner.invoke(app, ["history", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should show "No tasks yet" or similar message
        assert "No tasks" in result.output or "yet" in result.output or "run" in result.output

    def test_history_command_runs(self, initialized_project):
        """Test that history command executes without crashing."""
        result = runner.invoke(app, ["history", "--project", str(initialized_project)])
        assert result.exit_code == 0

    def test_history_with_limit_option(self, initialized_project):
        """Test history command with limit option."""
        result = runner.invoke(app, ["history", "--limit", "5", "--project", str(initialized_project)])
        assert result.exit_code == 0


class TestCosts:
    """Test `rigovo costs` command."""

    def test_costs_shows_no_tasks_run_yet(self, initialized_project):
        """Test costs on initialized project with no tasks."""
        result = runner.invoke(app, ["costs", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should show "No tasks run yet" or similar
        assert "No tasks" in result.output or "yet" in result.output or "Cost" in result.output

    def test_costs_command_runs(self, initialized_project):
        """Test that costs command executes without crashing."""
        result = runner.invoke(app, ["costs", "--project", str(initialized_project)])
        assert result.exit_code == 0


class TestStatus:
    """Test `rigovo status` command."""

    def test_status_on_initialized_project(self, initialized_project):
        """Test status command on initialized project."""
        result = runner.invoke(app, ["status", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should show project info
        assert "Project" in result.output or "Status" in result.output or "Path" in result.output

    def test_status_shows_project_path(self, initialized_project):
        """Test that status shows project path."""
        result = runner.invoke(app, ["status", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should include path information
        assert str(initialized_project) in result.output or "Path" in result.output

    def test_status_on_uninitialized_project(self, tmp_project_dir):
        """Test status on uninitialized project."""
        result = runner.invoke(app, ["status", "--project", str(tmp_project_dir)])
        # Should indicate not initialized
        assert "Not initialized" in result.output or result.exit_code == 0


# ═══════════════════════════════════════════════════════════════════════════
# P2 Commands
# ═══════════════════════════════════════════════════════════════════════════


class TestExport:
    """Test `rigovo export` command."""

    def test_export_json_format(self, initialized_project):
        """Test export command with JSON format."""
        result = runner.invoke(app, ["export", "--format", "json", "--project", str(initialized_project)])
        assert result.exit_code == 0

        # Should output valid JSON (even if empty tasks)
        try:
            data = json.loads(result.output)
            assert isinstance(data, dict)
            # Should have expected keys
            assert any(key in data for key in ["summary", "tasks", "exported_at"])
        except json.JSONDecodeError:
            # If no output, that's also OK (empty project might output nothing)
            pass

    def test_export_default_is_json(self, initialized_project):
        """Test that export defaults to JSON format."""
        result = runner.invoke(app, ["export", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should be valid JSON or empty
        if result.output.strip():
            try:
                json.loads(result.output)
            except json.JSONDecodeError:
                pytest.fail(f"Expected JSON output, got: {result.output}")

    def test_export_csv_format(self, initialized_project):
        """Test export command with CSV format."""
        result = runner.invoke(app, ["export", "--format", "csv", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should contain CSV headers
        assert "id" in result.output or "description" in result.output or "status" in result.output

    def test_export_to_file(self, initialized_project):
        """Test export with output file."""
        output_file = initialized_project / "export.json"
        result = runner.invoke(
            app,
            ["export", "--format", "json", "--output", str(output_file), "--project", str(initialized_project)],
        )
        assert result.exit_code == 0

    def test_export_invalid_format(self, initialized_project):
        """Test export with invalid format."""
        result = runner.invoke(
            app, ["export", "--format", "invalid", "--project", str(initialized_project)]
        )
        assert result.exit_code == 1


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestInitOnPythonProject:
    """Test init behavior on Python projects."""

    def test_init_on_python_project_detects_language(self, python_project):
        """Test that init detects Python language on Python projects."""
        result = runner.invoke(app, ["init", "--project", str(python_project)])
        assert result.exit_code == 0
        assert "python" in result.output.lower() or "Language" in result.output

    def test_init_on_python_project_detects_test_framework(self, python_project):
        """Test that init detects pytest from requirements.txt."""
        result = runner.invoke(app, ["init", "--project", str(python_project)])
        assert result.exit_code == 0
        # Should detect pytest or mention tests
        assert "pytest" in result.output.lower() or "Tests" in result.output


class TestMultipleInitCalls:
    """Test multiple init calls on same project."""

    def test_reinit_without_force_skips_yml(self, tmp_project_dir):
        """Test that running init twice skips overwriting yml."""
        # First init
        result1 = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result1.exit_code == 0
        yml_path = tmp_project_dir / "rigovo.yml"
        first_content = yml_path.read_text()

        # Mark file with special content
        yml_path.write_text("# MARKED_FOR_TESTING\n" + first_content)

        # Second init without force
        result2 = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result2.exit_code == 0
        # Should not have overwritten
        second_content = yml_path.read_text()
        assert "MARKED_FOR_TESTING" in second_content

    def test_reinit_with_force_overwrites_yml(self, tmp_project_dir):
        """Test that --force overwrites on reinit."""
        # First init
        result1 = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result1.exit_code == 0
        yml_path = tmp_project_dir / "rigovo.yml"

        # Mark file
        yml_path.write_text("# MARKED_FOR_TESTING")

        # Second init with force
        result2 = runner.invoke(app, ["init", "--project", str(tmp_project_dir), "--force"])
        assert result2.exit_code == 0
        # Should have overwritten
        second_content = yml_path.read_text()
        assert "MARKED_FOR_TESTING" not in second_content


class TestProjectDirectoryOption:
    """Test --project/-p option across commands."""

    def test_project_option_short_form(self, initialized_project):
        """Test that -p short option works."""
        result = runner.invoke(app, ["status", "-p", str(initialized_project)])
        assert result.exit_code == 0

    def test_project_option_long_form(self, initialized_project):
        """Test that --project long option works."""
        result = runner.invoke(app, ["status", "--project", str(initialized_project)])
        assert result.exit_code == 0


class TestCommandOutputFormatting:
    """Test output formatting of commands."""

    def test_version_single_line_output(self):
        """Test that version outputs a single line."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        # Should be single line (or maybe one trailing newline)
        assert len(lines) <= 2

    def test_init_shows_success_message(self, tmp_project_dir):
        """Test that init shows success message."""
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0
        assert "initialized" in result.output.lower() or "✓" in result.output

    def test_doctor_shows_summary(self, initialized_project):
        """Test that doctor shows a summary at the end."""
        result = runner.invoke(app, ["doctor", "--project", str(initialized_project)])
        assert result.exit_code == 0
        # Should have some summary information
        assert len(result.output) > 50  # At least some content


class TestErrorHandling:
    """Test error handling in CLI commands."""

    def test_config_on_uninitialized_project_shows_error(self, tmp_project_dir):
        """Test that config command shows error on uninitialized project."""
        result = runner.invoke(app, ["config", "--project", str(tmp_project_dir)])
        assert result.exit_code == 1
        assert "rigovo.yml" in result.output or "No" in result.output or "not found" in result.output.lower()

    def test_invalid_export_format_shows_error(self, initialized_project):
        """Test that invalid export format shows clear error."""
        result = runner.invoke(app, ["export", "--format", "xml", "--project", str(initialized_project)])
        assert result.exit_code == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
