"""Tests for Rigovo CLI P0 commands (high priority, core functionality).

This test suite covers:
- version: output version string
- init: project initialization with config detection
- doctor: diagnostic checks
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
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

    def test_init_writes_full_orchestration_fields(self, tmp_project_dir):
        """init should generate orchestration deep + consultation defaults."""
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0

        yml_path = tmp_project_dir / "rigovo.yml"
        data = yaml.safe_load(yml_path.read_text(encoding="utf-8"))

        orchestration = data["orchestration"]
        assert "deep_mode" in orchestration
        assert "deep_pro" in orchestration
        assert "consultation" in orchestration
        assert "subagents" in orchestration

        consultation = orchestration["consultation"]
        assert "enabled" in consultation
        assert "allowed_targets" in consultation

        subagents = orchestration["subagents"]
        assert "enabled" in subagents
        assert "max_subtasks_per_agent_step" in subagents

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
