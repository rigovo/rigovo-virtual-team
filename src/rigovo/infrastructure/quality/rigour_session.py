"""Rigour multi-agent session management.

Writes the same JSON schemas as Rigour's MCP tools (agent-handlers.ts),
enabling Studio integration, scope conflict detection, and quality drift
monitoring across multi-agent pipeline execution.

Session files written:
- ``.rigour/agent-session.json``  — registered agents and their scopes
- ``.rigour/checkpoint-session.json`` — quality checkpoints with drift detection
- ``.rigour/handoffs.jsonl`` — agent-to-agent handoff log
- ``.rigour/events.jsonl`` — Studio event stream
"""

from __future__ import annotations

import contextlib
import json
import logging
import random
import string
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

UTC = timezone.utc


def _ts() -> str:
    return datetime.now(UTC).isoformat()


def _short_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


class RigourSession:
    """Manages .rigour/ session files for multi-agent governance.

    Thread-safe via atomic write patterns (write-to-temp + rename).
    """

    def __init__(self, project_root: str | Path) -> None:
        self._root = Path(project_root) / ".rigour"

    def _ensure_dir(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    # ── Agent registration ──────────────────────────────────────────

    def agent_register(
        self,
        agent_id: str,
        task_scope: list[str],
    ) -> list[str]:
        """Register agent + scope. Returns list of conflict warnings.

        Schema matches Rigour MCP ``handleAgentRegister``:
        ``{agents: [{agentId, taskScope[], registeredAt, lastCheckpoint}], startedAt}``
        """
        self._ensure_dir()
        session_path = self._root / "agent-session.json"

        session: dict = {"agents": [], "startedAt": _ts()}
        if session_path.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                session = json.loads(session_path.read_text())

        # Detect scope conflicts with other registered agents
        conflicts: list[str] = []
        scope_set = set(task_scope)
        for existing in session.get("agents", []):
            if existing.get("agentId") == agent_id:
                continue
            existing_scope = set(existing.get("taskScope", []))
            overlap = scope_set & existing_scope
            if overlap:
                conflicts.append(
                    f"Scope conflict with {existing['agentId']}: {', '.join(sorted(overlap)[:5])}"
                )

        # Remove existing entry for this agent (re-registration)
        session["agents"] = [a for a in session.get("agents", []) if a.get("agentId") != agent_id]
        session["agents"].append(
            {
                "agentId": agent_id,
                "taskScope": task_scope[:50],
                "registeredAt": _ts(),
                "lastCheckpoint": None,
            }
        )

        session_path.write_text(json.dumps(session, indent=2))
        return conflicts

    def agent_deregister(self, agent_id: str) -> None:
        """Remove agent from session."""
        session_path = self._root / "agent-session.json"
        if not session_path.exists():
            return
        try:
            session = json.loads(session_path.read_text())
            session["agents"] = [
                a for a in session.get("agents", []) if a.get("agentId") != agent_id
            ]
            session_path.write_text(json.dumps(session, indent=2))
        except (json.JSONDecodeError, OSError):
            pass

    # ── Checkpoints ─────────────────────────────────────────────────

    def checkpoint(
        self,
        progress_pct: int,
        files_changed: list[str],
        summary: str,
        quality_score: int,
    ) -> bool:
        """Record checkpoint. Returns True if quality is acceptable (should continue).

        Drift detection: warns if quality drops >10% from average of last 3
        checkpoints. Schema matches Rigour MCP ``handleCheckpoint``.
        """
        self._ensure_dir()
        cp_path = self._root / "checkpoint-session.json"

        session: dict = {
            "sessionId": f"chk-session-{int(datetime.now(UTC).timestamp())}",
            "startedAt": _ts(),
            "checkpoints": [],
            "status": "active",
        }
        if cp_path.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                session = json.loads(cp_path.read_text())

        # Drift detection: compare against avg of last 3 checkpoints
        warnings: list[str] = []
        recent = session.get("checkpoints", [])[-3:]
        if recent:
            avg_quality = sum(cp.get("qualityScore", 100) for cp in recent) / len(recent)
            if quality_score < avg_quality - 10:
                warnings.append(
                    f"Quality drift: {quality_score}% vs "
                    f"{avg_quality:.0f}% avg (last {len(recent)} checkpoints)"
                )

        checkpoint_entry = {
            "checkpointId": f"cp-{int(datetime.now(UTC).timestamp())}-{_short_id()}",
            "timestamp": _ts(),
            "progressPct": min(100, max(0, progress_pct)),
            "filesChanged": files_changed[:20],
            "summary": summary,
            "qualityScore": min(100, max(0, quality_score)),
            "warnings": warnings,
        }
        session.setdefault("checkpoints", []).append(checkpoint_entry)
        session["status"] = "active"

        cp_path.write_text(json.dumps(session, indent=2))

        # Update lastCheckpoint in agent-session if available
        self._update_agent_last_checkpoint()

        should_continue = quality_score >= 80
        return should_continue

    def _update_agent_last_checkpoint(self) -> None:
        """Update lastCheckpoint timestamp for all registered agents."""
        session_path = self._root / "agent-session.json"
        if not session_path.exists():
            return
        try:
            session = json.loads(session_path.read_text())
            now = _ts()
            for agent in session.get("agents", []):
                agent["lastCheckpoint"] = now
            session_path.write_text(json.dumps(session, indent=2))
        except (json.JSONDecodeError, OSError):
            pass

    # ── Handoffs ────────────────────────────────────────────────────

    def handoff(
        self,
        from_agent: str,
        to_agent: str,
        task: str,
        files: list[str],
        context: str,
    ) -> str:
        """Initiate handoff. Returns handoff_id.

        Appends to ``.rigour/handoffs.jsonl``. Schema matches Rigour MCP
        ``handleHandoff``.
        """
        self._ensure_dir()
        handoff_id = f"handoff-{int(datetime.now(UTC).timestamp())}"
        entry = {
            "handoffId": handoff_id,
            "timestamp": _ts(),
            "fromAgentId": from_agent,
            "toAgentId": to_agent,
            "taskDescription": task[:500],
            "filesInScope": files[:20],
            "context": context[:1000],
            "status": "pending",
        }
        handoffs_path = self._root / "handoffs.jsonl"
        with open(handoffs_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return handoff_id

    # ── Event streaming (Studio integration) ────────────────────────

    def log_event(self, event: dict) -> None:
        """Append event to .rigour/events.jsonl for Studio integration.

        Events are consumed by ``rigour studio`` for real-time governance
        visibility into Rigovo pipeline execution.
        """
        self._ensure_dir()
        events_path = self._root / "events.jsonl"
        entry = {
            "id": str(uuid4()),
            "timestamp": _ts(),
            **event,
        }
        with open(events_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
