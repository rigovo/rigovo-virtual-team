"""Integration tests for Rigovo CLI commands.

This test suite covers:
- Init behavior on Python projects
- Multiple init calls on same project
- Project directory option across commands
- Command output formatting
- Error handling in CLI commands
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
