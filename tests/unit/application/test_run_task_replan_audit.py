"""Tests for RunTaskCommand replan audit persistence during streaming."""

from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from rigovo.application.commands.run_task import RunTaskCommand
from rigovo.domain.entities.audit_entry import AuditAction


class _FakeCompiled:
    async def astream(self, _initial_state, **_kwargs):
        yield {
            "replan": {
                "events": [
                    {
                        "type": "replan_triggered",
                        "replan_count": 1,
                        "trigger_reason": "retry_threshold",
                        "strategy": "deterministic",
                        "target_role": "coder",
                    },
                    {
                        "type": "replan_failed",
                        "replan_count": 1,
                        "max_replans_per_task": 1,
                        "trigger_reason": "retry_threshold",
                        "strategy": "deterministic",
                    },
                ]
            }
        }


class _FakeGraphBuilder:
    def __init__(self, compiled):
        self._compiled = compiled
        self.received_checkpointer = None

    def build_langgraph(self, checkpointer=None):
        self.received_checkpointer = checkpointer
        return self._compiled


class TestRunTaskReplanAudit(unittest.IsolatedAsyncioTestCase):
    async def test_stream_graph_persists_replan_events_to_audit(self):
        cmd = RunTaskCommand.__new__(RunTaskCommand)
        cmd._event_emitter = MagicMock()
        cmd._workspace_id = uuid4()
        cmd._audit_repo = AsyncMock()

        task_id = str(uuid4())
        initial_state = {
            "task_id": task_id,
            "events": [],
        }

        result = await cmd._stream_graph(_FakeCompiled(), initial_state, None)
        assert result["events"][0]["type"] == "replan_triggered"
        assert result["events"][1]["type"] == "replan_failed"
        assert cmd._audit_repo.append.await_count == 2

        first_entry = cmd._audit_repo.append.await_args_list[0].args[0]
        second_entry = cmd._audit_repo.append.await_args_list[1].args[0]
        assert first_entry.action == AuditAction.REPLAN_TRIGGERED
        assert second_entry.action == AuditAction.REPLAN_FAILED

    async def test_run_graph_uses_effective_project_root_for_checkpoints(self):
        cmd = RunTaskCommand.__new__(RunTaskCommand)
        cmd._project_root = Path("/tmp/command-root")
        cmd._stream_graph = AsyncMock(return_value={"status": "ok"})

        compiled = object()
        graph_builder = _FakeGraphBuilder(compiled)
        initial_state = {
            "task_id": str(uuid4()),
            "project_root": "/tmp/effective-workspace",
            "events": [],
        }
        expected_checkpoint_db = Path(initial_state["project_root"]) / ".rigovo" / "checkpoints.db"

        @asynccontextmanager
        async def _checkpoint_context():
            yield "checkpoint-sentinel"

        with patch(
            "rigovo.application.commands.run_task.GraphBuilder.create_sqlite_checkpointer",
            return_value=_checkpoint_context(),
        ) as mock_create:
            result = await cmd._run_graph(graph_builder, initial_state, resume_thread_id=None)

        assert result["status"] == "ok"
        mock_create.assert_called_once_with(expected_checkpoint_db)
        assert graph_builder.received_checkpointer == "checkpoint-sentinel"


if __name__ == "__main__":
    unittest.main()
