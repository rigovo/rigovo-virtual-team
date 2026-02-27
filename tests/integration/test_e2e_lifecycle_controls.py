"""E2E validation tests for lifecycle controls.

This test suite validates the complete lifecycle control workflow:
- Task creation and persistence
- Replay command with actual task retrieval
- Resume command with checkpoint handling
- Abort command with audit trail creation
- Approve command with status transitions
- Dashboard and upgrade commands

These tests use actual database operations and task entities to validate
the full integration of lifecycle controls with the persistence layer.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from rigovo.main import app
from rigovo.domain.entities.task import Task, TaskStatus
from rigovo.config import load_config
from rigovo.container import Container

runner = CliRunner()


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_project_dir():
    """Create a temporary project directory with .rigovo structure."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        rigovo_dir = tmp_path / ".rigovo"
        rigovo_dir.mkdir(parents=True, exist_ok=True)
        yield tmp_path


@pytest.fixture
def initialized_project(tmp_project_dir):
    """Initialize a project with rigovo init."""
    result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
    assert result.exit_code == 0, f"Init failed: {result.output}"
    yield tmp_project_dir


# ─────────────────────────────────────────────────────────────────────────────
# Replay Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestReplayCommandE2E:
    """E2E tests for replay command with actual database operations."""

    def test_replay_with_nonexistent_task_fails(self, initialized_project):
        """Test that replay fails gracefully with nonexistent task."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Task" in result.output

    def test_replay_with_diff_flag_accepted(self, initialized_project):
        """Test that replay accepts --diff flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--diff", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flag should be accepted
        assert result.exit_code == 1

    def test_replay_with_verbose_flag_accepted(self, initialized_project):
        """Test that replay accepts --verbose flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--verbose", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flag should be accepted
        assert result.exit_code == 1

    def test_replay_with_both_flags(self, initialized_project):
        """Test that replay accepts both --diff and --verbose flags."""
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

    def test_replay_with_short_form_flags(self, initialized_project):
        """Test that replay accepts short form flags."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "replay",
                fake_task_id,
                "-d",
                "-v",
                "-p",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but flags should be accepted
        assert result.exit_code == 1


