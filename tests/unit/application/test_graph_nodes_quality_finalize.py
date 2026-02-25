"""Unit tests for quality check and finalize graph nodes."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from rigovo.application.graph.nodes.quality_check import quality_check_node
from rigovo.application.graph.nodes.finalize import finalize_node
from rigovo.application.graph.state import TaskState
from rigovo.domain.entities.quality import GateResult, Violation, GateStatus, ViolationSeverity


class TestQualityCheckNode(unittest.IsolatedAsyncioTestCase):
    """Test the quality_check_node function."""

    async def test_quality_check_skipped_for_non_code_role(self):
        """Test quality_check_node skips gates for non-code-producing roles."""
        state: TaskState = {
            "task_id": "task-1",
            "current_agent_role": "architect",
            "team_config": {
                "agents": {},
                "gates_after": ["backend", "frontend"],
            },
            "events": [],
        }

        mock_gate = AsyncMock()

        result = await quality_check_node(state, [mock_gate])

        assert result["gate_results"]["status"] == "skipped"
        assert result["gate_results"]["passed"] is True
        assert "gates_skipped_architect" in result["status"]
        assert len(result["events"]) == 1
        assert result["events"][0]["status"] == "skipped"

    async def test_quality_check_all_gates_passed(self):
        """Test quality_check_node when all gates pass."""
        state: TaskState = {
            "task_id": "task-1",
            "current_agent_role": "backend",
            "team_config": {
                "agents": {},
                "gates_after": ["backend"],
            },
            "agent_outputs": {
                "backend": {
                    "summary": "Fixed auth issue",
                    "files_changed": ["src/auth.py"],
                }
            },
            "project_root": "/project",
            "events": [],
        }

        # Mock passing gates
        mock_gate1 = AsyncMock()
        mock_gate1.run.return_value = GateResult(
            status="passed",
            gates_run=1,
            gates_passed=1,
            violations=[],
        )

        mock_gate2 = AsyncMock()
        mock_gate2.run.return_value = GateResult(
            status="passed",
            gates_run=1,
            gates_passed=1,
            violations=[],
        )

        result = await quality_check_node(state, [mock_gate1, mock_gate2])

        assert result["gate_results"]["passed"] is True
        assert result["gate_results"]["gates_run"] == 2
        assert result["gate_results"]["gates_passed"] == 2
        assert result["gate_results"]["violation_count"] == 0
        assert "gate_passed_backend" in result["status"]
        assert len(result["events"]) == 1
        assert result["events"][0]["passed"] is True

    async def test_quality_check_gate_failed_builds_fix_packet(self):
        """Test quality_check_node builds fix packet on gate failure."""
        state: TaskState = {
            "task_id": "task-1",
            "current_agent_role": "backend",
            "team_config": {
                "agents": {},
                "gates_after": ["backend"],
            },
            "agent_outputs": {
                "backend": {
                    "summary": "Made changes",
                    "files_changed": ["src/broken.py"],
                }
            },
            "project_root": "/project",
            "retry_count": 0,
            "max_retries": 3,
            "events": [],
        }

        violation = Violation(
            gate_id="gate-1",
            file_path="src/broken.py",
            message="Syntax error on line 10",
            suggestion="Fix the syntax error",
            severity=ViolationSeverity.ERROR,
            line=10,
        )

        mock_gate = AsyncMock()
        mock_gate.run.return_value = GateResult(
            status=GateStatus.FAILED,
            gates_run=1,
            gates_passed=0,
            violations=[violation],
        )

        result = await quality_check_node(state, [mock_gate])

        assert result["gate_results"]["passed"] is False
        assert result["gate_results"]["violation_count"] == 1
        assert "gate_failed_backend" in result["status"]
        assert result["retry_count"] == 1
        assert "fix_packets" in result
        assert len(result["fix_packets"]) == 1
        assert len(result["events"]) == 1

    async def test_quality_check_accumulates_violations(self):
        """Test quality_check_node accumulates violations from multiple gates."""
        state: TaskState = {
            "task_id": "task-1",
            "current_agent_role": "backend",
            "team_config": {
                "agents": {},
                "gates_after": ["backend"],
            },
            "agent_outputs": {
                "backend": {"summary": "Changes", "files_changed": ["src/file.py"]}
            },
            "project_root": "/project",
            "retry_count": 1,
            "max_retries": 3,
            "fix_packets": [],
            "events": [],
        }

        v1 = Violation(
            gate_id="gate-1",
            file_path="src/file.py",
            message="Issue 1",
            suggestion="Fix 1",
            severity=ViolationSeverity.ERROR,
            line=5,
        )
        v2 = Violation(
            gate_id="gate-2",
            file_path="src/file.py",
            message="Issue 2",
            suggestion="Fix 2",
            severity=ViolationSeverity.WARNING,
            line=10,
        )

        gate1 = AsyncMock()
        gate1.run.return_value = GateResult(
            status=GateStatus.FAILED,
            gates_run=1,
            gates_passed=0,
            violations=[v1],
        )

        gate2 = AsyncMock()
        gate2.run.return_value = GateResult(
            status=GateStatus.FAILED,
            gates_run=1,
            gates_passed=0,
            violations=[v2],
        )

        result = await quality_check_node(state, [gate1, gate2])

        assert result["gate_results"]["violation_count"] == 2
        assert result["retry_count"] == 2


class TestFinalizeNode(unittest.IsolatedAsyncioTestCase):
    """Test the finalize_node function."""

    async def test_finalize_node_completed_status(self):
        """Test finalize_node sets completed status on success."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {
                "backend": {
                    "tokens": 200,
                    "cost": 0.05,
                    "duration_ms": 5000,
                    "files_changed": ["src/auth.py"],
                },
                "frontend": {
                    "tokens": 150,
                    "cost": 0.03,
                    "duration_ms": 3000,
                    "files_changed": ["src/ui.tsx"],
                },
            },
            "approval_status": "approved",
            "gate_results": {"passed": True},
            "retry_count": 0,
            "events": [],
        }

        result = await finalize_node(state)

        assert result["status"] == "completed"
        assert len(result["events"]) == 1
        event = result["events"][0]
        assert event["type"] == "task_finalized"
        assert event["agents_run"] == ["backend", "frontend"]
        assert event["total_tokens"] == 350
        assert event["total_cost"] == 0.08
        assert event["total_duration_ms"] == 8000
        assert len(event["files_changed"]) == 2

    async def test_finalize_node_rejected_status(self):
        """Test finalize_node sets rejected status when approval rejected."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {},
            "approval_status": "rejected",
            "gate_results": {},
            "events": [],
        }

        result = await finalize_node(state)

        assert result["status"] == "rejected"
        assert result["events"][0]["status"] == "rejected"

    async def test_finalize_node_failed_status_on_error(self):
        """Test finalize_node sets failed status on error."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {},
            "error": "Agent crashed",
            "events": [],
        }

        result = await finalize_node(state)

        assert result["status"] == "failed"

    async def test_finalize_node_failed_status_max_retries_exceeded(self):
        """Test finalize_node sets failed status when max retries exceeded."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {},
            "gate_results": {"passed": False},
            "retry_count": 3,
            "max_retries": 3,
            "events": [],
        }

        result = await finalize_node(state)

        assert result["status"] == "failed"

    async def test_finalize_node_aggregates_unique_files(self):
        """Test finalize_node deduplicates files changed."""
        state: TaskState = {
            "task_id": "task-1",
            "agent_outputs": {
                "agent1": {"files_changed": ["file.py", "config.yml"]},
                "agent2": {"files_changed": ["file.py", "test.py"]},
            },
            "events": [],
        }

        result = await finalize_node(state)

        files = result["events"][0]["files_changed"]
        assert len(files) == 3
        assert "file.py" in files


if __name__ == "__main__":
    unittest.main()
