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
    _resolve_base_role,
    _run_verification_command,
    verify_execution_node,
)
from rigovo.application.graph.state import TaskState


class TestResolveBaseRole(unittest.TestCase):
    """Test base-role resolution from instance IDs."""

    def test_simple_role(self):
        assert _resolve_base_role("coder") == "coder"

    def test_instance_suffix(self):
        assert _resolve_base_role("coder-1") == "coder"

    def test_compound_role_with_suffix(self):
        """backend-engineer-1 → backend-engineer (not verifiable, but correctly resolved)."""
        assert _resolve_base_role("backend-engineer-1") == "backend-engineer"

    def test_compound_role_no_suffix(self):
        assert _resolve_base_role("backend-engineer") == "backend-engineer"

    def test_qa_suffix(self):
        assert _resolve_base_role("qa-2") == "qa"


class TestDetectProjectType(unittest.TestCase):
    """Test project type detection from marker files."""

    def test_python_pyproject(self):
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

    def test_csharp_project(self):
        """Detect C#/.NET project from .csproj."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "MyApp.csproj").write_text("<Project/>")
            info = _detect_project_type(root)
            assert info["language"] == "csharp"
            assert "dotnet build" in (info["build_cmd"] or "")
            assert "dotnet test" in (info["test_cmd"] or "")

    def test_cpp_cmake_project(self):
        """Detect C++ project from CMakeLists.txt."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.0)")
            info = _detect_project_type(root)
            assert info["language"] == "cpp"
            assert "cmake" in (info["build_cmd"] or "")

    def test_ruby_project(self):
        """Detect Ruby project from Gemfile."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Gemfile").write_text("source 'https://rubygems.org'")
            info = _detect_project_type(root)
            assert info["language"] == "ruby"
            assert "rspec" in (info["test_cmd"] or "")

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

    def test_dockerfile_uses_hadolint(self):
        """Docker validation should use hadolint, not docker build --check."""
        validators = _detect_config_validators(["Dockerfile"])
        assert any("hadolint" in v for v in validators)
        # Must NOT contain invalid 'docker build --check'
        assert not any("docker build --check" in v for v in validators)

    def test_docker_compose(self):
        validators = _detect_config_validators(["docker-compose.yml"])
        assert any("docker compose" in v and "config" in v for v in validators)

    def test_helm_chart(self):
        validators = _detect_config_validators(["charts/myapp/Chart.yaml"])
        assert any("helm lint" in v for v in validators)

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

    @patch("rigovo.application.graph.nodes.verify_execution.Path.is_dir", return_value=True)
    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_coder_build_passes(self, mock_detect, mock_runner_cls, _mock_isdir):
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

    @patch("rigovo.application.graph.nodes.verify_execution.Path.is_dir", return_value=True)
    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_coder_build_fails(self, mock_detect, mock_runner_cls, _mock_isdir):
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

    @patch("rigovo.application.graph.nodes.verify_execution.Path.is_dir", return_value=True)
    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_qa_with_test_files(self, mock_detect, mock_runner_cls, _mock_isdir):
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

    @patch("rigovo.application.graph.nodes.verify_execution.Path.is_dir", return_value=True)
    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_qa_no_test_files_written(self, mock_detect, mock_runner_cls, _mock_isdir):
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

    @patch("rigovo.application.graph.nodes.verify_execution.Path.is_dir", return_value=True)
    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_qa_runs_full_suite_for_e2e_scope(self, mock_detect, mock_runner_cls, _mock_isdir):
        """QA automation/e2e scope should run targeted tests and full suite."""
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
            "description": "Build e2e automation",
            "project_root": "/tmp/test-project",
            "current_agent_role": "qa",
            "current_instance_id": "qa-1",
            "team_config": {
                "agents": {"qa-1": {"role": "qa", "name": "QA"}},
            },
            "agent_outputs": {
                "qa-1": {
                    "summary": "Added e2e coverage",
                    "files_changed": ["tests/e2e/test_checkout.py"],
                },
            },
            "events": [],
        }

        result = await verify_execution_node(state)

        assert result["execution_verification"]["status"] == "passed"
        assert mock_runner.run.call_count == 2
        commands = [str(call.kwargs.get("command") or call.args[0]) for call in mock_runner.run.call_args_list]
        assert any("tests/e2e/test_checkout.py" in cmd for cmd in commands)
        assert any(cmd == "python -m pytest --tb=short -q" for cmd in commands)

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

    async def test_compound_role_not_falsely_verifiable(self):
        """backend-engineer-1 should NOT be treated as coder/qa/devops/sre."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Code",
            "current_agent_role": "backend-engineer-1",
            "current_instance_id": "backend-engineer-1",
            "team_config": {
                "agents": {
                    "backend-engineer-1": {"role": "backend-engineer", "name": "BE"},
                },
            },
            "agent_outputs": {},
            "events": [],
        }

        result = await verify_execution_node(state)
        # backend-engineer is NOT in VERIFIABLE_ROLES → skipped
        assert result["execution_verification"]["status"] == "skipped"

    async def test_missing_project_root_skips_gracefully(self):
        """Non-existent project root should not crash — skip with reason."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Code",
            "project_root": "/nonexistent/path/that/does/not/exist",
            "current_agent_role": "coder",
            "current_instance_id": "coder-1",
            "team_config": {
                "agents": {"coder-1": {"role": "coder"}},
            },
            "agent_outputs": {
                "coder-1": {"summary": "done", "files_changed": ["src/x.py"]},
            },
            "events": [],
        }

        result = await verify_execution_node(state)
        assert result["execution_verification"]["status"] == "skipped"
        assert "not found" in result["execution_verification"]["reason"]

    async def test_missing_state_fields_defaults_safely(self):
        """Minimal state (backward compat) — no team_config, no agent_outputs."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Code",
            "current_agent_role": "planner",
            "events": [],
        }

        result = await verify_execution_node(state)
        assert result["execution_verification"]["status"] == "skipped"
        assert "verification_history" in result

    @patch("rigovo.application.graph.nodes.verify_execution.Path.is_dir", return_value=True)
    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_qa_data_files_not_treated_as_tests(self, mock_detect, mock_runner_cls, _mock_isdir):
        """Files like test_data.json should not be treated as runnable tests."""
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
                "agents": {"qa-1": {"role": "qa", "name": "QA"}},
            },
            "agent_outputs": {
                "qa-1": {
                    "summary": "Wrote test data",
                    "files_changed": ["tests/test_data.json", "tests/test_fixtures.yaml"],
                },
            },
            "events": [],
        }

        result = await verify_execution_node(state)
        # JSON/YAML files should not be treated as runnable test files
        # No code test files, no infra files → failure (QA must write actual tests)
        assert result["execution_verification"]["passed"] is False

    @patch("rigovo.application.graph.nodes.verify_execution.Path.is_dir", return_value=True)
    @patch("rigovo.application.graph.nodes.verify_execution.CommandRunner")
    @patch("rigovo.application.graph.nodes.verify_execution._detect_project_type")
    async def test_unknown_project_no_checks(self, mock_detect, mock_runner_cls, _mock_isdir):
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
