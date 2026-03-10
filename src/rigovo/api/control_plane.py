"""FastAPI control-plane service for desktop and connector integrations."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json

# ── Module-level refs set by create_api() ──────────────────────────
# These are assigned inside create_api() so that module-level event
# handlers (_on_agent_event) can access them without closure scope.
import logging as _logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import UUID, uuid4

import httpx
import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from rigovo.config import load_config
from rigovo.container import Container
from rigovo.domain.entities.audit_entry import AuditAction, AuditEntry
from rigovo.domain.entities.task import Task, TaskStatus
from rigovo.infrastructure.persistence.sqlite_audit_repo import SqliteAuditRepository
from rigovo.infrastructure.persistence.sqlite_settings_repo import SqliteSettingsRepository
from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository
from rigovo.infrastructure.plugins.manifest import PluginManifest

_api_container: Container | None = None
_api_logger = _logging.getLogger("rigovo.api")
logger = _api_logger  # alias used throughout the module
_background_tasks: set[asyncio.Task[Any]] = set()

_ROLE_LABELS: dict[str, str] = {
    "master": "Chief Architect",
    "planner": "Project Manager",
    "coder": "Software Engineer",
    "reviewer": "Code Reviewer",
    "security": "Security Engineer",
    "qa": "QA Engineer",
    "devops": "DevOps Engineer",
    "sre": "SRE Engineer",
    "lead": "Tech Lead",
    "memory": "Knowledge Base",
    "rigour": "Rigour Gates",
    "trinity": "Rigour Gates",
}
_ROLE_KEYWORDS: dict[str, str] = {
    "master": "master",
    "architect": "master",
    "planner": "planner",
    "pm": "planner",
    "manager": "planner",
    "coder": "coder",
    "engineer": "coder",
    "software": "coder",
    "developer": "coder",
    "implementer": "coder",
    "reviewer": "reviewer",
    "review": "reviewer",
    "security": "security",
    "auditor": "security",
    "qa": "qa",
    "tester": "qa",
    "test": "qa",
    "devops": "devops",
    "infra": "devops",
    "sre": "sre",
    "reliability": "sre",
    "lead": "lead",
    "memory": "memory",
    "kb": "memory",
    "knowledge": "memory",
    "rigour": "rigour",
    "trinity": "trinity",
}
_SINGLETON_ROLES = {"master", "memory", "rigour", "trinity"}

_MARKETPLACE_INTEGRATIONS: list[dict[str, Any]] = [
    {
        "id": "figma-read",
        "name": "Figma Read",
        "summary": "Inspect frames and design metadata from Figma.",
        "kind": "connector",
        "trust_level": "verified",
        "connector": {
            "id": "figma",
            "provider": "figma",
            "kind": "api",
            "outbound_actions": ["figma.read", "figma.comment"],
        },
    },
    {
        "id": "miro-board-read",
        "name": "Miro Board Read",
        "summary": "Read board context for planning and architecture synthesis.",
        "kind": "connector",
        "trust_level": "verified",
        "connector": {
            "id": "miro",
            "provider": "miro",
            "kind": "api",
            "outbound_actions": ["miro.read"],
        },
    },
    {
        "id": "gdrive-search",
        "name": "Google Drive Search",
        "summary": "Search and read docs from Google Drive.",
        "kind": "connector",
        "trust_level": "verified",
        "connector": {
            "id": "gdrive",
            "provider": "gdrive",
            "kind": "api",
            "outbound_actions": ["gdrive.search", "gdrive.read"],
        },
    },
    {
        "id": "figma-mcp",
        "name": "Figma MCP Server",
        "summary": "MCP server for frame-level reads and file listing.",
        "kind": "mcp",
        "trust_level": "verified",
        "mcp_server": {
            "id": "figma-mcp",
            "transport": "stdio",
            "command": "npx -y @acme/figma-mcp",
            "operations": ["figma.read_frame", "figma.list_files"],
        },
    },
]


def _normalize_step_status(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    if s == "completed":
        return "complete"
    return s or "pending"


def _is_internal_runtime_path(path: str) -> bool:
    """Return True for internal Rigovo runtime artifacts."""
    normalized = str(path or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized == ".rigovo" or normalized.startswith(".rigovo/")


def _filter_user_files(files: list[str]) -> list[str]:
    """Exclude internal runtime artifacts from UI-facing file ledgers."""
    return [path for path in files if not _is_internal_runtime_path(path)]


def _canonical_agent_identity(
    raw_role: str | None, raw_name: str | None = None
) -> tuple[str, str, str]:
    import re

    role_source = str(raw_role or "").strip()
    name_source = str(raw_name or "").strip()
    lowered = role_source.lower()

    if lowered in _ROLE_LABELS:
        role = lowered
    else:
        parts = [p for p in re.split(r"[^a-z0-9]+", lowered) if p]
        role = ""
        for p in parts:
            mapped = _ROLE_KEYWORDS.get(p)
            if mapped:
                role = mapped
                break
        if not role:
            role = lowered or "unknown"

    index = ""
    for source in (lowered, name_source.lower()):
        m = re.search(r"(\d+)$", source)
        if m:
            index = m.group(1)
            break

    instance = role if not index or role in _SINGLETON_ROLES else f"{role}-{index}"
    label = _ROLE_LABELS.get(role, (name_source or role.replace("_", " ").title()))
    if index and role not in _SINGLETON_ROLES:
        label = f"{label} {index}"
    return role, instance, label


# ── Live agent progress tracker (in-memory, per-task) ──────────────
# Populated by event emitter callbacks during graph execution.
# The detail endpoint reads this for running tasks; completed tasks
# fall back to persisted pipeline_steps in SQLite.
_live_agent_progress: dict[str, dict[str, dict]] = {}  # task_id -> {role -> step_data}
_live_task_events: dict[str, list[dict[str, Any]]] = {}  # task_id -> rolling runtime events
_live_task_classification: dict[
    str, dict[str, Any]
] = {}  # task_id -> classification data (set early)
_classification_cleanup_tasks: dict[str, Any] = {}  # task_id -> asyncio.Task for TTL cleanup
_active_task_runs: dict[str, float] = {}  # task_id -> epoch start time for in-process runner


def _schedule_classification_cleanup(task_id: str, ttl_seconds: int = 300) -> None:
    """Schedule removal of classification from live cache after TTL.

    This allows the task detail API to still read classification data
    for up to 5 minutes after the task finishes/fails, preventing the
    'unclassified' display bug.
    """
    import asyncio

    # Cancel any existing cleanup for this task
    existing = _classification_cleanup_tasks.pop(task_id, None)
    if existing and not existing.done():
        existing.cancel()

    async def _cleanup() -> None:
        await asyncio.sleep(ttl_seconds)
        _live_task_classification.pop(task_id, None)
        _classification_cleanup_tasks.pop(task_id, None)

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_cleanup())
        _classification_cleanup_tasks[task_id] = task
    except RuntimeError:
        # No event loop running — just leave in cache (it'll be cleaned up eventually)
        pass


# ── Human-in-the-loop approval synchronization ─────────────────────
# When tier="approve" the graph pauses at each checkpoint and calls the
# approval_handler (blocking, runs in a thread-pool via asyncio.to_thread).
# The handler blocks on a threading.Event until the /approve or /deny API
# endpoint unblocks it with the human's decision.
_APPROVAL_TIMEOUT_SECS = 86_400  # 24 h — after this auto-approve to unblock graph
_approval_events: dict[str, threading.Event] = {}  # task_id → event
_approval_decisions: dict[str, dict[str, Any]] = {}  # task_id → decision payload


def _make_approval_handler(
    task_id: str,
    main_loop: asyncio.AbstractEventLoop,
    container: Container | None = None,
) -> Any:
    """Return a synchronous approval_handler suitable for asyncio.to_thread.

    Lifecycle:
      1. Called by the graph node *inside* a thread-pool thread.
      2. Writes AWAITING_APPROVAL to DB via the main event loop.
      3. Blocks on a threading.Event until /approve or /deny is called.
      4. Returns {"approval_status": "approved"|"rejected", "approval_feedback": "..."}.
    """

    def handler(state: dict[str, Any]) -> dict[str, Any]:
        checkpoint = (state.get("events") or [{}])[-1].get("checkpoint", "checkpoint")

        # ── 1. Persist AWAITING_APPROVAL status so the UI shows the banner ──
        async def _set_awaiting() -> None:
            task_repo = SqliteTaskRepository(container.get_db())
            task = await task_repo.get(UUID(task_id))
            if task and not task.is_terminal:
                task.await_approval(checkpoint, state.get("approval_data") or {})
                await task_repo.update_status(task)

        fut = asyncio.run_coroutine_threadsafe(_set_awaiting(), main_loop)
        try:
            fut.result(timeout=10)
        except Exception:
            logger.warning(
                "Approval handler: failed to persist AWAITING_APPROVAL for task %s",
                task_id,
                exc_info=True,
            )

        # ── 2. Block until human decision (or timeout) ───────────────────
        event = threading.Event()
        _approval_events[task_id] = event
        signalled = event.wait(timeout=_APPROVAL_TIMEOUT_SECS)

        decision = _approval_decisions.pop(task_id, {})
        _approval_events.pop(task_id, None)

        if not signalled:
            # Timeout: auto-approve so the graph is never permanently stuck.
            # Also update DB so the UI doesn't show AWAITING_APPROVAL indefinitely.
            async def _clear_awaiting() -> None:
                try:
                    task_repo = SqliteTaskRepository(container.get_db())
                    task = await task_repo.get(UUID(task_id))
                    if task and task.status == TaskStatus.AWAITING_APPROVAL:
                        task.start()  # transition back to running
                        await task_repo.update_status(task)
                except Exception:
                    pass  # best-effort

            asyncio.run_coroutine_threadsafe(_clear_awaiting(), main_loop)
            return {
                "approval_status": "approved",
                "approval_feedback": "auto-approved after timeout",
            }

        return decision

    return handler


def _make_notify_handler(
    task_id: str,
    main_loop: asyncio.AbstractEventLoop,
    db_factory: Any,  # callable → LocalDatabase  (e.g. container.get_db)
    workspace_uuid: UUID,  # pre-resolved workspace ID
) -> Any:
    """Return a non-blocking approval_handler for tier='notify'.

    The graph calls this just like _make_approval_handler, but instead of
    blocking on a threading.Event it immediately approves and records a
    GATE_NOTIFICATION audit entry so the UI can surface it as an info card.

    db_factory and workspace_uuid are passed explicitly so this module-level
    function does not rely on create_app-scoped variables.
    """

    def handler(state: dict[str, Any]) -> dict[str, Any]:
        checkpoint = (state.get("events") or [{}])[-1].get("checkpoint", "checkpoint")
        summary = state.get("approval_data", {}).get("summary") or f"Gate reached: {checkpoint}"

        async def _record_notification() -> None:
            try:
                audit_repo = SqliteAuditRepository(db_factory())
                entry = AuditEntry(
                    workspace_id=workspace_uuid,
                    action=AuditAction.GATE_NOTIFICATION,
                    summary=summary,
                    task_id=UUID(task_id) if task_id else None,
                    metadata={"checkpoint": checkpoint, "tier": "notify"},
                )
                await audit_repo.append(entry)
            except Exception:
                pass  # best-effort — never block task execution

        fut = asyncio.run_coroutine_threadsafe(_record_notification(), main_loop)
        with contextlib.suppress(Exception):
            fut.result(timeout=5)

        # Immediately approve — notify tier never blocks
        return {"approval_status": "approved", "approval_feedback": "auto-approved (notify tier)"}

    return handler


def _on_agent_event(event: dict) -> None:
    """Handle agent lifecycle + gate result events from the graph.

    Supported event types:
    - agent_started: Agent begins execution
    - agent_complete: Agent finished producing output
    - gate_results: Quality gates ran for the agent (from quality_check_node)
    - task_classified: Master Agent finished classification (persist early)
    - task_finalized / task_failed: Cleanup live state
    """
    etype = event.get("type", "")
    task_id = event.get("task_id", "")

    if etype in ("task_finalized", "task_failed") and task_id:
        # Clean up live caches after terminal transitions.
        _live_agent_progress.pop(task_id, None)
        _live_task_events.pop(task_id, None)
        _active_task_runs.pop(task_id, None)
        # Keep classification briefly so completed/failed detail still resolves.
        _schedule_classification_cleanup(task_id, ttl_seconds=300)
        return

    if etype == "agent_streaming" and task_id:
        role = str(event.get("role", "") or "").strip()
        instance_id = str(event.get("instance_id", "") or "").strip()
        if not role:
            return
        if task_id not in _live_agent_progress:
            _live_agent_progress[task_id] = {}
        task_steps = _live_agent_progress[task_id]
        role_key, canonical_instance, canonical_name = _canonical_agent_identity(
            instance_id or role,
            str(event.get("name", "") or ""),
        )
        step_key = canonical_instance or role_key or role
        existing = task_steps.get(step_key, {})
        chunk = str(event.get("chunk", "") or "")
        existing_output = str(existing.get("output", "") or "")
        merged_output = (existing_output + chunk)[-24000:]
        task_steps[step_key] = {
            **existing,
            "agent": canonical_instance,
            "agent_role": role_key,
            "agent_instance": canonical_instance,
            "agent_name": canonical_name,
            "status": "running",
            "started_at": existing.get("started_at") or datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "output": merged_output,
            "files_changed": _filter_user_files(existing.get("files_changed", [])),
            "gate_results": existing.get("gate_results", []),
            "last_activity_at": datetime.now(timezone.utc).isoformat(),
        }
        return

    # deterministic_classified fires INSTANTLY (<50ms) before the LLM call
    if etype == "deterministic_classified" and task_id:
        _live_task_classification[task_id] = {
            "task_type": event.get("task_type", "feature"),
            "complexity": event.get("complexity", "medium"),
            "workspace_type": "pending_llm",  # Will be refined by task_classified
            "workspace_root": event.get("workspace_root", ""),
            "target_root": event.get("target_root", ""),
            "target_mode": event.get("target_mode", ""),
            "reasoning": (
                f"Deterministic classification (confidence: {event.get('confidence', 0):.0%})"
            ),
            "agent_count": 0,
            "agent_instances": [],
            "source": event.get("source", "regex"),
            "confidence": event.get("confidence", 0),
        }
        return

    # reclassified — late-binding reclassification updates live classification
    if etype == "reclassified" and task_id:
        _live_task_classification[task_id] = {
            "task_type": event.get("new_task_type", "feature"),
            "complexity": event.get("new_complexity", "medium"),
            "workspace_type": _live_task_classification.get(task_id, {}).get(
                "workspace_type", "existing_project"
            ),
            "workspace_root": _live_task_classification.get(task_id, {}).get("workspace_root", ""),
            "target_root": _live_task_classification.get(task_id, {}).get("target_root", ""),
            "target_mode": _live_task_classification.get(task_id, {}).get("target_mode", ""),
            "reasoning": (
                f"Reclassified from {event.get('previous_task_type', '?')}: "
                f"{event.get('reason', '')}"
            ),
            "agent_count": _live_task_classification.get(task_id, {}).get("agent_count", 0),
            "agent_instances": _live_task_classification.get(task_id, {}).get(
                "agent_instances", []
            ),
            "reclassified": True,
            "previous_task_type": event.get("previous_task_type", ""),
        }
        return

    # task_classified has no 'role' — handle it before the role guard
    if etype == "task_classified" and task_id:
        _live_task_classification[task_id] = {
            "task_type": event.get("task_type", "feature"),
            "complexity": event.get("complexity", "medium"),
            "workspace_type": event.get("workspace_type", "existing_project"),
            "workspace_root": event.get("workspace_root", ""),
            "target_root": event.get("target_root", ""),
            "target_mode": event.get("target_mode", ""),
            "reasoning": event.get("reasoning", ""),
            "agent_count": event.get("agent_count", 0),
            "agent_instances": event.get("agent_instances", []),
        }
        # Also persist to Task entity in DB so it survives across restarts
        try:
            from rigovo.domain.entities.task import TaskComplexity, TaskType

            if _api_container is None:
                return
            task_repo = SqliteTaskRepository(_api_container.get_db())

            async def _persist_classification() -> None:
                _task = await task_repo.get(UUID(task_id))
                if _task and _task.task_type is None:
                    raw_type = event.get("task_type", "")
                    if raw_type:
                        try:
                            _task.task_type = TaskType(raw_type)
                        except ValueError:
                            _task.task_type = TaskType.FEATURE
                    raw_cx = event.get("complexity", "")
                    if raw_cx:
                        try:
                            _task.complexity = TaskComplexity(raw_cx)
                        except ValueError:
                            _task.complexity = TaskComplexity.MEDIUM
                    await task_repo.save(_task)

            try:
                loop = asyncio.get_running_loop()
                persist_task = loop.create_task(_persist_classification())
                _background_tasks.add(persist_task)
                persist_task.add_done_callback(_background_tasks.discard)
            except RuntimeError:
                asyncio.run(_persist_classification())
        except Exception:
            _api_logger.debug(
                "Could not persist early classification for %s", task_id, exc_info=True
            )
        return

    # pipeline_assembled — capture execution_dag and upgrade agent_instances list
    # This fires from assemble_node (after task_classified) and provides the
    # true DAG edges so the MAP can render accurate topology instead of static defaults.
    if etype == "pipeline_assembled" and task_id:
        dag = event.get("execution_dag")
        if dag and isinstance(dag, dict):
            existing_cls = _live_task_classification.get(task_id, {})
            _live_task_classification[task_id] = {
                **existing_cls,
                "execution_dag": dag,
            }
        # Also refresh agent_instances with the assembled order (instance_ids + roles)
        summaries = event.get("agent_summaries", [])
        if summaries and isinstance(summaries, list):
            existing_cls = _live_task_classification.get(task_id, {})
            _live_task_classification[task_id] = {
                **existing_cls,
                "agent_instances": [
                    {
                        "instance_id": s.get("instance_id", ""),
                        "role": s.get("role", ""),
                        "specialisation": s.get("specialisation", ""),
                        "assignment": (s.get("assignment", "") or "")[:200],
                    }
                    for s in summaries
                    if isinstance(s, dict)
                ],
            }
        return

    role = str(event.get("role", "") or "").strip()
    instance_id = str(event.get("instance_id", "") or "").strip()
    if not task_id or not role:
        return

    if task_id not in _live_agent_progress:
        _live_agent_progress[task_id] = {}
    task_steps = _live_agent_progress[task_id]
    role_key, canonical_instance, canonical_name = _canonical_agent_identity(
        instance_id or role,
        str(event.get("name", "") or ""),
    )
    step_key = canonical_instance or role_key or role

    if etype == "agent_started":
        existing = task_steps.get(step_key, {})
        # Archive previous run when retrying after gate failure
        # This preserves the first attempt's output/gate results so the
        # timeline can show: Attempt 1 → Gate failure → Attempt 2 (fixing)
        if existing and existing.get("status") in ("complete", "gate_failed", "running"):
            prev_attempts = list(existing.get("attempts", []))
            prev_attempt = {k: v for k, v in existing.items() if k != "attempts"}
            prev_attempt["attempt_num"] = len(prev_attempts) + 1
            prev_attempts.append(prev_attempt)
            gate_retry_count = len(prev_attempts)
        else:
            prev_attempts = []
            gate_retry_count = 0
        task_steps[step_key] = {
            "agent": canonical_instance,
            "agent_role": role_key,
            "agent_instance": canonical_instance,
            "agent_name": canonical_name,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "output": "",
            "files_changed": [],
            "gate_results": [],
            # Retry tracking — preserved across overwrites
            "gate_retry_count": gate_retry_count,  # how many previous attempts
            "attempts": prev_attempts,  # archived previous runs
        }
    elif etype == "agent_complete":
        existing = task_steps.get(step_key, {})
        _live_agent_progress[task_id][step_key] = {
            **existing,
            "agent": canonical_instance,
            "agent_role": role_key,
            "agent_instance": canonical_instance,
            "agent_name": canonical_name,
            "status": "complete",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "output": event.get("summary", existing.get("output", "")),
            "files_changed": _filter_user_files(event.get("files_changed", [])),
            "input_tokens": event.get("input_tokens", 0),
            "output_tokens": event.get("output_tokens", 0),
            "tokens": event.get("tokens", 0),
            "cost_usd": event.get("cost", 0.0),
            "duration_ms": event.get("duration_ms", 0),
            "cached_input_tokens": event.get("cached_input_tokens", 0),
            "cache_write_tokens": event.get("cache_write_tokens", 0),
            "cache_source": event.get("cache_source", "none"),
            "cache_saved_tokens": event.get("cache_saved_tokens", 0),
            "cache_saved_cost_usd": event.get("cache_saved_cost_usd", 0.0),
            "gate_results": existing.get("gate_results", []),
            "execution_log": event.get("execution_log", existing.get("execution_log", [])),
            "execution_verified": event.get(
                "execution_verified", existing.get("execution_verified", False)
            ),
        }
    elif etype == "gate_results":
        # Wire quality_check_node gate results into the agent's live step.
        # This fires after quality_check_node runs for this role.
        existing = task_steps.get(step_key, {})
        if not existing and role_key:
            existing = task_steps.get(role_key, {})
        if existing:
            passed = event.get("passed", True)
            violation_count = event.get("violations", 0)
            gates_run = event.get("gates_run", 0)
            reason = event.get("reason", "")
            deep = event.get("deep", False)
            pro = event.get("pro", False)

            violation_details = event.get("violation_details", [])
            gate_entry: dict[str, Any] = {
                "gate": "rigour",
                "passed": passed,
                "message": reason
                if reason
                else (
                    f"Score: {gates_run} gate{'s' if gates_run != 1 else ''} run"
                    if passed
                    else f"{violation_count} violation{'s' if violation_count != 1 else ''}"
                ),
                "severity": "info" if passed else "error",
                "violation_count": violation_count,
                "violation_details": violation_details,  # actual violation messages
                "gates_run": gates_run,
                "deep": deep,
                "pro": pro,
            }
            # Persona violations are tagged in the event
            if reason == "persona_violation":
                gate_entry["gate"] = "persona"
                gate_entry["message"] = (
                    "Persona boundary violation: "
                    f"{violation_count} issue{'s' if violation_count != 1 else ''}"
                )
            elif reason == "contract_failed":
                gate_entry["gate"] = "contract"
                gate_entry["message"] = (
                    "Output contract failed: "
                    f"{violation_count} violation{'s' if violation_count != 1 else ''}"
                )

            existing_gates = existing.get("gate_results", [])
            existing_gates.append(gate_entry)
            existing["gate_results"] = existing_gates
            if not passed:
                existing["status"] = "failed"
    elif etype in ("task_finalized", "task_failed"):
        # handled in early terminal branch above
        return


def _on_runtime_event(event: dict) -> None:
    """Capture live collaboration/policy events for active task playback."""
    task_id = str(event.get("task_id", "") or "").strip()
    if not task_id:
        return
    bucket = _live_task_events.setdefault(task_id, [])
    normalized = dict(event)
    normalized.setdefault("created_at", time.time())
    bucket.append(normalized)
    # Keep memory bounded.
    if len(bucket) > 500:
        del bucket[:-500]


class TaskActionRequest(BaseModel):
    reason: str = ""
    actor: str = "operator"
    resume_now: bool = False


class WorkspaceRequest(BaseModel):
    workspace_name: str = Field(alias="workspaceName")
    workspace_slug: str = Field(alias="workspaceSlug")
    admin_email: str = Field(alias="adminEmail")
    deployment_mode: str = Field(default="cloud", alias="deploymentMode")
    region: str = "us-east-1"
    model_config = {"populate_by_name": True}


class CreateTaskRequest(BaseModel):
    description: str
    team: str = ""
    tier: str = "auto"
    approve: bool = False
    project_id: str = ""  # UUID of the active project (optional)
    workspace_path: str = ""  # Absolute path of the target repo/folder for this task
    workspace_label: str = ""  # Human-readable name shown in sidebar (e.g. folder/repo name)


class RenameTaskRequest(BaseModel):
    title: str  # Custom display title; overrides description in the inbox/sidebar


class TestSessionBootstrapRequest(BaseModel):
    email: str = "e2e@rigovo.test"
    full_name: str = "Rigovo E2E"
    first_name: str = "Rigovo"
    last_name: str = "E2E"
    role: str = "admin"
    workspace_name: str = "Rigovo E2E Workspace"
    workspace_slug: str = "rigovo-e2e"
    admin_email: str = "e2e@rigovo.test"
    region: str = "us-east-1"


class TestSeedTaskRequest(BaseModel):
    scenario: str = "approval_pending"
    description: str = "Seeded E2E task"
    tier: str = "approve"


class PingResponse(BaseModel):
    """Response schema for the GET /v1/ping liveness probe."""

    status: str
    timestamp: str


class RegisterProjectRequest(BaseModel):
    path: str
    name: str = ""


class UpdateSettingsRequest(BaseModel):
    """Partial settings update from the UI.

    Any field can be sent individually. The backend merges changes.
    """

    # API keys — any provider
    api_keys: dict[str, str] | None = None  # e.g. {"anthropic": "sk-...", "deepseek": "ds-..."}
    # Other .env settings
    default_model: str | None = None
    ollama_url: str | None = None
    custom_base_url: str | None = None  # For OpenAI-compatible endpoints
    # Per-agent model overrides (written to rigovo.yml)
    agent_models: dict[str, str] | None = None
    # Per-agent tool/capability overrides (written to rigovo.yml)
    agent_tools: dict[str, list[str]] | None = None
    # Plugin/integration policy override (written to rigovo.yml.plugins)
    plugin_policy: dict[str, Any] | None = None
    # Raw YAML override (written directly to rigovo.yml)
    yml_raw: str | None = None
    # Database/runtime storage settings
    db_backend: str | None = None  # sqlite|postgres
    local_db_path: str | None = None  # Used when backend=sqlite
    db_url: str | None = None  # Postgres DSN (persisted to .env)


class RollbackPromotionRequest(BaseModel):
    reason: str = Field(default="operator_requested", max_length=240)
    actor: str = Field(default="operator", max_length=64)


class CustomConnectorRequest(BaseModel):
    id: str
    provider: str = ""
    kind: str = "api"  # webhook|api|socket
    inbound_events: list[str] = Field(default_factory=list)
    outbound_actions: list[str] = Field(default_factory=list)


class CustomMCPServerRequest(BaseModel):
    id: str
    transport: str = "stdio"  # stdio|sse|http
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    operations: list[str] = Field(default_factory=list)


class AddCustomIntegrationRequest(BaseModel):
    plugin_id: str
    name: str = ""
    description: str = ""
    trust_level: str = "verified"  # community|verified|internal
    connector: CustomConnectorRequest | None = None
    mcp_server: CustomMCPServerRequest | None = None
    enable_plugin: bool = True
    enable_tools: bool = True
    allow_operations: bool = True


class MarketplaceInstallRequest(BaseModel):
    integration_id: str
    plugin_id: str | None = None
    enable_plugin: bool = True
    enable_tools: bool = True
    allow_operations: bool = True


class GitHubInstallRequest(BaseModel):
    github_url: str
    ref: str = "main"
    plugin_id: str | None = None
    enable_plugin: bool = True
    enable_tools: bool = True
    allow_operations: bool = True


class PersonaMember(BaseModel):
    id: str
    name: str
    role: str
    team: str


class PolicyRequest(BaseModel):
    auth_mode: str = Field(default="email_only", alias="authMode")
    default_tier: str = Field(default="notify", alias="defaultTier")
    deep_rigour: bool = Field(default=True, alias="deepRigour")
    require_approval_high_risk: bool = Field(default=True, alias="requireApprovalHighRisk")
    require_approval_prod_secrets: bool = Field(default=True, alias="requireApprovalProdSecrets")
    notify_channels: list[str] = Field(
        default_factory=lambda: ["slack", "email"],
        alias="notifyChannels",
    )
    model_config = {"populate_by_name": True}


class ControlPlaneState(BaseModel):
    auth: dict[str, Any] = Field(
        default_factory=lambda: {"signed_in": False, "email": "", "full_name": ""}
    )
    workspace: dict[str, Any] = Field(
        default_factory=lambda: {
            "workspaceName": "",
            "workspaceSlug": "",
            "adminEmail": "",
            "deploymentMode": "self_hosted",
            "region": "us-east-1",
        }
    )
    policy: dict[str, Any] = Field(
        default_factory=lambda: {
            "authMode": "email_only",
            "defaultTier": "notify",
            "deepRigour": True,
            "requireApprovalHighRisk": True,
            "requireApprovalProdSecrets": True,
            "notifyChannels": ["slack", "email"],
        }
    )
    personas: list[dict[str, Any]] = Field(default_factory=list)
    connectors: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "name": "WorkOS AuthKit",
                "type": "Identity",
                "state": "connected",
                "notes": "Redirect-based auth via browser",
                "channel": "AuthKit",
            },
            {
                "name": "Slack Adapter",
                "type": "Messaging",
                "state": "offline",
                "notes": "Not configured",
                "channel": "",
            },
            {
                "name": "n8n Bridge",
                "type": "Workflow",
                "state": "offline",
                "notes": "Not configured",
                "channel": "",
            },
            {
                "name": "Company KB",
                "type": "Knowledge",
                "state": "offline",
                "notes": "Not configured",
                "channel": "",
            },
        ]
    )
    invitations: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    identity: dict[str, Any] = Field(
        default_factory=lambda: {
            "provider": "",
            "authMode": "",
            "workosApiKey": "",
            "workosClientId": "",
            "workosOrganizationId": "",
        }
    )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _relative(ts: datetime | None) -> str:
    if ts is None:
        return "unknown"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = _now_utc() - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _to_utc(ts: datetime | None) -> datetime | None:
    """Normalize timestamps to UTC for safe comparisons."""
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _percentile(values: list[float], pct: float) -> float:
    """Compute percentile using linear interpolation."""
    if not values:
        return 0.0
    if pct <= 0:
        return float(min(values))
    if pct >= 100:
        return float(max(values))
    ordered = sorted(float(v) for v in values)
    idx = (len(ordered) - 1) * (pct / 100.0)
    low = int(idx)
    high = min(low + 1, len(ordered) - 1)
    weight = idx - low
    return ordered[low] + (ordered[high] - ordered[low]) * weight


def _tier_from_task(task) -> str:
    raw = str(getattr(task, "tier", "") or "").strip().lower()
    if raw in {"auto", "notify", "approve"}:
        return raw
    # Legacy fallback for rows created before tier persistence.
    complexity = (task.complexity.value if task.complexity else "").lower()
    if task.status == TaskStatus.AWAITING_APPROVAL or complexity == "critical":
        return "approve"
    if complexity == "high":
        return "notify"
    return "auto"


def _compute_confidence_score(pipeline_steps: list) -> int:
    """
    Compute confidence score from pipeline steps.

    Scoring logic (Phase 11):
    - Start at 100
    - Subtract 10 if no deep analysis ran on ANY step
    - Subtract 5 for each gate retry
    - Subtract 15 for each unresolved gate failure
    - Subtract 10 for each persona violation
    - Floor at 0, cap at 100
    """
    score = 100

    if not pipeline_steps:
        return score

    # Check if deep analysis ran on ANY step
    any_deep_ran = False
    for step in pipeline_steps:
        if not step or not isinstance(step, object):
            continue
        # Check gate_violations for deep flag
        gate_violations = getattr(step, "gate_violations", []) or []
        if isinstance(gate_violations, list):
            for gv in gate_violations:
                if isinstance(gv, dict) and gv.get("deep"):
                    any_deep_ran = True
                    break
        if any_deep_ran:
            break

    if not any_deep_ran:
        score -= 10

    # Count retries and failures from gate_violations
    total_retries = 0
    total_failures = 0
    persona_violations_count = 0

    for step in pipeline_steps:
        if not step or not isinstance(step, object):
            continue

        # Accumulate retry count
        retry_count = getattr(step, "retry_count", 0) or 0
        if isinstance(retry_count, int):
            total_retries += retry_count

        # Check gate_violations for failures and persona violations
        gate_violations = getattr(step, "gate_violations", []) or []
        if isinstance(gate_violations, list):
            for gv in gate_violations:
                if not isinstance(gv, dict):
                    continue

                passed = gv.get("passed", True)
                if not passed:
                    total_failures += 1

                gate_name = gv.get("gate", "")
                if gate_name == "persona":
                    persona_violations_count += 1

    # Apply penalties
    score -= min(total_retries * 5, 50)  # Cap retry penalty at 50
    score -= min(total_failures * 15, 50)  # Cap failure penalty at 50
    score -= min(persona_violations_count * 10, 30)  # Cap persona penalty at 30

    # Floor at 0, cap at 100
    return max(0, min(100, score))


def _setup_logging(root: Path) -> Path:
    """Configure structured file logging for the Rigovo control plane.

    Logs are stored in <project>/.rigovo/logs/ so users can inspect them.
    Three log files:
      - app.log     — all application events (INFO+)
      - error.log   — errors and warnings only
      - audit.log   — task lifecycle + settings changes (structured JSON)
    """
    import logging
    import logging.handlers

    log_dir = root / ".rigovo" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # JSON-ish formatter for structured logs
    class StructuredFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
            base = {
                "ts": ts,
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info and record.exc_info[1]:
                base["error"] = str(record.exc_info[1])
            return json.dumps(base, default=str)

    # Human-readable formatter for app.log
    readable_fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  [%(name)s]  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # App log — rotating, 5MB per file, keep 5
    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(readable_fmt)

    # Error log — errors and warnings only
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(readable_fmt)

    # Audit log — structured JSON, one line per event
    audit_handler = logging.handlers.RotatingFileHandler(
        log_dir / "audit.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    audit_handler.setLevel(logging.INFO)
    audit_handler.setFormatter(StructuredFormatter())

    # Wire up root logger for rigovo namespace
    root_logger = logging.getLogger("rigovo")
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(app_handler)
    root_logger.addHandler(error_handler)

    # Separate audit logger
    audit_logger = logging.getLogger("rigovo.audit")
    audit_logger.addHandler(audit_handler)
    audit_logger.propagate = True  # also appears in app.log

    # Console handler for development
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(readable_fmt)
    root_logger.addHandler(console)

    logging.getLogger("rigovo.api").info("Logging initialized → %s", log_dir)

    return log_dir


def create_app(project_root: Path | None = None) -> FastAPI:
    root = project_root or Path.cwd()
    config = load_config(root)
    container = Container(config)
    test_mode = str(os.environ.get("RIGOVO_TEST_MODE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # Expose to module-level event handlers
    global _api_container
    _api_container = container

    # Set up structured file logging
    log_dir = _setup_logging(root)

    import logging

    logger = logging.getLogger("rigovo.api")

    # Auto-initialize database schema (ensures tables exist on first run)
    try:
        db = container.get_db()
        db.initialize()
        logger.info("Database schema initialized successfully")
        # Recover orphaned "running" tasks from previous crashed/restarted API process.
        # Task execution is in-process, so any active state at startup is stale.
        active_statuses = (
            TaskStatus.RUNNING.value,
            TaskStatus.ASSEMBLING.value,
            TaskStatus.ROUTING.value,
            TaskStatus.CLASSIFYING.value,
            TaskStatus.QUALITY_CHECK.value,
        )
        stale = db.fetchall(
            "SELECT id FROM tasks WHERE status IN (?, ?, ?, ?, ?)",
            active_statuses,
        )
        if stale:
            now_iso = datetime.now(timezone.utc).isoformat()
            db.execute(
                """UPDATE tasks
                   SET status = ?, completed_at = ?, user_feedback = ?
                   WHERE status IN (?, ?, ?, ?, ?)""",
                (
                    TaskStatus.FAILED.value,
                    now_iso,
                    (
                        "Recovered after API restart (previous run was interrupted). "
                        "Please resume the task."
                    ),
                    *active_statuses,
                ),
            )
            db.commit()
            logger.warning("Recovered %d orphaned running task(s) on startup", len(stale))
    except Exception:
        logger.warning(
            "Could not auto-initialize database — run `rigovo init` if errors persist",
            exc_info=True,
        )

    # One-time migration: copy API keys from .env → encrypted SQLite
    try:
        repo = container.get_settings_repo()
        _env_keys = {
            "ANTHROPIC_API_KEY": config.llm.anthropic_api_key,
            "OPENAI_API_KEY": config.llm.openai_api_key,
            "GOOGLE_API_KEY": config.llm.google_api_key,
            "DEEPSEEK_API_KEY": config.llm.deepseek_api_key,
            "GROQ_API_KEY": config.llm.groq_api_key,
            "MISTRAL_API_KEY": config.llm.mistral_api_key,
        }
        migrated = []
        for key_name, key_val in _env_keys.items():
            if key_val and not repo.get(key_name):
                repo.set(key_name, key_val)
                migrated.append(key_name)
        if migrated:
            logger.info(
                "Migrated %d API key(s) from .env to encrypted SQLite: %s", len(migrated), migrated
            )
    except Exception:
        logger.debug("API key migration skipped", exc_info=True)

    app = FastAPI(title="Rigovo Control Plane API", version="0.1.0")
    app.state.container = container
    app.state.project_root = root
    app.state.test_mode = test_mode

    # CORS — allow Electron renderer (file:// sends null origin),
    # Vite dev server, and electron-vite dev server to reach the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Wire up live agent progress tracking ---
    try:
        emitter = container.get_event_emitter()
        emitter.on("agent_started", _on_agent_event)
        emitter.on("agent_streaming", _on_agent_event)
        emitter.on("agent_complete", _on_agent_event)
        emitter.on("gate_results", _on_agent_event)
        emitter.on("task_finalized", _on_agent_event)
        emitter.on("task_failed", _on_agent_event)
        emitter.on("task_classified", _on_agent_event)
        for evt_name in [
            "agent_consult_requested",
            "agent_consult_completed",
            "debate_round",
            "feedback_loop",
            "subtask_spawned",
            "subtask_complete",
            "subtask_blocked",
            "remediation_lock",
            "integration_invoked",
            "integration_blocked",
            "replan_triggered",
            "replan_failed",
            "cache_hit",
            "cache_miss",
            "artifact_cache_hit",
            "artifact_cache_miss",
            "budget_warning_internal",
            "budget_soft_extension_applied",
            "auto_compaction_applied",
            "budget_exceeded",
            "approval_requested",
            "approval_granted",
            "approval_denied",
            "token_pressure_mode",
            "no_files_nudge",
            "gate_remediation_scheduled",
            "gate_retries_exhausted",
        ]:
            emitter.on(evt_name, _on_runtime_event)
        logger.info("Live agent progress tracking enabled")
    except Exception:
        logger.debug("Could not wire event emitter for live tracking", exc_info=True)

    # --- WorkOS AuthKit PKCE state ----
    # Pending auth flow: stores {state: {code_verifier, redirect_uri}}
    _pending_auth: dict[str, dict[str, str]] = {}

    state_path = root / ".rigovo" / "control_plane_state.json"
    runtime_workos_api_key = ""

    def _workos_settings(state: ControlPlaneState | None = None) -> dict[str, str]:
        """Resolve WorkOS settings from multiple sources (highest priority first):

        1. runtime_workos_api_key  — set in-memory by POST /v1/control/identity
        2. Encrypted SQLite        — persisted across restarts via settings repo
        3. config (.env / env var) — developer/CI fallback only

        Client ID is public and safe to embed in the binary.
        API key is secret and stored encrypted at rest in SQLite.
        """
        nonlocal runtime_workos_api_key
        current = state or _read_state()
        identity = current.identity

        provider = identity.get("provider") or config.identity.provider or "local"
        auth_mode = identity.get("authMode") or config.identity.auth_mode or "email_only"

        # Resolve API key: memory → encrypted SQLite → .env fallback
        api_key = runtime_workos_api_key
        if not api_key:
            try:
                repo = _settings_repo()
                api_key = repo.get("WORKOS_API_KEY") or ""
                if api_key:
                    runtime_workos_api_key = api_key  # cache in memory
            except Exception:
                api_key = ""
        if not api_key:
            api_key = config.identity.workos_api_key or ""

        # Resolve client ID: state → encrypted SQLite → config default
        client_id = identity.get("workosClientId") or ""
        if not client_id:
            try:
                repo = _settings_repo()
                client_id = repo.get("WORKOS_CLIENT_ID") or ""
            except Exception:
                pass
        if not client_id:
            client_id = config.identity.workos_client_id or ""

        organization_id = (
            identity.get("workosOrganizationId") or config.identity.workos_organization_id or ""
        )
        return {
            "provider": str(provider).strip(),
            "authMode": str(auth_mode).strip(),
            "apiKey": str(api_key).strip(),
            "clientId": str(client_id).strip(),
            "organizationId": str(organization_id).strip(),
        }

    def _workos_enabled(state: ControlPlaneState | None = None) -> bool:
        """WorkOS is enabled if we have a client ID (public, embedded in app).
        API key is optional — only needed for admin operations (org/role lookup)."""
        settings = _workos_settings(state)
        return bool(settings["clientId"])

    def _workos_admin_enabled(state: ControlPlaneState | None = None) -> bool:
        """Admin operations (org lookup, invitations) need the API key."""
        settings = _workos_settings(state)
        return bool(settings["clientId"]) and bool(settings["apiKey"])

    def _apply_config_defaults(state: ControlPlaneState) -> ControlPlaneState:
        if not state.identity.get("provider"):
            state.identity["provider"] = config.identity.provider or "local"
        if not state.identity.get("authMode"):
            state.identity["authMode"] = config.identity.auth_mode
        if not state.identity.get("workosClientId"):
            state.identity["workosClientId"] = config.identity.workos_client_id
        if not state.identity.get("workosOrganizationId"):
            state.identity["workosOrganizationId"] = config.identity.workos_organization_id
        # Never persist API key in control-plane state JSON.
        state.identity.pop("workosApiKey", None)

        if not state.policy.get("authMode"):
            state.policy["authMode"] = state.identity.get("authMode", config.identity.auth_mode)
        return state

    def _read_state() -> ControlPlaneState:
        if not state_path.exists():
            return _apply_config_defaults(ControlPlaneState())
        try:
            data = json.loads(state_path.read_text())
            return _apply_config_defaults(ControlPlaneState.model_validate(data))
        except Exception:
            return _apply_config_defaults(ControlPlaneState())

    def _write_state(state: ControlPlaneState) -> None:
        state.identity.pop("workosApiKey", None)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state.model_dump(), indent=2))

    def _require_test_mode() -> None:
        if not test_mode:
            raise HTTPException(status_code=404, detail="Not found")

    def _reset_runtime_buffers() -> None:
        _live_agent_progress.clear()
        _live_task_classification.clear()
        _live_task_events.clear()
        _approval_events.clear()
        _approval_decisions.clear()
        _active_task_runs.clear()

    def _reset_persisted_state() -> None:
        db = container.get_db()
        tables = [
            "tasks",
            "cost_ledger",
            "audit_log",
            "memories",
            "memory_promotion_ledger",
            "team_cache",
            "agent_cache",
            "workspace_cache",
            "sync_queue",
            "prompt_cache_exact",
            "prompt_cache_semantic",
            "artifact_cache",
        ]
        for table in tables:
            with contextlib.suppress(Exception):
                db.execute(f"DELETE FROM {table}")
        with contextlib.suppress(Exception):
            db.commit()

    def _seed_task_for_test(
        scenario: str,
        description: str,
        tier: str,
    ) -> Task:
        task = Task(
            workspace_id=_workspace_id(),
            description=description,
            tier=tier if tier in {"auto", "notify", "approve"} else "approve",
            workspace_path=str(root),
            workspace_label=root.name,
        )
        task.start()

        if scenario == "approval_pending":
            task.await_approval(
                "risk_action_required",
                {
                    "checkpoint": "risk_action_required",
                    "summary": "Deploy to protected environment",
                    "current_role": "devops",
                    "kind": "deploy",
                    "tool_name": "run_command",
                    "requires_human_approval": True,
                },
            )
        elif scenario == "failed_remediation":
            task.fail("Rigour remediation exhausted")
            task.approval_data = {
                **(task.approval_data or {}),
                "collaboration": {
                    "events": [
                        {
                            "type": "fix_packet_created",
                            "role": "coder",
                            "created_at": time.time() - 3,
                            "prompt": "FIX REQUIRED",
                            "items": [
                                {
                                    "gate_id": "rigour",
                                    "file_path": "src/app.py",
                                    "message": "Missing verification",
                                    "suggestion": "Add tests",
                                    "severity": "error",
                                }
                            ],
                        },
                        {
                            "type": "downstream_locked",
                            "role": "coder",
                            "reason": "awaiting_remediation",
                            "created_at": time.time() - 2,
                        },
                    ],
                    "messages": [],
                },
            }
        elif scenario == "resumable_running":
            task.status = TaskStatus.RUNNING
            task.checkpoint_timeline = [
                {
                    "node": "execute_agent",
                    "status": "running",
                    "current_role": "coder",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ]
        else:
            raise HTTPException(status_code=400, detail=f"Unknown test scenario: {scenario}")

        return task

    def _auth_result_html(success: bool, detail: str) -> str:
        """Return a simple HTML page for the browser callback tab."""
        if success:
            return f"""<!DOCTYPE html>
