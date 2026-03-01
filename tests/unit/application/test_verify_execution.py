"""Unit tests for the verify_execution node (Phase 4)."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from rigovo.application.graph.nodes.verify_execution import (
    VERIFIABLE_ROLES,
    _detect_config_validators,
    _detect_project_type,
    _run_verification_command,
    verify_execution_node,
)
from rigovo.application.graph.state import TaskState


class TestDetectProjectType(unittest.TestCase):
    """Test project type detection from marker files."""

    def test_python_pyproject(self, tmp_path=None):
        """Detect Python project from pyproject.toml."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project]")
            info = _detect_project_type(root)
            assert info["language"] == "python"
            assert "pytest" in (info["test_cmd"] or "")

    def test_typescript_project(self):
        """Detect TypeScript project from tsconfig.json."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tsconfig.json").write_text("{}")
            (root / "package.json").write_text("{}")
            info = _detect_project_type(root)
            assert info["language"] == "typescript"
            assert "tsc" in (info["build_cmd"] or "")
            assert "npm test" in (info["test_cmd"] or "")

    def test_go_project(self):
        """Detect Go project from go.mod."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "go.mod").write_text("module example")
            info = _detect_project_type(root)
            assert info["language"] == "go"
            assert "go build" in (info["build_cmd"] or "")
            assert "go test" in (info["test_cmd"] or "")

    def test_rust_project(self):
        """Detect Rust project from Cargo.toml."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Cargo.toml").write_text("[package]")
            info = _detect_project_type(root)
            assert info["language"] == "rust"
            assert "cargo check" in (info["build_cmd"] or "")

    def test_unknown_project(self):
        """Unknown project type returns defaults."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            info = _detect_project_type(root)
            assert info["language"] == "unknown"
            assert info["build_cmd"] is None
            assert info["test_cmd"] is None


class TestDetectConfigValidators(unittest.TestCase):
    """Test config file validator detection."""

    def test_terraform_files(self):
        validators = _detect_config_validators(["infra/main.tf", "infra/vars.tf"])
        assert any("terraform" in v for v in validators)
        # Only one terraform validate even for multiple .tf files
        assert sum(1 for v in validators if "terraform" in v) == 1

    def test_no_config_files(self):
        validators = _detect_config_validators(["src/main.py", "src/utils.py"])
        assert validators == []


class TestRunVerificationCommand(unittest.TestCase):
    """Test the verification command runner."""

    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    def test_passing_command(self, mock_runner_cls):
        runner = MagicMock()
        runner.run.return_value = {
            "command": "pytest",
            "exit_code": 0,
            "stdout": "5 passed",
            "stderr": "",
            "timed_out": False,
        }
        result = _run_verification_command(runner, "pytest", "test")
        assert result["passed"] is True
        assert result["label"] == "test"

    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    def test_failing_command(self, mock_runner_cls):
        runner = MagicMock()
        runner.run.return_value = {
            "command": "pytest",
            "exit_code": 1,
            "stdout": "2 failed",
            "stderr": "AssertionError",
            "timed_out": False,
        }
        result = _run_verification_command(runner, "pytest", "test")
        assert result["passed"] is False
        assert result["exit_code"] == 1

    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    def test_timed_out_command(self, mock_runner_cls):
        runner = MagicMock()
        runner.run.return_value = {
            "command": "pytest",
            "exit_code": -1,
            "stdout": "",
            "stderr": "timed out",
            "timed_out": True,
        }
        result = _run_verification_command(runner, "pytest", "test")
        assert result["passed"] is False
        assert result["timed_out"] is True


