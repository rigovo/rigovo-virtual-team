"""Tests for RunTaskCommand replan audit persistence during streaming."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock
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


if __name__ == "__main__":
    unittest.main()
