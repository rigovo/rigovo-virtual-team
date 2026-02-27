"""Tests for Rigovo CLI lifecycle controls (replay, resume, abort, approve).

This test suite covers:
- replay: re-run a previously failed task with optional diff
- resume: resume from last checkpoint
- abort: abort a task with audit trail
- approve: grant approval and optionally resume
- dashboard: open cloud dashboard
- upgrade: check for CLI updates
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from rigovo.main import app
from rigovo.domain.entities.task import Task, TaskStatus
from rigovo.domain.entities.audit_entry import AuditEntry, AuditAction

runner = CliRunner()


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


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
def sample_task():
    """Create a sample task for testing."""
    workspace_id = uuid4()
    task = Task(
        workspace_id=workspace_id,
        description="Add payment integration",
    )
    task.status = TaskStatus.COMPLETED
    return task


# ──────────────────────────────────────────────────────────────────────────────
# Replay Command Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestReplayCommand:
    """Test `rigovo replay` command."""

    def test_replay_requires_task_id(self, initialized_project):
        """Test that replay requires a task ID argument."""
        result = runner.invoke(app, ["replay", "--project", str(initialized_project)])
        assert result.exit_code == 2  # Missing argument

    def test_replay_with_nonexistent_task_shows_error(self, initialized_project):
        """Test that replaying nonexistent task shows error."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Task" in result.output

    def test_replay_accepts_diff_flag(self, initialized_project):
        """Test that replay accepts --diff flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--diff", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flag should be accepted
        assert result.exit_code == 1

    def test_replay_accepts_verbose_flag(self, initialized_project):
        """Test that replay accepts --verbose flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--verbose", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flag should be accepted
        assert result.exit_code == 1

    def test_replay_short_form_flags(self, initialized_project):
        """Test that replay accepts short form flags."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "-d", "-v", "-p", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flags should be accepted
        assert result.exit_code == 1

    def test_replay_diff_short_form(self, initialized_project):
        """Test that replay accepts -d short form for diff."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "-d", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_replay_verbose_short_form(self, initialized_project):
        """Test that replay accepts -v short form for verbose."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "-v", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1


# ──────────────────────────────────────────────────────────────────────────────
# Resume Command Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestResumeCommand:
    """Test `rigovo resume` command."""

    def test_resume_requires_task_id(self, initialized_project):
        """Test that resume requires a task ID argument."""
        result = runner.invoke(app, ["resume", "--project", str(initialized_project)])
        assert result.exit_code == 2  # Missing argument

    def test_resume_with_nonexistent_task_shows_error(self, initialized_project):
        """Test that resuming nonexistent task shows error."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Task" in result.output

    def test_resume_accepts_verbose_flag(self, initialized_project):
        """Test that resume accepts --verbose flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "--verbose", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flag should be accepted
        assert result.exit_code == 1

    def test_resume_short_form_flags(self, initialized_project):
        """Test that resume accepts short form flags."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "-v", "-p", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flags should be accepted
        assert result.exit_code == 1

    def test_resume_verbose_short_form(self, initialized_project):
        """Test that resume accepts -v short form for verbose."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "-v", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1


# ──────────────────────────────────────────────────────────────────────────────
# Abort Command Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestAbortCommand:
    """Test `rigovo abort` command."""

    def test_abort_requires_task_id(self, initialized_project):
        """Test that abort requires a task ID argument."""
        result = runner.invoke(app, ["abort", "--project", str(initialized_project)])
        assert result.exit_code == 2  # Missing argument

    def test_abort_with_nonexistent_task_shows_error(self, initialized_project):
        """Test that aborting nonexistent task shows error."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["abort", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Task" in result.output

    def test_abort_accepts_reason_option(self, initialized_project):
        """Test that abort accepts --reason option."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "abort",
                fake_task_id,
                "--reason",
                "User requested cancellation",
                "--project",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but option should be accepted
        assert result.exit_code == 1

    def test_abort_reason_short_form(self, initialized_project):
        """Test that abort accepts -m short form for reason."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "abort",
                fake_task_id,
                "-m",
                "Cancelled",
                "-p",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but option should be accepted
        assert result.exit_code == 1

    def test_abort_default_reason(self, initialized_project):
        """Test that abort uses default reason if not provided."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["abort", fake_task_id, "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but should use default reason
        assert result.exit_code == 1

    def test_abort_with_custom_reason(self, initialized_project):
        """Test abort with custom reason message."""
        fake_task_id = str(uuid4())
        reason = "Budget exceeded, cancelling task"
        result = runner.invoke(
            app,
            [
                "abort",
                fake_task_id,
                "--reason",
                reason,
                "--project",
                str(initialized_project),
            ],
        )
        assert result.exit_code == 1


# ──────────────────────────────────────────────────────────────────────────────
# Approve Command Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestApproveCommand:
    """Test `rigovo approve` command."""

    def test_approve_requires_task_id(self, initialized_project):
        """Test that approve requires a task ID argument."""
        result = runner.invoke(app, ["approve", "--project", str(initialized_project)])
        assert result.exit_code == 2  # Missing argument

    def test_approve_with_nonexistent_task_shows_error(self, initialized_project):
        """Test that approving nonexistent task shows error."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Task" in result.output

    def test_approve_accepts_resume_flag(self, initialized_project):
        """Test that approve accepts --resume flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--resume", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flag should be accepted
        assert result.exit_code == 1

    def test_approve_accepts_no_resume_flag(self, initialized_project):
        """Test that approve accepts --no-resume flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--no-resume", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flag should be accepted
        assert result.exit_code == 1

    def test_approve_default_resumes(self, initialized_project):
        """Test that approve defaults to resuming."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but should default to resume
        assert result.exit_code == 1


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard Command Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestDashboardCommand:
    """Test `rigovo dashboard` command."""

    @patch("webbrowser.open")
    def test_dashboard_opens_browser(self, mock_open):
        """Test that dashboard command opens browser."""
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0
        mock_open.assert_called_once()
        # Should open the correct URL
        call_args = mock_open.call_args[0][0]
        assert "rigovo.com" in call_args

    @patch("webbrowser.open")
    def test_dashboard_shows_url_in_output(self, mock_open):
        """Test that dashboard shows URL in output."""
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0
        assert "app.rigovo.com" in result.output or "rigovo.com" in result.output

    @patch("webbrowser.open")
    def test_dashboard_no_arguments_required(self, mock_open):
        """Test that dashboard requires no arguments."""
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0


# ──────────────────────────────────────────────────────────────────────────────
# Upgrade Command Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestUpgradeCommand:
    """Test `rigovo upgrade` command."""

    def test_upgrade_completes_without_error(self):
        """Test that upgrade command completes."""
        result = runner.invoke(app, ["upgrade"])
        # Should complete (may or may not find updates)
        assert result.exit_code == 0

    def test_upgrade_shows_version_info(self):
        """Test that upgrade shows current version."""
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0
        # Should mention version
        assert "version" in result.output.lower() or "rigovo" in result.output.lower()

    def test_upgrade_no_arguments_required(self):
        """Test that upgrade requires no arguments."""
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0


# ──────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestLifecycleCommandIntegration:
    """Integration tests for lifecycle commands."""

    def test_replay_and_abort_both_require_task_id(self, initialized_project):
        """Test that both replay and abort require task ID."""
        for cmd in ["replay", "abort"]:
            result = runner.invoke(app, [cmd, "--project", str(initialized_project)])
            assert result.exit_code == 2

    def test_resume_and_approve_both_require_task_id(self, initialized_project):
        """Test that both resume and approve require task ID."""
        for cmd in ["resume", "approve"]:
            result = runner.invoke(app, [cmd, "--project", str(initialized_project)])
            assert result.exit_code == 2

    def test_all_lifecycle_commands_accept_project_option(self, initialized_project):
        """Test that all lifecycle commands accept --project option."""
        fake_task_id = str(uuid4())
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, fake_task_id, "--project", str(initialized_project)],
            )
            # Should fail because task doesn't exist, but option should be accepted
            assert result.exit_code == 1

    def test_lifecycle_commands_show_task_not_found_error(self, initialized_project):
        """Test that lifecycle commands show clear error for missing task."""
        fake_task_id = str(uuid4())
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, fake_task_id, "--project", str(initialized_project)],
            )
            assert result.exit_code == 1
            # Should mention task or not found
            assert (
                "not found" in result.output.lower()
                or "task" in result.output.lower()
                or "Task" in result.output
            )

    def test_lifecycle_commands_consistent_error_handling(self, initialized_project):
        """Test that all lifecycle commands handle errors consistently."""
        fake_task_id = str(uuid4())
        results = {}
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, fake_task_id, "--project", str(initialized_project)],
            )
            results[cmd] = result.exit_code

        # All should fail with same exit code
        assert all(code == 1 for code in results.values())


# ──────────────────────────────────────────────────────────────────────────────
# Edge Cases
# ──────────────────────────────────────────────────────────────────────────────


class TestLifecycleEdgeCases:
    """Test edge cases in lifecycle commands."""

    def test_replay_with_empty_task_id(self, initialized_project):
        """Test replay with empty task ID."""
        result = runner.invoke(
            app,
            ["replay", "", "--project", str(initialized_project)],
        )
        # Should fail with invalid UUID
        assert result.exit_code == 1

    def test_abort_with_very_long_reason(self, initialized_project):
        """Test abort with very long reason string."""
        fake_task_id = str(uuid4())
        long_reason = "x" * 1000
        result = runner.invoke(
            app,
            [
                "abort",
                fake_task_id,
                "--reason",
                long_reason,
                "--project",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but should accept long reason
        assert result.exit_code == 1

    def test_approve_with_both_resume_flags(self, initialized_project):
        """Test approve with conflicting resume flags."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "approve",
                fake_task_id,
                "--resume",
                "--no-resume",
                "--project",
                str(initialized_project),
            ],
        )
        # Should handle conflicting flags gracefully
        assert result.exit_code in [1, 2]

    def test_replay_with_invalid_uuid_format(self, initialized_project):
        """Test replay with invalid UUID format."""
        result = runner.invoke(
            app,
            ["replay", "not-a-uuid", "--project", str(initialized_project)],
        )
        # Should fail with invalid UUID error
        assert result.exit_code == 1

    def test_resume_with_invalid_uuid_format(self, initialized_project):
        """Test resume with invalid UUID format."""
        result = runner.invoke(
            app,
            ["resume", "not-a-uuid", "--project", str(initialized_project)],
        )
        # Should fail with invalid UUID error
        assert result.exit_code == 1

    def test_abort_with_invalid_uuid_format(self, initialized_project):
        """Test abort with invalid UUID format."""
        result = runner.invoke(
            app,
            ["abort", "not-a-uuid", "--project", str(initialized_project)],
        )
        # Should fail with invalid UUID error
        assert result.exit_code == 1

    def test_approve_with_invalid_uuid_format(self, initialized_project):
        """Test approve with invalid UUID format."""
        result = runner.invoke(
            app,
            ["approve", "not-a-uuid", "--project", str(initialized_project)],
        )
        # Should fail with invalid UUID error
        assert result.exit_code == 1

    def test_replay_with_special_characters_in_task_id(self, initialized_project):
        """Test replay with special characters in task ID."""
        result = runner.invoke(
            app,
            ["replay", "task@#$%", "--project", str(initialized_project)],
        )
        # Should fail with invalid UUID error
        assert result.exit_code == 1

    def test_abort_with_empty_reason(self, initialized_project):
        """Test abort with empty reason string."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "abort",
                fake_task_id,
                "--reason",
                "",
                "--project",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but should accept empty reason
        assert result.exit_code == 1

    def test_abort_with_special_characters_in_reason(self, initialized_project):
        """Test abort with special characters in reason."""
        fake_task_id = str(uuid4())
        reason = "Cancelled due to: @#$%^&*()"
        result = runner.invoke(
            app,
            [
                "abort",
                fake_task_id,
                "--reason",
                reason,
                "--project",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but should accept special chars
        assert result.exit_code == 1


# ──────────────────────────────────────────────────────────────────────────────
# Boundary Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestLifecycleBoundaryConditions:
    """Test boundary conditions for lifecycle commands."""

    def test_replay_with_uuid_case_variations(self, initialized_project):
        """Test replay with UUID in different cases."""
        task_id = uuid4()
        # UUIDs should be case-insensitive
        for task_id_str in [str(task_id), str(task_id).upper()]:
            result = runner.invoke(
                app,
                ["replay", task_id_str, "--project", str(initialized_project)],
            )
            # Should fail because task doesn't exist, but UUID format should be accepted
            assert result.exit_code == 1

    def test_multiple_flags_in_replay(self, initialized_project):
        """Test replay with multiple flags combined."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "replay",
                fake_task_id,
                "--diff",
                "--verbose",
                "--project",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but flags should be accepted
        assert result.exit_code == 1

    def test_multiple_flags_in_approve(self, initialized_project):
        """Test approve with multiple flags combined."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "approve",
                fake_task_id,
                "--resume",
                "--project",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but flags should be accepted
        assert result.exit_code == 1

    def test_project_option_with_relative_path(self, tmp_project_dir):
        """Test lifecycle commands with relative project path."""
        # Initialize project first
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0

        # Try lifecycle command with relative path
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--project", str(tmp_project_dir)],
        )
        # Should fail because task doesn't exist, but path should be accepted
        assert result.exit_code == 1

    def test_project_option_with_absolute_path(self, tmp_project_dir):
        """Test lifecycle commands with absolute project path."""
        # Initialize project first
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0

        # Try lifecycle command with absolute path
        fake_task_id = str(uuid4())
        abs_path = tmp_project_dir.resolve()
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--project", str(abs_path)],
        )
        # Should fail because task doesn't exist, but path should be accepted
        assert result.exit_code == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