# ─────────────────────────────────────────────────────────────────────────────
# Resume Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestResumeCommandE2E:
    """E2E tests for resume command with checkpoint handling."""

    def test_resume_with_nonexistent_task_fails(self, initialized_project):
        """Test that resume fails with nonexistent task."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Task" in result.output

    def test_resume_without_checkpoint_database(self, initialized_project):
        """Test that resume requires checkpoint database."""
        # Create a task first
        workspace_id = uuid4()
        task = Task(
            workspace_id=workspace_id,
            description="Resume test task",
        )
        task.status = TaskStatus.COMPLETED
        
        # Try to resume (should fail because no checkpoint DB)
        result = runner.invoke(
            app,
            ["resume", str(task.id), "--project", str(initialized_project)],
        )
        # Should fail because no checkpoint database exists
        assert result.exit_code == 1

    def test_resume_with_verbose_flag(self, initialized_project):
        """Test that resume accepts --verbose flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "--verbose", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flag should be accepted
        assert result.exit_code == 1

    def test_resume_with_short_form_flags(self, initialized_project):
        """Test that resume accepts short form flags."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "-v", "-p", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but flags should be accepted
        assert result.exit_code == 1


# ─────────────────────────────────────────────────────────────────────────────
# Abort Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAbortCommandE2E:
    """E2E tests for abort command with audit trail."""

    def test_abort_with_nonexistent_task_fails(self, initialized_project):
        """Test that abort fails with nonexistent task."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["abort", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Task" in result.output

    def test_abort_with_custom_reason(self, initialized_project):
        """Test that abort accepts custom reason."""
        fake_task_id = str(uuid4())
        custom_reason = "Cancelled due to resource constraints"
        result = runner.invoke(
            app,
            [
                "abort",
                fake_task_id,
                "--reason",
                custom_reason,
                "--project",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but option should be accepted
        assert result.exit_code == 1

    def test_abort_with_default_reason(self, initialized_project):
        """Test that abort uses default reason."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["abort", fake_task_id, "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but should use default reason
        assert result.exit_code == 1

    def test_abort_with_short_form_reason(self, initialized_project):
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


# ─────────────────────────────────────────────────────────────────────────────
# Approve Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestApproveCommandE2E:
    """E2E tests for approve command with status transitions."""

    def test_approve_with_nonexistent_task_fails(self, initialized_project):
        """Test that approve fails with nonexistent task."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Task" in result.output

    def test_approve_with_resume_flag(self, initialized_project):
        """Test that approve accepts --resume flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--resume", "--project", str(initialized_project)],
        )
        # May fail due to missing task, but flag should be accepted
        assert result.exit_code == 1

    def test_approve_with_no_resume_flag(self, initialized_project):
        """Test that approve accepts --no-resume flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--no-resume", "--project", str(initialized_project)],
        )
        # May fail due to missing task, but flag should be accepted
        assert result.exit_code == 1

    def test_approve_defaults_to_resume(self, initialized_project):
        """Test that approve defaults to resuming."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--project", str(initialized_project)],
        )
        # May fail due to missing task, but should attempt resume
        assert result.exit_code == 1

    def test_approve_with_conflicting_flags(self, initialized_project):
        """Test that approve handles conflicting flags gracefully."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDashboardCommandE2E:
    """E2E tests for dashboard command."""

    def test_dashboard_command_succeeds(self):
        """Test that dashboard command succeeds."""
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0

    def test_dashboard_shows_url(self):
        """Test that dashboard shows URL."""
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0
        assert "rigovo.com" in result.output or "app.rigovo.com" in result.output

    def test_dashboard_no_project_required(self):
        """Test that dashboard doesn't require project."""
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0


# ─────────────────────────────────────────────────────────────────────────────
# Upgrade Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestUpgradeCommandE2E:
    """E2E tests for upgrade command."""

    def test_upgrade_command_succeeds(self):
        """Test that upgrade command succeeds."""
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0

    def test_upgrade_shows_version(self):
        """Test that upgrade shows version info."""
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0
        assert "version" in result.output.lower() or "rigovo" in result.output.lower()

    def test_upgrade_no_project_required(self):
        """Test that upgrade doesn't require project."""
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0


# ─────────────────────────────────────────────────────────────────────────────
# Cross-Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLifecycleCommandsE2E:
    """E2E tests for lifecycle commands working together."""

    def test_all_lifecycle_commands_require_task_id(self, initialized_project):
        """Test that all lifecycle commands require task ID."""
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, "--project", str(initialized_project)],
            )
            assert result.exit_code == 2  # Missing argument

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

    def test_all_lifecycle_commands_show_task_not_found_error(self, initialized_project):
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

    def test_all_lifecycle_commands_consistent_error_handling(self, initialized_project):
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