<html><head><title>Rigovo - Signed In</title>
<style>body{{font-family:system-ui;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f8fafc}}
.card{{text-align:center;padding:3rem;border-radius:1rem;background:white;
box-shadow:0 4px 24px rgba(0,0,0,.08)}}
h1{{color:#0f172a;font-size:1.5rem}}p{{color:#64748b;margin-top:.5rem}}</style></head>
<body><div class="card">
<h1>Welcome, {detail}!</h1>
<p>You're signed in to Rigovo. You can close this tab and return to the app.</p>
</div></body></html>"""
        return f"""<!DOCTYPE html>
<html><head><title>Rigovo - Auth Error</title>
<style>body{{font-family:system-ui;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#fef2f2}}
.card{{text-align:center;padding:3rem;border-radius:1rem;background:white;
box-shadow:0 4px 24px rgba(0,0,0,.08)}}
h1{{color:#991b1b;font-size:1.5rem}}p{{color:#64748b;margin-top:.5rem}}</style></head>
<body><div class="card">
<h1>Authentication Failed</h1>
<p>{detail}</p>
<p style="margin-top:1rem"><a href="javascript:window.close()">Close this tab</a> and try again.</p>
</div></body></html>"""

    def _find_pending_invitation(state: ControlPlaneState, email: str) -> dict[str, Any] | None:
        email_l = email.strip().lower()
        for invite in state.invitations:
            if (
                invite.get("email", "").strip().lower() == email_l
                and invite.get("status") == "pending"
            ):
                return invite
        return None

    def _create_workos_invitation(
        state: ControlPlaneState, email: str, role: str
    ) -> dict[str, Any] | None:
        settings = _workos_settings(state)
        if not _workos_admin_enabled(state):
            return None
        org_id = settings["organizationId"]
        if not org_id:
            return None
        headers = {
            "Authorization": f"Bearer {settings['apiKey']}",
            "Content-Type": "application/json",
        }
        payload = {
            "email": email,
            "organization_id": org_id,
            "role_slug": role,
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(
                    "https://api.workos.com/user_management/invitations",
                    headers=headers,
                    json=payload,
                )
            if res.status_code >= 400:
                return {"status": "error", "code": res.status_code, "message": res.text[:500]}
            return res.json()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _workspace_id() -> UUID:
        return UUID(container.config.workspace_id) if container.config.workspace_id else UUID(int=0)

    async def _load_task(task_id: str):
        task_repo = SqliteTaskRepository(container.get_db())
        try:
            task_uuid = UUID(task_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid task id: {task_id}") from e
        task = await task_repo.get(task_uuid)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        return task_repo, task

    async def _append_audit(
        action: AuditAction,
        task,
        summary: str,
        metadata: dict | None = None,
        actor: str = "system",
    ) -> None:
        repo = SqliteAuditRepository(container.get_db())
        await repo.append(
            AuditEntry(
                workspace_id=task.workspace_id,
                task_id=task.id,
                action=action,
                agent_role=actor,
                summary=summary,
                metadata=metadata or {},
            )
        )

    async def _resume_task_async(
        task_id: str,
        description: str,
        use_task_id: str | None = None,
        tier: str = "auto",
        project_id: str = "",
        workspace_path: str = "",
        workspace_label: str = "",
    ) -> None:
        """Run a task in background. use_task_id ensures the DB record is reused, not duplicated.

        tier controls the human-in-the-loop behaviour:
          "auto"    → run freely, no approval gates
          "notify"  → run freely but record audit entries at each gate (future: push notification)
          "approve" → pause at plan_approval and commit_approval; block until human decision

        project_id is stored on the task record so agents know which repo they work on.
        workspace_path is the absolute path of the target folder/repo for this task (if provided).
        workspace_label is the human-readable label shown in the sidebar.
        """
        import logging as _logging

        _bg_logger = _logging.getLogger("rigovo.api.background")
        real_task_id = use_task_id or task_id
        if real_task_id in _active_task_runs:
            _bg_logger.info(
                "Skipping duplicate background run for task %s (already active)",
                real_task_id,
            )
            return
        _active_task_runs[real_task_id] = time.time()
        try:
            # Read parallel setting from config (default True for speed)
            enable_parallel = getattr(
                getattr(getattr(container, "config", None), "yml", None),
                "orchestration",
                None,
            )
            parallel = (
                getattr(enable_parallel, "parallel_agents", True) if enable_parallel else True
            )

            # ── @file mention injection ───────────────────────────────────────
            # Parse @filepath tokens in the description and prepend file contents
            # so the master agent has the full context without manual copy-paste.
            enriched_description = description
            try:
                import re as _re
                from pathlib import Path as _Path

                at_mentions = _re.findall(r"@([\w.\-/\\]+)", description)
                if at_mentions:
                    mention_root = (
                        _Path(workspace_path).expanduser()
                        if str(workspace_path or "").strip()
                        else getattr(getattr(container, "config", None), "project_root", None)
                    )
                    if mention_root:
                        file_blocks: list[str] = []
                        for mention in at_mentions:
                            fpath = _Path(str(mention_root)) / mention
                            try:
                                if fpath.is_file() and fpath.stat().st_size < 200_000:
                                    content = fpath.read_text(encoding="utf-8", errors="replace")
                                    ext = fpath.suffix.lstrip(".") or "text"
                                    file_blocks.append(
                                        f'<file path="{mention}">\n'
                                        f"```{ext}\n{content}\n```\n"
                                        "</file>"
                                    )
                            except OSError:
                                pass
                        if file_blocks:
                            enriched_description = (
                                description
                                + "\n\n### Referenced Files\n\n"
                                + "\n\n".join(file_blocks)
                            )
                            _bg_logger.debug(
                                "Injected %d file(s) into task %s description",
                                len(file_blocks),
                                real_task_id,
                            )
            except Exception as _inj_err:
                _bg_logger.warning("@file injection failed (non-fatal): %s", _inj_err)

            # ── Translate tier → graph builder flags ─────────────────────────
            # "auto"    → auto_approve=True,  no handler (gate skipped entirely)
            # "notify"  → auto_approve=False, non-blocking handler records audit entry
            # "approve" → auto_approve=False, blocking handler waits for human decision
            main_loop = asyncio.get_event_loop()
            if tier == "notify":
                auto_approve = False
                approval_handler = _make_notify_handler(
                    real_task_id,
                    main_loop,
                    container.get_db,
                    _workspace_id(),
                )
            elif tier == "approve":
                auto_approve = False
                approval_handler = _make_approval_handler(real_task_id, main_loop, container)
            else:
                auto_approve = True
                approval_handler = None

            cmd = container.build_run_task_command(
                offline=False,
                enable_parallel=parallel,
                enable_streaming=True,
                auto_approve=auto_approve,
                approval_handler=approval_handler,
            )
            await cmd.execute(
                description=enriched_description,
                resume_thread_id=task_id,
                task_id=real_task_id,
                project_id=project_id or None,
                tier=tier,
                workspace_path=workspace_path,
                workspace_label=workspace_label,
            )
        except Exception as exc:
            _bg_logger.error("Task %s failed in background: %s", real_task_id, exc, exc_info=True)
            # Mark the task as failed in the DB so the UI doesn't show it stuck forever
            try:
                task_repo = SqliteTaskRepository(container.get_db())
                from uuid import UUID as _UUID

                task_obj = await task_repo.get(_UUID(str(real_task_id)))
                if task_obj and task_obj.status not in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.REJECTED,
                ):
                    task_obj.fail(str(exc)[:500])
                    await task_repo.update_status(task_obj)
                    _bg_logger.info("Marked task %s as failed", real_task_id)
            except Exception as db_exc:
                _bg_logger.warning("Could not mark task %s as failed: %s", real_task_id, db_exc)
        finally:
            _active_task_runs.pop(real_task_id, None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/ping")
    def ping() -> PingResponse:
        """Liveness probe returning current UTC timestamp."""
        return PingResponse(
            status="ok",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @app.get("/v1/runtime/capabilities")
    def runtime_capabilities() -> dict[str, Any]:
        """Expose runtime guardrails/capabilities for desktop visibility."""
        orchestration = config.yml.orchestration
        plugins = config.yml.plugins
        return {
            "orchestration": {
                "parallel_agents": bool(orchestration.parallel_agents),
                "max_retries": int(orchestration.max_retries),
                "consultation_enabled": bool(orchestration.consultation.enabled),
                "subagents": {
                    "enabled": bool(orchestration.subagents.enabled),
                    "max_subtasks_per_agent_step": int(
                        orchestration.subagents.max_subtasks_per_agent_step
                    ),
                    "max_subtask_rounds": int(orchestration.subagents.max_subtask_rounds),
                },
                "replan": {
                    "enabled": bool(orchestration.replan.enabled),
                    "max_replans_per_task": int(orchestration.replan.max_replans_per_task),
                    "trigger_retry_count": int(orchestration.replan.trigger_retry_count),
                },
                "budget": {
                    "max_cost_per_task": float(orchestration.budget.max_cost_per_task),
                    "max_tokens_per_task": int(orchestration.budget.max_tokens_per_task),
                    "token_warning_ratio": float(orchestration.budget.token_warning_ratio),
                    "auto_compact_on_token_pressure": bool(
                        orchestration.budget.auto_compact_on_token_pressure
                    ),
                    "max_auto_compactions_per_task": int(
                        orchestration.budget.max_auto_compactions_per_task
                    ),
                    "soft_fail_on_token_limit": bool(orchestration.budget.soft_fail_on_token_limit),
                },
                "learning": {
                    "enabled": bool(orchestration.learning.enabled),
                    "safe_mode": bool(orchestration.learning.safe_mode),
                    "allow_internet_ingestion": bool(
                        orchestration.learning.allow_internet_ingestion
                    ),
                    "promotion_threshold": float(orchestration.learning.promotion_threshold),
                },
            },
            "plugins": {
                "enabled": bool(plugins.enabled),
                "enable_connector_tools": bool(plugins.enable_connector_tools),
                "enable_mcp_tools": bool(plugins.enable_mcp_tools),
                "enable_action_tools": bool(plugins.enable_action_tools),
                "min_trust_level": str(plugins.min_trust_level),
                "allowed_plugin_ids": list(plugins.allowed_plugin_ids),
                "allowed_connector_operations": list(plugins.allowed_connector_operations),
                "allowed_mcp_operations": list(plugins.allowed_mcp_operations),
                "allowed_action_operations": list(plugins.allowed_action_operations),
                "allow_approval_required_actions": bool(plugins.allow_approval_required_actions),
                "allow_sensitive_payload_keys": bool(plugins.allow_sensitive_payload_keys),
                "allowed_shell_commands": list(plugins.allowed_shell_commands),
                "dry_run": bool(plugins.dry_run),
            },
            "runtime": {
                "filesystem_sandbox": str(
                    os.environ.get("RIGOVO_FILESYSTEM_SANDBOX_MODE", "project_root")
                ),
                "worktree_mode": str(os.environ.get("RIGOVO_WORKTREE_MODE", "project")),
                "worktree_root": str(os.environ.get("RIGOVO_WORKTREE_ROOT", "")),
                "debate_enabled": True,
                "debate_max_rounds": 2,
                "quality_gate_enabled": True,
                "memory_learning_enabled": True,
            },
            "database": {
                "backend": str(config.db_backend),
                "local_path": str(config.local_db_path),
                "local_full_path": str(config.local_db_full_path),
                "dsn_configured": bool(config.db_url),
            },
        }

    @app.get("/v1/memory/metrics")
    async def memory_metrics() -> dict[str, Any]:
        """Aggregate memory-learning metrics for cross-run observability."""
        try:
            from rigovo.infrastructure.persistence.sqlite_memory_repo import SqliteMemoryRepository

            repo = SqliteMemoryRepository(container.get_db())
            memories = await repo.list_by_workspace(_workspace_id(), limit=5000)
        except Exception:
            memories = []

        total = len(memories)
        total_usage = sum(int(m.usage_count or 0) for m in memories)
        used = sum(1 for m in memories if int(m.usage_count or 0) > 0)
        cross_project_total = sum(int(m.cross_project_usage or 0) for m in memories)
        return {
            "total_memories": total,
            "used_memories": used,
            "unused_memories": max(total - used, 0),
            "total_usage_count": total_usage,
            "cross_project_usage_total": cross_project_total,
            "avg_usage_per_memory": round(total_usage / total, 3) if total else 0.0,
            "utilization_rate": round(used / total, 3) if total else 0.0,
        }

    @app.get("/v1/memory/promotions")
    async def memory_promotions(
        limit: int = 100, role: str = "", status: str = ""
    ) -> dict[str, Any]:
        """List role-learning promotion ledger entries."""
        limit = min(max(int(limit or 100), 1), 500)
        db = container.get_db()
        clauses = ["workspace_id = ?"]
        params: list[Any] = [str(_workspace_id())]
        if role.strip():
            clauses.append("role = ?")
            params.append(role.strip())
        if status.strip():
            clauses.append("status = ?")
            params.append(status.strip())
        where_sql = " AND ".join(clauses)
        try:
            rows = db.fetchall(
                f"""SELECT id, task_id, role, memory_id, score, status, summary, metadata,
                           created_at, rolled_back_at, rollback_reason, rollback_actor
                    FROM memory_promotion_ledger
                    WHERE {where_sql}
                    ORDER BY created_at DESC
                    LIMIT ?""",
                tuple([*params, limit]),
            )
        except Exception:
            rows = []
        items: list[dict[str, Any]] = []
        for row in rows:
            raw_meta = row["metadata"]
            try:
                meta = json.loads(raw_meta) if raw_meta else {}
            except Exception:
                meta = {}
            items.append(
                {
                    "id": row["id"],
                    "task_id": row["task_id"],
                    "role": row["role"],
                    "memory_id": row["memory_id"],
                    "score": float(row["score"] or 0.0),
                    "status": row["status"],
                    "summary": row["summary"] or "",
                    "metadata": meta,
                    "created_at": row["created_at"],
                    "rolled_back_at": row["rolled_back_at"],
                    "rollback_reason": row["rollback_reason"],
                    "rollback_actor": row["rollback_actor"],
                }
            )
        return {"items": items}

    @app.post("/v1/memory/promotions/{promotion_id}/rollback")
    async def rollback_memory_promotion(
        promotion_id: str,
        req: RollbackPromotionRequest,
    ) -> dict[str, Any]:
        """Rollback promoted learning memory and mark ledger row."""
        db = container.get_db()
        try:
            row = db.fetchone(
                """SELECT id, workspace_id, memory_id, status
                   FROM memory_promotion_ledger
                   WHERE id = ?""",
                (promotion_id,),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Promotion ledger unavailable: {exc}"
            ) from exc
        if not row or str(row["workspace_id"]) != str(_workspace_id()):
            raise HTTPException(status_code=404, detail="Promotion record not found")
        if str(row["status"] or "") == "rolled_back":
            return {"ok": True, "already_rolled_back": True}

        now_iso = _now_utc().isoformat()
        db.execute(
            "DELETE FROM memories WHERE id = ? AND workspace_id = ?",
            (str(row["memory_id"]), str(_workspace_id())),
        )
        db.execute(
            """UPDATE memory_promotion_ledger
               SET status = ?, rolled_back_at = ?, rollback_reason = ?, rollback_actor = ?
               WHERE id = ?""",
            (
                "rolled_back",
                now_iso,
                req.reason.strip() or "operator_requested",
                req.actor.strip() or "operator",
                promotion_id,
            ),
        )
        db.commit()

        try:
            audit_repo = SqliteAuditRepository(container.get_db())
            await audit_repo.append(
                AuditEntry(
                    workspace_id=_workspace_id(),
                    action=AuditAction.PATTERN_DETECTED,
                    agent_role="operator",
                    summary="Rolled back promoted learning memory",
                    metadata={
                        "promotion_id": promotion_id,
                        "memory_id": str(row["memory_id"]),
                        "reason": req.reason.strip() or "operator_requested",
                        "actor": req.actor.strip() or "operator",
                    },
                )
            )
        except Exception:
            logger.warning("Failed to append rollback audit entry", exc_info=True)

        return {"ok": True, "promotion_id": promotion_id, "rolled_back_at": now_iso}

    @app.get("/v1/adaptive/metrics")
    async def adaptive_metrics(task_limit: int = 500, promotion_limit: int = 500) -> dict[str, Any]:
        """Aggregate adaptive budget, compaction, and role-learning metrics."""
        task_limit = min(max(int(task_limit or 500), 25), 5000)
        promotion_limit = min(max(int(promotion_limit or 500), 25), 5000)
        task_repo = SqliteTaskRepository(container.get_db())
        tasks = await task_repo.list_by_workspace(_workspace_id(), limit=task_limit)

        soft_extensions_total = 0
        auto_compactions_total = 0
        compaction_checkpoint_total = 0
        adaptive_budget_applied_tasks = 0
        adaptive_budget_sources: dict[str, int] = {}

        for task in tasks:
            approval_data = task.approval_data or {}
            runtime = (
                approval_data.get("adaptive_runtime", {}) if isinstance(approval_data, dict) else {}
            )
            if isinstance(runtime, dict):
                soft_extensions_total += int(runtime.get("budget_soft_extensions_used", 0) or 0)
                auto_compactions_total += int(runtime.get("budget_auto_compactions", 0) or 0)
                checkpoints = runtime.get("compaction_checkpoints", [])
                if isinstance(checkpoints, list):
                    compaction_checkpoint_total += len(checkpoints)
            collaboration = (
                approval_data.get("collaboration", {}) if isinstance(approval_data, dict) else {}
            )
            events = collaboration.get("events", []) if isinstance(collaboration, dict) else []
            if isinstance(events, list):
                for event in events:
                    if not isinstance(event, dict) or event.get("type") != "intent_detected":
                        continue
                    source = str(event.get("budget_source", "")).strip() or "unknown"
                    adaptive_budget_sources[source] = int(
                        adaptive_budget_sources.get(source, 0) + 1
                    )
                    if bool(event.get("adaptive_budget_applied", False)):
                        adaptive_budget_applied_tasks += 1
                    break

        db = container.get_db()
        try:
            ledger_rows = db.fetchall(
                """SELECT role, status, score, created_at
                   FROM memory_promotion_ledger
                   WHERE workspace_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (str(_workspace_id()), promotion_limit),
            )
        except Exception:
            ledger_rows = []
        promoted_by_role: dict[str, int] = {}
        rolled_back_by_role: dict[str, int] = {}
        role_scores: dict[str, list[float]] = {}
        promoted_scores: list[float] = []
        recent_promotions: list[dict[str, Any]] = []
        for row in ledger_rows:
            role_name = str(row["role"] or "unknown")
            status_name = str(row["status"] or "promoted")
            score = float(row["score"] or 0.0)
            if status_name == "rolled_back":
                rolled_back_by_role[role_name] = int(rolled_back_by_role.get(role_name, 0) + 1)
            else:
                promoted_by_role[role_name] = int(promoted_by_role.get(role_name, 0) + 1)
                promoted_scores.append(score)
                role_scores.setdefault(role_name, []).append(score)
            if len(recent_promotions) < 20:
                recent_promotions.append(
                    {
                        "role": role_name,
                        "status": status_name,
                        "score": score,
                        "created_at": row["created_at"],
                    }
                )

        return {
            "budget": {
                "adaptive_budget_applied_tasks": adaptive_budget_applied_tasks,
                "adaptive_budget_sources": adaptive_budget_sources,
            },
            "compaction": {
                "soft_extensions_total": soft_extensions_total,
                "auto_compactions_total": auto_compactions_total,
                "compaction_checkpoint_total": compaction_checkpoint_total,
            },
            "learning": {
                "promoted_by_role": promoted_by_role,
                "rolled_back_by_role": rolled_back_by_role,
                "promoted_total": int(sum(promoted_by_role.values())),
                "rolled_back_total": int(sum(rolled_back_by_role.values())),
                "avg_promoted_score": round(sum(promoted_scores) / len(promoted_scores), 3)
                if promoted_scores
                else 0.0,
                "role_policy_tuning": {
                    role_name: {
                        "promotions": int(promoted_by_role.get(role_name, 0)),
                        "rollbacks": int(rolled_back_by_role.get(role_name, 0)),
                        "avg_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
                        "top_score": round(max(scores), 3) if scores else 0.0,
                    }
                    for role_name, scores in role_scores.items()
                },
                "recent": recent_promotions,
            },
        }

    @app.get("/v1/integrations/policy")
    def integrations_policy() -> dict[str, Any]:
        """Return effective connector/MCP/action policy + plugin gate outcomes."""
        plugins_cfg = config.yml.plugins
        policy = {
            "plugins_enabled": bool(plugins_cfg.enabled),
            "enable_connector_tools": bool(plugins_cfg.enable_connector_tools),
            "enable_mcp_tools": bool(plugins_cfg.enable_mcp_tools),
            "enable_action_tools": bool(plugins_cfg.enable_action_tools),
            "min_trust_level": str(plugins_cfg.min_trust_level),
            "allowed_plugin_ids": list(plugins_cfg.allowed_plugin_ids),
            "allowed_connector_operations": list(plugins_cfg.allowed_connector_operations),
            "allowed_mcp_operations": list(plugins_cfg.allowed_mcp_operations),
            "allowed_action_operations": list(plugins_cfg.allowed_action_operations),
            "allow_approval_required_actions": bool(plugins_cfg.allow_approval_required_actions),
            "allow_sensitive_payload_keys": bool(plugins_cfg.allow_sensitive_payload_keys),
            "allowed_shell_commands": list(plugins_cfg.allowed_shell_commands),
            "dry_run": bool(plugins_cfg.dry_run),
        }
        if not plugins_cfg.enabled:
            return {
                "policy": policy,
                "plugins": [],
                "summary": {
                    "loaded_plugins": 0,
                    "allowed_plugins": 0,
                    "blocked_plugins": 0,
                },
            }

        trust_order = {"community": 0, "verified": 1, "internal": 2}
        min_rank = trust_order.get(str(plugins_cfg.min_trust_level).lower(), 1)
        allowlist = set(plugins_cfg.allowed_plugin_ids or [])

        try:
            registry = container.get_plugin_registry()
            manifests = registry.load(include_disabled=True)
        except Exception as exc:
            logger.warning("Failed to load plugin registry for policy view: %s", exc)
            return {
                "policy": policy,
                "plugins": [],
                "summary": {
                    "loaded_plugins": 0,
                    "allowed_plugins": 0,
                    "blocked_plugins": 0,
                    "error": "registry_load_failed",
                },
            }

        rows: list[dict[str, Any]] = []
        allowed_plugins = 0
        blocked_plugins = 0
        for manifest in manifests:
            plugin_id = str(manifest.id)
            trust_level = str(getattr(manifest, "trust_level", "community")).lower()
            trust_ok = trust_order.get(trust_level, 0) >= min_rank
            allowlisted = not allowlist or plugin_id in allowlist
            enabled = bool(getattr(manifest, "enabled", True))
            plugin_allowed = enabled and trust_ok and allowlisted
            reasons: list[str] = []
            if not enabled:
                reasons.append("disabled")
            if not trust_ok:
                reasons.append("trust_below_policy")
            if not allowlisted:
                reasons.append("not_allowlisted")
            if plugin_allowed:
                allowed_plugins += 1
            else:
                blocked_plugins += 1

            rows.append(
                {
                    "id": plugin_id,
                    "name": str(getattr(manifest, "name", plugin_id)),
                    "enabled": enabled,
                    "trust_level": trust_level,
                    "capabilities": list(getattr(manifest, "capabilities", [])),
                    "allowed": plugin_allowed,
                    "blocked_reasons": reasons,
                    "connectors": [
                        {
                            "id": c.id,
                            "operations": list(getattr(c, "outbound_actions", []) or []),
                            "allowed": plugin_allowed and policy["enable_connector_tools"],
                        }
                        for c in getattr(manifest, "connectors", [])
                    ],
                    "mcp_servers": [
                        {
                            "id": m.id,
                            "operations": list(getattr(m, "operations", []) or []),
                            "allowed": plugin_allowed and policy["enable_mcp_tools"],
                        }
                        for m in getattr(manifest, "mcp_servers", [])
                    ],
                    "actions": [
                        {
                            "id": a.id,
                            "requires_approval": bool(getattr(a, "requires_approval", False)),
                            "allowed": (
                                plugin_allowed
                                and policy["enable_action_tools"]
                                and (
                                    not bool(getattr(a, "requires_approval", False))
                                    or policy["allow_approval_required_actions"]
                                )
                            ),
                        }
                        for a in getattr(manifest, "actions", [])
                    ],
                }
            )

        return {
            "policy": policy,
            "plugins": rows,
            "summary": {
                "loaded_plugins": len(rows),
                "allowed_plugins": allowed_plugins,
                "blocked_plugins": blocked_plugins,
            },
        }

    @app.post("/v1/integrations/custom")
    async def add_custom_integration(req: AddCustomIntegrationRequest) -> dict[str, Any]:
        """Register or update a custom connector/MCP plugin end-to-end.

        Writes a plugin manifest under `.rigovo/plugins/<plugin_id>/plugin.yml`,
        updates `rigovo.yml.plugins` policy/enabled list, and hot-reloads config.
        """
        await asyncio.sleep(0)
        if req.connector is None and req.mcp_server is None:
            raise HTTPException(
                status_code=400,
                detail="Provide at least one integration target: connector or mcp_server.",
            )

        def _slug(value: str, fallback: str) -> str:
            s = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
            return s or fallback

        def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
            return list(dict.fromkeys([*(base or []), *(extra or [])]))

        plugin_id = _slug(req.plugin_id, "custom-plugin")
        trust_level = str(req.trust_level or "verified").strip().lower()
        if trust_level not in {"community", "verified", "internal"}:
            raise HTTPException(
                status_code=400,
                detail="trust_level must be one of: community|verified|internal",
            )

        plugin_root = root / ".rigovo" / "plugins" / plugin_id
        plugin_root.mkdir(parents=True, exist_ok=True)
        manifest_path = plugin_root / "plugin.yml"

        if manifest_path.exists():
            raw_existing = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        else:
            raw_existing = {
                "schema_version": "rigovo.plugin.v1",
                "id": plugin_id,
                "name": req.name.strip() or plugin_id.replace("-", " ").title(),
                "version": "0.1.0",
                "description": req.description.strip(),
                "author": "workspace",
                "enabled": True,
                "trust_level": trust_level,
                "capabilities": [],
                "connectors": [],
                "mcp_servers": [],
                "actions": [],
                "skills": [],
                "hooks": [],
            }

        raw_existing["id"] = plugin_id
        raw_existing["name"] = req.name.strip() or raw_existing.get("name") or plugin_id
        raw_existing["description"] = req.description.strip() or raw_existing.get("description", "")
        raw_existing["enabled"] = bool(req.enable_plugin)
        raw_existing["trust_level"] = trust_level
        raw_existing.setdefault("connectors", [])
        raw_existing.setdefault("mcp_servers", [])
        raw_existing.setdefault("actions", [])
        raw_existing.setdefault("skills", [])
        raw_existing.setdefault("hooks", [])

        created_connector_id = ""
        created_mcp_id = ""

        if req.connector is not None:
            cid = _slug(req.connector.id, "connector")
            created_connector_id = cid
            connectors = list(raw_existing.get("connectors") or [])
            next_connector = {
                "id": cid,
                "provider": (req.connector.provider or cid).strip(),
                "kind": (req.connector.kind or "api").strip(),
                "inbound_events": [
                    e.strip() for e in req.connector.inbound_events if str(e).strip()
                ],
                "outbound_actions": [
                    a.strip() for a in req.connector.outbound_actions if str(a).strip()
                ],
                "config_schema": {},
            }
            replaced = False
            for idx, existing in enumerate(connectors):
                if str(existing.get("id", "")).strip().lower() == cid:
                    connectors[idx] = next_connector
                    replaced = True
                    break
            if not replaced:
                connectors.append(next_connector)
            raw_existing["connectors"] = connectors

        if req.mcp_server is not None:
            mid = _slug(req.mcp_server.id, "mcp")
            created_mcp_id = mid
            mcp_servers = list(raw_existing.get("mcp_servers") or [])
            next_mcp = {
                "id": mid,
                "transport": (req.mcp_server.transport or "stdio").strip(),
                "command": (req.mcp_server.command or "").strip(),
                "args": [a.strip() for a in req.mcp_server.args if str(a).strip()],
                "env": {str(k): str(v) for k, v in (req.mcp_server.env or {}).items()},
                "url": (req.mcp_server.url or "").strip(),
                "operations": [o.strip() for o in req.mcp_server.operations if str(o).strip()],
            }
            replaced = False
            for idx, existing in enumerate(mcp_servers):
                if str(existing.get("id", "")).strip().lower() == mid:
                    mcp_servers[idx] = next_mcp
                    replaced = True
                    break
            if not replaced:
                mcp_servers.append(next_mcp)
            raw_existing["mcp_servers"] = mcp_servers

        caps = set(str(c).strip().lower() for c in (raw_existing.get("capabilities") or []))
        if raw_existing.get("connectors"):
            caps.add("connector")
        if raw_existing.get("mcp_servers"):
            caps.add("mcp")
        raw_existing["capabilities"] = sorted(c for c in caps if c)

        manifest = PluginManifest.model_validate(raw_existing)
        manifest_path.write_text(
            yaml.dump(manifest.model_dump(), default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        yml_path = root / "rigovo.yml"
        yml_data: dict[str, Any] = {}
        if yml_path.exists():
            yml_data = yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}
        plugins_section = yml_data.setdefault("plugins", {})
        if not isinstance(plugins_section, dict):
            plugins_section = {}
            yml_data["plugins"] = plugins_section

        paths = list(plugins_section.get("paths") or [])
        if ".rigovo/plugins" not in paths:
            paths.append(".rigovo/plugins")
        plugins_section["paths"] = paths

        if req.enable_plugin:
            enabled_plugins = set(plugins_section.get("enabled_plugins") or [])
            enabled_plugins.add(plugin_id)
            plugins_section["enabled_plugins"] = sorted(enabled_plugins)

        if req.enable_tools and req.connector is not None:
            plugins_section["enable_connector_tools"] = True
        if req.enable_tools and req.mcp_server is not None:
            plugins_section["enable_mcp_tools"] = True

        allowed_plugin_ids = list(plugins_section.get("allowed_plugin_ids") or [])
        if allowed_plugin_ids:
            plugins_section["allowed_plugin_ids"] = _merge_unique(allowed_plugin_ids, [plugin_id])

        if req.allow_operations and req.connector is not None:
            plugins_section["allowed_connector_operations"] = _merge_unique(
                list(plugins_section.get("allowed_connector_operations") or []),
                [a.strip() for a in req.connector.outbound_actions if str(a).strip()],
            )
        if req.allow_operations and req.mcp_server is not None:
            plugins_section["allowed_mcp_operations"] = _merge_unique(
                list(plugins_section.get("allowed_mcp_operations") or []),
                [o.strip() for o in req.mcp_server.operations if str(o).strip()],
            )

        yml_path.write_text(
            yaml.dump(yml_data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        try:
            container.reload_config()
        except Exception as exc:
            logger.warning("Config reload failed after custom integration add: %s", exc)

        return {
            "status": "ok",
            "plugin_id": plugin_id,
            "connector_id": created_connector_id,
            "mcp_server_id": created_mcp_id,
            "manifest_path": str(manifest_path.relative_to(root)),
        }

    @app.post("/v1/integrations/github/install")
    async def install_github_integration(req: GitHubInstallRequest) -> dict[str, Any]:
        """Install plugin manifest directly from a GitHub repository URL."""
        await asyncio.sleep(0)

        def _slug(value: str, fallback: str) -> str:
            s = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
            return s or fallback

        def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
            return list(dict.fromkeys([*(base or []), *(extra or [])]))

        parsed = urlparse(req.github_url.strip())
        if parsed.scheme not in {"https", "http"} or parsed.netloc.lower() not in {
            "github.com",
            "www.github.com",
        }:
            raise HTTPException(
                status_code=400, detail="github_url must be a valid github.com URL."
            )
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise HTTPException(status_code=400, detail="github_url must include owner/repo.")
        owner, repo = parts[0], parts[1].removesuffix(".git")
        if not owner or not repo:
            raise HTTPException(status_code=400, detail="Invalid owner/repo in github_url.")

        ref = (req.ref or "main").strip() or "main"
        candidates = [
            "plugin.yml",
            "plugin.yaml",
            "plugin.json",
            "manifest.yml",
            "manifest.yaml",
            "manifest.json",
        ]
        manifest_raw: dict[str, Any] | None = None
        async with httpx.AsyncClient(timeout=8.0) as client:
            for candidate in candidates:
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{candidate}"
                try:
                    resp = await client.get(raw_url)
                except Exception:
                    continue
                if resp.status_code != 200 or not resp.text.strip():
                    continue
                try:
                    if candidate.endswith(".json"):
                        payload = json.loads(resp.text)
                    else:
                        payload = yaml.safe_load(resp.text) or {}
                except Exception:
                    continue
                if isinstance(payload, dict):
                    manifest_raw = payload
                    break
        if manifest_raw is None:
            raise HTTPException(
                status_code=404,
                detail="No plugin manifest found in repository root (plugin.yml/plugin.json).",
            )

        manifest = PluginManifest.model_validate(manifest_raw)
        plugin_id = _slug(req.plugin_id or manifest.id, "github-plugin")
        manifest.id = plugin_id
        if not manifest.name:
            manifest.name = plugin_id

        plugin_root = root / ".rigovo" / "plugins" / plugin_id
        plugin_root.mkdir(parents=True, exist_ok=True)
        manifest_path = plugin_root / "plugin.yml"
        manifest_path.write_text(
            yaml.dump(manifest.model_dump(), default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        yml_path = root / "rigovo.yml"
        yml_data: dict[str, Any] = {}
        if yml_path.exists():
            yml_data = yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}
        plugins_section = yml_data.setdefault("plugins", {})
        if not isinstance(plugins_section, dict):
            plugins_section = {}
            yml_data["plugins"] = plugins_section

        paths = list(plugins_section.get("paths") or [])
        if ".rigovo/plugins" not in paths:
            paths.append(".rigovo/plugins")
        plugins_section["paths"] = paths

        if req.enable_plugin:
            enabled_plugins = set(plugins_section.get("enabled_plugins") or [])
            enabled_plugins.add(plugin_id)
            plugins_section["enabled_plugins"] = sorted(enabled_plugins)

        connector_ops: list[str] = []
        mcp_ops: list[str] = []
        action_ops: list[str] = []
        if req.enable_tools:
            if manifest.connectors:
                plugins_section["enable_connector_tools"] = True
                for c in manifest.connectors:
                    connector_ops.extend(
                        [str(a).strip() for a in (c.outbound_actions or []) if str(a).strip()]
                    )
            if manifest.mcp_servers:
                plugins_section["enable_mcp_tools"] = True
                for m in manifest.mcp_servers:
                    mcp_ops.extend([str(o).strip() for o in (m.operations or []) if str(o).strip()])
            if manifest.actions:
                plugins_section["enable_action_tools"] = True
                for a in manifest.actions:
                    action_ops.append(str(a.id).strip())

        allowed_plugin_ids = list(plugins_section.get("allowed_plugin_ids") or [])
        if allowed_plugin_ids:
            plugins_section["allowed_plugin_ids"] = _merge_unique(allowed_plugin_ids, [plugin_id])

        if req.allow_operations:
            plugins_section["allowed_connector_operations"] = _merge_unique(
                list(plugins_section.get("allowed_connector_operations") or []),
                connector_ops,
            )
            plugins_section["allowed_mcp_operations"] = _merge_unique(
                list(plugins_section.get("allowed_mcp_operations") or []),
                mcp_ops,
            )
            plugins_section["allowed_action_operations"] = _merge_unique(
                list(plugins_section.get("allowed_action_operations") or []),
                action_ops,
            )

        yml_path.write_text(
            yaml.dump(yml_data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        try:
            container.reload_config()
        except Exception as exc:
            logger.warning("Config reload failed after GitHub integration install: %s", exc)

        return {
            "status": "ok",
            "source": "github",
            "github_repo": f"{owner}/{repo}",
            "ref": ref,
            "plugin_id": plugin_id,
            "manifest_path": str(manifest_path.relative_to(root)),
        }

    @app.get("/v1/integrations/marketplace/catalog")
    async def integrations_marketplace_catalog() -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"items": list(_MARKETPLACE_INTEGRATIONS)}

    @app.post("/v1/integrations/marketplace/install")
    async def install_marketplace_integration(req: MarketplaceInstallRequest) -> dict[str, Any]:
        await asyncio.sleep(0)
        selected = next(
            (item for item in _MARKETPLACE_INTEGRATIONS if item.get("id") == req.integration_id),
            None,
        )
        if not selected:
            raise HTTPException(status_code=404, detail="Marketplace integration not found.")

        derived_plugin_id = req.plugin_id or f"market-{req.integration_id}"
        mapped = AddCustomIntegrationRequest(
            plugin_id=derived_plugin_id,
            name=str(selected.get("name", req.integration_id)),
            description=str(selected.get("summary", "")),
            trust_level=str(selected.get("trust_level", "verified")),
            connector=(
                CustomConnectorRequest.model_validate(selected["connector"])
                if selected.get("connector")
                else None
            ),
            mcp_server=(
                CustomMCPServerRequest.model_validate(selected["mcp_server"])
                if selected.get("mcp_server")
                else None
            ),
            enable_plugin=req.enable_plugin,
            enable_tools=req.enable_tools,
            allow_operations=req.allow_operations,
        )
        result = await add_custom_integration(mapped)
        result["source"] = "marketplace"
        result["integration_id"] = req.integration_id
        return result

    @app.get("/v1/observability/slo")
    async def observability_slo(
        window_days: int = 7, task_limit: int = 500, audit_limit: int = 2000
    ) -> dict[str, Any]:
        """Aggregate launch SLO metrics from task and audit history."""
        if window_days < 1 or window_days > 90:
            raise HTTPException(status_code=400, detail="window_days must be between 1 and 90")
        task_limit = min(max(task_limit, 25), 5000)
        audit_limit = min(max(audit_limit, 100), 10000)

        cutoff = _now_utc() - timedelta(days=window_days)
        task_repo = SqliteTaskRepository(container.get_db())
        audit_repo = SqliteAuditRepository(container.get_db())

        tasks = await task_repo.list_by_workspace(_workspace_id(), limit=task_limit)
        tasks_window = [
            t for t in tasks if (_to_utc(getattr(t, "created_at", None)) or _now_utc()) >= cutoff
        ]
        total = len(tasks_window)
        completed = sum(1 for t in tasks_window if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in tasks_window if t.status == TaskStatus.FAILED)
        rejected = sum(1 for t in tasks_window if t.status == TaskStatus.REJECTED)
        awaiting_approval = sum(1 for t in tasks_window if t.status == TaskStatus.AWAITING_APPROVAL)
        finished = [
            t
            for t in tasks_window
            if t.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.REJECTED}
        ]

        durations_ms = [
            float(t.duration_ms) for t in finished if int(getattr(t, "duration_ms", 0) or 0) > 0
        ]
        costs = [float(t.total_cost_usd or 0.0) for t in tasks_window]
        tokens = [float(t.total_tokens or 0) for t in tasks_window]

        audits = await audit_repo.list_by_workspace(_workspace_id(), limit=audit_limit)
        audits_window = [
            a for a in audits if (_to_utc(getattr(a, "created_at", None)) or _now_utc()) >= cutoff
        ]
        replan_triggered = sum(1 for a in audits_window if a.action == AuditAction.REPLAN_TRIGGERED)
        replan_failed = sum(1 for a in audits_window if a.action == AuditAction.REPLAN_FAILED)
        approvals_requested = sum(
            1 for a in audits_window if a.action == AuditAction.APPROVAL_REQUESTED
        )
        approvals_granted = sum(
            1 for a in audits_window if a.action == AuditAction.APPROVAL_GRANTED
        )
        approvals_denied = sum(1 for a in audits_window if a.action == AuditAction.APPROVAL_DENIED)
        memory_stored = sum(1 for a in audits_window if a.action == AuditAction.MEMORY_STORED)

        duration_target_ms = int(config.yml.orchestration.timeout_per_agent) * 1000
        slo_met = sum(1 for d in durations_ms if d <= duration_target_ms)

        return {
            "window_days": window_days,
            "window_start_utc": cutoff.isoformat(),
            "window_end_utc": _now_utc().isoformat(),
            "tasks": {
                "total": total,
                "completed": completed,
                "failed": failed,
                "rejected": rejected,
                "awaiting_approval": awaiting_approval,
                "success_rate": _safe_rate(completed, total),
                "failure_rate": _safe_rate(failed, total),
                "approval_pending_rate": _safe_rate(awaiting_approval, total),
            },
            "performance": {
                "duration_target_ms": duration_target_ms,
                "duration_slo_met_rate": _safe_rate(slo_met, len(durations_ms)),
                "duration_ms": {
                    "avg": round(sum(durations_ms) / len(durations_ms), 2) if durations_ms else 0.0,
                    "p50": round(_percentile(durations_ms, 50), 2),
                    "p95": round(_percentile(durations_ms, 95), 2),
                    "p99": round(_percentile(durations_ms, 99), 2),
                    "max": round(max(durations_ms), 2) if durations_ms else 0.0,
                },
                "cost_usd": {
                    "total": round(sum(costs), 4),
                    "avg": round(sum(costs) / len(costs), 4) if costs else 0.0,
                    "p95": round(_percentile(costs, 95), 4),
                },
                "tokens": {
                    "total": int(sum(tokens)),
                    "avg": round(sum(tokens) / len(tokens), 2) if tokens else 0.0,
                    "p95": round(_percentile(tokens, 95), 2),
                },
            },
            "workflow": {
                "replan_triggered": replan_triggered,
                "replan_failed": replan_failed,
                "replan_trigger_rate": _safe_rate(replan_triggered, total),
                "approvals_requested": approvals_requested,
                "approvals_granted": approvals_granted,
                "approvals_denied": approvals_denied,
                "approval_grant_rate": _safe_rate(approvals_granted, approvals_requested),
                "memory_stored_events": memory_stored,
            },
        }

    @app.get("/v1/control/state")
    def get_control_state() -> dict[str, Any]:
        return _read_state().model_dump()

    @app.get("/v1/control/identity")
    def get_identity_status() -> dict[str, Any]:
        state = _read_state()
        settings = _workos_settings(state)
        return {
            "provider": settings["provider"],
            "authMode": state.policy.get("authMode", settings["authMode"]),
            "workosClientId": settings["clientId"],
            "workosOrganizationId": settings["organizationId"],
            "workosEnabled": _workos_enabled(state),
            "workosOrganizationIdConfigured": bool(settings["organizationId"]),
            "workosClientIdConfigured": bool(settings["clientId"]),
            "workosApiKeyConfigured": bool(settings["apiKey"]),
        }

    @app.post("/v1/control/identity")
    def set_identity(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal runtime_workos_api_key
        state = _read_state()
        provider = (
            str(payload.get("provider", state.identity.get("provider", "local"))).strip().lower()
        )
        auth_mode = (
            str(payload.get("authMode", state.policy.get("authMode", "email_only"))).strip().lower()
        )
        workos_client_id = str(
            payload.get("workosClientId", state.identity.get("workosClientId", ""))
        ).strip()
        workos_organization_id = str(
            payload.get("workosOrganizationId", state.identity.get("workosOrganizationId", ""))
        ).strip()
        workos_api_key = str(payload.get("workosApiKey", "")).strip()

        if provider not in {"local", "workos"}:
            raise HTTPException(status_code=400, detail="provider must be local or workos")
        if auth_mode not in {"email_only", "hybrid", "sso_required"}:
            raise HTTPException(status_code=400, detail="invalid authMode")

        state.identity.update(
            {
                "provider": provider,
                "authMode": auth_mode,
                "workosClientId": workos_client_id,
                "workosOrganizationId": workos_organization_id,
            }
        )
        state.policy["authMode"] = auth_mode

        # Persist identity runtime config to encrypted SQLite for restart stability.
        repo = _settings_repo()
        repo.set_many(
            {
                "RIGOVO_IDENTITY_PROVIDER": provider,
                "RIGOVO_AUTH_MODE": auth_mode,
                "WORKOS_CLIENT_ID": workos_client_id,
                "WORKOS_ORGANIZATION_ID": workos_organization_id,
            }
        )
        if workos_api_key:
            runtime_workos_api_key = workos_api_key
            repo.set("WORKOS_API_KEY", workos_api_key)

        config.identity.provider = provider
        config.identity.auth_mode = auth_mode
        config.identity.workos_client_id = workos_client_id
        config.identity.workos_organization_id = workos_organization_id
        if workos_api_key:
            config.identity.workos_api_key = workos_api_key

        _write_state(state)

        return {
            "status": "ok",
            "identity": {
                "provider": provider,
                "authMode": auth_mode,
                "workosClientId": workos_client_id,
                "workosOrganizationId": workos_organization_id,
                "workosEnabled": _workos_enabled(state),
                "workosClientIdConfigured": bool(workos_client_id),
                "workosOrganizationIdConfigured": bool(workos_organization_id),
                "workosApiKeyConfigured": bool(workos_api_key),
            },
        }

    # ── WorkOS AuthKit redirect-based authentication ──────────────────
    #
    # Flow (like Claude Code / gh CLI):
    # 1. GET /v1/auth/url → returns {url} → frontend opens browser
    # 2. User authenticates on WorkOS hosted UI
    # 3. WorkOS redirects to GET /v1/auth/callback?code=xxx&state=yyy
    # 4. Backend exchanges code for user → stores session
    # 5. Frontend polls GET /v1/auth/session → detects signed_in
    #

    @app.get("/v1/auth/url")
    def get_auth_url(request: Request) -> dict[str, str]:
        """Build WorkOS authorization URL. Frontend opens this in system browser.

        The redirect_uri is derived from the incoming request's origin so it
        always matches the actual running server — no env vars that can drift.
        This must match EXACTLY what is configured in the WorkOS dashboard:
        ``http://127.0.0.1:8787/v1/auth/callback``
        """
        settings = _workos_settings()
        client_id = settings["clientId"]
        if not client_id:
            raise HTTPException(
                status_code=400,
                detail="WORKOS_CLIENT_ID not configured. Set it in .env or identity settings.",
            )

        # PKCE: generate code_verifier and code_challenge
        code_verifier = secrets.token_urlsafe(64)
        code_challenge_bytes = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge_b64 = (
            base64.urlsafe_b64encode(code_challenge_bytes).rstrip(b"=").decode("ascii")
        )

        state_token = secrets.token_urlsafe(32)

        # ── Redirect URI — derived from the request, not env vars ──────
        # The canonical redirect URI registered in WorkOS is:
        #   http://127.0.0.1:8787/v1/auth/callback
        #
        # We derive it from the actual request origin so it always matches
        # the running server.  This prevents stale env vars or old processes
        # from sending the wrong redirect_uri (e.g. localhost:3000).
        base_url = str(request.base_url).rstrip("/")
        redirect_uri = f"{base_url}/v1/auth/callback"

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state_token,
            "code_challenge": code_challenge_b64,
            "code_challenge_method": "S256",
            "provider": "authkit",
        }

        org_id = settings["organizationId"]
        if org_id:
            params["organization_id"] = org_id

        # Store pending state for callback verification
        _pending_auth[state_token] = {
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }

        url = f"https://api.workos.com/user_management/authorize?{urlencode(params)}"
        return {"url": url, "state": state_token}

    @app.get("/v1/auth/callback")
    def auth_callback(
        code: str = "", state: str = "", error: str = "", error_description: str = ""
    ) -> HTMLResponse:
        """WorkOS redirects here after authentication. Exchanges code for user."""
        if error:
            return HTMLResponse(
                _auth_result_html(False, f"Authentication failed: {error_description or error}"),
                status_code=400,
            )
        if not code or not state:
            return HTMLResponse(
                _auth_result_html(False, "Missing authorization code or state parameter."),
                status_code=400,
            )

        pending = _pending_auth.pop(state, None)
        if not pending:
            return HTMLResponse(
                _auth_result_html(
                    False, "Invalid or expired state token. Please try signing in again."
                ),
                status_code=400,
            )

        # Exchange authorization code for user via WorkOS API
        settings = _workos_settings()
        client_id = settings["clientId"]
        api_key = settings["apiKey"]

        exchange_payload: dict[str, str] = {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": pending["code_verifier"],
        }
        # PKCE handles auth without a client secret.  Only attach the secret
        # when it has been explicitly set by the user for THIS client ID —
        # a stale key from a previous WorkOS environment causes "Invalid
        # client secret" rejections even though PKCE would succeed without it.
        # Admin-only features (org lookup, invitations) use the key separately.

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    "https://api.workos.com/user_management/authenticate",
                    json=exchange_payload,
                )
            if res.status_code >= 400:
                detail = res.text[:500]
                try:
                    detail = res.json().get("message", detail)
                except (ValueError, TypeError, AttributeError):
                    logger.debug("WorkOS error payload was not JSON-decodable", exc_info=True)
                return HTMLResponse(
                    _auth_result_html(False, f"Code exchange failed: {detail}"),
                    status_code=400,
                )

            auth_data = res.json()
            user = auth_data.get("user", {})
            email = user.get("email", "")
            first_name = user.get("first_name", "")
            last_name = user.get("last_name", "")
            full_name = f"{first_name} {last_name}".strip() or email
            org_id = auth_data.get("organization_id", "")

            # Fetch organization details + user role from WorkOS if org exists
            org_name = ""
            user_role = "admin"  # default for first user
            if org_id and api_key:
                try:
                    with httpx.Client(timeout=10.0) as org_client:
                        # Get organization name
                        org_res = org_client.get(
                            f"https://api.workos.com/organizations/{org_id}",
                            headers={"Authorization": f"Bearer {api_key}"},
                        )
                        if org_res.status_code < 400:
                            org_data = org_res.json()
                            org_name = org_data.get("name", "")

                        # Get user's organization membership (role)
                        workos_user_id = user.get("id", "")
                        if workos_user_id:
                            memberships_res = org_client.get(
                                "https://api.workos.com/user_management/organization_memberships",
                                headers={"Authorization": f"Bearer {api_key}"},
                                params={"user_id": workos_user_id, "organization_id": org_id},
                            )
                            if memberships_res.status_code < 400:
                                memberships = memberships_res.json().get("data", [])
                                if memberships:
                                    role_data = memberships[0].get("role", {})
                                    user_role = (
                                        role_data.get("slug", "admin") if role_data else "admin"
                                    )
                except Exception:
                    logger.warning("Failed to enrich WorkOS org details", exc_info=True)

            # Store session with full identity
            cp_state = _read_state()
            cp_state.auth = {
                "signed_in": True,
                "email": email,
                "full_name": full_name,
                "first_name": first_name,
                "last_name": last_name,
                "workos_user_id": user.get("id", ""),
                "access_token": auth_data.get("access_token", ""),
                "refresh_token": auth_data.get("refresh_token", ""),
                "organization_id": org_id,
                "organization_name": org_name,
                "role": user_role,
                "authentication_method": auth_data.get("authentication_method", ""),
            }

            # Auto-provision workspace from WorkOS org data
            slug = (org_name or email.split("@")[0]).lower().replace(" ", "-")
            slug = "".join(c for c in slug if c.isalnum() or c == "-")
            cp_state.workspace = {
                "workspaceName": org_name or email.split("@")[0].title(),
                "workspaceSlug": slug,
                "adminEmail": email,
                "deploymentMode": "self_hosted",
                "region": "us-east-1",
            }

            _write_state(cp_state)

            return HTMLResponse(_auth_result_html(True, full_name or email))

        except Exception as exc:
            return HTMLResponse(
                _auth_result_html(False, f"Authentication error: {exc}"),
                status_code=500,
            )

    @app.get("/v1/auth/session")
    def get_auth_session() -> dict[str, Any]:
        """Poll this to check if user has completed auth in browser.
        Returns full identity + workspace data so frontend can skip onboarding."""
        cp_state = _read_state()
        auth = cp_state.auth
        ws = cp_state.workspace
        return {
            "signed_in": auth.get("signed_in", False),
            "email": auth.get("email", ""),
            "full_name": auth.get("full_name", ""),
            "first_name": auth.get("first_name", ""),
            "last_name": auth.get("last_name", ""),
            "role": auth.get("role", ""),
            "organization_id": auth.get("organization_id", ""),
            "organization_name": auth.get("organization_name", ""),
            "workspace": {
                "name": ws.get("workspaceName", ""),
                "slug": ws.get("workspaceSlug", ""),
                "admin_email": ws.get("adminEmail", ""),
                "region": ws.get("region", ""),
            },
        }

    @app.post("/v1/auth/logout")
    def logout() -> dict[str, str]:
        cp_state = _read_state()
        cp_state.auth = {"signed_in": False, "email": "", "full_name": ""}
        _write_state(cp_state)
        return {"status": "ok"}

    if test_mode:

        @app.post("/v1/test/session/bootstrap")
        def test_bootstrap_session(req: TestSessionBootstrapRequest) -> dict[str, Any]:
            _require_test_mode()
            cp_state = _read_state()
            cp_state.auth = {
                "signed_in": True,
                "email": req.email,
                "full_name": req.full_name,
                "first_name": req.first_name,
                "last_name": req.last_name,
                "role": req.role,
            }
            cp_state.workspace = {
                "workspaceName": req.workspace_name,
                "workspaceSlug": req.workspace_slug,
                "adminEmail": req.admin_email,
                "deploymentMode": "self_hosted",
                "region": req.region,
            }
            _write_state(cp_state)
            return {"status": "ok", "session": get_auth_session()}

        @app.post("/v1/test/reset")
        def test_reset_state() -> dict[str, str]:
            _require_test_mode()
            _reset_runtime_buffers()
            _reset_persisted_state()
            _write_state(_apply_config_defaults(ControlPlaneState()))
            return {"status": "ok"}

        @app.post("/v1/test/tasks/seed")
        async def test_seed_task(req: TestSeedTaskRequest) -> dict[str, Any]:
            _require_test_mode()
            task = _seed_task_for_test(req.scenario, req.description, req.tier)
            task_repo = SqliteTaskRepository(container.get_db())
            await task_repo.save(task)
            return {
                "status": "ok",
                "task_id": str(task.id),
                "scenario": req.scenario,
                "task_status": task.status.value,
            }

        @app.get("/v1/test/tasks/{task_id}/wait")
        async def test_wait_for_task(
            task_id: str,
            status: str = "",
            timeout_ms: int = 5000,
        ) -> dict[str, Any]:
            _require_test_mode()
            task_repo, _ = await _load_task(task_id)
            deadline = time.monotonic() + max(0.1, timeout_ms / 1000.0)
            expected = status.strip().lower()
            while time.monotonic() <= deadline:
                task = await task_repo.get(UUID(task_id))
                if task is None:
                    raise HTTPException(status_code=404, detail="Task not found")
                current = str(task.status.value if hasattr(task.status, "value") else task.status)
                if not expected or current.lower() == expected:
                    return {
                        "status": "ok",
                        "task_id": task_id,
                        "task_status": current,
                    }
                await asyncio.sleep(0.05)
            task = await task_repo.get(UUID(task_id))
            current = str(task.status.value if hasattr(task.status, "value") else task.status)
            return {
                "status": "timeout",
                "task_id": task_id,
                "task_status": current,
                "expected_status": expected,
            }

    @app.post("/v1/control/workspace")
    def set_workspace(req: WorkspaceRequest) -> dict[str, Any]:
        state = _read_state()
        state.workspace = req.model_dump(by_alias=True)
        _write_state(state)
        return {"status": "ok", "workspace": state.workspace}

    @app.get("/v1/control/personas")
    def get_personas() -> list[dict[str, Any]]:
        return _read_state().personas

    @app.post("/v1/control/personas")
    def set_personas(personas: list[PersonaMember]) -> dict[str, Any]:
        state = _read_state()
        state.personas = [p.model_dump() for p in personas]
        _write_state(state)
        return {"status": "ok", "count": len(state.personas)}

    @app.get("/v1/control/policy")
    def get_policy() -> dict[str, Any]:
        return _read_state().policy

    @app.post("/v1/control/policy")
    def set_policy(req: PolicyRequest) -> dict[str, Any]:
        state = _read_state()
        state.policy = req.model_dump(by_alias=True)
        _write_state(state)
        return {"status": "ok", "policy": state.policy}

    @app.get("/v1/control/connectors")
    def get_connectors() -> list[dict[str, Any]]:
        return _read_state().connectors

    @app.post("/v1/control/connectors")
    def set_connectors(connectors: list[dict[str, Any]]) -> dict[str, Any]:
        state = _read_state()
        state.connectors = connectors
        _write_state(state)
        return {"status": "ok", "count": len(state.connectors)}

    @app.get("/v1/control/invitations")
    def get_invitations() -> list[dict[str, Any]]:
        return _read_state().invitations

    @app.post("/v1/control/invitations")
    def create_invitation(payload: dict[str, Any]) -> dict[str, Any]:
        state = _read_state()
        email = str(payload.get("email", "")).strip().lower()
        if not email:
            raise HTTPException(status_code=400, detail="email is required")

        invitation = {
            "id": str(uuid4()),
            "email": email,
            "role": str(payload.get("role", "viewer")),
            "team": str(payload.get("team", "unassigned")),
            "status": "pending",
            "invitedBy": str(payload.get("invitedBy", "admin")),
            "createdAt": _now_utc().isoformat(),
        }
        workos_result = _create_workos_invitation(state, email=email, role=invitation["role"])
        if workos_result:
            invitation["provider"] = "workos"
            invitation["providerResponse"] = workos_result
        else:
            invitation["provider"] = "local"
        state.invitations.append(invitation)
        _write_state(state)
        return {"status": "ok", "invitation": invitation}

    @app.get("/v1/ui/inbox")
    async def ui_inbox(limit: int = 25) -> list[dict]:
        repo = SqliteTaskRepository(container.get_db())
        tasks = await repo.list_by_workspace(_workspace_id(), limit=limit)
        items = []
        for task in tasks:
            updated = task.completed_at or task.started_at or task.created_at
            # custom_title wins over raw description (set via PATCH /v1/tasks/{id}/rename)
            display_title = getattr(task, "custom_title", None) or task.description
            workspace_path = getattr(task, "workspace_path", None) or ""
            workspace_label = getattr(task, "workspace_label", None) or ""
            # Derive label from path basename if not explicitly set
            if workspace_path and not workspace_label:
                import os

                workspace_label = os.path.basename(workspace_path.rstrip("/\\"))
            items.append(
                {
                    "id": str(task.id),
                    "title": display_title,
                    "source": "rigovo",
                    "tier": _tier_from_task(task),
                    "status": task.status.value,
                    "team": str(task.team_id)[:8] if task.team_id else "unassigned",
                    "updatedAt": _relative(updated),
                    "workspacePath": workspace_path,
                    "workspaceLabel": workspace_label,
                }
            )
        return items

    @app.patch("/v1/tasks/{task_id}/rename")
    async def rename_task(task_id: str, req: RenameTaskRequest) -> dict[str, str]:
        """Set a custom display title for a task (shown in sidebar, overrides description)."""
        title = req.title.strip()[:200]
        if not title:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="title cannot be empty")
        db = container.get_db()
        db.execute(
            "UPDATE tasks SET custom_title = ? WHERE id = ?",
            (title, task_id),
        )
        db.commit()
        return {"status": "ok", "task_id": task_id, "title": title}

    @app.get("/v1/ui/approvals")
    async def ui_approvals(limit: int = 25) -> list[dict]:
        items: list[dict] = []

        # ── 1. Blocking approval requests (tier="approve") ────────────────
        task_repo = SqliteTaskRepository(container.get_db())
        tasks = await task_repo.list_by_workspace(_workspace_id(), limit=limit)
        pending = [t for t in tasks if t.status == TaskStatus.AWAITING_APPROVAL]
        for t in pending:
            items.append(
                {
                    "id": f"apv_{str(t.id)[:8]}",
                    "taskId": str(t.id),
                    "summary": t.approval_data.get("summary", "Pending human approval"),
                    "tier": "approve",
                    "requestedBy": "master-agent",
                    "age": _relative(t.started_at or t.created_at),
                }
            )

        # ── 2. Non-blocking gate notifications (tier="notify") ───────────
        # Show the most recent GATE_NOTIFICATION audit entries as info cards.
        try:
            audit_repo = SqliteAuditRepository(container.get_db())
            all_entries = await audit_repo.list_by_workspace(_workspace_id(), limit=100)
            notify_entries = [e for e in all_entries if e.action == AuditAction.GATE_NOTIFICATION][
                :limit
            ]
            for e in notify_entries:
                items.append(
                    {
                        "id": f"ntf_{str(e.id)[:8]}",
                        "taskId": str(e.task_id) if e.task_id else "",
                        "summary": e.summary or "Gate passed (notify tier)",
                        "tier": "notify",
                        "requestedBy": "master-agent",
                        "age": _relative(e.created_at),
                    }
                )
        except Exception:
            pass  # audit log query failure must not break approve items

        return items

    @app.get("/v1/ui/workforce")
    def ui_workforce() -> list[dict]:
        rows: list[dict] = []
        roles = ["planner", "coder", "reviewer", "qa", "devops", "sre", "lead"]
        for team_name, team_cfg in container.config.yml.teams.items():
            if not team_cfg.enabled:
                continue
            row = {"team": team_name}
            for role in roles:
                override = team_cfg.agents.get(role)
                row[role] = override.model if (override and override.model) else f"default:{role}"
            rows.append(row)
        return rows

    @app.get("/v1/ui/events")
    async def ui_events(limit: int = 50) -> list[dict]:
        repo = SqliteAuditRepository(container.get_db())
        entries = await repo.list_by_workspace(_workspace_id(), limit=limit)
        return [
            {
                "id": str(e.id),
                "time": e.created_at.strftime("%H:%M:%S"),
                "event": e.action.value,
                "details": e.summary,
            }
            for e in entries
        ]

    # ---- Project management ----

    @app.get("/v1/projects")
    def list_projects() -> list[dict]:
        """List registered projects."""
        state = _read_state()
        return state.projects if hasattr(state, "projects") else []

    @app.post("/v1/projects")
    def register_project(req: RegisterProjectRequest) -> dict:
        """Register a project folder for task execution."""
        import os

        project_path = req.path
        if not os.path.isdir(project_path):
            raise HTTPException(status_code=400, detail=f"Directory not found: {project_path}")

        # Detect project name from folder name if not provided
        name = req.name.strip() or os.path.basename(project_path)

        # Detect language/framework from project files
        language = "unknown"
        framework = ""
        if os.path.exists(os.path.join(project_path, "package.json")):
            language = "typescript"
            if os.path.exists(os.path.join(project_path, "next.config.js")) or os.path.exists(
                os.path.join(project_path, "next.config.mjs")
            ):
                framework = "nextjs"
            elif os.path.exists(os.path.join(project_path, "vite.config.ts")):
                framework = "vite"
        elif os.path.exists(os.path.join(project_path, "pyproject.toml")) or os.path.exists(
            os.path.join(project_path, "setup.py")
        ):
            language = "python"
            if os.path.exists(os.path.join(project_path, "manage.py")):
                framework = "django"
        elif os.path.exists(os.path.join(project_path, "Cargo.toml")):
            language = "rust"
        elif os.path.exists(os.path.join(project_path, "go.mod")):
            language = "go"

        project = {
            "id": str(uuid4()),
            "name": name,
            "path": project_path,
            "language": language,
            "framework": framework,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        state = _read_state()
        if not hasattr(state, "projects"):
            state.__dict__["projects"] = []
        # Avoid duplicates by path
        existing_paths = [p["path"] for p in state.__dict__.get("projects", [])]
        if project_path not in existing_paths:
            state.__dict__.setdefault("projects", []).append(project)
            _write_state(state)

        return project

    @app.delete("/v1/projects/{project_id}")
    def remove_project(project_id: str) -> dict:
        """Remove a registered project."""
        state = _read_state()
        projects = state.__dict__.get("projects", [])
        state.__dict__["projects"] = [p for p in projects if p.get("id") != project_id]
        _write_state(state)
        return {"status": "removed", "project_id": project_id}

    # ---- Task detail ----

    @app.get("/v1/tasks/{task_id}/detail")
    async def get_task_detail(task_id: str) -> dict:
        """Get full task detail with steps, diffs, gate results, and costs."""
        task_repo = SqliteTaskRepository(container.get_db())
        try:
            task = await task_repo.get(UUID(task_id))
        except Exception:
            raise HTTPException(status_code=404, detail="Task not found") from None
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        # --- Priority 1: Live agent progress (for running tasks) ---
        live_steps = _live_agent_progress.get(task_id, {})
        steps = []

        if live_steps:
            # Task is actively running — return live tracked steps
            steps = list(live_steps.values())

        # --- Priority 2: Persisted pipeline_steps (for completed tasks) ---
        if not steps and task.pipeline_steps:
            for ps in task.pipeline_steps:
                # Prefer structured gate_violations (Phase 8) over legacy gate_passed scalar
                gate_results = []
                if ps.gate_violations:
                    gate_results = list(ps.gate_violations)
                elif ps.gate_passed is not None:
                    gate_results.append(
                        {
                            "gate": "rigour",
                            "passed": ps.gate_passed,
                            "message": f"Score: {ps.gate_score:.1f}" if ps.gate_score else "",
                            "severity": "info" if ps.gate_passed else "error",
                        }
                    )
                steps.append(
                    {
                        "agent": ps.agent_role,
                        "agent_name": ps.agent_name,
                        "status": _normalize_step_status(ps.status),
                        "started_at": ps.started_at.isoformat() if ps.started_at else None,
                        "completed_at": ps.completed_at.isoformat() if ps.completed_at else None,
                        "output": ps.summary,
                        "files_changed": _filter_user_files(ps.files_changed or []),
                        "input_tokens": ps.input_tokens,
                        "output_tokens": ps.output_tokens,
                        "tokens": ps.total_tokens,
                        "cost_usd": ps.cost_usd,
                        "duration_ms": ps.duration_ms,
                        "cached_input_tokens": getattr(ps, "cached_input_tokens", 0),
                        "cache_write_tokens": getattr(ps, "cache_write_tokens", 0),
                        "cache_source": getattr(ps, "cache_source", "none"),
                        "cache_saved_tokens": getattr(ps, "cache_saved_tokens", 0),
                        "cache_saved_cost_usd": getattr(ps, "cache_saved_cost_usd", 0.0),
                        "gate_results": gate_results,
                        "execution_log": ps.execution_log or [],
                        "execution_verified": ps.execution_verified,
                    }
                )
        elif steps:
            # Normalize live-step status values for UI consistency.
            for step in steps:
                if isinstance(step, dict):
                    step["status"] = _normalize_step_status(str(step.get("status", "")))

        # Canonicalize step identity at the bridge boundary:
        # one stable schema for UI consumers.
        for step in steps:
            if not isinstance(step, dict):
                continue
            role_key, instance_id, label = _canonical_agent_identity(
                str(step.get("agent", "")),
                str(step.get("agent_name", "") or ""),
            )
            step["agent"] = instance_id
            step["agent_role"] = role_key
            step["agent_instance"] = instance_id
            step["agent_name"] = label

        # Cost info
        cost = None
        try:
            from rigovo.infrastructure.persistence.sqlite_cost_repo import SqliteCostRepository

            cost_repo = SqliteCostRepository(container.get_db())
            entries = await cost_repo.list_by_task(task.id)
            if entries:
                total_tokens = sum(e.total_tokens for e in entries)
                total_cost = sum(e.cost_usd for e in entries)
                cost = {"total_tokens": total_tokens, "total_cost_usd": round(total_cost, 4)}
        except Exception:
            logger.warning("Unable to load cost details for task %s", task_id, exc_info=True)

        # Compute confidence score from pipeline steps
        confidence_score = _compute_confidence_score(task.pipeline_steps or [])

        # Resolve task_type: DB first, then live classification cache, then "unclassified"
        resolved_task_type: str = "unclassified"
        resolved_complexity: str | None = None
        planned_roles: list[str] = []
        live_cls = _live_task_classification.get(task_id)
        task_is_active = task.status in {
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.AWAITING_APPROVAL,
            TaskStatus.CLASSIFYING,
            TaskStatus.ROUTING,
            TaskStatus.ASSEMBLING,
            TaskStatus.QUALITY_CHECK,
        }
        if live_cls and task_is_active:
            resolved_task_type = live_cls.get(
                "task_type",
                (
                    str(task.task_type.value)
                    if task.task_type and hasattr(task.task_type, "value")
                    else str(task.task_type or "unclassified")
                ),
            )
            resolved_complexity = live_cls.get(
                "complexity",
                task.complexity.value if task.complexity else None,
            )
        elif task.task_type:
            resolved_task_type = (
                str(task.task_type.value)
                if hasattr(task.task_type, "value")
                else str(task.task_type)
            )
            resolved_complexity = task.complexity.value if task.complexity else None
        else:
            if live_cls:
                resolved_task_type = live_cls.get("task_type", "unclassified")
                resolved_complexity = live_cls.get("complexity")
        execution_dag: dict[str, list[str]] = {}
        if live_cls:
            raw_instances = live_cls.get("agent_instances", [])
            if isinstance(raw_instances, list):
                for inst in raw_instances:
                    if not isinstance(inst, dict):
                        continue
                    role = str(inst.get("role", "")).strip().lower()
                    if role:
                        canonical_role, _, _ = _canonical_agent_identity(role, "")
                        if canonical_role and canonical_role not in planned_roles:
                            planned_roles.append(canonical_role)
            raw_dag = live_cls.get("execution_dag", {})
            if isinstance(raw_dag, dict):
                execution_dag = {str(k): [str(d) for d in v] for k, v in raw_dag.items() if isinstance(v, list)}

        # Surface pipeline failure reason (Fix #5)
        error_reason = (
            task.user_feedback if task.status == TaskStatus.FAILED and task.user_feedback else None
        )

        all_gate_results = [
            g
            for s in steps
            if isinstance(s, dict)
            for g in (s.get("gate_results") or [])
            if isinstance(g, dict)
        ]
        gates_total = len(all_gate_results)
        gates_failed = sum(1 for g in all_gate_results if not bool(g.get("passed", False)))
        completed_roles = {
            str(s.get("agent_role", "")).strip().lower()
            for s in steps
            if isinstance(s, dict) and str(s.get("status", "")) == "complete"
        }
        preferred_role_order = [
            "planner",
            "coder",
            "reviewer",
            "security",
            "qa",
            "devops",
            "sre",
            "lead",
        ]
        next_expected_role = next(
            (r for r in preferred_role_order if r in planned_roles and r not in completed_roles),
            None,
        )
        running_step = next(
            (s for s in steps if isinstance(s, dict) and str(s.get("status", "")) == "running"),
            None,
        )
        token_approval_requested = 0
        token_approval_granted = 0
        token_approval_denied = 0
        token_approval_pending = False
        if task.status == TaskStatus.FAILED:
            next_expected_reason = None
        elif running_step is not None:
            next_expected_reason = "awaiting current execution"
        elif gates_failed > 0:
            next_expected_reason = "awaiting gate remediation"
        else:
            next_expected_reason = "queued by planner sequence"

        collab_stored = (task.approval_data or {}).get("collaboration", {})
        collab_events = collab_stored.get("events", []) if isinstance(collab_stored, dict) else []
        if not isinstance(collab_events, list):
            collab_events = []
        live_events = _live_task_events.get(task_id, [])
        merged_events = [*collab_events, *(live_events if isinstance(live_events, list) else [])]
        token_approval_requested = sum(
            1
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", "")) == "approval_requested"
            and str(e.get("checkpoint", "")) == "token_budget_exceeded"
        )
        token_approval_granted = sum(
            1
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", "")) == "approval_granted"
            and str(e.get("checkpoint", "")) == "token_budget_exceeded"
        )
        token_approval_denied = sum(
            1
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", "")) == "approval_denied"
            and str(e.get("checkpoint", "")) == "token_budget_exceeded"
        )
        token_approval_pending = token_approval_requested > (
            token_approval_granted + token_approval_denied
        )
        remediation_step = next(
            (
                s
                for s in reversed(steps)
                if isinstance(s, dict)
                and any(
                    isinstance(g, dict) and not bool(g.get("passed", False))
                    for g in (s.get("gate_results") or [])
                )
            ),
            None,
        )
        remediation_role = (
            str(remediation_step.get("agent_role", "") or "").strip().lower()
            if isinstance(remediation_step, dict)
            else ""
        )
        if task.status != TaskStatus.FAILED:
            if token_approval_pending:
                next_expected_reason = "awaiting token extension approval"
            elif gates_failed > 0 and remediation_role:
                next_expected_reason = f"awaiting gate remediation by {remediation_role}"
            if gates_failed > 0 and remediation_role:
                next_expected_role = remediation_role
        consult_count = sum(
            1
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", "")) in {"agent_consult_requested", "agent_consult_completed"}
        )
        debate_count = sum(
            1
            for e in merged_events
            if isinstance(e, dict) and str(e.get("type", "")) in {"debate_round", "feedback_loop"}
        )
        cache_hits_exact = sum(
            1
            for e in merged_events
            if isinstance(e, dict)
            and (
                str(e.get("type", "")) == "artifact_cache_hit"
                or (
                    str(e.get("type", "")) == "cache_hit"
                    and str(e.get("cache_source", "") or "") == "rigovo_exact"
                )
            )
        )
        cache_hits_semantic = sum(
            1
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", "")) == "cache_hit"
            and str(e.get("cache_source", "") or "") == "rigovo_semantic"
        )
        cache_lookups = sum(
            1
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", ""))
            in {
                "cache_hit",
                "cache_miss",
                "artifact_cache_hit",
                "artifact_cache_miss",
            }
        )
        cache_saved_tokens = sum(
            int(s.get("cache_saved_tokens", 0) or 0) for s in steps if isinstance(s, dict)
        )
        cache_saved_tokens += sum(
            int(e.get("saved_tokens", 0) or 0)
            for e in merged_events
            if isinstance(e, dict) and str(e.get("type", "")) == "cache_hit"
        )
        cache_saved_cost_usd = round(
            sum(
                float(s.get("cache_saved_cost_usd", 0.0) or 0.0)
                for s in steps
                if isinstance(s, dict)
            ),
            6,
        )
        provider_cached_input_tokens = sum(
            int(s.get("cached_input_tokens", 0) or 0) for s in steps if isinstance(s, dict)
        )
        soft_extensions_from_events = sum(
            1
            for e in merged_events
            if isinstance(e, dict) and str(e.get("type", "")) == "budget_soft_extension_applied"
        )
        auto_compactions_from_events = sum(
            1
            for e in merged_events
            if isinstance(e, dict) and str(e.get("type", "")) == "auto_compaction_applied"
        )
        auto_approved_extensions = sum(
            1
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", "")) == "approval_granted"
            and str(e.get("checkpoint", "")) == "token_budget_exceeded"
            and "auto-approved" in str(e.get("feedback", "")).lower()
        )
        remediation_step = next(
            (
                s
                for s in reversed(steps)
                if isinstance(s, dict)
                and any(
                    isinstance(g, dict) and not bool(g.get("passed", False))
                    for g in (s.get("gate_results") or [])
                )
            ),
            None,
        )
        remediation_role = (
            str(remediation_step.get("agent_role", "") or "").strip().lower()
            if isinstance(remediation_step, dict)
            else ""
        )
        remediation_failed_gates = (
            sum(
                1
                for g in (remediation_step.get("gate_results") or [])
                if isinstance(g, dict) and not bool(g.get("passed", False))
            )
            if isinstance(remediation_step, dict)
            else 0
        )
        latest_fix_packet = next(
            (
                e
                for e in reversed(merged_events)
                if isinstance(e, dict) and str(e.get("type", "")) == "fix_packet_created"
            ),
            None,
        )
        latest_downstream_lock = next(
            (
                e
                for e in reversed(merged_events)
                if isinstance(e, dict) and str(e.get("type", "")) == "downstream_locked"
            ),
            None,
        )
        supervisory_decisions = [
            e
            for e in merged_events
            if isinstance(e, dict) and str(e.get("type", "")).startswith("master_")
        ][-20:]
        risk_action_queue = [
            e
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", ""))
            in {
                "risk_action_evaluated",
                "approval_required",
                "approval_granted",
                "approval_denied",
                "master_risk_escalation",
            }
        ][-20:]
        required_approval_actions = [
            e for e in risk_action_queue if str(e.get("type", "")) == "approval_required"
        ][-20:]
        spawn_history = [
            e
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", ""))
            in {"spawn_requested", "spawn_started", "spawn_completed", "subtask_spawned"}
        ][-20:]
        debate_history = [
            e
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", "")) in {"debate_round", "debate_adjudicated"}
        ][-20:]
        active_consultations = [
            e
            for e in merged_events
            if isinstance(e, dict)
            and str(e.get("type", ""))
            in {"agent_consult_requested", "agent_consult_completed", "consultation_visible"}
        ][-20:]

        total_tokens = int((cost or {}).get("total_tokens") or task.total_tokens or 0)
        total_cost_usd = float((cost or {}).get("total_cost_usd") or task.total_cost_usd or 0.0)
        elapsed_ms = None
        if task.started_at:
            end_ts = task.completed_at or datetime.utcnow()
            elapsed_ms = max(0, int((end_ts - task.started_at).total_seconds() * 1000))
        now_utc = datetime.utcnow()
        agent_execution_ms = 0
        for s in steps:
            if not isinstance(s, dict):
                continue
            dur = s.get("duration_ms")
            if isinstance(dur, (int, float)) and int(dur) > 0:
                agent_execution_ms += int(dur)
                continue
            status_val = str(s.get("status", "")).strip().lower()
            started_raw = s.get("started_at")
            if status_val == "running" and isinstance(started_raw, str) and started_raw:
                try:
                    start_dt = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
                    if start_dt.tzinfo is not None:
                        start_dt = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    agent_execution_ms += max(0, int((now_utc - start_dt).total_seconds() * 1000))
                except Exception:
                    continue
        if elapsed_ms is None:
            master_waiting_ms = 0
            master_thinking_ms = 0
        else:
            master_waiting_ms = max(0, min(agent_execution_ms, elapsed_ms))
            master_thinking_ms = max(0, elapsed_ms - master_waiting_ms)

        raw_baseline = (task.approval_data or {}).get("baseline_tokens")
        try:
            baseline_tokens = int(raw_baseline) if raw_baseline is not None else None
        except Exception:
            baseline_tokens = None
        if baseline_tokens is not None and baseline_tokens <= 0:
            baseline_tokens = None
        adaptive_runtime = (task.approval_data or {}).get("adaptive_runtime", {})
        if not isinstance(adaptive_runtime, dict):
            adaptive_runtime = {}
        checkpoint_contract = (task.approval_data or {}).get("checkpoint_contract", {})
        if not isinstance(checkpoint_contract, dict):
            checkpoint_contract = {}

        workspace_root = str(
            (live_cls or {}).get("workspace_root")
            or (task.approval_data or {}).get("workspace_root")
            or task.workspace_path
            or ""
        )
        target_root = str(
            (live_cls or {}).get("target_root")
            or (task.approval_data or {}).get("target_root")
            or workspace_root
        )
        target_mode = str(
            (live_cls or {}).get("target_mode")
            or (task.approval_data or {}).get("target_mode")
            or ""
        )

        ui_summary = {
            "tier_requested": str(getattr(task, "tier", "auto") or "auto"),
            "tier_effective": _tier_from_task(task),
            "tokens_total": total_tokens,
            "cost_total_usd": total_cost_usd,
            "elapsed_ms": elapsed_ms,
            "master_thinking_ms": master_thinking_ms,
            "master_waiting_ms": master_waiting_ms,
            "baseline_tokens": baseline_tokens,
            "saved_pct": (
                round(max(0.0, (baseline_tokens - total_tokens) / baseline_tokens * 100.0), 2)
                if baseline_tokens
                else None
            ),
            "consult_count": consult_count,
            "debate_count": debate_count,
            "cache_hits_exact": cache_hits_exact,
            "cache_hits_semantic": cache_hits_semantic,
            "cache_hit_rate": (
                round(((cache_hits_exact + cache_hits_semantic) / cache_lookups) * 100.0, 2)
                if cache_lookups > 0
                else None
            ),
            "cache_saved_tokens": cache_saved_tokens,
            "cache_saved_cost_usd": cache_saved_cost_usd,
            "provider_cached_input_tokens": provider_cached_input_tokens,
            "budget_soft_extensions_used": max(
                int(adaptive_runtime.get("budget_soft_extensions_used", 0) or 0),
                int(soft_extensions_from_events),
            ),
            "budget_auto_compactions": max(
                int(adaptive_runtime.get("budget_auto_compactions", 0) or 0),
                int(auto_compactions_from_events),
            ),
            "budget_token_approval_requested": int(token_approval_requested),
            "budget_token_approval_granted": int(token_approval_granted),
            "budget_token_approval_denied": int(token_approval_denied),
            "budget_token_approval_pending": bool(token_approval_pending),
            "budget_auto_approved_extensions": int(auto_approved_extensions),
            "checkpoint_policy_hash": str(checkpoint_contract.get("policy_hash", "")),
            "checkpoint_memory_snapshot_hash": str(
                checkpoint_contract.get("memory_snapshot_hash", "")
            ),
            "gates_total": gates_total,
            "gates_failed": gates_failed,
            "remediation_pending": bool(gates_failed > 0),
            "remediation_role": remediation_role or None,
            "remediation_role_name": (
                _canonical_agent_identity(remediation_role, "")[2] if remediation_role else None
            ),
            "remediation_failed_gates": int(remediation_failed_gates),
            "next_expected_role": next_expected_role,
            "next_expected_role_name": (
                _canonical_agent_identity(next_expected_role or "", "")[2]
                if next_expected_role
                else None
            ),
            "next_expected_reason": next_expected_reason,
            "workspace_root": workspace_root or None,
            "target_root": target_root or None,
            "target_mode": target_mode or None,
        }
        learning_runtime = (task.approval_data or {}).get("learning_runtime", {})
        if not isinstance(learning_runtime, dict):
            learning_runtime = {}
        learning_updates = learning_runtime.get("agent_learning_updates", {}) or {}
        if not isinstance(learning_updates, dict):
            learning_updates = {}
        behavior_change_audit = learning_runtime.get("behavior_change_audit", []) or []
        if not isinstance(behavior_change_audit, list):
            behavior_change_audit = []
        promotion_records = learning_runtime.get("memory_promotion_records", []) or []
        if not isinstance(promotion_records, list):
            promotion_records = []

        role_learning_metrics: dict[str, dict[str, Any]] = {}
        for role_name, updates in learning_updates.items():
            if not isinstance(updates, list):
                continue
            scores: list[float] = []
            for update in updates:
                if not isinstance(update, dict):
                    continue
                try:
                    scores.append(float(update.get("score", 0.0) or 0.0))
                except (TypeError, ValueError):
                    continue
            role_learning_metrics[str(role_name)] = {
                "update_count": len(updates),
                "top_score": round(max(scores), 3) if scores else 0.0,
                "avg_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
                "behavior_changes": sum(
                    1
                    for item in behavior_change_audit
                    if isinstance(item, dict)
                    and str(item.get("role", "") or "").strip() == str(role_name)
                ),
                "promotions": sum(
                    1
                    for item in promotion_records
                    if isinstance(item, dict)
                    and str(item.get("role", "") or "").strip() == str(role_name)
                ),
            }

        return {
            "id": str(task.id),
            "description": task.description,
            "status": task.status.value,
            "task_type": resolved_task_type,
            "complexity": resolved_complexity,
            "tier": _tier_from_task(task),
            "team": str(task.team_id)[:8] if task.team_id else "unassigned",
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "steps": steps,
            "planned_roles": planned_roles,
            "execution_dag": execution_dag,
            "cost": cost,
            "approval_data": task.approval_data or {},
            "confidence_score": confidence_score,
            "error": error_reason,
            "workspace_root": workspace_root or None,
            "target_root": target_root or None,
            "target_mode": target_mode or None,
            "ui_summary": ui_summary,
            "active_fix_packet": latest_fix_packet or {},
            "downstream_lock_reason": (
                str(latest_downstream_lock.get("reason", "") or "")
                if isinstance(latest_downstream_lock, dict)
                else ""
            ),
            "active_consultations": active_consultations,
            "spawn_history": spawn_history,
            "debate_history": debate_history,
            "supervisory_decisions": supervisory_decisions,
            "risk_action_queue": risk_action_queue,
            "required_approval_actions": required_approval_actions,
            "agent_learning_updates": learning_updates,
            "behavior_change_audit": behavior_change_audit,
            "role_learning_metrics": role_learning_metrics,
        }

    @app.post("/v1/tasks")
    async def create_task(
        req: CreateTaskRequest,
        background_tasks: BackgroundTasks,
    ) -> dict:
        """Create and run a new task from the desktop UI."""
        await asyncio.sleep(0)
        if not req.description.strip():
            raise HTTPException(status_code=400, detail="Task description is required")

        # Pre-flight: verify the default model's API key is configured
        default_model = config.llm.model
        try:
            from rigovo.infrastructure.llm.model_catalog import detect_provider

            provider = detect_provider(default_model)
        except ImportError:
            provider = "anthropic"  # safe default

        if provider != "ollama":
            from rigovo.infrastructure.llm.llm_factory import _PROVIDER_DB_KEY

            db_key = _PROVIDER_DB_KEY.get(provider, "")
            if db_key:
                repo = _settings_repo()
                key_val = repo.get(db_key, "")
                if not key_val:
                    # Also check env/config fallback
                    from rigovo.infrastructure.llm.llm_factory import _PROVIDER_KEY_ATTR

                    attr = _PROVIDER_KEY_ATTR.get(provider, "")
                    env_val = getattr(config.llm, attr, "") if attr else ""
                    if not env_val:
                        raise HTTPException(
                            status_code=400,
                            detail=f"No API key configured for {provider}. "
                            f"Go to Settings → API Keys and add your {provider.title()} key.",
                        )

        task_id = str(uuid4())
        safe_tier = req.tier if req.tier in ("auto", "notify", "approve") else "auto"
        safe_project_id = req.project_id.strip() if req.project_id else ""
        safe_workspace_path = req.workspace_path.strip() if req.workspace_path else ""
        safe_workspace_label = req.workspace_label.strip() if req.workspace_label else ""
        import logging as _logging

        _logging.getLogger("rigovo.audit").info(
            "Task created: id=%s tier=%s project=%s workspace=%r desc=%r",
            task_id,
            safe_tier,
            safe_project_id or "none",
            safe_workspace_path or "none",
            req.description.strip()[:100],
        )
        background_tasks.add_task(
            _resume_task_async,
            task_id,
            req.description.strip(),
            task_id,
            safe_tier,
            safe_project_id,
            safe_workspace_path,
            safe_workspace_label,
        )
        return {
            "status": "created",
            "task_id": task_id,
            "description": req.description.strip(),
            "tier": safe_tier,
        }

    @app.post("/v1/tasks/{task_id}/abort")
    async def abort_task(task_id: str, req: TaskActionRequest) -> dict:
        task_repo, task = await _load_task(task_id)
        reason = req.reason or "Aborted by operator"
        task.fail(reason=reason)
        await task_repo.update_status(task)
        await _append_audit(
            AuditAction.TASK_FAILED,
            task,
            summary=f"Task aborted: {reason}",
            metadata={"source": "api.abort"},
            actor=req.actor,
        )
        return {"status": "aborted", "task_id": task_id}

    @app.post("/v1/tasks/{task_id}/approve")
    async def approve_task(
        task_id: str,
        req: TaskActionRequest,
        background_tasks: BackgroundTasks,
    ) -> dict:
        task_repo, task = await _load_task(task_id)
        task.approve()
        await task_repo.update_status(task)
        await _append_audit(
            AuditAction.APPROVAL_GRANTED,
            task,
            summary="Approval granted via control plane",
            metadata={"source": "api.approve"},
            actor=req.actor,
        )
        # If the graph is blocking on an approval_handler event, unblock it now.
        # This covers the tier="approve" path where the graph is paused inside
        # asyncio.to_thread; /approve both updates DB AND signals the handler.
        if task_id in _approval_events:
            _approval_decisions[task_id] = {"approval_status": "approved", "approval_feedback": ""}
            _approval_events[task_id].set()
        elif req.resume_now:
            # Legacy / tier="auto" path: no blocking handler; restart the graph
            background_tasks.add_task(_resume_task_async, task_id, task.description, task_id)
        return {"status": "approved", "task_id": task_id}

    @app.post("/v1/tasks/{task_id}/deny")
    async def deny_task(task_id: str, req: TaskActionRequest) -> dict:
        """Reject/deny a task at an approval gate.  Transitions task → REJECTED."""
        task_repo, task = await _load_task(task_id)
        feedback = req.reason or "Rejected by operator"
        task.reject(feedback)
        await task_repo.update_status(task)
        await _append_audit(
            AuditAction.APPROVAL_DENIED,
            task,
            summary=f"Approval denied: {feedback}",
            metadata={"source": "api.deny", "feedback": feedback},
            actor=req.actor,
        )
        # Unblock the blocking approval_handler so the graph can route to "rejected"
        if task_id in _approval_events:
            _approval_decisions[task_id] = {
                "approval_status": "rejected",
                "approval_feedback": feedback,
            }
            _approval_events[task_id].set()
        return {"status": "rejected", "task_id": task_id}

    @app.post("/v1/tasks/{task_id}/resume")
    async def resume_task(
        task_id: str,
        req: TaskActionRequest,
        background_tasks: BackgroundTasks,
    ) -> dict:
        _, task = await _load_task(task_id)

        # Guard: don't spawn another run if an in-process execution is actually active.
        active_statuses = (
            TaskStatus.RUNNING,
            TaskStatus.ASSEMBLING,
            TaskStatus.ROUTING,
            TaskStatus.CLASSIFYING,
            TaskStatus.QUALITY_CHECK,
        )
        if task.status in active_statuses:
            if task_id in _active_task_runs:
                return {"status": "already_running", "task_id": task_id}

            live_steps = _live_agent_progress.get(task_id, {})
            has_running_live_step = any(
                isinstance(step, dict) and str(step.get("status", "")) == "running"
                for step in live_steps.values()
            )
            recent_runtime_signal = False
            live_events = _live_task_events.get(task_id, [])
            if isinstance(live_events, list) and live_events:
                now_ts = time.time()
                for ev in reversed(live_events[-25:]):
                    if not isinstance(ev, dict):
                        continue
                    ts = ev.get("created_at")
                    if isinstance(ts, (int, float)) and (now_ts - float(ts)) <= 20:
                        recent_runtime_signal = True
                        break

            if has_running_live_step or recent_runtime_signal:
                return {"status": "already_running", "task_id": task_id}

            # Stale active-status recovery: no in-process runner and no live activity.
            _live_agent_progress.pop(task_id, None)
            _live_task_events.pop(task_id, None)
            _active_task_runs.pop(task_id, None)
            await _append_audit(
                AuditAction.TASK_STARTED,
                task,
                summary="Recovered stale running state before resume",
                metadata={"source": "api.resume", "stale_recovery": True},
                actor=req.actor,
            )

        # Restore the original tier so approval gates behave identically to first run
        restored_tier = getattr(task, "tier", "auto") or "auto"
        restored_project_id = str(task.project_id) if getattr(task, "project_id", None) else ""
        await _append_audit(
            AuditAction.TASK_STARTED,
            task,
            summary="Resume requested via control plane",
            metadata={"source": "api.resume", "tier": restored_tier},
            actor=req.actor,
        )
        background_tasks.add_task(
            _resume_task_async,
            task_id,
            task.description,
            task_id,
            restored_tier,
            restored_project_id,
        )
        return {"status": "resuming", "task_id": task_id}

    # ── Task enrichment endpoints ──────────────────────────────────
    # Richer data for the multi-panel desktop UI.

    @app.get("/v1/tasks/{task_id}/audit")
    async def task_audit(task_id: str, limit: int = 100) -> dict:
        """Audit log entries for a specific task."""
        try:
            audit_repo = SqliteAuditRepository(container.get_db())
            entries = await audit_repo.list_by_task(UUID(task_id), limit=limit)
            return {
                "task_id": task_id,
                "entries": [
                    {
                        "id": str(e.id),
                        "action": e.action.value if hasattr(e.action, "value") else str(e.action),
                        "agent_role": _canonical_agent_identity(e.agent_role or "", "")[0],
                        "agent_name": _canonical_agent_identity(e.agent_role or "", "")[2],
                        "summary": e.summary,
                        "metadata": e.metadata or {},
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in entries
                ],
            }
        except Exception:
            return {"task_id": task_id, "entries": []}

    @app.get("/v1/tasks/{task_id}/collaboration")
    async def task_collaboration(task_id: str) -> dict[str, Any]:
        """Return collaboration timeline: consult, debate, integration, policy interactions."""
        try:
            task_uuid = UUID(task_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid task id") from exc

        task_repo = SqliteTaskRepository(container.get_db())
        task = await task_repo.get(task_uuid)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        stored = (task.approval_data or {}).get("collaboration", {})
        stored_events = stored.get("events", []) if isinstance(stored, dict) else []
        stored_messages = stored.get("messages", []) if isinstance(stored, dict) else []

        live_events = _live_task_events.get(task_id, [])
        merged_events = []
        for ev in [*(stored_events if isinstance(stored_events, list) else []), *live_events]:
            if isinstance(ev, dict):
                ev_type = str(ev.get("type", "")).strip()
                # Backward/forward compatibility:
                # debate loop events are currently emitted as "feedback_loop" in the graph
                # while some UI surfaces expect "debate_round".
                if ev_type == "feedback_loop":
                    normalized = dict(ev)
                    normalized["type"] = "debate_round"
                    normalized.setdefault("from_role", ev.get("source_role"))
                    normalized.setdefault("to_role", ev.get("target_coder"))
                    normalized.setdefault("reviewer_feedback", ev.get("feedback_preview", ""))
                    merged_events.append(normalized)
                else:
                    merged_events.append(ev)

        # Canonicalize role identity in collaboration events for stable UI schema.
        normalized_events: list[dict[str, Any]] = []
        for ev in merged_events:
            if not isinstance(ev, dict):
                continue
            item = dict(ev)
            for key in ("role", "from_role", "to_role", "source_role", "target_coder"):
                raw = str(item.get(key, "") or "").strip()
                if not raw:
                    continue
                canonical_role, _, canonical_name = _canonical_agent_identity(raw, "")
                item[key] = canonical_role
                item[f"{key}_name"] = canonical_name
            normalized_events.append(item)
        merged_events = normalized_events

        def _event_ts(ev: dict[str, Any]) -> float:
            val = ev.get("created_at")
            if isinstance(val, (int, float)):
                return float(val)
            return 0.0

        merged_events = sorted(merged_events, key=_event_ts)[-400:]
        messages = [
            m
            for m in (stored_messages if isinstance(stored_messages, list) else [])
            if isinstance(m, dict)
        ][-400:]
        normalized_messages: list[dict[str, Any]] = []
        for msg in messages:
            item = dict(msg)
            from_role = str(item.get("from_role", "") or "").strip()
            to_role = str(item.get("to_role", "") or "").strip()
            if from_role:
                canonical_role, _, canonical_name = _canonical_agent_identity(from_role, "")
                item["from_role"] = canonical_role
                item["from_role_name"] = canonical_name
            if to_role:
                canonical_role, _, canonical_name = _canonical_agent_identity(to_role, "")
                item["to_role"] = canonical_role
                item["to_role_name"] = canonical_name
            normalized_messages.append(item)
        messages = normalized_messages

        summary = {
            "consult_requests": sum(
                1 for e in merged_events if str(e.get("type", "")) == "agent_consult_requested"
            ),
            "consult_completions": sum(
                1 for e in merged_events if str(e.get("type", "")) == "agent_consult_completed"
            ),
            "debate_rounds": sum(
                1
                for e in merged_events
                if str(e.get("type", "")) in {"debate_round", "feedback_loop"}
            ),
            "integration_invoked": sum(
                1 for e in merged_events if str(e.get("type", "")) == "integration_invoked"
            ),
            "integration_blocked": sum(
                1 for e in merged_events if str(e.get("type", "")) == "integration_blocked"
            ),
            "replan_triggered": sum(
                1 for e in merged_events if str(e.get("type", "")) == "replan_triggered"
            ),
            "replan_failed": sum(
                1 for e in merged_events if str(e.get("type", "")) == "replan_failed"
            ),
            "subtasks_spawned": sum(
                1 for e in merged_events if str(e.get("type", "")) == "subtask_spawned"
            ),
            "subtasks_completed": sum(
                1 for e in merged_events if str(e.get("type", "")) == "subtask_complete"
            ),
            "subtasks_blocked": sum(
                1 for e in merged_events if str(e.get("type", "")) == "subtask_blocked"
            ),
            "consultation_visible": sum(
                1 for e in merged_events if str(e.get("type", "")) == "consultation_visible"
            ),
            "spawn_started": sum(
                1 for e in merged_events if str(e.get("type", "")) == "spawn_started"
            ),
            "spawn_completed": sum(
                1 for e in merged_events if str(e.get("type", "")) == "spawn_completed"
            ),
            "debate_adjudicated": sum(
                1 for e in merged_events if str(e.get("type", "")) == "debate_adjudicated"
            ),
        }

        return {
            "task_id": task_id,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "summary": summary,
            "events": merged_events,
            "messages": messages,
        }

    @app.get("/v1/tasks/{task_id}/governance")
    async def task_governance(task_id: str) -> dict[str, Any]:
        """Governance timeline: policy decisions, approvals, replans, and gate outcomes."""
        try:
            task_uuid = UUID(task_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid task id") from exc

        task_repo = SqliteTaskRepository(container.get_db())
        audit_repo = SqliteAuditRepository(container.get_db())
        task = await task_repo.get(task_uuid)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        audits = await audit_repo.list_by_task(task_uuid, limit=300)
        collab = (task.approval_data or {}).get("collaboration", {})
        events = collab.get("events", []) if isinstance(collab, dict) else []
        if task_id in _live_task_events:
            events = [
                *(events if isinstance(events, list) else []),
                *_live_task_events.get(task_id, []),
            ]

        timeline: list[dict[str, Any]] = []
        for a in audits:
            action = a.action.value if hasattr(a.action, "value") else str(a.action)
            category = "task"
            decision = "info"
            if action in {"approval_requested", "approval_granted", "approval_denied"}:
                category = "approval"
                decision = (
                    "allow"
                    if action == "approval_granted"
                    else ("deny" if action == "approval_denied" else "pending")
                )
            elif action in {"replan_triggered", "replan_failed"}:
                category = "replan"
                decision = "allow" if action == "replan_triggered" else "deny"
            elif action in {"gate_failed", "gate_passed"}:
                category = "quality_gate"
                decision = "deny" if action == "gate_failed" else "allow"
            elif action in {"risk_action_evaluated", "approval_required", "master_risk_escalation"}:
                category = "governance_risk"
                decision = "pending" if action == "approval_required" else "info"
            elif action in {"task_failed", "task_completed"}:
                category = "task"
                decision = "deny" if action == "task_failed" else "allow"

            timeline.append(
                {
                    "ts": a.created_at.isoformat() if a.created_at else None,
                    "category": category,
                    "decision": decision,
                    "action": action,
                    "actor": _canonical_agent_identity(a.agent_role or "system", "")[0],
                    "actor_name": _canonical_agent_identity(a.agent_role or "system", "")[2],
                    "summary": a.summary,
                    "metadata": a.metadata or {},
                    "source": "audit",
                }
            )

        for ev in events if isinstance(events, list) else []:
            if not isinstance(ev, dict):
                continue
            ev_type = str(ev.get("type", "")).strip()
            if ev_type not in {
                "integration_invoked",
                "integration_blocked",
                "replan_triggered",
                "replan_failed",
                "approval_requested",
                "approval_granted",
                "approval_denied",
                "risk_action_evaluated",
                "approval_required",
                "master_risk_escalation",
            }:
                continue
            ts_value = ev.get("created_at")
            ts_iso = None
            if isinstance(ts_value, (int, float)):
                ts_iso = datetime.fromtimestamp(float(ts_value), tz=timezone.utc).isoformat()
            elif isinstance(ts_value, str):
                ts_iso = ts_value

            category = "policy"
            decision = "allow"
            if ev_type in {"integration_blocked", "replan_failed", "approval_denied"}:
                decision = "deny"
            if ev_type == "approval_requested":
                decision = "pending"
                category = "approval"
            elif ev_type.startswith("replan_"):
                category = "replan"
            elif ev_type.startswith("integration_"):
                category = "policy"
            elif ev_type.startswith("approval_"):
                category = "approval"
            elif ev_type in {"risk_action_evaluated", "master_risk_escalation"}:
                category = "governance_risk"
                decision = "info"
            elif ev_type == "approval_required":
                category = "governance_risk"
                decision = "pending"

            summary = ""
            if ev_type == "integration_invoked":
                summary = (
                    f"{ev.get('role', 'agent')} invoked {ev.get('kind', 'integration')}:"
                    f"{ev.get('operation', 'op')}"
                )
            elif ev_type == "integration_blocked":
                summary = (
                    f"{ev.get('role', 'agent')} blocked for {ev.get('kind', 'integration')}:"
                    f"{ev.get('operation', 'op')} ({ev.get('blocked_reason', 'policy')})"
                )
            elif ev_type == "replan_triggered":
                trigger_reason = ev.get("trigger_reason", "policy_replan")
                strategy = ev.get("strategy", "deterministic")
                summary = f"Replan triggered: {trigger_reason} (strategy: {strategy})"
            elif ev_type == "replan_failed":
                trigger_reason = ev.get("trigger_reason", "unknown")
                summary = f"Replan failed: {trigger_reason} - budget exhausted"
            elif ev_type in {
                "risk_action_evaluated",
                "master_risk_escalation",
                "approval_required",
            }:
                summary = str(
                    ev.get("summary")
                    or ev.get("reason")
                    or ev.get("action")
                    or "Governance risk evaluated"
                )
            else:
                summary = ev_type.replace("_", " ")

            timeline.append(
                {
                    "ts": ts_iso,
                    "category": category,
                    "decision": decision,
                    "action": ev_type,
                    "actor": _canonical_agent_identity(
                        str(ev.get("role") or ev.get("from_role") or "system"),
                        "",
                    )[0],
                    "actor_name": _canonical_agent_identity(
                        str(ev.get("role") or ev.get("from_role") or "system"),
                        "",
                    )[2],
                    "summary": summary,
                    "metadata": ev,
                    "source": "event",
                }
            )

        def _sort_key(item: dict[str, Any]) -> str:
            return str(item.get("ts") or "")

        timeline = sorted(timeline, key=_sort_key)[-400:]
        summary = {
            "allow": sum(1 for t in timeline if t.get("decision") == "allow"),
            "deny": sum(1 for t in timeline if t.get("decision") == "deny"),
            "pending": sum(1 for t in timeline if t.get("decision") == "pending"),
            "approval_events": sum(1 for t in timeline if t.get("category") == "approval"),
            "replan_events": sum(1 for t in timeline if t.get("category") == "replan"),
            "policy_events": sum(1 for t in timeline if t.get("category") == "policy"),
            "governance_risk_events": sum(
                1 for t in timeline if t.get("category") == "governance_risk"
            ),
            "quality_gate_events": sum(1 for t in timeline if t.get("category") == "quality_gate"),
        }

        return {
            "task_id": task_id,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "summary": summary,
            "timeline": timeline,
        }

    @app.get("/v1/tasks/{task_id}/costs")
    async def task_costs(task_id: str) -> dict:
        """Per-agent cost breakdown for a task."""
        try:
            from rigovo.infrastructure.persistence.sqlite_cost_repo import SqliteCostRepository

            task_repo = SqliteTaskRepository(container.get_db())
            task = await task_repo.get(UUID(task_id))
            role_by_agent_id: dict[str, str] = {}
            instance_by_agent_id: dict[str, str] = {}
            name_by_agent_id: dict[str, str] = {}
            if task and task.pipeline_steps:
                for ps in task.pipeline_steps:
                    aid = str(getattr(ps, "agent_id", "") or "").strip()
                    raw_role = str(getattr(ps, "agent_role", "") or "").strip()
                    raw_name = str(getattr(ps, "agent_name", "") or "").strip()
                    role, instance, label = _canonical_agent_identity(raw_role, raw_name)
                    if aid and role:
                        role_by_agent_id[aid] = role
                        instance_by_agent_id[aid] = instance
                        name_by_agent_id[aid] = label

            cost_repo = SqliteCostRepository(container.get_db())
            entries = await cost_repo.list_by_task(UUID(task_id))
            per_agent: dict[str, dict] = {}
            total_tokens = 0
            total_cost = 0.0
            for e in entries:
                aid = str(getattr(e, "agent_id", "") or "").strip()
                role = role_by_agent_id.get(aid, "")
                instance = instance_by_agent_id.get(aid, "")
                if not role:
                    fallback = f"agent:{aid[:8]}" if aid else "unknown"
                    role, instance, label = _canonical_agent_identity(fallback, "")
                else:
                    _, instance, label = _canonical_agent_identity(instance or role, "")
                key = instance or role
                if key not in per_agent:
                    per_agent[key] = {
                        "agent_role": role,
                        "agent_instance": instance,
                        "agent_name": name_by_agent_id.get(aid, label),
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cached_input_tokens": 0,
                        "cache_write_tokens": 0,
                        "cache_saved_tokens": 0,
                        "cache_saved_cost_usd": 0.0,
                        "cost_usd": 0.0,
                        "model": "",
                    }
                per_agent[key]["input_tokens"] += e.input_tokens
                per_agent[key]["output_tokens"] += e.output_tokens
                per_agent[key]["cost_usd"] += e.cost_usd
                per_agent[key]["model"] = e.llm_model or per_agent[key]["model"]
                total_tokens += e.total_tokens
                total_cost += e.cost_usd

            # Fallback: when cost_ledger is empty, derive cost from persisted pipeline steps.
            if not entries and task and task.pipeline_steps:
                per_agent = {}
                total_tokens = 0
                total_cost = 0.0
                for ps in task.pipeline_steps:
                    role, instance, label = _canonical_agent_identity(
                        getattr(ps, "agent_role", ""),
                        getattr(ps, "agent_name", ""),
                    )
                    key = instance or role or "unknown"
                    per_agent[key] = {
                        "agent_role": role,
                        "agent_instance": instance,
                        "agent_name": label,
                        "input_tokens": int(getattr(ps, "input_tokens", 0) or 0),
                        "output_tokens": int(getattr(ps, "output_tokens", 0) or 0),
                        "cached_input_tokens": int(getattr(ps, "cached_input_tokens", 0) or 0),
                        "cache_write_tokens": int(getattr(ps, "cache_write_tokens", 0) or 0),
                        "cache_saved_tokens": int(getattr(ps, "cache_saved_tokens", 0) or 0),
                        "cache_saved_cost_usd": float(
                            getattr(ps, "cache_saved_cost_usd", 0.0) or 0.0
                        ),
                        "cost_usd": float(getattr(ps, "cost_usd", 0.0) or 0.0),
                        "model": "",
                    }
                    total_tokens += int(getattr(ps, "total_tokens", 0) or 0)
                    total_cost += float(getattr(ps, "cost_usd", 0.0) or 0.0)

            return {
                "task_id": task_id,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 4),
                "per_agent": per_agent,
            }
        except Exception:
            return {"task_id": task_id, "total_tokens": 0, "total_cost_usd": 0.0, "per_agent": {}}

    @app.get("/v1/tasks/{task_id}/mission")
    async def task_mission(task_id: str) -> dict:
        """Mission-control summary: decisions, policy signals, and trust evidence."""
        try:
            task_uuid = UUID(task_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid task id") from exc

        task_repo = SqliteTaskRepository(container.get_db())
        audit_repo = SqliteAuditRepository(container.get_db())
        task = await task_repo.get(task_uuid)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        audits = await audit_repo.list_by_task(task_uuid, limit=300)
        orchestration = config.yml.orchestration
        plugins = config.yml.plugins

        workflow = {
            "replan_triggered": 0,
            "replan_failed": 0,
            "approvals_requested": 0,
            "approvals_granted": 0,
            "approvals_denied": 0,
            "gate_failed": 0,
            "agent_failed": 0,
            "agent_retried": 0,
        }
        trace: list[dict[str, Any]] = []
        for entry in audits:
            action = entry.action.value if hasattr(entry.action, "value") else str(entry.action)
            if action in workflow:
                workflow[action] += 1
            elif action == "gate_failed":
                workflow["gate_failed"] += 1
            elif action == "agent_failed":
                workflow["agent_failed"] += 1
            elif action == "agent_retried":
                workflow["agent_retried"] += 1

            if action in {
                "task_classified",
                "task_assigned",
                "task_started",
                "replan_triggered",
                "replan_failed",
                "approval_requested",
                "approval_granted",
                "approval_denied",
                "gate_failed",
                "gate_passed",
                "task_completed",
                "task_failed",
            }:
                trace.append(
                    {
                        "ts": entry.created_at.isoformat() if entry.created_at else None,
                        "action": action,
                        "summary": entry.summary,
                        "actor": _canonical_agent_identity(entry.agent_role or "system", "")[0],
                        "metadata": entry.metadata or {},
                    }
                )

        risk_points = 0
        risk_points += workflow["gate_failed"] * 3
        risk_points += workflow["agent_failed"] * 2
        risk_points += workflow["replan_triggered"] * 2
        risk_points += workflow["approvals_denied"] * 3
        risk_points += workflow["agent_retried"]
        if risk_points >= 8:
            risk_level = "high"
        elif risk_points >= 4:
            risk_level = "medium"
        else:
            risk_level = "low"

        cost_data = {
            "total_tokens": int(task.total_tokens or 0),
            "total_cost_usd": float(task.total_cost_usd or 0.0),
        }

        policies = {
            "parallel_agents": bool(orchestration.parallel_agents),
            "consultation_enabled": bool(orchestration.consultation.enabled),
            "subagents_enabled": bool(orchestration.subagents.enabled),
            "replan_enabled": bool(orchestration.replan.enabled),
            "max_replans_per_task": int(orchestration.replan.max_replans_per_task),
            "filesystem_sandbox": str(
                os.environ.get("RIGOVO_FILESYSTEM_SANDBOX_MODE", "project_root")
            ),
            "worktree_mode": str(os.environ.get("RIGOVO_WORKTREE_MODE", "project")),
            "plugins_enabled": bool(plugins.enabled),
            "connector_tools": bool(plugins.enable_connector_tools),
            "mcp_tools": bool(plugins.enable_mcp_tools),
            "action_tools": bool(plugins.enable_action_tools),
            "plugin_trust_floor": str(plugins.min_trust_level),
            "approval_required_actions_allowed": bool(plugins.allow_approval_required_actions),
            "sensitive_payload_keys_allowed": bool(plugins.allow_sensitive_payload_keys),
            "quality_gate_enabled": True,
            "debate_enabled": True,
            "debate_max_rounds": 2,
        }

        team_roles: list[str] = []
        if task.pipeline_steps:
            team_roles = [s.agent_role for s in task.pipeline_steps if s.agent_role]
        if not team_roles:
            pipeline = (getattr(task, "metadata", {}) or {}).get("pipeline", [])
            for step in pipeline:
                role = str(step.get("role", "")).strip()
                if role:
                    team_roles.append(role)
        team_roles = [_canonical_agent_identity(r, "")[0] for r in team_roles if str(r).strip()]

        # Resolve task_type with live classification fallback
        _mission_task_type: str = "unclassified"
        if task.task_type:
            _mission_task_type = (
                str(task.task_type.value)
                if hasattr(task.task_type, "value")
                else str(task.task_type)
            )
        else:
            live_cls = _live_task_classification.get(task_id)
            if live_cls:
                _mission_task_type = live_cls.get("task_type", "unclassified")

        return {
            "task_id": task_id,
            "task_status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "task_type": _mission_task_type,
            "risk": {"level": risk_level, "points": risk_points},
            "cost": cost_data,
            "team": {"size": len(set(team_roles)), "roles": sorted(set(team_roles))},
            "workflow": workflow,
            "policies": policies,
            "decision_trace": sorted(
                trace,
                key=lambda x: x["ts"] or "",
            )[-80:],
        }

    @app.get("/v1/tasks/{task_id}/files")
    async def task_files(task_id: str) -> dict:
        """Aggregated file changes across all agent steps."""
        try:
            task_repo = SqliteTaskRepository(container.get_db())
            task = await task_repo.get(UUID(task_id))
            if not task:
                return {"task_id": task_id, "files": [], "by_agent": {}}

            by_agent: dict[str, list[str]] = {}
            all_files: set[str] = set()
            pipeline = (task.metadata or {}).get("pipeline", [])
            for step in pipeline:
                raw_role = str(step.get("role", "unknown"))
                role = _canonical_agent_identity(raw_role, "")[0]
                files = _filter_user_files(step.get("files_changed", []))
                if files:
                    by_agent[role] = files
                    all_files.update(files)

            return {
                "task_id": task_id,
                "files": sorted(all_files),
                "by_agent": by_agent,
            }
        except Exception:
            return {"task_id": task_id, "files": [], "by_agent": {}}

    @app.get("/v1/tasks/{task_id}/files/{file_path:path}")
    async def task_file_content(task_id: str, file_path: str) -> dict:
        """Return the content of a specific file changed by an agent."""
        try:
            task_repo = SqliteTaskRepository(container.get_db())
            task = await task_repo.get(UUID(task_id))
            if not task:
                return {"path": file_path, "content": "", "error": "Task not found"}

            # Try to find the file in the project working directory
            if _is_internal_runtime_path(file_path):
                return {"path": file_path, "content": "", "error": "Internal runtime file"}

            project_dir = (task.metadata or {}).get("project_dir", ".")
            full_path = Path(project_dir) / file_path
            if full_path.is_file():
                try:
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                    return {"path": file_path, "content": content}
                except Exception:
                    return {"path": file_path, "content": "", "error": "Cannot read file"}

            # File might have been generated but not yet written to disk
            # Check task output/artifacts
            pipeline = (task.metadata or {}).get("pipeline", [])
            for step in pipeline:
                output = step.get("output", "")
                files = _filter_user_files(step.get("files_changed", []))
                if file_path in files and output:
                    return {
                        "path": file_path,
                        "content": f"// Content from {step.get('role', 'agent')} output:\n{output}",
                    }

            return {"path": file_path, "content": "", "error": "File content not available"}
        except Exception:
            return {"path": file_path, "content": "", "error": "Internal error"}

    # ── Settings API ─────────────────────────────────────────────────
    # Lets the desktop UI read/write LLM keys & per-agent model
    # overrides so end-users never need to touch .env or rigovo.yml.
    #
    # Supports ALL providers the engine knows (Anthropic, OpenAI,
    # Google, DeepSeek, Groq, Mistral, Ollama) plus any
    # OpenAI-compatible endpoint via custom base_url.

    agent_roles = [
        "planner",
        "coder",
        "reviewer",
        "qa",
        "security",
        "devops",
        "sre",
        "docs",
        "lead",
    ]
    default_models = {
        "lead": "claude-opus-4-6",
        "coder": "claude-opus-4-6",
        "planner": "claude-sonnet-4-6",
        "reviewer": "claude-sonnet-4-6",
        "security": "claude-haiku-4-5",
        "qa": "claude-haiku-4-5",
        "devops": "claude-haiku-4-5",
        "sre": "claude-haiku-4-5",
        "docs": "claude-haiku-4-5",
    }

    # All providers with their env var name and console link
    providers = {
        "anthropic": {
            "key_env": "ANTHROPIC_API_KEY",
            "label": "Anthropic",
            "link": "https://console.anthropic.com/settings/keys",
        },
        "openai": {
            "key_env": "OPENAI_API_KEY",
            "label": "OpenAI",
            "link": "https://platform.openai.com/api-keys",
        },
        "google": {
            "key_env": "GOOGLE_API_KEY",
            "label": "Google AI",
            "link": "https://aistudio.google.com/apikey",
        },
        "deepseek": {
            "key_env": "DEEPSEEK_API_KEY",
            "label": "DeepSeek",
            "link": "https://platform.deepseek.com/api_keys",
        },
        "groq": {
            "key_env": "GROQ_API_KEY",
            "label": "Groq",
            "link": "https://console.groq.com/keys",
        },
        "mistral": {
            "key_env": "MISTRAL_API_KEY",
            "label": "Mistral",
            "link": "https://console.mistral.ai/api-keys",
        },
        "ollama": {"key_env": "", "label": "Ollama (Local)", "link": "https://ollama.com"},
    }

    available_models = [
        # Anthropic
        {
            "id": "claude-opus-4-6",
            "label": "Claude Opus 4.6",
            "provider": "anthropic",
            "tier": "premium",
        },
        {
            "id": "claude-sonnet-4-6",
            "label": "Claude Sonnet 4.6",
            "provider": "anthropic",
            "tier": "standard",
        },
        {
            "id": "claude-haiku-4-5",
            "label": "Claude Haiku 4.5",
            "provider": "anthropic",
            "tier": "budget",
        },
        # OpenAI
        {"id": "gpt-4o", "label": "GPT-4o", "provider": "openai", "tier": "premium"},
        {"id": "gpt-4o-mini", "label": "GPT-4o Mini", "provider": "openai", "tier": "budget"},
        {"id": "o1", "label": "o1", "provider": "openai", "tier": "premium"},
        {"id": "o3-mini", "label": "o3-mini", "provider": "openai", "tier": "standard"},
        # Google
        {
            "id": "gemini-2.0-flash",
            "label": "Gemini 2.0 Flash",
            "provider": "google",
            "tier": "standard",
        },
        {
            "id": "gemini-2.5-pro",
            "label": "Gemini 2.5 Pro",
            "provider": "google",
            "tier": "premium",
        },
        # DeepSeek
        {"id": "deepseek-chat", "label": "DeepSeek V3", "provider": "deepseek", "tier": "budget"},
        {
            "id": "deepseek-reasoner",
            "label": "DeepSeek R1",
            "provider": "deepseek",
            "tier": "standard",
        },
        # Groq
        {
            "id": "llama-3.3-70b-versatile",
            "label": "Llama 3.3 70B (Groq)",
            "provider": "groq",
            "tier": "budget",
        },
        {
            "id": "mixtral-8x7b-32768",
            "label": "Mixtral 8x7B (Groq)",
            "provider": "groq",
            "tier": "budget",
        },
        # Mistral
        {
            "id": "mistral-large-latest",
            "label": "Mistral Large",
            "provider": "mistral",
            "tier": "premium",
        },
        {"id": "codestral-latest", "label": "Codestral", "provider": "mistral", "tier": "standard"},
        # Ollama / Local
        {"id": "llama3", "label": "Llama 3 (Ollama)", "provider": "ollama", "tier": "local"},
        {"id": "codellama", "label": "Code Llama (Ollama)", "provider": "ollama", "tier": "local"},
    ]

    def _settings_repo() -> SqliteSettingsRepository:
        return container.get_settings_repo()

    def _mask_key(val: str) -> str:
        if not val:
            return ""
        if len(val) > 8:
            return f"{'•' * 8}…{val[-4:]}"
        return "•••"

    def _mask_dsn(dsn: str) -> str:
        if not dsn:
            return ""
        if "@" in dsn:
            tail = dsn.rsplit("@", 1)[1]
            return f"••••@{tail}"
        if len(dsn) > 12:
            return f"{dsn[:6]}••••{dsn[-4:]}"
        return "••••"

    def _upsert_env_var(key: str, value: str) -> None:
        env_path = root / ".env"
        lines: list[str] = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        updated = False
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                out.append(line)
                continue
            k, _ = line.split("=", 1)
            if k.strip() == key:
                updated = True
                if value:
                    out.append(f"{key}={value}")
                continue
            out.append(line)
        if value and not updated:
            out.append(f"{key}={value}")
        env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")

    @app.get("/v1/settings")
    async def get_settings() -> dict:
        """Read current LLM settings — keys masked, all providers listed."""
        await asyncio.sleep(0)
        repo = _settings_repo()
        all_keys = [meta["key_env"] for meta in providers.values() if meta["key_env"]]
        all_keys += ["LLM_MODEL", "OLLAMA_BASE_URL", "OPENAI_BASE_URL"]
        stored = repo.get_many(all_keys)

        configured_providers: dict[str, dict] = {}
        for name, meta in providers.items():
            key_env = meta["key_env"]
            val = stored.get(key_env, "") if key_env else ""
            configured_providers[name] = {
                "configured": bool(val),
                "masked": _mask_key(val),
                "key_env": key_env,
                "label": meta["label"],
                "link": meta["link"],
            }

        # Read per-agent model overrides from rigovo.yml
        yml = config.yml if hasattr(config, "yml") else None
        agent_models: dict[str, str] = {}
        agent_tools: dict[str, list[str]] = {}
        for role in agent_roles:
            override = ""
            tools_override: list[str] = []
            if yml and hasattr(yml, "teams"):
                eng = yml.teams.get("engineering")
                if eng and role in eng.agents:
                    override = eng.agents[role].model
                    tools_override = list(getattr(eng.agents[role], "tools", []) or [])
            agent_models[role] = override or default_models.get(role, "claude-sonnet-4-6")
            agent_tools[role] = tools_override

        # Return a fully-normalised YAML string so the Settings editor always
        # shows every section (even on projects created before a section was
        # added to the schema).  We load the on-disk file (if it exists) through
        # RigovoConfig so missing keys receive their schema defaults, then
        # serialise back to a human-readable string WITHOUT writing to disk.
        from rigovo.config_schema import (
            RigovoConfig,
            load_rigovo_yml,
            rigovo_yml_to_string,
            save_rigovo_yml,
        )

        yml_path = root / "rigovo.yml"
        if yml_path.exists():
            # Merge on-disk values with current schema defaults (fills any gaps)
            merged_cfg = load_rigovo_yml(root)
        else:
            # First run — create the file so the engine can start from it
            merged_cfg = RigovoConfig()
            save_rigovo_yml(merged_cfg, root)
        yml_raw = rigovo_yml_to_string(merged_cfg)

        return {
            "providers": configured_providers,
            "default_model": stored.get("LLM_MODEL", "") or config.llm.model,
            "agent_models": agent_models,
            "agent_tools": agent_tools,
            "available_models": available_models,
            "default_agent_models": default_models,
            "ollama_url": stored.get("OLLAMA_BASE_URL", "") or "http://localhost:11434",
            "custom_base_url": stored.get("OPENAI_BASE_URL", ""),
            "plugins_policy": {
                "enabled": bool(config.yml.plugins.enabled),
                "enable_connector_tools": bool(config.yml.plugins.enable_connector_tools),
                "enable_mcp_tools": bool(config.yml.plugins.enable_mcp_tools),
                "enable_action_tools": bool(config.yml.plugins.enable_action_tools),
                "min_trust_level": str(config.yml.plugins.min_trust_level),
                "dry_run": bool(config.yml.plugins.dry_run),
                "allow_approval_required_actions": bool(
                    config.yml.plugins.allow_approval_required_actions
                ),
                "allow_sensitive_payload_keys": bool(
                    config.yml.plugins.allow_sensitive_payload_keys
                ),
                "allowed_plugin_ids": list(config.yml.plugins.allowed_plugin_ids),
                "allowed_connector_operations": list(
                    config.yml.plugins.allowed_connector_operations
                ),
                "allowed_mcp_operations": list(config.yml.plugins.allowed_mcp_operations),
                "allowed_action_operations": list(config.yml.plugins.allowed_action_operations),
            },
            "database": {
                "backend": str(config.db_backend or "sqlite"),
                "local_db_path": str(config.local_db_path or ".rigovo/local.db"),
                "local_db_full_path": str(config.local_db_full_path),
                "dsn_configured": bool(config.db_url),
                "dsn_masked": _mask_dsn(str(config.db_url or "")),
            },
            "yml_raw": yml_raw,
        }

    @app.post("/v1/settings")
    async def update_settings(req: UpdateSettingsRequest) -> dict:
        """Update LLM settings — API keys stored encrypted in SQLite."""
        await asyncio.sleep(0)
        import logging as _logging

        _logger = _logging.getLogger("rigovo.api.settings")
        changes: list[str] = []
        errors: list[str] = []
        repo = _settings_repo()
        restart_required = False

        # 1. Save API keys (encrypted at rest in SQLite)
        if req.api_keys:
            try:
                for provider_name, key_value in req.api_keys.items():
                    meta = providers.get(provider_name)
                    if meta and meta["key_env"]:
                        repo.set(meta["key_env"], key_value)
                        changes.append(meta["key_env"])
                        _logger.info("Saved %s to encrypted settings", meta["key_env"])
                    else:
                        _logger.warning("Unknown provider '%s' — skipping", provider_name)
            except Exception as exc:
                _logger.error("Failed to save API keys: %s", exc, exc_info=True)
                errors.append(f"Failed to save API keys: {exc!s}")

        # 2. Save other settings (model, URLs — not secrets, plain text)
        try:
            if req.default_model is not None:
                repo.set("LLM_MODEL", req.default_model)
                changes.append("LLM_MODEL")
            if req.ollama_url is not None:
                repo.set("OLLAMA_BASE_URL", req.ollama_url)
                changes.append("OLLAMA_BASE_URL")
            if req.custom_base_url is not None:
                repo.set("OPENAI_BASE_URL", req.custom_base_url)
                changes.append("OPENAI_BASE_URL")
        except Exception as exc:
            _logger.error("Failed to save settings: %s", exc, exc_info=True)
            errors.append(f"Failed to save settings: {exc!s}")

        # 3. Database backend settings (rigovo.yml + .env)
        if req.db_backend is not None or req.local_db_path is not None or req.db_url is not None:
            try:
                yml_path = root / "rigovo.yml"
                yml_data: dict = {}
                if yml_path.exists():
                    yml_data = yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}

                db_section = yml_data.setdefault("database", {})
                if not isinstance(db_section, dict):
                    db_section = {}
                    yml_data["database"] = db_section

                if req.db_backend is not None:
                    backend = str(req.db_backend).strip().lower()
                    if backend not in {"sqlite", "postgres"}:
                        errors.append("db_backend must be either 'sqlite' or 'postgres'")
                    else:
                        db_section["backend"] = backend
                        changes.append("database.backend")
                        restart_required = True

                if req.local_db_path is not None:
                    db_section["local_path"] = str(req.local_db_path).strip() or ".rigovo/local.db"
                    changes.append("database.local_path")
                    restart_required = True

                if req.db_url is not None:
                    _upsert_env_var("RIGOVO_DB_URL", str(req.db_url).strip())
                    changes.append("RIGOVO_DB_URL")
                    restart_required = True

                yml_path.write_text(
                    yaml.dump(yml_data, default_flow_style=False, sort_keys=False), encoding="utf-8"
                )
            except Exception as exc:
                _logger.error("Failed to update database settings: %s", exc, exc_info=True)
                errors.append(f"Failed to update database settings: {exc!s}")

        # 4. If raw YAML is provided, write it directly
        if req.yml_raw is not None:
            try:
                yml_path = root / "rigovo.yml"
                # Validate it's valid YAML first
                yaml.safe_load(req.yml_raw)
                yml_path.write_text(req.yml_raw, encoding="utf-8")
                changes.append("rigovo.yml (raw)")
                _logger.info("Updated rigovo.yml from raw editor")
            except yaml.YAMLError as exc:
                errors.append(f"Invalid YAML syntax: {exc!s}")
            except Exception as exc:
                _logger.error("Failed to write rigovo.yml: %s", exc, exc_info=True)
                errors.append(f"Failed to write rigovo.yml: {exc!s}")

        # 5. Structured rigovo.yml updates for models/tools/plugin policy.
        elif req.agent_models or req.agent_tools or req.plugin_policy:
            try:
                yml_path = root / "rigovo.yml"
                yml_data: dict = {}
                if yml_path.exists():
                    yml_data = yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}

                teams = yml_data.setdefault("teams", {})
                eng = teams.setdefault("engineering", {})
                agents = eng.setdefault("agents", {})

                if req.agent_models:
                    for role, model in req.agent_models.items():
                        if role not in agent_roles:
                            continue
                        if model == default_models.get(role, ""):
                            if (
                                role in agents
                                and isinstance(agents.get(role), dict)
                                and "model" in agents[role]
                            ):
                                del agents[role]["model"]
                                if not agents[role]:
                                    del agents[role]
                        else:
                            agent_cfg = agents.setdefault(role, {})
                            if not isinstance(agent_cfg, dict):
                                agents[role] = {"model": model}
                            else:
                                agent_cfg["model"] = model
                        changes.append(f"agent.{role}.model")

                if req.agent_tools:
                    for role, tools in req.agent_tools.items():
                        if role not in agent_roles:
                            continue
                        cleaned = [str(t).strip() for t in (tools or []) if str(t).strip()]
                        agent_cfg = agents.setdefault(role, {})
                        if not isinstance(agent_cfg, dict):
                            agent_cfg = {}
                            agents[role] = agent_cfg
                        if cleaned:
                            agent_cfg["tools"] = cleaned
                        elif "tools" in agent_cfg:
                            del agent_cfg["tools"]
                            if not agent_cfg:
                                del agents[role]
                        changes.append(f"agent.{role}.tools")

                if req.plugin_policy:
                    plugins_section = yml_data.setdefault("plugins", {})
                    if not isinstance(plugins_section, dict):
                        plugins_section = {}
                        yml_data["plugins"] = plugins_section
                    allowed_keys = {
                        "enabled",
                        "enable_connector_tools",
                        "enable_mcp_tools",
                        "enable_action_tools",
                        "min_trust_level",
                        "dry_run",
                        "allow_approval_required_actions",
                        "allow_sensitive_payload_keys",
                        "allowed_plugin_ids",
                        "allowed_connector_operations",
                        "allowed_mcp_operations",
                        "allowed_action_operations",
                    }
                    for key, value in req.plugin_policy.items():
                        if key not in allowed_keys:
                            continue
                        plugins_section[key] = value
                        changes.append(f"plugins.{key}")

                yml_path.write_text(
                    yaml.dump(yml_data, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
                _logger.info("Updated rigovo.yml structured settings")
            except Exception as exc:
                _logger.error("Failed to update rigovo.yml: %s", exc, exc_info=True)
                errors.append(f"Failed to write rigovo.yml: {exc!s}")

        if errors:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "detail": "; ".join(errors),
                    "errors": errors,
                    "changes": changes,
                },
            )

        # Hot-reload rigovo.yml so next task uses updated settings (no restart needed)
        if changes:
            try:
                container.reload_config()
                _logger.info("Hot-reloaded config after settings update: %s", changes)
            except Exception as exc:
                _logger.warning(
                    "Config hot-reload failed (changes saved, apply on restart): %s", exc
                )

        # DB backend/path changes still need a process restart (connection pooling)
        note = ""
        if restart_required:
            note = (
                "Database backend/DSN changes saved. Restart the app to switch "
                "database connections."
            )

        return {
            "status": "updated",
            "changes": changes,
            "note": note,
        }

    # ── Database tools API ──────────────────────────────────────────

    @app.post("/v1/settings/test-db-connection")
    async def test_db_connection(request: Request) -> dict:
        """Test a PostgreSQL DSN before saving it.

        Lets the Settings UI validate connectivity before committing
        the change, so users aren't stuck with a broken backend.

        Uses Request object directly for robust body parsing — avoids
        FastAPI validation edge cases that can return 422 without an
        ``error`` field the frontend expects.
        """
        try:
            body = await request.json()
        except Exception:
            return {"ok": False, "error": "Invalid request body — expected JSON with 'dsn' field."}

        dsn = (body.get("dsn") or "").strip() if isinstance(body, dict) else ""
        if not dsn:
            return {"ok": False, "error": "No DSN provided. Enter a PostgreSQL connection string."}

        try:
            from rigovo.infrastructure.persistence.postgres_local import (
                PostgresDatabase,
            )
        except ImportError:
            return {
                "ok": False,
                "error": (
                    "PostgreSQL support not installed. "
                    "Run: pip install 'psycopg[binary]' — then restart Rigovo."
                ),
            }

        try:
            pg = PostgresDatabase(dsn)
            result = pg.test_connection()
            pg.close()
            # Guarantee 'error' key exists even if test_connection omits it
            if "error" not in result:
                result["error"] = None if result.get("ok") else "Unknown connection error"
            return result
        except Exception as e:
            return {"ok": False, "error": str(e) or "Connection failed (no details available)"}

    @app.post("/v1/settings/migrate-to-postgres")
    async def migrate_to_postgres(request: Request) -> dict:
        """One-click migration from SQLite to PostgreSQL.

        Reads all data from the current SQLite database and inserts it
        into the target PostgreSQL database. Idempotent — safe to run
        multiple times (uses ON CONFLICT DO UPDATE).
        """
        try:
            body = await request.json()
        except Exception:
            return {"ok": False, "error": "Invalid request body — expected JSON with 'dsn' field."}

        dsn = (body.get("dsn") or "").strip() if isinstance(body, dict) else ""
        if not dsn:
            return {"ok": False, "error": "No PostgreSQL DSN provided."}

        # Resolve SQLite path
        sqlite_path = str(config.db_full_path) if hasattr(config, "db_full_path") else None
        if not sqlite_path:
            try:
                sqlite_path = str(config.local_db_full_path)
            except Exception:
                sqlite_path = str(config.project_root / ".rigovo" / "local.db")

        import os

        if not os.path.exists(sqlite_path):
            return {"ok": False, "error": f"SQLite database not found at {sqlite_path}"}

        try:
            from rigovo.infrastructure.persistence.postgres_local import (
                migrate_sqlite_to_postgres,
            )

            result = migrate_sqlite_to_postgres(sqlite_path, dsn)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Logs API ──────────────────────────────────────────────────────
    # Users can view app, error, and audit logs from the desktop UI.
    # Logs are stored in <project>/.rigovo/logs/

    @app.get("/v1/logs")
    async def list_log_files() -> dict:
        """List available log files with sizes and last-modified times."""
        await asyncio.sleep(0)
        if not log_dir.exists():
            return {"log_dir": str(log_dir), "files": []}
        files = []
        for f in sorted(log_dir.iterdir()):
            if f.is_file() and f.suffix == ".log":
                stat = f.stat()
                files.append(
                    {
                        "name": f.name,
                        "size_bytes": stat.st_size,
                        "size_human": _human_size(stat.st_size),
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                    }
                )
        return {"log_dir": str(log_dir), "files": files}

    @app.get("/v1/logs/{log_name}")
    async def read_log_file(log_name: str, tail: int = 200) -> dict:
        """Read the last N lines of a log file.

        Args:
            log_name: Name of the log file (e.g. 'app.log', 'error.log', 'audit.log')
            tail: Number of lines from the end to return (default 200)
        """
        # Sanitize — only allow .log files in the log directory
        await asyncio.sleep(0)
        if ".." in log_name or "/" in log_name or not log_name.endswith(".log"):
            raise HTTPException(status_code=400, detail="Invalid log file name")

        log_file = log_dir / log_name
        if not log_file.exists():
            return {"name": log_name, "lines": [], "total_lines": 0, "truncated": False}

        try:
            all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(all_lines)
            lines = all_lines[-tail:] if total > tail else all_lines
            return {
                "name": log_name,
                "lines": lines,
                "total_lines": total,
                "truncated": total > tail,
                "showing": f"last {len(lines)} of {total}",
            }
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read log: {exc}",
            ) from exc

    def _human_size(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
            size //= 1024
        return f"{size} TB"

    # ── Request logging middleware ────────────────────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
        import time

        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000
        # Log non-health requests
        if request.url.path not in ("/health", "/v1/ping"):
            logger.info(
                "%s %s → %d (%.0fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            # Log errors to audit
            if response.status_code >= 400:
                logging.getLogger("rigovo.audit").warning(
                    "API error: %s %s → %d",
                    request.method,
                    request.url.path,
                    response.status_code,
                )
        return response

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        container.close()

    return app
