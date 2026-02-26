"""FastAPI control-plane service for desktop and connector integrations."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
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
from rigovo.domain.entities.task import TaskStatus
from rigovo.infrastructure.persistence.sqlite_audit_repo import SqliteAuditRepository
from rigovo.infrastructure.persistence.sqlite_settings_repo import SqliteSettingsRepository
from rigovo.infrastructure.persistence.sqlite_task_repo import SqliteTaskRepository


# ── Live agent progress tracker (in-memory, per-task) ──────────────
# Populated by event emitter callbacks during graph execution.
# The detail endpoint reads this for running tasks; completed tasks
# fall back to persisted pipeline_steps in SQLite.
_live_agent_progress: dict[str, dict[str, dict]] = {}  # task_id -> {role -> step_data}


def _on_agent_event(event: dict) -> None:
    """Handle agent_started / agent_complete events from the graph."""
    etype = event.get("type", "")
    task_id = event.get("task_id", "")
    role = event.get("role", "")
    if not task_id or not role:
        return

    if task_id not in _live_agent_progress:
        _live_agent_progress[task_id] = {}

    if etype == "agent_started":
        _live_agent_progress[task_id][role] = {
            "agent": role,
            "agent_name": event.get("name", role.replace("_", " ").title()),
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "output": "",
            "files_changed": [],
            "gate_results": [],
        }
    elif etype == "agent_complete":
        existing = _live_agent_progress[task_id].get(role, {})
        _live_agent_progress[task_id][role] = {
            **existing,
            "agent": role,
            "agent_name": event.get("name", role.replace("_", " ").title()),
            "status": "complete",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "output": event.get("summary", existing.get("output", "")),
            "files_changed": event.get("files_changed", []),
            "tokens": event.get("tokens", 0),
            "cost_usd": event.get("cost", 0.0),
            "duration_ms": event.get("duration_ms", 0),
            "gate_results": [],
        }
    elif etype in ("task_finalized", "task_failed"):
        # Clean up live state once task is done
        _live_agent_progress.pop(task_id, None)


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


class RegisterProjectRequest(BaseModel):
    path: str
    name: str = ""


class UpdateSettingsRequest(BaseModel):
    """Partial settings update from the UI.

    Any field can be sent individually. The backend merges changes.
    """
    # API keys — any provider
    api_keys: dict[str, str] | None = None       # e.g. {"anthropic": "sk-...", "deepseek": "ds-..."}
    # Other .env settings
    default_model: str | None = None
    ollama_url: str | None = None
    custom_base_url: str | None = None            # For OpenAI-compatible endpoints
    # Per-agent model overrides (written to rigovo.yml)
    agent_models: dict[str, str] | None = None
    # Raw YAML override (written directly to rigovo.yml)
    yml_raw: str | None = None


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


def _tier_from_task(task) -> str:
    complexity = (task.complexity.value if task.complexity else "").lower()
    if task.status == TaskStatus.AWAITING_APPROVAL or complexity == "critical":
        return "approve"
    if complexity == "high":
        return "notify"
    return "auto"


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
        log_dir / "app.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(readable_fmt)

    # Error log — errors and warnings only
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(readable_fmt)

    # Audit log — structured JSON, one line per event
    audit_handler = logging.handlers.RotatingFileHandler(
        log_dir / "audit.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
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

    # Set up structured file logging
    log_dir = _setup_logging(root)

    import logging
    logger = logging.getLogger("rigovo.api")

    # Auto-initialize database schema (ensures tables exist on first run)
    try:
        db = container.get_db()
        db.initialize()
        logger.info("Database schema initialized successfully")
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
            logger.info("Migrated %d API key(s) from .env to encrypted SQLite: %s", len(migrated), migrated)
    except Exception:
        logger.debug("API key migration skipped", exc_info=True)

    app = FastAPI(title="Rigovo Control Plane API", version="0.1.0")

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
        emitter.on("agent_complete", _on_agent_event)
        emitter.on("task_finalized", _on_agent_event)
        emitter.on("task_failed", _on_agent_event)
        logger.info("Live agent progress tracking enabled")
    except Exception:
        logger.debug("Could not wire event emitter for live tracking", exc_info=True)

    # --- WorkOS AuthKit PKCE state ----
    # Pending auth flow: stores {state: {code_verifier, redirect_uri}}
    _pending_auth: dict[str, dict[str, str]] = {}

    state_path = root / ".rigovo" / "control_plane_state.json"
    runtime_workos_api_key = ""

    def _workos_settings(state: ControlPlaneState | None = None) -> dict[str, str]:
        nonlocal runtime_workos_api_key
        current = state or _read_state()
        identity = current.identity
        provider = identity.get("provider") or config.identity.provider or "local"
        auth_mode = identity.get("authMode") or config.identity.auth_mode or "email_only"
        api_key = runtime_workos_api_key or config.identity.workos_api_key or ""
        client_id = identity.get("workosClientId") or config.identity.workos_client_id or ""
        organization_id = (
            identity.get("workosOrganizationId")
            or config.identity.workos_organization_id
            or ""
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

    def _auth_result_html(success: bool, detail: str) -> str:
        """Return a simple HTML page for the browser callback tab."""
        if success:
            return f"""<!DOCTYPE html>