class TestVerifyExecutionNode(unittest.IsolatedAsyncioTestCase):
    """Test the verify_execution_node function."""

    async def test_skip_non_verifiable_role(self):
        """Non-code-producing roles should be skipped."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Review code",
            "current_agent_role": "reviewer",
            "current_instance_id": "reviewer-1",
            "team_config": {
                "agents": {
                    "reviewer-1": {"role": "reviewer", "name": "Reviewer"},
                },
            },
            "agent_outputs": {},
            "events": [],
        }

        result = await verify_execution_node(state)

        assert result["execution_verification"]["status"] == "skipped"
        assert any(
            e["type"] == "execution_verification" and e["status"] == "skipped"
            for e in result["events"]
        )

    async def test_skip_planner(self):
        """Planner is non-verifiable."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Plan",
            "current_agent_role": "planner",
            "current_instance_id": "planner",
            "team_config": {"agents": {}},
            "agent_outputs": {},
            "events": [],
        }

        result = await verify_execution_node(state)
        assert result["execution_verification"]["status"] == "skipped"

    async def test_skip_no_files(self):
        """Coder with no files produces skip (quality_check handles it)."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Code task",
            "current_agent_role": "coder",
            "current_instance_id": "coder-1",
            "team_config": {
                "agents": {
                    "coder-1": {"role": "coder", "name": "Coder"},
                },
            },
            "agent_outputs": {
                "coder-1": {"summary": "done", "files_changed": []},
            },
            "events": [],
        }

        result = await verify_execution_node(state)
        assert result["execution_verification"]["status"] == "skipped"
        assert result["execution_verification"]["reason"] == "No files produced to verify"

    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_coder_build_passes(self, mock_detect, mock_runner_cls):
        """Coder verification with passing build and tests."""
        mock_detect.return_value = {
            "language": "python",
            "build_cmd": None,
            "test_cmd": "python -m pytest --tb=short -q",
            "validate_cmds": [],
        }
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "command": "python -m pytest --tb=short -q",
            "exit_code": 0,
            "stdout": "10 passed",
            "stderr": "",
            "timed_out": False,
        }
        mock_runner_cls.return_value = mock_runner

        state: TaskState = {
            "task_id": "task-1",
            "description": "Add feature",
            "project_root": "/tmp/test-project",
            "current_agent_role": "coder",
            "current_instance_id": "coder-1",
            "team_config": {
                "agents": {
                    "coder-1": {"role": "coder", "name": "Coder"},
                },
            },
            "agent_outputs": {
                "coder-1": {
                    "summary": "Wrote auth module",
                    "files_changed": ["src/auth.py"],
                },
            },
            "events": [],
        }

        result = await verify_execution_node(state)

        assert result["execution_verification"]["status"] == "passed"
        assert result["execution_verification"]["passed"] is True
        assert result["execution_verification"]["total_checks"] == 1
        assert result["execution_verification"]["passed_checks"] == 1

    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_coder_build_fails(self, mock_detect, mock_runner_cls):
        """Coder verification with failing tests produces failure details."""
        mock_detect.return_value = {
            "language": "python",
            "build_cmd": None,
            "test_cmd": "python -m pytest --tb=short -q",
            "validate_cmds": [],
        }
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "command": "python -m pytest --tb=short -q",
            "exit_code": 1,
            "stdout": "3 failed, 7 passed",
            "stderr": "FAILED test_auth.py::test_login",
            "timed_out": False,
        }
        mock_runner_cls.return_value = mock_runner

        state: TaskState = {
            "task_id": "task-1",
            "description": "Add feature",
            "project_root": "/tmp/test-project",
            "current_agent_role": "coder",
            "current_instance_id": "coder-1",
            "team_config": {
                "agents": {
                    "coder-1": {"role": "coder", "name": "Coder"},
                },
            },
            "agent_outputs": {
                "coder-1": {
                    "summary": "Wrote auth module",
                    "files_changed": ["src/auth.py"],
                },
            },
            "events": [],
        }

        result = await verify_execution_node(state)

        assert result["execution_verification"]["status"] == "failed"
        assert result["execution_verification"]["passed"] is False
        assert len(result["execution_verification"]["failure_details"]) > 0

    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_qa_with_test_files(self, mock_detect, mock_runner_cls):
        """QA verification runs the test files they wrote."""
        mock_detect.return_value = {
            "language": "python",
            "build_cmd": None,
            "test_cmd": "python -m pytest --tb=short -q",
            "validate_cmds": [],
        }
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "command": "python -m pytest tests/test_auth.py --tb=short -q",
            "exit_code": 0,
            "stdout": "5 passed",
            "stderr": "",
            "timed_out": False,
        }
        mock_runner_cls.return_value = mock_runner

        state: TaskState = {
            "task_id": "task-1",
            "description": "Test auth",
            "project_root": "/tmp/test-project",
            "current_agent_role": "qa",
            "current_instance_id": "qa-1",
            "team_config": {
                "agents": {
                    "qa-1": {"role": "qa", "name": "QA"},
                },
            },
            "agent_outputs": {
                "qa-1": {
                    "summary": "Wrote test suite",
                    "files_changed": ["tests/test_auth.py", "tests/conftest.py"],
                },
            },
            "events": [],
        }

        result = await verify_execution_node(state)

        assert result["execution_verification"]["status"] == "passed"
        assert result["execution_verification"]["passed_checks"] >= 1
        # conftest.py is not a test file so shouldn't add a separate check

    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_qa_no_test_files_written(self, mock_detect, mock_runner_cls):
        """QA wrote files but none are test files → verification failure."""
        mock_detect.return_value = {
            "language": "python",
            "build_cmd": None,
            "test_cmd": "python -m pytest --tb=short -q",
            "validate_cmds": [],
        }
        mock_runner_cls.return_value = MagicMock()

        state: TaskState = {
            "task_id": "task-1",
            "description": "Test auth",
            "project_root": "/tmp/test-project",
            "current_agent_role": "qa",
            "current_instance_id": "qa-1",
            "team_config": {
                "agents": {
                    "qa-1": {"role": "qa", "name": "QA"},
                },
            },
            "agent_outputs": {
                "qa-1": {
                    "summary": "Wrote utils",
                    "files_changed": ["src/utils.py"],  # NOT a test file
                },
            },
            "events": [],
        }

        result = await verify_execution_node(state)

        assert result["execution_verification"]["status"] == "failed"
        assert result["execution_verification"]["passed"] is False

    async def test_verification_history_accumulates(self):
        """Verification history includes entries from all agents."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Code",
            "current_agent_role": "reviewer",
            "current_instance_id": "reviewer-1",
            "team_config": {
                "agents": {
                    "reviewer-1": {"role": "reviewer", "name": "Reviewer"},
                },
            },
            "agent_outputs": {},
            "verification_history": [
                {"instance_id": "coder-1", "role": "coder", "status": "passed"},
            ],
            "events": [],
        }

        result = await verify_execution_node(state)

        assert len(result["verification_history"]) == 2
        assert result["verification_history"][0]["instance_id"] == "coder-1"
        assert result["verification_history"][1]["instance_id"] == "reviewer-1"

    async def test_instance_id_suffix_stripped_for_role_detection(self):
        """Instance IDs like 'coder-1' should be recognized as 'coder' role."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Code",
            "current_agent_role": "coder-1",
            "current_instance_id": "coder-1",
            "team_config": {"agents": {}},  # No agents cfg — backward compat
            "agent_outputs": {
                "coder-1": {"summary": "done", "files_changed": []},
            },
            "events": [],
        }

        result = await verify_execution_node(state)
        # coder-1 → coder base role → verifiable but no files → skip
        assert result["execution_verification"]["status"] == "skipped"
        assert result["execution_verification"]["reason"] == "No files produced to verify"

    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_unknown_project_no_checks(self, mock_detect, mock_runner_cls):
        """Unknown project type with no build/test commands → no_checks (soft pass)."""
        mock_detect.return_value = {
            "language": "unknown",
            "build_cmd": None,
            "test_cmd": None,
            "validate_cmds": [],
        }
        mock_runner_cls.return_value = MagicMock()

        state: TaskState = {
            "task_id": "task-1",
            "description": "Code task",
            "project_root": "/tmp/test-project",
            "current_agent_role": "coder",
            "current_instance_id": "coder-1",
            "team_config": {
                "agents": {
                    "coder-1": {"role": "coder", "name": "Coder"},
                },
            },
            "agent_outputs": {
                "coder-1": {
                    "summary": "Wrote code",
                    "files_changed": ["src/main.xyz"],
                },
            },
            "events": [],
        }

        result = await verify_execution_node(state)

        assert result["execution_verification"]["status"] == "no_checks"
        assert result["execution_verification"]["passed"] is True


class TestVerifyExecutionWithQualityCheck(unittest.IsolatedAsyncioTestCase):
    """Integration: verify_execution results flow into quality_check."""

    async def test_execution_failure_becomes_gate_failure(self):
        """When execution verification fails, quality_check should include it."""
        from rigovo.application.graph.nodes.quality_check import quality_check_node

        state: TaskState = {
            "task_id": "task-1",
            "description": "Code task",
            "current_agent_role": "coder-1",
            "team_config": {
                "agents": {
                    "coder-1": {"role": "coder"},
                },
                "gates_after": ["coder-1"],
                "pipeline_order": ["coder-1"],
            },
            "agent_outputs": {
                "coder-1": {
                    "summary": "Code",
                    "files_changed": ["src/main.py"],
                },
            },
            "execution_verification": {
                "status": "failed",
                "passed": False,
                "failure_details": [
                    "[test] python -m pytest\n  stderr: FAILED test_main.py::test_func"
                ],
            },
            "events": [],
        }

        # Use empty gate list (no static gates) — only execution verification matters
        result = await quality_check_node(state, quality_gates=[])

        assert result["gate_results"]["passed"] is False
        assert result["gate_results"]["violation_count"] >= 1
        assert any(
            v["gate_id"] == "execution-verification-failed"
            for v in result["gate_results"]["violations"]
        )
        assert "gate_failed" in result["status"]


if __name__ == "__main__":
    unittest.main()
