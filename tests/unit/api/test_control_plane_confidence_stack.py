from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import rigovo.api.control_plane as control_plane_module
from rigovo.api.control_plane import create_app
from rigovo.domain.entities.task import Task, TaskStatus, TaskType
from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository


class _FakeRunTaskCommand:
    def __init__(self, app, project_root: Path) -> None:
        self._app = app
        self._project_root = project_root

    async def execute(
        self,
        *,
        description: str,
        resume_thread_id: str | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
        tier: str = "auto",
        workspace_path: str = "",
        workspace_label: str = "",
    ) -> None:
        assert task_id is not None
        repo = SqliteTaskRepository(self._app.state.container.get_db())
        task_uuid = UUID(str(task_id))
        task = await repo.get(task_uuid)
        if task is None:
            task = Task(
                workspace_id=UUID(int=0),
                description=description,
                id=task_uuid,
            )
        task.tier = tier
        task.project_id = UUID(project_id) if project_id else None
        task.workspace_path = workspace_path or str(self._project_root)
        task.workspace_label = workspace_label or Path(task.workspace_path).name
        if task.status != TaskStatus.RUNNING:
            task.start()
        task.langgraph_thread_id = str(resume_thread_id or task_id)
        task.approval_data = {
            **(task.approval_data or {}),
            "collaboration": {
                "events": [
                    {
                        "type": "master_decision",
                        "task_type": "new_project",
                        "workspace_type": "new_project",
                        "execution_mode": "linear",
                        "created_at": 1,
                    }
                ],
                "messages": [],
            },
        }
        task.checkpoint_timeline = [
            *(task.checkpoint_timeline or []),
            {
                "node": "execute_agent",
                "status": "completed",
                "current_role": "coder",
            },
            {
                "node": "finalize",
                "status": "completed",
                "current_role": "finalize",
            },
        ]
        task.complete()
        await repo.save(task)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RIGOVO_TEST_MODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    app = create_app(project_root=tmp_path)
    app.state.container.close = lambda: None
    client = TestClient(app)
    reset = client.post("/v1/test/reset")
    assert reset.status_code == 200
    bootstrap = client.post("/v1/test/session/bootstrap", json={})
    assert bootstrap.status_code == 200
    workspace = client.post(
        "/v1/control/workspace",
        json={
            "workspaceName": "Rigovo E2E Workspace",
            "workspaceSlug": "rigovo-e2e",
            "adminEmail": "e2e@rigovo.test",
            "deploymentMode": "self_hosted",
            "region": "us-east-1",
        },
    )
    assert workspace.status_code == 200
    yield client
    client.close()


def test_bootstrap_and_seeded_approval_lifecycle(client: TestClient) -> None:
    seed = client.post(
        "/v1/test/tasks/seed",
        json={
            "scenario": "approval_pending",
            "description": "Deploy auth service",
            "tier": "approve",
        },
    )
    assert seed.status_code == 200
    task_id = seed.json()["task_id"]

    detail = client.get(f"/v1/tasks/{task_id}/detail")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "awaiting_approval"
    assert body["approval_data"]["checkpoint"] == "risk_action_required"

    approve = client.post(f"/v1/tasks/{task_id}/approve", json={"actor": "e2e"})
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    waited = client.get(
        f"/v1/test/tasks/{task_id}/wait",
        params={"status": "running", "timeout_ms": 500},
    )
    assert waited.status_code == 200
    assert waited.json()["status"] == "ok"

    detail_after = client.get(f"/v1/tasks/{task_id}/detail")
    assert detail_after.status_code == 200
    assert detail_after.json()["status"] == "running"


def test_seeded_remediation_detail_exposes_fix_packet_truth(client: TestClient) -> None:
    seed = client.post(
        "/v1/test/tasks/seed",
        json={"scenario": "failed_remediation", "description": "Broken task", "tier": "approve"},
    )
    assert seed.status_code == 200
    task_id = seed.json()["task_id"]

    detail = client.get(f"/v1/tasks/{task_id}/detail")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "failed"
    assert body["active_fix_packet"]["type"] == "fix_packet_created"
    assert body["active_fix_packet"]["role"] == "coder"
    assert body["downstream_lock_reason"] == "awaiting_remediation"


