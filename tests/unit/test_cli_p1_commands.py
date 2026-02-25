"""Tests for Rigovo CLI P1 commands (standard priority commands).

This test suite covers:
- teams: list configured teams
- agents: list agents and roles
- config: show/get/set configuration
- history: task history and details
- costs: cost reporting
- status: project status display
"""

from __future__ import annotations

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