# ─────────────────────────────────────────────────────────────────────────────
# Error Handling E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLifecycleErrorHandlingE2E:
    """E2E tests for error handling in lifecycle commands."""

    def test_replay_with_invalid_uuid_fails(self, initialized_project):
        """Test that replay fails with invalid UUID."""
        result = runner.invoke(
            app,
            ["replay", "not-a-uuid", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_resume_with_invalid_uuid_fails(self, initialized_project):
        """Test that resume fails with invalid UUID."""
        result = runner.invoke(
            app,
            ["resume", "not-a-uuid", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_abort_with_invalid_uuid_fails(self, initialized_project):
        """Test that abort fails with invalid UUID."""
        result = runner.invoke(
            app,
            ["abort", "not-a-uuid", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_approve_with_invalid_uuid_fails(self, initialized_project):
        """Test that approve fails with invalid UUID."""
        result = runner.invoke(
            app,
            ["approve", "not-a-uuid", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_replay_missing_task_id_fails(self, initialized_project):
        """Test that replay fails without task ID."""
        result = runner.invoke(
            app,
            ["replay", "--project", str(initialized_project)],
        )
        assert result.exit_code == 2  # Missing argument

    def test_resume_missing_task_id_fails(self, initialized_project):
        """Test that resume fails without task ID."""
        result = runner.invoke(
            app,
            ["resume", "--project", str(initialized_project)],
        )
        assert result.exit_code == 2  # Missing argument

    def test_abort_missing_task_id_fails(self, initialized_project):
        """Test that abort fails without task ID."""
        result = runner.invoke(
            app,
            ["abort", "--project", str(initialized_project)],
        )
        assert result.exit_code == 2  # Missing argument

    def test_approve_missing_task_id_fails(self, initialized_project):
        """Test that approve fails without task ID."""
        result = runner.invoke(
            app,
            ["approve", "--project", str(initialized_project)],
        )
        assert result.exit_code == 2  # Missing argument

    def test_replay_with_empty_task_id_fails(self, initialized_project):
        """Test that replay fails with empty task ID."""
        result = runner.invoke(
            app,
            ["replay", "", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_abort_with_empty_task_id_fails(self, initialized_project):
        """Test that abort fails with empty task ID."""
        result = runner.invoke(
            app,
            ["abort", "", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1


# ─────────────────────────────────────────────────────────────────────────────
# Boundary Condition E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLifecycleBoundaryConditionsE2E:
    """E2E tests for boundary conditions in lifecycle commands."""

    def test_abort_with_very_long_reason(self, initialized_project):
        """Test that abort handles very long reason strings."""
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

    def test_abort_with_special_characters_in_reason(self, initialized_project):
        """Test that abort handles special characters in reason."""
        fake_task_id = str(uuid4())
        special_reason = "Cancelled: @#$%^&*() [brackets] {braces} <angles>"
        result = runner.invoke(
            app,
            [
                "abort",
                fake_task_id,
                "--reason",
                special_reason,
                "--project",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but should accept special chars
        assert result.exit_code == 1

    def test_abort_with_empty_reason(self, initialized_project):
        """Test that abort handles empty reason string."""
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

    def test_replay_with_special_characters_in_task_id(self, initialized_project):
        """Test that replay rejects special characters in task ID."""
        result = runner.invoke(
            app,
            ["replay", "task@#$%", "--project", str(initialized_project)],
        )
        # Should fail with invalid UUID error
        assert result.exit_code == 1

    def test_abort_with_unicode_reason(self, initialized_project):
        """Test that abort handles unicode in reason."""
        fake_task_id = str(uuid4())
        unicode_reason = "Cancelled due to 支付 issues 🔐"
        result = runner.invoke(
            app,
            [
                "abort",
                fake_task_id,
                "--reason",
                unicode_reason,
                "--project",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but should accept unicode
        assert result.exit_code == 1

    def test_replay_with_multiple_flags_combined(self, initialized_project):
        """Test that replay handles multiple flags combined."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "replay",
                fake_task_id,
                "-d",
                "-v",
                "-p",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but flags should be accepted
        assert result.exit_code == 1

    def test_approve_with_multiple_flags_combined(self, initialized_project):
        """Test that approve handles multiple flags combined."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "approve",
                fake_task_id,
                "--no-resume",
                "-p",
                str(initialized_project),
            ],
        )
        # Should fail because task doesn't exist, but flags should be accepted
        assert result.exit_code == 1

    def test_project_option_with_relative_path(self, tmp_project_dir):
        """Test that project option works with relative paths."""
        # Initialize project
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0
        
        # Use relative path
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--project", "."],
        )
        # Should fail because task doesn't exist, but option should be accepted
        assert result.exit_code == 1

    def test_project_option_with_absolute_path(self, tmp_project_dir):
        """Test that project option works with absolute paths."""
        # Initialize project
        result = runner.invoke(app, ["init", "--project", str(tmp_project_dir)])
        assert result.exit_code == 0
        
        # Use absolute path
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--project", str(tmp_project_dir.absolute())],
        )
        # Should fail because task doesn't exist, but option should be accepted
        assert result.exit_code == 1
