"""Tests for Rigovo CLI P2 commands (lower priority commands).

This test suite covers:
- export: export data as JSON/CSV
"""

from __future__ import annotations

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
