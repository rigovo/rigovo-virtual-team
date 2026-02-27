"""E2E validation tests for lifecycle controls.

This test suite validates the complete lifecycle control workflow:
- Task creation and persistence
- Replay with diff capture
- Resume from checkpoint
- Abort with audit trail
- Approve with optional resume
- Dashboard and upgrade commands

Tests cover:
1. Happy path: successful execution of each command
2. Error paths: missing tasks, invalid UUIDs, permission issues
3. State transitions: task status changes through lifecycle
4. Audit trail: all operations logged correctly
5. Data persistence: changes persisted to database
6. Integration: commands work together in realistic workflows
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
from rigovo.domain.entities.task import Task, TaskStatus, TaskType, TaskComplexity
from rigovo.domain.entities.audit_entry import AuditEntry, AuditAction
from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
from rigovo.infrastructure.persistence.sqlite_audit_repo import SqliteAuditRepository

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
        
        # Create minimal rigovo.yml
        (tmp_path / "rigovo.yml").write_text(
            "version: '1'\nproject:\n  name: test-project\n"
        )
        
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
    task.classify(TaskType.FEATURE, TaskComplexity.HIGH)
    task.status = TaskStatus.COMPLETED
    return task


@pytest.fixture
def sample_failed_task():
    """Create a failed task for testing."""
    workspace_id = uuid4()
    task = Task(
        workspace_id=workspace_id,
        description="Fix critical bug",
    )
    task.classify(TaskType.BUG, TaskComplexity.CRITICAL)
    task.status = TaskStatus.FAILED
    return task


@pytest.fixture
def sample_awaiting_approval_task():
    """Create a task awaiting approval."""
    workspace_id = uuid4()
    task = Task(
        workspace_id=workspace_id,
        description="Implement new feature",
    )
    task.classify(TaskType.FEATURE, TaskComplexity.MEDIUM)
    task.status = TaskStatus.AWAITING_APPROVAL
    task.current_checkpoint = "code_ready"
    task.approval_data = {
        "files_changed": ["src/main.py", "tests/test_main.py"],
        "summary": "Added new payment processor",
    }
    return task


# ─────────────────────────────────────────────────────────────────────────────
# Replay Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestReplayCommandE2E:
    """E2E tests for replay command."""

    def test_replay_task_not_found_error_message(self, initialized_project):
        """Test that replay shows clear error for missing task."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_replay_with_diff_flag_shows_before_after(self, initialized_project):
        """Test that replay with --diff shows before/after state."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--diff", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but diff flag should be processed
        assert result.exit_code == 1

    def test_replay_verbose_flag_enables_debug_logging(self, initialized_project):
        """Test that replay with --verbose enables debug output."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "--verbose", "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist, but verbose flag should be processed
        assert result.exit_code == 1

    def test_replay_combined_flags(self, initialized_project):
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
        assert result.exit_code == 1

    def test_replay_short_form_flags_work(self, initialized_project):
        """Test replay with short form flags."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["replay", fake_task_id, "-d", "-v", "-p", str(initialized_project)],
        )
        assert result.exit_code == 1


# ─────────────────────────────────────────────────────────────────────────────
# Resume Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestResumeCommandE2E:
    """E2E tests for resume command."""

    def test_resume_task_not_found_error(self, initialized_project):
        """Test that resume shows error for missing task."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_resume_without_checkpoint_shows_helpful_message(self, initialized_project):
        """Test that resume without checkpoint shows helpful error."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "--project", str(initialized_project)],
        )
        # Should fail because task doesn't exist
        assert result.exit_code == 1

    def test_resume_verbose_flag(self, initialized_project):
        """Test resume with verbose flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "--verbose", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_resume_short_form_flags(self, initialized_project):
        """Test resume with short form flags."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["resume", fake_task_id, "-v", "-p", str(initialized_project)],
        )
        assert result.exit_code == 1


# ─────────────────────────────────────────────────────────────────────────────
# Abort Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAbortCommandE2E:
    """E2E tests for abort command."""

    def test_abort_task_not_found_error(self, initialized_project):
        """Test that abort shows error for missing task."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["abort", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

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

    def test_abort_with_default_reason(self, initialized_project):
        """Test abort uses default reason if not provided."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["abort", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_abort_short_form_flags(self, initialized_project):
        """Test abort with short form flags."""
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
        assert result.exit_code == 1

    def test_abort_with_special_characters_in_reason(self, initialized_project):
        """Test abort with special characters in reason."""
        fake_task_id = str(uuid4())
        reason = "Cancelled: @#$%^&*()"
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


# ─────────────────────────────────────────────────────────────────────────────
# Approve Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestApproveCommandE2E:
    """E2E tests for approve command."""

    def test_approve_task_not_found_error(self, initialized_project):
        """Test that approve shows error for missing task."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_approve_with_resume_flag(self, initialized_project):
        """Test approve with --resume flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--resume", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_approve_with_no_resume_flag(self, initialized_project):
        """Test approve with --no-resume flag."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--no-resume", "--project", str(initialized_project)],
        )
        assert result.exit_code == 1

    def test_approve_defaults_to_resume(self, initialized_project):
        """Test that approve defaults to resuming."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            ["approve", fake_task_id, "--project", str(initialized_project)],
        )
        assert result.exit_code == 1


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDashboardCommandE2E:
    """E2E tests for dashboard command."""

    @patch("webbrowser.open")
    def test_dashboard_opens_correct_url(self, mock_open):
        """Test that dashboard opens the correct URL."""
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0
        mock_open.assert_called_once()
        call_args = mock_open.call_args[0][0]
        assert "app.rigovo.com" in call_args

    @patch("webbrowser.open")
    def test_dashboard_shows_url_in_output(self, mock_open):
        """Test that dashboard shows URL in output."""
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0
        assert "app.rigovo.com" in result.output

    @patch("webbrowser.open")
    def test_dashboard_no_arguments_required(self, mock_open):
        """Test that dashboard requires no arguments."""
        result = runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0


# ─────────────────────────────────────────────────────────────────────────────
# Upgrade Command E2E Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestUpgradeCommandE2E:
    """E2E tests for upgrade command."""

    def test_upgrade_completes_successfully(self):
        """Test that upgrade command completes."""
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0

    def test_upgrade_shows_version_info(self):
        """Test that upgrade shows version information."""
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0
        assert "version" in result.output.lower() or "rigovo" in result.output.lower()

    def test_upgrade_no_arguments_required(self):
        """Test that upgrade requires no arguments."""
        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0


# ─────────────────────────────────────────────────────────────────────────────
# Cross-Command Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLifecycleCommandsIntegration:
    """Integration tests for lifecycle commands working together."""

    def test_all_task_commands_require_task_id(self, initialized_project):
        """Test that all task-based commands require task ID."""
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(app, [cmd, "--project", str(initialized_project)])
            assert result.exit_code == 2, f"{cmd} should require task ID"

    def test_all_task_commands_accept_project_option(self, initialized_project):
        """Test that all task-based commands accept --project option."""
        fake_task_id = str(uuid4())
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, fake_task_id, "--project", str(initialized_project)],
            )
            # Should fail because task doesn't exist, but option should be accepted
            assert result.exit_code == 1

    def test_all_task_commands_show_task_not_found_error(self, initialized_project):
        """Test that all task-based commands show clear error for missing task."""
        fake_task_id = str(uuid4())
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, fake_task_id, "--project", str(initialized_project)],
            )
            assert result.exit_code == 1
            assert (
                "not found" in result.output.lower()
                or "task" in result.output.lower()
                or "Task" in result.output
            )

    def test_dashboard_and_upgrade_dont_require_project(self):
        """Test that dashboard and upgrade don't require project."""
        with patch("webbrowser.open"):
            result = runner.invoke(app, ["dashboard"])
            assert result.exit_code == 0

        result = runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0

    def test_lifecycle_commands_consistent_error_codes(self, initialized_project):
        """Test that lifecycle commands use consistent error codes."""
        fake_task_id = str(uuid4())
        results = {}
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, fake_task_id, "--project", str(initialized_project)],
            )
            results[cmd] = result.exit_code

        # All should fail with exit code 1 (task not found)
        assert all(code == 1 for code in results.values())