<html><head><title>Rigovo – Signed In</title>
<style>body{{font-family:system-ui;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f8fafc}}
.card{{text-align:center;padding:3rem;border-radius:1rem;background:white;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
h1{{color:#0f172a;font-size:1.5rem}}p{{color:#64748b;margin-top:.5rem}}</style></head>
<body><div class="card">
<h1>Welcome, {detail}!</h1>
<p>You're signed in to Rigovo. You can close this tab and return to the app.</p>
</div></body></html>"""
        return f"""<!DOCTYPE html>
<html><head><title>Rigovo – Auth Error</title>
<style>body{{font-family:system-ui;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#fef2f2}}
.card{{text-align:center;padding:3rem;border-radius:1rem;background:white;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
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

    async def _resume_task_async(task_id: str, description: str, use_task_id: str | None = None) -> None:
        """Run a task in background. use_task_id ensures the DB record is reused, not duplicated."""
        import logging as _logging
        _bg_logger = _logging.getLogger("rigovo.api.background")
        real_task_id = use_task_id or task_id
        try:
            # Read parallel setting from config (default True for speed)
            enable_parallel = getattr(
                getattr(getattr(container, "config", None), "yml", None),
                "orchestration", None,
            )
            parallel = getattr(enable_parallel, "parallel_agents", True) if enable_parallel else True
            cmd = container.build_run_task_command(
                offline=False,
                enable_parallel=parallel,
                enable_streaming=True,
            )
            await cmd.execute(
                description=description,
                resume_thread_id=task_id,
                task_id=real_task_id,
            )
        except Exception as exc:
            _bg_logger.error("Task %s failed in background: %s", real_task_id, exc, exc_info=True)
            # Mark the task as failed in the DB so the UI doesn't show it stuck forever
            try:
                task_repo = SqliteTaskRepository(container.get_db())
                from uuid import UUID as _UUID
                task_obj = await task_repo.get(_UUID(str(real_task_id)))
                if task_obj and task_obj.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.REJECTED):
                    task_obj.fail(str(exc)[:500])
                    await task_repo.update_status(task_obj)
                    _bg_logger.info("Marked task %s as failed", real_task_id)
            except Exception as db_exc:
                _bg_logger.warning("Could not mark task %s as failed: %s", real_task_id, db_exc)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
                "replan": {
                    "enabled": bool(orchestration.replan.enabled),
                    "max_replans_per_task": int(orchestration.replan.max_replans_per_task),
                    "trigger_retry_count": int(orchestration.replan.trigger_retry_count),
                },
            },
            "plugins": {
                "enabled": bool(plugins.enabled),
                "enable_connector_tools": bool(plugins.enable_connector_tools),
                "enable_mcp_tools": bool(plugins.enable_mcp_tools),
                "enable_action_tools": bool(plugins.enable_action_tools),
                "min_trust_level": str(plugins.min_trust_level),
                "dry_run": bool(plugins.dry_run),
            },
            "runtime": {
                "filesystem_sandbox": "project_root",
                "worktree_mode": str(os.environ.get("RIGOVO_WORKTREE_MODE", "project")),
                "worktree_root": str(os.environ.get("RIGOVO_WORKTREE_ROOT", "")),
                "debate_enabled": True,
                "debate_max_rounds": 2,
                "quality_gate_enabled": True,
                "memory_learning_enabled": True,
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
        provider = str(
            payload.get("provider", state.identity.get("provider", "local"))
        ).strip().lower()
        auth_mode = str(
            payload.get("authMode", state.policy.get("authMode", "email_only"))
        ).strip().lower()
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
        repo.set_many({
            "RIGOVO_IDENTITY_PROVIDER": provider,
            "RIGOVO_AUTH_MODE": auth_mode,
            "WORKOS_CLIENT_ID": workos_client_id,
            "WORKOS_ORGANIZATION_ID": workos_organization_id,
        })
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
    def get_auth_url(screen_hint: str = "sign-in") -> dict[str, str]:
        """Build WorkOS authorization URL. Frontend opens this in system browser."""
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
            base64.urlsafe_b64encode(code_challenge_bytes)
            .rstrip(b"=")
            .decode("ascii")
        )

        state_token = secrets.token_urlsafe(32)

        # Backend callback URL — e2e script passes port via env; default to 8787
        api_port = os.environ.get("RIGOVO_API_PORT", "8787")
        redirect_uri = f"http://127.0.0.1:{api_port}/v1/auth/callback"

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state_token,
            "code_challenge": code_challenge_b64,
            "code_challenge_method": "S256",
            "provider": "authkit",
        }
        if screen_hint in ("sign-up", "sign-in"):
            params["screen_hint"] = screen_hint

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
    def auth_callback(code: str = "", state: str = "", error: str = "", error_description: str = "") -> HTMLResponse:
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
                _auth_result_html(False, "Invalid or expired state token. Please try signing in again."),
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
        # Use client_secret if we have the API key, otherwise rely on PKCE
        if api_key:
            exchange_payload["client_secret"] = api_key

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
                except Exception:
                    pass
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
                                    user_role = role_data.get("slug", "admin") if role_data else "admin"
                except Exception:
                    pass  # org fetch is best-effort, auth still succeeds

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
            items.append(
                {
                    "id": str(task.id),
                    "title": task.description,
                    "source": "rigovo",
                    "tier": _tier_from_task(task),
                    "status": task.status.value,
                    "team": str(task.team_id)[:8] if task.team_id else "unassigned",
                    "updatedAt": _relative(updated),
                }
            )
        return items

    @app.get("/v1/ui/approvals")
    async def ui_approvals(limit: int = 25) -> list[dict]:
        repo = SqliteTaskRepository(container.get_db())
        tasks = await repo.list_by_workspace(_workspace_id(), limit=limit)
        pending = [t for t in tasks if t.status == TaskStatus.AWAITING_APPROVAL]
        return [
            {
                "id": f"apv_{str(t.id)[:8]}",
                "taskId": str(t.id),
                "summary": t.approval_data.get("summary", "Pending human approval"),
                "tier": "approve",
                "requestedBy": "master-agent",
                "age": _relative(t.started_at or t.created_at),
            }
            for t in pending
        ]

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
            raise HTTPException(status_code=404, detail="Task not found")
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
                gate_results = []
                if ps.gate_passed is not None:
                    gate_results.append({
                        "gate": "rigour",
                        "passed": ps.gate_passed,
                        "message": f"Score: {ps.gate_score:.1f}" if ps.gate_score else "",
                        "severity": "info" if ps.gate_passed else "error",
                    })
                steps.append({
                    "agent": ps.agent_role,
                    "agent_name": ps.agent_name,
                    "status": ps.status,
                    "started_at": ps.started_at.isoformat() if ps.started_at else None,
                    "completed_at": ps.completed_at.isoformat() if ps.completed_at else None,
                    "output": ps.summary,
                    "files_changed": ps.files_changed or [],
                    "tokens": ps.total_tokens,
                    "cost_usd": ps.cost_usd,
                    "duration_ms": ps.duration_ms,
                    "gate_results": gate_results,
                })

        # --- Priority 3: Synthetic placeholders (legacy / no data) ---
        if not steps:
            agents = ["planner", "coder", "reviewer", "qa"]
            for agent in agents:
                if task.status.value in ("completed", "done"):
                    steps.append({"agent": agent, "status": "complete", "started_at": None, "completed_at": None, "output": "", "files_changed": [], "gate_results": []})
                elif task.status.value in ("running", "in_progress", "assembling", "routing", "classifying"):
                    s = "complete" if agents.index(agent) < 1 else ("running" if agents.index(agent) == 1 else "pending")
                    steps.append({"agent": agent, "status": s, "started_at": None, "completed_at": None, "output": "", "files_changed": [], "gate_results": []})
                else:
                    steps.append({"agent": agent, "status": "pending", "started_at": None, "completed_at": None, "output": "", "files_changed": [], "gate_results": []})

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
            pass

        return {
            "id": str(task.id),
            "description": task.description,
            "status": task.status.value,
            "task_type": task.task_type or "unclassified",
            "tier": _tier_from_task(task),
            "team": str(task.team_id)[:8] if task.team_id else "unassigned",
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "steps": steps,
            "cost": cost,
            "approval_data": task.approval_data or {},
        }

    @app.post("/v1/tasks")
    async def create_task(
        req: CreateTaskRequest,
        background_tasks: BackgroundTasks,
    ) -> dict:
        """Create and run a new task from the desktop UI."""
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
        import logging as _logging
        _logging.getLogger("rigovo.audit").info(
            "Task created: id=%s desc=%r", task_id, req.description.strip()[:100],
        )
        background_tasks.add_task(_resume_task_async, task_id, req.description.strip(), task_id)
        return {
            "status": "created",
            "task_id": task_id,
            "description": req.description.strip(),
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
        if req.resume_now:
            background_tasks.add_task(_resume_task_async, task_id, task.description, task_id)
        return {"status": "approved", "task_id": task_id, "resuming": bool(req.resume_now)}

    @app.post("/v1/tasks/{task_id}/resume")
    async def resume_task(
        task_id: str,
        req: TaskActionRequest,
        background_tasks: BackgroundTasks,
    ) -> dict:
        _, task = await _load_task(task_id)

        # Guard: don't spawn another run if already running
        if task.status in (TaskStatus.RUNNING, TaskStatus.ASSEMBLING, TaskStatus.ROUTING, TaskStatus.CLASSIFYING, TaskStatus.QUALITY_CHECK):
            return {"status": "already_running", "task_id": task_id}

        await _append_audit(
            AuditAction.TASK_STARTED,
            task,
            summary="Resume requested via control plane",
            metadata={"source": "api.resume"},
            actor=req.actor,
        )
        background_tasks.add_task(_resume_task_async, task_id, task.description, task_id)
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
                        "agent_role": e.agent_role or "",
                        "summary": e.summary,
                        "metadata": e.metadata or {},
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in entries
                ],
            }
        except Exception:
            return {"task_id": task_id, "entries": []}

    @app.get("/v1/tasks/{task_id}/costs")
    async def task_costs(task_id: str) -> dict:
        """Per-agent cost breakdown for a task."""
        try:
            from rigovo.infrastructure.persistence.sqlite_cost_repo import SqliteCostRepository
            cost_repo = SqliteCostRepository(container.get_db())
            entries = await cost_repo.list_by_task(UUID(task_id))
            per_agent: dict[str, dict] = {}
            total_tokens = 0
            total_cost = 0.0
            for e in entries:
                role = e.agent_role if hasattr(e, "agent_role") and e.agent_role else "unknown"
                if role not in per_agent:
                    per_agent[role] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": ""}
                per_agent[role]["input_tokens"] += e.input_tokens
                per_agent[role]["output_tokens"] += e.output_tokens
                per_agent[role]["cost_usd"] += e.cost_usd
                per_agent[role]["model"] = e.llm_model or per_agent[role]["model"]
                total_tokens += e.total_tokens
                total_cost += e.cost_usd
            return {
                "task_id": task_id,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 4),
                "per_agent": per_agent,
            }
        except Exception:
            return {"task_id": task_id, "total_tokens": 0, "total_cost_usd": 0.0, "per_agent": {}}

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
                role = step.get("role", "unknown")
                files = step.get("files_changed", [])
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
                files = step.get("files_changed", [])
                if file_path in files and output:
                    return {"path": file_path, "content": f"// Content from {step.get('role', 'agent')} output:\n{output}"}

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

    AGENT_ROLES = ["planner", "coder", "reviewer", "qa", "security", "devops", "sre", "docs", "lead"]
    DEFAULT_MODELS = {
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
    PROVIDERS = {
        "anthropic": {"key_env": "ANTHROPIC_API_KEY", "label": "Anthropic", "link": "https://console.anthropic.com/settings/keys"},
        "openai":    {"key_env": "OPENAI_API_KEY",    "label": "OpenAI",    "link": "https://platform.openai.com/api-keys"},
        "google":    {"key_env": "GOOGLE_API_KEY",     "label": "Google AI", "link": "https://aistudio.google.com/apikey"},
        "deepseek":  {"key_env": "DEEPSEEK_API_KEY",   "label": "DeepSeek",  "link": "https://platform.deepseek.com/api_keys"},
        "groq":      {"key_env": "GROQ_API_KEY",       "label": "Groq",      "link": "https://console.groq.com/keys"},
        "mistral":   {"key_env": "MISTRAL_API_KEY",     "label": "Mistral",   "link": "https://console.mistral.ai/api-keys"},
        "ollama":    {"key_env": "",                     "label": "Ollama (Local)", "link": "https://ollama.com"},
    }

    AVAILABLE_MODELS = [
        # Anthropic
        {"id": "claude-opus-4-6",   "label": "Claude Opus 4.6",   "provider": "anthropic", "tier": "premium"},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "provider": "anthropic", "tier": "standard"},
        {"id": "claude-haiku-4-5",  "label": "Claude Haiku 4.5",  "provider": "anthropic", "tier": "budget"},
        # OpenAI
        {"id": "gpt-4o",      "label": "GPT-4o",      "provider": "openai", "tier": "premium"},
        {"id": "gpt-4o-mini", "label": "GPT-4o Mini", "provider": "openai", "tier": "budget"},
        {"id": "o1",          "label": "o1",           "provider": "openai", "tier": "premium"},
        {"id": "o3-mini",     "label": "o3-mini",      "provider": "openai", "tier": "standard"},
        # Google
        {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash", "provider": "google",   "tier": "standard"},
        {"id": "gemini-2.5-pro",   "label": "Gemini 2.5 Pro",   "provider": "google",   "tier": "premium"},
        # DeepSeek
        {"id": "deepseek-chat",     "label": "DeepSeek V3",       "provider": "deepseek", "tier": "budget"},
        {"id": "deepseek-reasoner", "label": "DeepSeek R1",       "provider": "deepseek", "tier": "standard"},
        # Groq
        {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B (Groq)", "provider": "groq", "tier": "budget"},
        {"id": "mixtral-8x7b-32768",      "label": "Mixtral 8x7B (Groq)",  "provider": "groq", "tier": "budget"},
        # Mistral
        {"id": "mistral-large-latest", "label": "Mistral Large",    "provider": "mistral", "tier": "premium"},
        {"id": "codestral-latest",     "label": "Codestral",        "provider": "mistral", "tier": "standard"},
        # Ollama / Local
        {"id": "llama3",   "label": "Llama 3 (Ollama)",   "provider": "ollama", "tier": "local"},
        {"id": "codellama","label": "Code Llama (Ollama)", "provider": "ollama", "tier": "local"},
    ]

    def _settings_repo() -> SqliteSettingsRepository:
        return container.get_settings_repo()

    def _mask_key(val: str) -> str:
        if not val:
            return ""
        if len(val) > 8:
            return f"{'•' * 8}…{val[-4:]}"
        return "•••"

    @app.get("/v1/settings")
    async def get_settings() -> dict:
        """Read current LLM settings — keys masked, all providers listed."""
        repo = _settings_repo()
        all_keys = [meta["key_env"] for meta in PROVIDERS.values() if meta["key_env"]]
        all_keys += ["LLM_MODEL", "OLLAMA_BASE_URL", "OPENAI_BASE_URL"]
        stored = repo.get_many(all_keys)

        providers: dict[str, dict] = {}
        for name, meta in PROVIDERS.items():
            key_env = meta["key_env"]
            val = stored.get(key_env, "") if key_env else ""
            providers[name] = {
                "configured": bool(val),
                "masked": _mask_key(val),
                "key_env": key_env,
                "label": meta["label"],
                "link": meta["link"],
            }

        # Read per-agent model overrides from rigovo.yml
        yml = config.yml if hasattr(config, "yml") else None
        agent_models: dict[str, str] = {}
        for role in AGENT_ROLES:
            override = ""
            if yml and hasattr(yml, "teams"):
                eng = yml.teams.get("engineering")
                if eng and role in eng.agents:
                    override = eng.agents[role].model
            agent_models[role] = override or DEFAULT_MODELS.get(role, "claude-sonnet-4-6")

        # Read rigovo.yml raw for the config editor — generate defaults if missing
        yml_path = root / "rigovo.yml"
        if yml_path.exists():
            yml_raw = yml_path.read_text(encoding="utf-8")
        else:
            from rigovo.config_schema import RigovoConfig, save_rigovo_yml
            default_cfg = RigovoConfig()
            save_rigovo_yml(default_cfg, root)
            yml_raw = yml_path.read_text(encoding="utf-8")

        return {
            "providers": providers,
            "default_model": stored.get("LLM_MODEL", "") or config.llm.model,
            "agent_models": agent_models,
            "available_models": AVAILABLE_MODELS,
            "default_agent_models": DEFAULT_MODELS,
            "ollama_url": stored.get("OLLAMA_BASE_URL", "") or "http://localhost:11434",
            "custom_base_url": stored.get("OPENAI_BASE_URL", ""),
            "yml_raw": yml_raw,
        }

    @app.post("/v1/settings")
    async def update_settings(req: UpdateSettingsRequest) -> dict:
        """Update LLM settings — API keys stored encrypted in SQLite."""
        import logging as _logging
        _logger = _logging.getLogger("rigovo.api.settings")
        changes: list[str] = []
        errors: list[str] = []
        repo = _settings_repo()

        # 1. Save API keys (encrypted at rest in SQLite)
        if req.api_keys:
            try:
                for provider_name, key_value in req.api_keys.items():
                    meta = PROVIDERS.get(provider_name)
                    if meta and meta["key_env"]:
                        repo.set(meta["key_env"], key_value)
                        changes.append(meta["key_env"])
                        _logger.info("Saved %s to encrypted settings", meta["key_env"])
                    else:
                        _logger.warning("Unknown provider '%s' — skipping", provider_name)
            except Exception as exc:
                _logger.error("Failed to save API keys: %s", exc, exc_info=True)
                errors.append(f"Failed to save API keys: {str(exc)}")

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
            errors.append(f"Failed to save settings: {str(exc)}")

        # 3. If raw YAML is provided, write it directly
        if req.yml_raw is not None:
            try:
                yml_path = root / "rigovo.yml"
                # Validate it's valid YAML first
                yaml.safe_load(req.yml_raw)
                yml_path.write_text(req.yml_raw, encoding="utf-8")
                changes.append("rigovo.yml (raw)")
                _logger.info("Updated rigovo.yml from raw editor")
            except yaml.YAMLError as exc:
                errors.append(f"Invalid YAML syntax: {str(exc)}")
            except Exception as exc:
                _logger.error("Failed to write rigovo.yml: %s", exc, exc_info=True)
                errors.append(f"Failed to write rigovo.yml: {str(exc)}")

        # 4. Update rigovo.yml for per-agent model overrides
        elif req.agent_models:
            try:
                yml_path = root / "rigovo.yml"
                yml_data: dict = {}
                if yml_path.exists():
                    yml_data = yaml.safe_load(yml_path.read_text()) or {}

                teams = yml_data.setdefault("teams", {})
                eng = teams.setdefault("engineering", {})
                agents = eng.setdefault("agents", {})

                for role, model in req.agent_models.items():
                    if role not in AGENT_ROLES:
                        continue
                    if model == DEFAULT_MODELS.get(role, ""):
                        if role in agents and isinstance(agents.get(role), dict) and "model" in agents[role]:
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

                yml_path.write_text(yaml.dump(yml_data, default_flow_style=False, sort_keys=False))
                _logger.info("Updated rigovo.yml agent models: %s", list(req.agent_models.keys()))
            except Exception as exc:
                _logger.error("Failed to update rigovo.yml: %s", exc, exc_info=True)
                errors.append(f"Failed to write rigovo.yml: {str(exc)}")

        if errors:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={"status": "error", "detail": "; ".join(errors), "errors": errors, "changes": changes},
            )

        # No restart needed — the LLM factory reads keys from SQLite
        # on every provider creation, so changes take effect immediately.

        return {
            "status": "updated",
            "changes": changes,
        }

    # ── Logs API ──────────────────────────────────────────────────────
    # Users can view app, error, and audit logs from the desktop UI.
    # Logs are stored in <project>/.rigovo/logs/

    @app.get("/v1/logs")
    async def list_log_files() -> dict:
        """List available log files with sizes and last-modified times."""
        if not log_dir.exists():
            return {"log_dir": str(log_dir), "files": []}
        files = []
        for f in sorted(log_dir.iterdir()):
            if f.is_file() and f.suffix == ".log":
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "size_bytes": stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
        return {"log_dir": str(log_dir), "files": files}

    @app.get("/v1/logs/{log_name}")
    async def read_log_file(log_name: str, tail: int = 200) -> dict:
        """Read the last N lines of a log file.

        Args:
            log_name: Name of the log file (e.g. 'app.log', 'error.log', 'audit.log')
            tail: Number of lines from the end to return (default 200)
        """
        # Sanitize — only allow .log files in the log directory
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
            raise HTTPException(status_code=500, detail=f"Failed to read log: {exc}")

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
        if request.url.path != "/health":
            logger.info(
                "%s %s → %d (%.0fms)",
                request.method, request.url.path, response.status_code, duration_ms,
            )
            # Log errors to audit
            if response.status_code >= 400:
                logging.getLogger("rigovo.audit").warning(
                    "API error: %s %s → %d",
                    request.method, request.url.path, response.status_code,
                )
        return response

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        container.close()

    return app
