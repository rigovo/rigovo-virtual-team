"""Adaptive token budgeting tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from rigovo.application.commands.run_task import (
    ADAPTIVE_BUDGET_CEILINGS,
    _derive_adaptive_budget_profiles,
    RunTaskCommand,
)
from rigovo.application.graph.nodes.intent_gate import intent_gate_node
from rigovo.domain.entities.task import Task, TaskStatus


class _FakeTaskRepo:
    def __init__(self, tasks: list[Task]) -> None:
        self._tasks = tasks

    async def list_by_workspace(self, _workspace_id: UUID, limit: int = 50) -> list[Task]:
        return self._tasks[:limit]


def _mk_task(description: str, tokens: int, status: TaskStatus = TaskStatus.COMPLETED) -> Task:
    task = Task(workspace_id=UUID(int=0), description=description, id=uuid4())
    task.status = status
    task.total_tokens = tokens
    return task


def test_derive_adaptive_profiles_build_budget_increases_with_history() -> None:
    profiles = _derive_adaptive_budget_profiles(
        {
            "brainstorm": [],
            "research": [],
            "fix": [],
            "build": [
                220_000,
                240_000,
                260_000,
                280_000,
                300_000,
                320_000,
                340_000,
                360_000,
                380_000,
                400_000,
                420_000,
                440_000,
            ],
        }
    )

    build = profiles["build"]
    assert build["sample_size"] == 12
    assert build["recommended_budget"] >= 200_000
    assert build["recommended_budget"] <= ADAPTIVE_BUDGET_CEILINGS["build"]


@pytest.mark.asyncio
async def test_build_adaptive_budget_profiles_only_when_sample_is_sufficient() -> None:
    build_tasks = [_mk_task("Implement robust auth flow", 260_000 + i * 10_000) for i in range(12)]
    fix_tasks = [_mk_task("Fix flaky CI test", 120_000 + i * 2_000) for i in range(6)]

    cmd = RunTaskCommand.__new__(RunTaskCommand)
    cmd._task_repo = _FakeTaskRepo(build_tasks + fix_tasks)
    cmd._workspace_id = UUID(int=0)

    profiles = await cmd._build_adaptive_token_budget_by_intent()
    assert "build" in profiles
    assert profiles["build"]["sample_size"] == 12
    assert "fix" not in profiles  # Below ADAPTIVE_BUDGET_MIN_SAMPLE


@pytest.mark.asyncio
async def test_intent_gate_applies_adaptive_budget_when_user_cap_not_explicit() -> None:
    state = {
        "description": "Implement a distributed lock service for our workers",
        "budget_max_tokens_per_task": 200_000,
        "adaptive_budget_user_cap": False,
        "adaptive_budget_min_sample": 12,
        "adaptive_token_budget_by_intent": {
            "build": {
                "recommended_budget": 480_000,
                "sample_size": 20,
                "p75": 420_000,
                "p95": 560_000,
            }
        },
        "events": [],
    }

    result = await intent_gate_node(state)
    assert result["budget_max_tokens_per_task"] == 480_000
    assert result["intent_profile"]["token_budget"] == 480_000
    assert result["events"][-1]["budget_source"] == "adaptive"


@pytest.mark.asyncio
async def test_intent_gate_respects_explicit_user_cap_over_adaptive_budget() -> None:
    state = {
        "description": "Implement a distributed lock service for our workers",
        "budget_max_tokens_per_task": 180_000,
        "adaptive_budget_user_cap": True,
        "adaptive_budget_min_sample": 12,
        "adaptive_token_budget_by_intent": {
            "build": {
                "recommended_budget": 480_000,
                "sample_size": 20,
                "p75": 420_000,
                "p95": 560_000,
            }
        },
        "events": [],
    }

    result = await intent_gate_node(state)
    assert result["budget_max_tokens_per_task"] == 180_000
    assert result["events"][-1]["budget_source"] == "adaptive_clamped_by_user_cap"
