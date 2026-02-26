"""Unit tests for replan graph node."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from rigovo.application.graph.nodes.replan import replan_node
from rigovo.application.graph.state import TaskState
from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage


class TestReplanNode(unittest.IsolatedAsyncioTestCase):
    async def test_replan_node_generates_fix_packet(self):
        state: TaskState = {
            "task_id": "task-1",
            "description": "Implement auth",
            "current_agent_role": "coder",
            "team_config": {"agents": {"coder": {"id": "a1"}}},
            "gate_results": {"passed": False, "violation_count": 2},
            "replan_policy": {"max_replans_per_task": 2},
            "replan_count": 0,
            "fix_packets": [],
            "events": [],
        }
        llm = AsyncMock()
        llm.invoke.return_value = LLMResponse(
            content=json.dumps(
                {
                    "adjustment": "Regenerate only auth module and tests.",
                    "target_role": "coder",
                    "reasoning": "Keep scope small.",
                }
            ),
            usage=LLMUsage(input_tokens=40, output_tokens=20),
            model="mock",
        )

        result = await replan_node(state, llm)
        assert result["status"] == "replanned"
        assert result["replan_count"] == 1
        assert result["current_agent_role"] == "coder"
        assert result["fix_packets"]
        assert "REPLAN REQUIRED #1" in result["fix_packets"][-1]
        trigger = next(e for e in result["events"] if e.get("type") == "replan_triggered")
        assert trigger["strategy"] == "deterministic"
        assert trigger["trigger_reason"] == "policy_replan"
        llm.invoke.assert_not_called()

    async def test_replan_node_fails_when_budget_exhausted(self):
        state: TaskState = {
            "task_id": "task-1",
            "description": "Implement auth",
            "current_agent_role": "coder",
            "team_config": {"agents": {"coder": {"id": "a1"}}},
            "replan_policy": {"max_replans_per_task": 1},
            "replan_count": 1,
            "events": [],
        }
        llm = AsyncMock()

        result = await replan_node(state, llm)
        assert result["status"] == "replan_failed"
        failure = next(e for e in result["events"] if e.get("type") == "replan_failed")
        assert failure["reason"] == "replan_budget_exhausted"
        assert failure["strategy"] == "deterministic"
        llm.invoke.assert_not_called()

    async def test_replan_node_can_use_llm_strategy(self):
        state: TaskState = {
            "task_id": "task-2",
            "description": "Fix contracts",
            "current_agent_role": "reviewer",
            "team_config": {"agents": {"reviewer": {"id": "a2"}}},
            "gate_results": {"passed": False, "reason": "contract_failed"},
            "contract_stage": "output",
            "replan_policy": {"max_replans_per_task": 2, "strategy": "llm"},
            "replan_count": 0,
            "fix_packets": [],
            "events": [],
        }
        llm = AsyncMock()
        llm.invoke.return_value = LLMResponse(
            content=json.dumps(
                {
                    "adjustment": "Regenerate reviewer summary with required schema.",
                    "target_role": "reviewer",
                    "reasoning": "contract mismatch",
                }
            ),
            usage=LLMUsage(input_tokens=30, output_tokens=20),
            model="mock",
        )

        result = await replan_node(state, llm)
        trigger = next(e for e in result["events"] if e.get("type") == "replan_triggered")
        assert trigger["strategy"] == "llm"
        assert trigger["trigger_reason"] == "contract_failure"
        llm.invoke.assert_called_once()