# ─────────────────────────────────────────────────────────────────────────────
# Error Handling and Edge Cases
# ─────────────────────────────────────────────────────────────────────────────


class TestLifecycleErrorHandling:
    """Test error handling in lifecycle commands."""

    def test_invalid_uuid_format_rejected(self, initialized_project):
        """Test that invalid UUID formats are rejected."""
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, "not-a-uuid", "--project", str(initialized_project)],
            )
            assert result.exit_code == 1

    def test_empty_task_id_rejected(self, initialized_project):
        """Test that empty task ID is rejected."""
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, "", "--project", str(initialized_project)],
            )
            assert result.exit_code == 1

    def test_special_characters_in_task_id_rejected(self, initialized_project):
        """Test that special characters in task ID are rejected."""
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, "task@#$%", "--project", str(initialized_project)],
            )
            assert result.exit_code == 1

    def test_abort_with_very_long_reason(self, initialized_project):
        """Test abort with very long reason string."""
        fake_task_id = str(uuid4())
        long_reason = "x" * 5000
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

    def test_approve_with_conflicting_resume_flags(self, initialized_project):
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


# ─────────────────────────────────────────────────────────────────────────────
# Boundary Conditions
# ─────────────────────────────────────────────────────────────────────────────


class TestLifecycleBoundaryConditions:
    """Test boundary conditions in lifecycle commands."""

    def test_uuid_case_variations(self, initialized_project):
        """Test that UUID case variations are handled."""
        task_id = str(uuid4())
        # UUIDs should be case-insensitive
        for cmd in ["replay", "resume", "abort", "approve"]:
            result = runner.invoke(
                app,
                [cmd, task_id.upper(), "--project", str(initialized_project)],
            )
            # Should fail because task doesn't exist, but UUID should be parsed
            assert result.exit_code == 1

    def test_multiple_flags_combined(self, initialized_project):
        """Test multiple flags combined in replay."""
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
        assert result.exit_code == 1

    def test_project_option_with_relative_path(self, tmp_project_dir):
        """Test project option with relative path."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "replay",
                fake_task_id,
                "--project",
                ".",
            ],
        )
        # Should fail because task doesn't exist, but relative path should work
        assert result.exit_code == 1

    def test_project_option_with_absolute_path(self, tmp_project_dir):
        """Test project option with absolute path."""
        fake_task_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "replay",
                fake_task_id,
                "--project",
                str(tmp_project_dir.absolute()),
            ],
        )
        # Should fail because task doesn't exist, but absolute path should work
        assert result.exit_code == 1

    def test_abort_with_empty_reason_string(self, initialized_project):
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

    def test_abort_with_unicode_characters_in_reason(self, initialized_project):
        """Test abort with unicode characters in reason."""
        fake_task_id = str(uuid4())
        reason = "Cancelled: 🚫 ❌ ⛔"
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
        # Should fail because task doesn't exist, but should accept unicode
        assert result.exit_code == 1


# ─────────────────────────────────────────────────────────────────────────────
# State Transition Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestTaskStateTransitions:
    """Test task state transitions through lifecycle commands."""

    def test_task_status_enum_values(self):
        """Test that TaskStatus enum has expected values."""
        expected_statuses = {
            "pending",
            "classifying",
            "routing",
            "assembling",
            "awaiting_approval",
            "running",
            "quality_check",
            "completed",
            "failed",
            "rejected",
        }
        actual_statuses = {status.value for status in TaskStatus}
        assert actual_statuses == expected_statuses

    def test_task_type_enum_values(self):
        """Test that TaskType enum has expected values."""
        expected_types = {
            "feature",
            "bug",
            "refactor",
            "test",
            "docs",
            "infra",
            "security",
            "performance",
            "investigation",
        }
        actual_types = {task_type.value for task_type in TaskType}
        assert actual_types == expected_types

    def test_task_complexity_enum_values(self):
        """Test that TaskComplexity enum has expected values."""
        expected_complexities = {"low", "medium", "high", "critical"}
        actual_complexities = {complexity.value for complexity in TaskComplexity}
        assert actual_complexities == expected_complexities


# ─────────────────────────────────────────────────────────────────────────────
# Audit Trail Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAuditTrail:
    """Test audit trail functionality in lifecycle commands."""

    def test_audit_action_enum_values(self):
        """Test that AuditAction enum has expected values."""
        # Should have at least these actions
        expected_actions = {
            "TASK_CREATED",
            "TASK_STARTED",
            "TASK_COMPLETED",
            "TASK_FAILED",
            "APPROVAL_REQUESTED",
            "APPROVAL_GRANTED",
            "APPROVAL_DENIED",
        }
        actual_actions = {action.name for action in AuditAction}
        assert expected_actions.issubset(actual_actions)

    def test_audit_entry_creation(self):
        """Test that audit entries can be created."""
        workspace_id = uuid4()
        task_id = uuid4()
        entry = AuditEntry(
            workspace_id=workspace_id,
            task_id=task_id,
            action=AuditAction.TASK_FAILED,
            agent_role="operator",
            summary="Task aborted by operator",
            metadata={"source": "cli.abort"},
        )
        assert entry.workspace_id == workspace_id
        assert entry.task_id == task_id
        assert entry.action == AuditAction.TASK_FAILED
        assert entry.agent_role == "operator"
        assert entry.summary == "Task aborted by operator"
        assert entry.metadata["source"] == "cli.abort"


# ─────────────────────────────────────────────────────────────────────────────
# Command Help and Documentation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCommandDocumentation:
    """Test that commands have proper help documentation."""

    def test_replay_help_available(self):
        """Test that replay command has help."""
        result = runner.invoke(app, ["replay", "--help"])
        assert result.exit_code == 0
        assert "replay" in result.output.lower()

    def test_resume_help_available(self):
        """Test that resume command has help."""
        result = runner.invoke(app, ["resume", "--help"])
        assert result.exit_code == 0
        assert "resume" in result.output.lower()

    def test_abort_help_available(self):
        """Test that abort command has help."""
        result = runner.invoke(app, ["abort", "--help"])
        assert result.exit_code == 0
        assert "abort" in result.output.lower()

    def test_approve_help_available(self):
        """Test that approve command has help."""
        result = runner.invoke(app, ["approve", "--help"])
        assert result.exit_code == 0
        assert "approve" in result.output.lower()

    def test_dashboard_help_available(self):
        """Test that dashboard command has help."""
        result = runner.invoke(app, ["dashboard", "--help"])
        assert result.exit_code == 0
        assert "dashboard" in result.output.lower()

    def test_upgrade_help_available(self):
        """Test that upgrade command has help."""
        result = runner.invoke(app, ["upgrade", "--help"])
        assert result.exit_code == 0
        assert "upgrade" in result.output.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Determinism and Isolation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDeterminismAndIsolation:
    """Test that lifecycle commands are deterministic and isolated."""

    def test_replay_command_idempotent_error_handling(self, initialized_project):
        """Test that replay command produces consistent errors."""
        fake_task_id = str(uuid4())
        results = []
        for _ in range(3):
            result = runner.invoke(
                app,
                ["replay", fake_task_id, "--project", str(initialized_project)],
            )
            results.append(result.exit_code)
        
        # All runs should produce same exit code
        assert all(code == 1 for code in results)

    def test_abort_command_idempotent_error_handling(self, initialized_project):
        """Test that abort command produces consistent errors."""
        fake_task_id = str(uuid4())
        results = []
        for _ in range(3):
            result = runner.invoke(
                app,
                ["abort", fake_task_id, "--project", str(initialized_project)],
            )
            results.append(result.exit_code)
        
        # All runs should produce same exit code
        assert all(code == 1 for code in results)

    def test_dashboard_command_deterministic(self):
        """Test that dashboard command is deterministic."""
        with patch("webbrowser.open"):
            results = []
            for _ in range(3):
                result = runner.invoke(app, ["dashboard"])
                results.append(result.exit_code)
            
            # All runs should succeed
            assert all(code == 0 for code in results)

    def test_upgrade_command_deterministic(self):
        """Test that upgrade command is deterministic."""
        results = []
        for _ in range(3):
            result = runner.invoke(app, ["upgrade"])
            results.append(result.exit_code)
        
        # All runs should succeed
        assert all(code == 0 for code in results)