def test_create_task_runs_to_completion_with_persisted_detail(
    client: TestClient,
    tmp_path: Path,
) -> None:
    client.app.state.container.build_run_task_command = lambda **_: _FakeRunTaskCommand(
        client.app, tmp_path
    )

    create = client.post(
        "/v1/tasks",
        json={
            "description": "Create auth identity SaaS in Python",
            "tier": "auto",
            "workspace_path": str(tmp_path),
            "workspace_label": "fixture-workspace",
        },
    )
    assert create.status_code == 200
    task_id = create.json()["task_id"]

    waited = client.get(
        f"/v1/test/tasks/{task_id}/wait",
        params={"status": "completed", "timeout_ms": 1500},
    )
    assert waited.status_code == 200
    assert waited.json()["status"] == "ok"

    detail = client.get(f"/v1/tasks/{task_id}/detail")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "completed"
    assert body["description"] == "Create auth identity SaaS in Python"
    assert body["ui_summary"]["next_expected_reason"] in {None, "queued by planner sequence"}
    assert body["supervisory_decisions"][0]["type"] == "master_decision"

    adaptive = client.get("/v1/adaptive/metrics")
    promotions = client.get("/v1/memory/promotions")
    assert adaptive.status_code == 200
    assert promotions.status_code == 200


def test_resume_restarts_from_seeded_checkpoint_and_persists_completion(
    client: TestClient,
    tmp_path: Path,
) -> None:
    client.app.state.container.build_run_task_command = lambda **_: _FakeRunTaskCommand(
        client.app, tmp_path
    )

    seed = client.post(
        "/v1/test/tasks/seed",
        json={"scenario": "resumable_running", "description": "Resume me", "tier": "auto"},
    )
    assert seed.status_code == 200
    task_id = seed.json()["task_id"]

    resume = client.post(f"/v1/tasks/{task_id}/resume", json={"actor": "e2e"})
    assert resume.status_code == 200
    assert resume.json()["status"] == "resuming"

    waited = client.get(
        f"/v1/test/tasks/{task_id}/wait",
        params={"status": "completed", "timeout_ms": 1500},
    )
    assert waited.status_code == 200
    assert waited.json()["status"] == "ok"

    detail = client.get(f"/v1/tasks/{task_id}/detail")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "completed"
    assert len(body["approval_data"].get("collaboration", {}).get("events", [])) >= 1
    assert len(body["steps"]) == 0 or isinstance(body["steps"], list)


def test_running_task_prefers_live_classification_and_exposes_target_metadata(
    client: TestClient,
    tmp_path: Path,
) -> None:
    repo = SqliteTaskRepository(client.app.state.container.get_db())
    task = Task(workspace_id=UUID(int=0), description="Create Identity api saas")
    task.task_type = TaskType.FEATURE
    task.workspace_path = str(tmp_path)
    task.workspace_label = tmp_path.name
    task.start()

    import asyncio

    asyncio.run(repo.save(task))

    control_plane_module._live_task_classification[str(task.id)] = {
        "task_type": "new_project",
        "complexity": "high",
        "workspace_type": "new_subfolder_project",
        "workspace_root": str(tmp_path),
        "target_root": str(tmp_path / "identity-api-saas"),
        "target_mode": "new_subfolder_project",
        "agent_count": 4,
        "agent_instances": [
            {"role": "lead"},
            {"role": "planner"},
            {"role": "coder"},
            {"role": "reviewer"},
        ],
    }

    detail = client.get(f"/v1/tasks/{task.id}/detail")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "running"
    assert body["task_type"] == "new_project"
    assert body["workspace_root"] == str(tmp_path)
    assert body["target_root"] == str(tmp_path / "identity-api-saas")
    assert body["target_mode"] == "new_subfolder_project"
    assert body["ui_summary"]["target_mode"] == "new_subfolder_project"
    assert body["planned_roles"] == ["lead", "planner", "coder", "reviewer"]
