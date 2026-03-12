"""Execute agent node — runs the current agent with context engineering.

Each agent execution follows the INTELLIGENT AGENT pattern:
1. PERCEIVE — project snapshot injected (scanned at task start)
2. REMEMBER — relevant memories from past tasks injected
3. REASON — system prompt + enrichment + quality contract
4. ACT — LLM generates response with tool calls (agentic loop)
5. VERIFY — Rigour gates check output (separate node)

Supports an **agentic tool loop**: the LLM calls tools (read_file,
write_file, run_command, etc.), we execute them and feed results back,
and the LLM continues until it has no more tool calls. This is how
agents actually write code, not just describe changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from rigovo.application.context.context_builder import ContextBuilder
from rigovo.application.context.memory_retriever import MemoryRetriever
from rigovo.application.context.memory_runtime import RigourMemoryRuntime
from rigovo.application.graph.state import AgentOutput, TaskState
from rigovo.domain.interfaces.embedding_provider import EmbeddingProvider
from rigovo.domain.interfaces.llm_provider import LLMProvider, LLMResponse, LLMUsage
from rigovo.domain.interfaces.repositories import MemoryRepository
from rigovo.domain.services.cost_calculator import CostCalculator
from rigovo.domains.engineering.tools import TOOL_DEFINITIONS, get_engineering_tools
from rigovo.infrastructure.filesystem.tool_executor import ToolExecutor
from rigovo.infrastructure.quality.rigour_session import RigourSession

logger = logging.getLogger(__name__)

# --- Named constants for agent execution defaults ---
DEFAULT_LLM_MODEL = "claude-sonnet-4-6"
DEFAULT_IDLE_TIMEOUT = 120  # No tokens for 2 min → something's wrong
DEFAULT_BATCH_TIMEOUT = 900  # 15 min hard ceiling for batch (non-streaming)
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 8192
MS_PER_SECOND = 1000
STREAM_CHUNK_MIN_SIZE = 4  # Minimum chars before emitting stream event
MAX_TOOL_ROUNDS = 25  # Default soft target for tool rounds
HARD_SAFETY_CAP = 100  # Absolute max — quality gates handle real termination
TOKEN_EXTENSION_STEP = 50_000
MAX_FS_SCAN_FILES = 20_000
ROLES_REQUIRING_FILE_WRITES = {"coder", "qa", "devops", "sre"}
MID_EXECUTION_CHECK_INTERVAL = 5  # Run quality check every N tool rounds
RIGOUR_CHECKPOINT_INTERVAL = 5  # Emit Rigour checkpoint every N tool rounds
_FS_IGNORE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".rigovo",
    "dist",
    "build",
    "release",
    "out",
}

# Per-role max_tokens — sized to what each role actually produces.
# Per-role max_tokens — sized to what each role actually produces.
# Coder needs room for full file contents. Planner (PM/EM/BDA) produces
# comprehensive execution plans with acceptance criteria and dependency graphs.
ROLE_MAX_TOKENS: dict[str, int] = {
    "lead": 4096,
    "planner": 8192,  # PM/EM/BDA: comprehensive execution plans
    "coder": 16384,  # Needs room for multi-file output
    "reviewer": 4096,
    "security": 4096,
    "qa": 8192,  # Test generation can be verbose
    "devops": 4096,
    "sre": 4096,
    "docs": 4096,
}

# ── RECLASSIFY signal detection ──────────────────────────────────────
# Agents can emit a RECLASSIFY signal in their output when they discover
# the initial classification was wrong. The signal is a structured block:
#
#   RECLASSIFY: infra
#   REASON: This task requires Docker and K8s setup, not a feature implementation.
#
# Or a JSON variant:
#   {"signal": "RECLASSIFY", "suggested_type": "infra", "reason": "..."}
#
# Only planner and lead roles can trigger reclassification.
RECLASSIFY_ALLOWED_ROLES = {"planner", "lead"}

_RECLASSIFY_TEXT_PATTERN = re.compile(
    r"RECLASSIFY\s*:\s*(\w+)\s*\n\s*REASON\s*:\s*(.+?)(?:\n|$)",
    re.IGNORECASE | re.DOTALL,
)


def _detect_reclassify_signal(
    text: str,
    role: str,
) -> tuple[bool, str, str]:
    """Detect a RECLASSIFY signal in agent output text.

    Returns:
        (detected, suggested_type, reason) — all empty strings if not detected.
    """
    if role not in RECLASSIFY_ALLOWED_ROLES:
        return False, "", ""

    # Try structured text pattern first
    match = _RECLASSIFY_TEXT_PATTERN.search(text)
    if match:
        return True, match.group(1).strip().lower(), match.group(2).strip()

    # Try JSON variant (agent may embed a JSON block)
    try:
        # Look for JSON block in the text
        json_match = re.search(r'\{[^{}]*"signal"\s*:\s*"RECLASSIFY"[^{}]*\}', text, re.IGNORECASE)
        if json_match:
            data = json.loads(json_match.group(0))
            if str(data.get("signal", "")).upper() == "RECLASSIFY":
                return (
                    True,
                    str(data.get("suggested_type", "")).strip().lower(),
                    str(data.get("reason", "")).strip(),
                )
    except (json.JSONDecodeError, ValueError):
        pass

    return False, "", ""


CONSULT_MAX_QUESTION_CHARS = 1200
CONSULT_MAX_RESPONSE_CHARS = 1200
SUBAGENT_MAX_SUBTASKS_PER_STEP = 3
SUBAGENT_MAX_ROUNDS = 10


@dataclass(frozen=True)
class RoleExecutionContract:
    """Shared specialist contract injected into role execution context."""

    goal_template: str
    allowed_tools: tuple[str, ...] = ()
    required_verifications: tuple[str, ...] = ()
    self_checklist: tuple[str, ...] = ()
    consultation_targets: tuple[str, ...] = ()
    spawn_permissions: tuple[str, ...] = ()
    completion_artifacts: tuple[str, ...] = ()
    risk_actions: tuple[str, ...] = ()
    learning_extractors: tuple[str, ...] = ()
    workflow_steps: tuple[str, ...] = ()  # Explicit write-execute-verify loop


ROLE_EXECUTION_CONTRACTS: dict[str, RoleExecutionContract] = {
    "planner": RoleExecutionContract(
        goal_template=(
            "Turn the task into an executable delivery plan with clear sequencing and risks."
        ),
        allowed_tools=("list_directory", "read_file", "search_codebase", "consult_agent"),
        required_verifications=("plan covers files, order, acceptance criteria, and constraints",),
        self_checklist=(
            "decide whether this is greenfield or existing-project work",
            "identify the starting owner and required specialists",
            "avoid unnecessary full-repo reconnaissance for brainstorming work",
        ),
        consultation_targets=("lead",),
        completion_artifacts=("implementation plan", "acceptance criteria", "risk summary"),
        learning_extractors=("planning heuristics", "project-shape patterns"),
    ),
    "coder": RoleExecutionContract(
        goal_template="Produce verified code changes and respond precisely to failing evidence.",
        allowed_tools=(
            "read_file",
            "write_file",
            "list_directory",
            "search_codebase",
            "run_command",
            "consult_agent",
            "spawn_subtask",
            "invoke_integration",
        ),
        required_verifications=(
            "build/test commands for touched code",
            "Rigour remediation packet",
        ),
        self_checklist=(
            "edit the smallest correct set of files",
            "execute verification after patching",
            "if remediation is active, patch against the exact failing evidence",
        ),
        consultation_targets=("reviewer", "security", "qa", "devops"),
        spawn_permissions=("bounded implementation subtask",),
        completion_artifacts=("files_changed", "verification evidence", "implementation summary"),
        risk_actions=("destructive command", "deploy/release", "privileged integration"),
        learning_extractors=("implementation patterns", "failure remediation patterns"),
        workflow_steps=(
            "WRITE: Create/modify files using write_file for each logical unit of work",
            "EXECUTE: Run build/compile via run_command (e.g. npm run build, python -m py_compile)",
            "VERIFY: Check output — if errors, go back to WRITE and fix immediately",
            "REPEAT for each logical unit of work until assignment is complete",
            "DONE: Only stop when build passes and your assignment is fully complete",
        ),
    ),
    "reviewer": RoleExecutionContract(
        goal_template=(
            "Independently verify implementation quality, correctness, and residual risk."
        ),
        allowed_tools=("read_file", "search_codebase", "run_command", "consult_agent"),
        required_verifications=("review verdict", "specific findings or explicit pass rationale"),
        self_checklist=(
            "review changed files, not stale assumptions",
            "escalate to security or lead when risk exceeds review scope",
        ),
        consultation_targets=("coder", "security", "lead"),
        completion_artifacts=("review verdict", "finding list", "handoff recommendation"),
        learning_extractors=("review heuristics", "missed-risk patterns"),
        workflow_steps=(
            "READ: Read all files changed by previous agents using read_file",
            "ANALYZE: Check for bugs, security issues, code quality, and adherence to plan",
            "VERIFY: Run tests if available using run_command to confirm correctness",
            "RESPOND: Either APPROVED or CHANGES_REQUESTED with specific file:line feedback",
        ),
    ),
    "qa": RoleExecutionContract(
        goal_template="Generate and verify tests that prove changed behavior.",
        allowed_tools=("read_file", "write_file", "run_command", "consult_agent"),
        required_verifications=("test execution results",),
        self_checklist=("cover changed flows", "report flaky or blocked verification explicitly"),
        consultation_targets=("coder", "reviewer", "security"),
        completion_artifacts=("test files", "test results"),
        learning_extractors=("test strategy", "flaky test signals"),
        workflow_steps=(
            "WRITE: Create test files using write_file targeting changed behavior",
            "EXECUTE: Run tests using run_command (e.g. pytest, npm test, cargo test)",
            "VERIFY: Check results — if failures, fix test OR flag the underlying bug",
            "REPEAT until all your tests pass",
            "DONE: Only stop when all tests pass and test coverage is adequate",
        ),
    ),
    "security": RoleExecutionContract(
        goal_template="Audit changed behavior for auth, data, and privilege risks.",
        allowed_tools=("read_file", "search_codebase", "consult_agent"),
        required_verifications=("security verdict",),
        self_checklist=("focus on auth, secrets, data flow, and privilege boundaries",),
        consultation_targets=("coder", "reviewer", "lead", "devops"),
        completion_artifacts=("security findings", "risk verdict"),
        learning_extractors=("security review patterns",),
    ),
    "devops": RoleExecutionContract(
        goal_template="Keep delivery, packaging, and deployment flow operational and safe.",
        allowed_tools=(
            "read_file",
            "write_file",
            "run_command",
            "consult_agent",
            "invoke_integration",
        ),
        required_verifications=("build/package/pipeline verification",),
        self_checklist=("treat deploy/release as risky actions",),
        consultation_targets=("sre", "security", "lead"),
        completion_artifacts=("pipeline/config files", "verification results"),
        risk_actions=("deploy/release", "external infra mutation", "privileged integration"),
        learning_extractors=("release and pipeline patterns",),
    ),
    "sre": RoleExecutionContract(
        goal_template="Protect reliability, rollback safety, and runtime operability.",
        allowed_tools=("read_file", "write_file", "run_command", "consult_agent"),
        required_verifications=("runtime/reliability checks",),
        self_checklist=("prefer reversible reliability improvements",),
        consultation_targets=("devops", "security", "lead"),
        completion_artifacts=("operability changes", "runtime checks"),
        learning_extractors=("reliability heuristics",),
    ),
    "docs": RoleExecutionContract(
        goal_template="Document the operator and user-facing truth of the implementation.",
        allowed_tools=("read_file", "write_file", "consult_agent"),
        required_verifications=("docs reflect shipped behavior",),
        self_checklist=("document real behavior, not intended behavior",),
        consultation_targets=("planner", "coder", "reviewer"),
        completion_artifacts=("documentation updates",),
        learning_extractors=("documentation patterns",),
    ),
    "lead": RoleExecutionContract(
        goal_template="Provide architectural direction and adjudicate cross-role conflict.",
        allowed_tools=("read_file", "search_codebase", "consult_agent"),
        required_verifications=("architectural verdict",),
        self_checklist=("decide when branching, consultation, or escalation is required",),
        consultation_targets=("planner", "coder", "reviewer", "security", "qa"),
        completion_artifacts=("architectural decision", "risk sign-off"),
        learning_extractors=("architecture decision patterns",),
    ),
}

RISKY_COMMAND_PATTERNS: tuple[tuple[re.Pattern[str], dict[str, str]], ...] = (
    (
        re.compile(r"\b(?:rm\s+-rf|terraform\s+destroy|kubectl\s+delete|dropdb)\b", re.IGNORECASE),
        {
            "kind": "destructive_command",
            "summary": "destructive infrastructure or filesystem command",
            "severity": "critical",
        },
    ),
    (
        re.compile(
            r"\b(?:terraform\s+apply|kubectl\s+apply|helm\s+(?:install|upgrade)|"
            r"flyctl\s+deploy|vercel(?:\s+deploy)?\s+--prod)\b",
            re.IGNORECASE,
        ),
        {"kind": "deploy", "summary": "deployment or infrastructure apply", "severity": "high"},
    ),
    (
        re.compile(r"\b(?:git\s+push|gh\s+release|npm\s+publish|docker\s+push)\b", re.IGNORECASE),
        {"kind": "release", "summary": "release or external publish action", "severity": "high"},
    ),
)

# Role-to-role consultation policy. Advisory-only, never full step completion.
#
# KEY RULE: Planner must NOT consult security/devops before code exists.
# Security and DevOps work on CODE — there is nothing for them to review
# until the Coder has written something. Planner may only consult Lead.
#
# All other roles may consult within their natural scope.
CONSULT_ALLOWED_TARGETS: dict[str, set[str]] = {
    "planner": {"lead"},  # NOT security/devops — no code yet
    "coder": {"reviewer", "security", "qa", "devops"},  # After writing — check correctness
    "reviewer": {"planner", "coder", "lead", "security"},
    "security": {"coder", "reviewer", "lead", "devops"},
    "qa": {"coder", "reviewer", "security"},
    "devops": {"sre", "lead", "security"},
    "sre": {"devops", "lead", "security"},
    "lead": {"planner", "coder", "reviewer", "security", "qa"},
}

# Max consultations per agent execution.
# Phase 5: raised from 1 to 3. Agents can consult multiple different targets,
# but per-target limit prevents chatbot loops (max 1 initial + 1 follow-up per target).
MAX_CONSULTS_PER_AGENT = 3
MAX_CONSULTS_PER_TARGET = 2  # 1 initial + 1 follow-up per target


def _resolve_consult_policy(
    state: TaskState | None,
) -> tuple[bool, int, int, dict[str, set[str]], int, int]:
    """Resolve consultation policy from state with safe defaults.

    Returns:
        (enabled, max_question_chars, max_response_chars, allowed_targets,
         max_consults_per_agent, max_consults_per_target)
    """
    enabled = True
    max_question_chars = CONSULT_MAX_QUESTION_CHARS
    max_response_chars = CONSULT_MAX_RESPONSE_CHARS
    allowed_targets = {k: set(v) for k, v in CONSULT_ALLOWED_TARGETS.items()}
    max_per_agent = MAX_CONSULTS_PER_AGENT
    max_per_target = MAX_CONSULTS_PER_TARGET

    if not state:
        return (
            enabled,
            max_question_chars,
            max_response_chars,
            allowed_targets,
            max_per_agent,
            max_per_target,
        )

    raw_policy = state.get("consultation_policy", {}) or {}
    if isinstance(raw_policy, dict):
        enabled = bool(raw_policy.get("enabled", enabled))
        q_chars = raw_policy.get("max_question_chars", max_question_chars)
        r_chars = raw_policy.get("max_response_chars", max_response_chars)
        if isinstance(q_chars, int) and q_chars > 100:
            max_question_chars = q_chars
        if isinstance(r_chars, int) and r_chars > 100:
            max_response_chars = r_chars

        # Configurable per-agent and per-target limits
        raw_per_agent = raw_policy.get("max_consults_per_agent")
        if isinstance(raw_per_agent, int) and 1 <= raw_per_agent <= 10:
            max_per_agent = raw_per_agent
        raw_per_target = raw_policy.get("max_consults_per_target")
        if isinstance(raw_per_target, int) and 1 <= raw_per_target <= 5:
            max_per_target = raw_per_target

        raw_targets = raw_policy.get("allowed_targets", {})
        if isinstance(raw_targets, dict):
            parsed: dict[str, set[str]] = {}
            for src_role, targets in raw_targets.items():
                if isinstance(src_role, str) and isinstance(targets, list):
                    parsed[src_role] = {str(t) for t in targets if str(t).strip()}
            if parsed:
                allowed_targets = parsed

    return (
        enabled,
        max_question_chars,
        max_response_chars,
        allowed_targets,
        max_per_agent,
        max_per_target,
    )


def _resolve_subagent_policy(state: TaskState | None) -> tuple[bool, int, int]:
    """Resolve sub-agent spawn policy from state with safe defaults."""
    enabled = True
    max_subtasks = SUBAGENT_MAX_SUBTASKS_PER_STEP
    max_rounds = SUBAGENT_MAX_ROUNDS
    if not state:
        return enabled, max_subtasks, max_rounds
    raw_policy = state.get("subagent_policy", {}) or {}
    if not isinstance(raw_policy, dict):
        return enabled, max_subtasks, max_rounds

    enabled = bool(raw_policy.get("enabled", enabled))
    raw_max_subtasks = raw_policy.get("max_subtasks_per_agent_step", max_subtasks)
    if isinstance(raw_max_subtasks, int) and raw_max_subtasks >= 0:
        max_subtasks = raw_max_subtasks
    raw_max_rounds = raw_policy.get("max_subtask_rounds", max_rounds)
    if isinstance(raw_max_rounds, int) and raw_max_rounds > 0:
        max_rounds = raw_max_rounds
    return enabled, max_subtasks, max_rounds


class BudgetExceededError(Exception):
    """Raised when the task's cost budget has been exceeded."""

    def __init__(self, spent: float, limit: float) -> None:
        self.spent = spent
        self.limit = limit
        super().__init__(f"Budget exceeded: ${spent:.4f} spent (limit ${limit:.2f})")


class AgentTimeoutError(Exception):
    """Raised when an agent exceeds its timeout."""

    def __init__(self, role: str, timeout: int) -> None:
        self.role = role
        self.timeout = timeout
        super().__init__(f"Agent '{role}' timed out after {timeout}s")


class RuntimeApprovalRequiredError(Exception):
    """Raised when a risky runtime action requires human approval."""

    def __init__(self, approval_event: dict[str, Any]) -> None:
        self.approval_event = approval_event
        super().__init__(approval_event.get("summary", "Runtime approval required"))


def _schema_type_ok(expected: str, value: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True


def _validate_contract(
    schema: dict[str, Any],
    payload: Any,
    path: str = "$",
) -> list[str]:
    """Minimal JSON-schema-like validation for input/output contracts."""
    if not isinstance(schema, dict) or not schema:
        return []

    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _schema_type_ok(expected_type, payload):
        return [f"{path}: expected type '{expected_type}'"]

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and payload not in enum_values:
        errors.append(f"{path}: value '{payload}' not in enum {enum_values}")

    if isinstance(payload, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in payload:
                    errors.append(f"{path}.{key}: required field missing")

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in payload and isinstance(child_schema, dict):
                    errors.extend(_validate_contract(child_schema, payload[key], f"{path}.{key}"))

    if isinstance(payload, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(payload):
                errors.extend(_validate_contract(item_schema, item, f"{path}[{idx}]"))

    return errors


def _contract_failure_result(
    state: TaskState,
    current_role: str,
    stage: str,
    violations: list[str],
) -> dict[str, Any]:
    events = list(state.get("events", []))
    events.append(
        {
            "type": "contract_failed",
            "role": current_role,
            "stage": stage,
            "violations": violations[:10],
        }
    )
    return {
        "status": f"contract_failed_{current_role}",
        "error": f"{stage} contract failed for '{current_role}'",
        "contract_stage": stage,
        "contract_violations": violations,
        "events": events,
    }


def _build_expert_context_block(
    current_role: str,
    verification_history: list[dict[str, Any]] | None = None,
    workspace_conventions: list[str] | None = None,
) -> str:
    """
    Build expert knowledge injection context for this role.

    Injects:
    - Past violations THIS role caused (from verification history)
    - Workspace conventions specific to this role
    Returns a short context block (< 500 chars) to inject into system message.
    """
    parts: list[str] = []

    # Extract past violations for this role
    if verification_history:
        role_violations: list[str] = []
        for entry in verification_history:
            if (entry.get("role") == current_role or entry.get("instance_id") == current_role) and (
                not entry.get("passed", True) and entry.get("failure_details")
            ):
                role_violations.extend(entry.get("failure_details", []))

        if role_violations:
            # Take top 2 unique violations
            unique_violations = list(set(role_violations))[:2]
            violation_text = ", ".join(
                v.split("]")[0] + "]" if "[" in v else v for v in unique_violations
            )
            parts.append(f"WATCH OUT: You previously failed {violation_text}. Avoid this.")

    # Add role-specific workspace conventions
    if workspace_conventions:
        role_conventions = [
            c
            for c in workspace_conventions
            if current_role.lower() in c.lower() or "all" in c.lower()
        ]
        if role_conventions:
            parts.append(f"CONVENTIONS: {role_conventions[0][:80]}")

    return " ".join(parts)


def _role_execution_contract(role: str) -> RoleExecutionContract:
    """Return the specialist execution contract for a role."""
    return ROLE_EXECUTION_CONTRACTS.get(
        role,
        RoleExecutionContract(
            goal_template="Execute your assigned specialist work with verification."
        ),
    )


def _role_contract_block(role: str) -> str:
    """Render a compact role contract block for prompt injection."""
    contract = _role_execution_contract(role)
    lines = [f"ROLE CONTRACT: {contract.goal_template}"]
    if contract.workflow_steps:
        lines.append("")
        lines.append("YOUR WORKFLOW (follow this exactly):")
        for i, step in enumerate(contract.workflow_steps, 1):
            lines.append(f"  {i}. {step}")
        lines.append("")
        lines.append(
            "You are a human engineer. You would NEVER submit work without verifying it first."
        )
    if contract.required_verifications:
        lines.append("REQUIRED VERIFICATION: " + "; ".join(contract.required_verifications))
    if contract.self_checklist:
        lines.append("SELF CHECKLIST: " + "; ".join(contract.self_checklist))
    if contract.consultation_targets:
        lines.append("CONSULT WHEN NEEDED: " + ", ".join(contract.consultation_targets))
    if contract.completion_artifacts:
        lines.append("COMPLETE WHEN YOU LEAVE: " + ", ".join(contract.completion_artifacts))
    return "\n".join(lines)


def _role_learning_block(
    state: TaskState,
    role: str,
    memory_section_text: str,
) -> str:
    """Render role-learning guidance from curated memory/promotion signals."""
    lines: list[str] = []
    retrieval_log = state.get("memory_retrieval_log", {}) or {}
    retrieved = retrieval_log.get(role, []) if isinstance(retrieval_log, dict) else []
    promotion_records = state.get("memory_promotion_records", []) or []
    behavior_change_audit = state.get("behavior_change_audit", []) or []
    pending_updates = (state.get("agent_learning_updates", {}) or {}).get(role, [])

    if isinstance(retrieved, list) and retrieved:
        top_score = 0.0
        for item in retrieved[:3]:
            if not isinstance(item, dict):
                continue
            try:
                top_score = max(top_score, float(item.get("score", 0.0) or 0.0))
            except (TypeError, ValueError):
                continue
        lines.append(
            "ROLE LEARNING: Apply recalled role memory first. "
            f"Retrieved {len(retrieved)} curated memories for this role"
            + (f" (top score {top_score:.2f})." if top_score > 0 else ".")
        )

    relevant_promotions = [
        record
        for record in promotion_records
        if isinstance(record, dict) and str(record.get("role", "")).strip() == role
    ]
    if relevant_promotions:
        lines.append(
            "PROMOTED HABITS: "
            f"{len(relevant_promotions)} prior role-learning promotion(s) exist for '{role}'. "
            "Prefer established workspace patterns over full rewrites."
        )

    relevant_audits = [
        audit
        for audit in behavior_change_audit
        if isinstance(audit, dict) and str(audit.get("role", "")).strip() == role
    ]
    if relevant_audits:
        latest = relevant_audits[-1]
        lines.append(
            "BEHAVIOR CHANGE AUDIT: "
            + str(
                latest.get("summary")
                or latest.get("reason")
                or latest.get("change")
                or "Role behavior was updated from promoted learning."
            )[:220]
        )

    if pending_updates:
        lines.append(
            "CURRENT TASK LEARNING CANDIDATES: "
            f"{len(pending_updates)} candidate pattern(s) already detected in this run. "
            "Reuse them if they materially improve the current step."
        )

    if not lines and memory_section_text:
        lines.append(
            "ROLE LEARNING: Use the recalled memory section as behavioral guidance. "
            "Do not ignore established workspace patterns."
        )

    return "\n".join(lines)


def _format_jsonish(value: Any) -> str:
    """Render structured values compactly for prompts."""
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    except TypeError:
        return str(value)


def _violation_fingerprint(item: dict[str, Any]) -> str:
    """Stable fingerprint for a violation — gate_id + file_path (ignoring line/message)."""
    return f"{item.get('gate_id', '?')}:{item.get('file_path', '')}"


def _build_persistence_warnings(state: TaskState, active_fix_packet: dict[str, Any]) -> list[str]:
    """Return warning lines for violations that persisted through the previous retry cycle.

    Compares current fix-packet items against the most recent gate_history entry
    that preceded them.  A violation is 'persisting' when the same gate_id+file_path
    pair appeared in the previous gate run, meaning the agent's last attempt did NOT
    remove it.
    """
    current_items = active_fix_packet.get("items", [])
    if not current_items:
        return []

    gate_history = list(state.get("gate_history", []) or [])
    # Need at least two entries: one before the latest retry and one after
    if len(gate_history) < 2:
        return []

    current_fps = {_violation_fingerprint(item) for item in current_items}

    # Walk backwards through gate_history looking for the last FAILED entry
    # that is NOT the very latest one (which represents the current failure).
    # We compare against that earlier failure to detect persistence.
    prev_violations: list[dict[str, Any]] = []
    for entry in reversed(gate_history[:-1]):
        if isinstance(entry, dict) and not entry.get("passed", True):
            prev_violations = [v for v in (entry.get("violations") or []) if isinstance(v, dict)]
            break

    if not prev_violations:
        return []

    prev_fps = {_violation_fingerprint(v) for v in prev_violations}
    persisting_fps = current_fps & prev_fps

    if not persisting_fps:
        return []

    warnings: list[str] = []
    for item in current_items:
        if _violation_fingerprint(item) in persisting_fps:
            file_path = item.get("file_path", "unknown")
            gate_id = item.get("gate_id", "?")
            suggestion = item.get("suggestion", "")
            warn_line = (
                f"  • [{gate_id}] {file_path} — your previous attempt did NOT resolve this. "
                "Apply a DIFFERENT, more targeted approach."
            )
            if suggestion:
                warn_line += f" Suggested fix: {suggestion}"
            warnings.append(warn_line)
    return warnings


def _build_surgical_fix_block(
    state: TaskState,
    active_fix_packet: dict[str, Any],
    retry_count: int,
    max_retries: int,
) -> str:
    """Build the SURGICAL FIX MODE system-prompt block for retry executions.

    This block is injected into the system prompt (highest priority) instead of
    as a user message (low priority) so the LLM treats it as a mandatory constraint
    rather than advisory guidance.
    """
    items: list[dict[str, Any]] = active_fix_packet.get("items", [])
    affected_files = list(
        dict.fromkeys(  # preserve order, deduplicate
            item.get("file_path", "") for item in items if item.get("file_path")
        )
    )

    lines: list[str] = [
        "═══════════════════════════════════════════════════════",
        f"SURGICAL FIX MODE  (Retry {retry_count}/{max_retries})",
        "═══════════════════════════════════════════════════════",
        "You MUST apply the exact fixes below. Rules:",
        "  1. Read ONLY the files listed in this fix packet — do not explore unrelated files.",
        "  2. Apply each fix precisely as described — do not re-architect the whole solution.",
        "  3. Call write_file for every file you change.",
        "  4. Do NOT add new features, refactor unrelated code, or add extra dependencies.",
        "  5. After applying all fixes, stop. Do not continue with other work.",
        "",
    ]

    # Inject persistence warnings when the same violation survived a previous attempt
    persistence_warnings = _build_persistence_warnings(state, active_fix_packet)
    if persistence_warnings:
        lines += [
            "⚠️  PERSISTENT VIOLATIONS — your last attempt did NOT fix these:",
        ]
        lines += persistence_warnings
        lines += ["", "You MUST use a different approach for each item above.", ""]

    # Rigour explain — human-readable analysis from `rigour explain`
    explain_text = active_fix_packet.get("explain_text", "")
    if explain_text:
        lines += [
            "── RIGOUR ANALYSIS ──",
            explain_text,
            "",
        ]

    lines.append("VIOLATIONS TO FIX:")
    for i, item in enumerate(items, 1):
        fp = item.get("file_path", "unknown")
        gid = item.get("gate_id", "?")
        msg = item.get("message", "?")
        sug = item.get("suggestion", "")
        line_no = item.get("line")
        loc = f":{line_no}" if line_no else ""
        lines.append(f"  {i}. [{gid}] {fp}{loc}")
        lines.append(f"     Issue: {msg}")
        if sug:
            lines.append(f"     Fix: {sug}")
        # Step-by-step instructions from Rigour Fix Packet v3
        for step in item.get("instructions", []):
            lines.append(f"     • {step}")

    if affected_files:
        lines += ["", "Files requiring changes: " + ", ".join(affected_files)]

    # Escalating urgency: after multiple failed attempts, push for deletion-first strategy
    if retry_count >= 3:
        lines += [
            "",
            f"FINAL WARNING: This is retry {retry_count}/{max_retries}.",
            "If you cannot fix these violations, REMOVE the offending code rather than",
            "trying alternative approaches. Focus on the SIMPLEST possible fix:",
            "  - Delete unused imports",
            "  - Simplify overly complex functions by splitting or removing code",
            "  - Remove code that triggers the gate instead of trying to make it work",
            "  - Prefer deletion over addition",
        ]
    elif retry_count >= 2:
        lines += [
            "",
            "WARNING: Previous attempts have not resolved these violations.",
            "Use a SIMPLER approach. If the code is triggering complexity or size gates,",
            "consider reducing the code rather than restructuring it.",
        ]

    lines.append("═══════════════════════════════════════════════════════")
    return "\n".join(lines)


async def _run_mid_execution_check(
    project_root: str,
    files: list[str],
) -> list[dict[str, Any]] | None:
    """Run a lightweight Rigour check mid-execution to catch drift early.

    Non-blocking (uses run_in_executor). Parses Rigour's ``failures[]``
    output and surfaces only critical/high issues — don't distract the
    agent with low-severity warnings mid-run.

    Returns a list of violation dicts or None.
    """
    from rigovo.infrastructure.quality.rigour_gate import RigourQualityGate

    binary = RigourQualityGate._find_binary(project_root)
    if not binary:
        return None
    try:
        cmd = RigourQualityGate._build_cmd(
            binary,
            "check",
            "--json",
            "--deep",
            *files[:10],
        )
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                cwd=project_root,
            ),
        )
        if not result.stdout.strip():
            return None
        data = json.loads(result.stdout)
        # Parse Rigour's actual output shape: {"failures": [...]}
        failures = data.get("failures", [])
        violations = [
            {
                "gate_id": f.get("id", ""),
                "message": f.get("title", f.get("details", "")),
                "severity": f.get("severity", "medium"),
                "files": f.get("files", []),
                "hint": f.get("hint", ""),
            }
            for f in failures
            if f.get("severity") in ("critical", "high")
        ]
        return violations or None
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


def _active_fix_packet(state: TaskState) -> dict[str, Any] | None:
    """Normalize active fix packet from current state."""
    packet = state.get("active_fix_packet") or state.get("fix_packet")
    if isinstance(packet, dict):
        return packet
    fix_packets = state.get("fix_packets", [])
    if isinstance(fix_packets, list) and fix_packets:
        return {
            "summary": str(fix_packets[-1]),
            "raw": fix_packets[-1],
            "remediation_phase": "diagnose",
        }
    return None


def _step_objective(state: TaskState, agent_config: dict[str, Any], role: str) -> str:
    """Return the explicit objective for the current role."""
    assignment = str(agent_config.get("assignment", "") or "").strip()
    if assignment:
        return assignment
    completion_contract = state.get("classification", {}).get("completion_contract")
    if isinstance(completion_contract, dict):
        by_role = completion_contract.get(role)
        if isinstance(by_role, str) and by_role.strip():
            return by_role.strip()
    return f"Advance the task for role '{role}' and leave verified, handoff-ready output."


def _required_consultations(state: TaskState, role: str) -> list[dict[str, Any]]:
    """Return mandatory consultation edges for the current role."""
    raw = state.get("classification", {}).get("consultation_requirements", [])
    if not isinstance(raw, list):
        return []
    required: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        from_role = str(item.get("from_role", "")).strip()
        if from_role == role:
            required.append(item)
    return required


def _pending_consultations(agent_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return consultation requests still awaiting a response."""
    responses = {
        str(msg.get("linked_to", "")).strip()
        for msg in agent_messages
        if msg.get("type") == "consult_response"
    }
    pending: list[dict[str, Any]] = []
    for msg in agent_messages:
        if msg.get("type") != "consult_request":
            continue
        if msg.get("status") == "answered" or str(msg.get("id", "")) in responses:
            continue
        pending.append(
            {
                "message_id": str(msg.get("id", "")),
                "from_role": str(msg.get("from_role", "")),
                "to_role": str(msg.get("to_role", "")),
                "content": str(msg.get("content", ""))[:240],
                "status": str(msg.get("status", "pending")),
            }
        )
    return pending


def _collect_event_records(
    prior: list[dict[str, Any]] | None,
    events: list[dict[str, Any]],
    allowed_types: set[str],
) -> list[dict[str, Any]]:
    """Merge prior state records with newly emitted event records."""
    merged: list[dict[str, Any]] = list(prior or [])
    merged.extend(event for event in events if event.get("type") in allowed_types)
    return merged


def _approval_records_from_events(
    state: TaskState,
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect governance approval records from state + new events."""
    risk_action_queue = _collect_event_records(
        state.get("risk_action_queue"),
        events,
        {"risk_action_evaluated", "approval_required", "approval_denied"},
    )
    required_approval_actions = _collect_event_records(
        state.get("required_approval_actions"),
        events,
        {"approval_required"},
    )
    return risk_action_queue, required_approval_actions


def _evaluate_risky_action(
    *,
    role: str,
    tool_name: str,
    tool_input: dict[str, Any],
    state: TaskState | None,
) -> dict[str, Any] | None:
    """Classify risky actions before execution and attach governance policy."""
    if state is None:
        return None
    tier = str(state.get("tier", "auto") or "auto").lower()
    action: dict[str, Any] | None = None

    if tool_name == "invoke_integration":
        kind = str(tool_input.get("kind", "integration") or "integration")
        operation = str(tool_input.get("operation", "") or "").strip()
        action = {
            "kind": f"{kind}_integration",
            "summary": f"{kind} integration operation '{operation or 'unknown'}'",
            "severity": "high" if operation.lower() not in {"read", "search", "list"} else "medium",
        }
    elif tool_name == "run_command":
        command = str(tool_input.get("command", "") or "").strip()
        for pattern, metadata in RISKY_COMMAND_PATTERNS:
            if pattern.search(command):
                action = {**metadata, "command": command[:240]}
                break

    if action is None:
        return None

    severity = str(action.get("severity", "medium"))
    decision = "allow"
    requires_approval_even_in_auto = severity == "critical"
    if severity in {"high", "critical"}:
        if tier == "approve":
            decision = "approval_required"
        elif tier == "notify":
            decision = "notify_only"
        elif tier == "auto" and requires_approval_even_in_auto:
            decision = "approval_required"

    return {
        **action,
        "type": "risk_action_evaluated",
        "role": role,
        "tool_name": tool_name,
        "decision": decision,
        "tier": tier,
        "policy": decision,
        "requires_approval_even_in_auto": requires_approval_even_in_auto,
    }


def _build_agent_messages(
    state: TaskState,
    system_prompt: str,
    agent_config: dict[str, Any],
    current_role: str,
    memory_section_text: str = "",
) -> list[dict[str, Any]]:
    """Build the message list for an agent execution."""
    # Resolve base role for contract lookups — instance IDs like "software-engineer-1"
    # need to map to "coder" for workflow contract injection.
    from rigovo.application.graph.agent_identity import resolve_base_role as _resolve_br

    _base_role_for_contract = _resolve_br(state, current_role)

    # Context engineering: assemble rich per-agent context
    context_builder = ContextBuilder()
    agent_context = context_builder.build(
        role=current_role,
        project_snapshot=state.get("project_snapshot"),
        enrichment_text=agent_config.get("enrichment_context", ""),
        previous_outputs=state.get("agent_outputs"),
        agent_messages=state.get("agent_messages"),
        specialisation=agent_config.get("specialisation", ""),
        task_type=state.get("classification", {}).get("task_type", ""),
        knowledge_graph=state.get("code_knowledge_graph"),
        resume_context=state.get("resume_context"),
        context_package=agent_config.get("context_package"),
        rigour_conventions=state.get("rigour_conventions", ""),
    )
    if memory_section_text:
        agent_context.memory_section = memory_section_text
    full_context = agent_context.to_full_context()
    if full_context:
        system_prompt += f"\n\n{full_context}"

    # Inject expert knowledge specific to this role's past violations and conventions
    expert_block = _build_expert_context_block(
        current_role,
        verification_history=state.get("verification_history"),
        workspace_conventions=agent_config.get("custom_rules"),
    )
    if expert_block:
        system_prompt += f"\n\n{expert_block}"

    # Use base role for contract lookup — ROLE_EXECUTION_CONTRACTS is keyed by
    # base roles ("coder", "qa") not instance IDs ("software-engineer-1").
    role_contract_block = _role_contract_block(_base_role_for_contract)
    if role_contract_block:
        system_prompt += f"\n\n{role_contract_block}"

    role_learning_block = _role_learning_block(state, current_role, memory_section_text)
    if role_learning_block:
        system_prompt += f"\n\n{role_learning_block}"

    # ── Surgical fix mode: inject mandatory constraints into system prompt ──
    # Injecting into the system prompt gives these instructions the highest
    # priority in the LLM's attention hierarchy — far more effective than
    # appending as user messages after the original task description.
    _retry_fix_packet = _active_fix_packet(state)
    _retry_count = int(state.get("retry_count", 0) or 0)
    _max_retries = int(state.get("max_retries", 5) or 5)
    if _retry_fix_packet and _retry_count > 0:
        surgical_block = _build_surgical_fix_block(
            state, _retry_fix_packet, _retry_count, _max_retries
        )
        system_prompt += f"\n\n{surgical_block}"

    # Role-specific action imperatives — forces execution not description
    # Intent-aware: brainstorm/think mode tells planner to reason, not read codebase
    intent_profile = state.get("intent_profile") or {}
    planner_mode = intent_profile.get("planner_mode", "survey")
    intent_type = intent_profile.get("intent", "build")
    classification = state.get("classification", {})
    intent = classification.get("task_type", state.get("task_type", "unknown"))
    workspace_mode = classification.get("workspace_type", "existing_project")
    target_root = str(state.get("target_root") or state.get("project_root") or ".")
    target_mode = str(state.get("target_mode") or workspace_mode)

    if current_role == "planner" and planner_mode == "think":
        _planner_imperative = (
            "This is a BRAINSTORMING/RESEARCH task. DO NOT read the codebase. "
            "DO NOT use read_file or list_directory. Instead, think through the "
            "problem conceptually and produce your analysis from the task description alone. "
            "Focus on ideas, architecture options, trade-offs, and recommendations."
        )
    elif current_role == "planner" and intent_type == "research":
        _planner_imperative = (
            "This is a RESEARCH/INVESTIGATION task. Read only the files directly relevant "
            "to the investigation. Do NOT survey the entire codebase. Limit your file reads "
            "to the specific area under investigation."
        )
    elif current_role == "planner" and workspace_mode in {"new_project", "new_subfolder_project"}:
        _planner_imperative = (
            "This is a greenfield build target. Do NOT begin with broad codebase "
            "reconnaissance. First produce the product, architecture, folder, and "
            "implementation plan for the target root. Only inspect files if they are "
            "directly relevant to the chosen target boundary."
        )
    else:
        _planner_imperative = "Read the codebase now and produce the implementation plan."

    action_imperatives: dict[str, str] = {
        "planner": _planner_imperative,
        "coder": "Read the relevant files and write all changed files now using write_file.",
        "reviewer": "Read the changed files now and produce your review verdict.",
        "security": "Read the changed files now and produce your security audit.",
        "qa": (
            "Read the changed files and write the test files now using write_file, then run them."
        ),
        "devops": "Read existing configs now and write all updated files using write_file.",
        "sre": (
            "Read the changed files now and write any missing reliability code using write_file."
        ),
        "lead": "Read the plan and relevant architecture files now and give your verdict.",
    }
    action_imperative = action_imperatives.get(current_role, "Execute your task now.")

    # Override imperative for surgical retry: direct the agent straight to the violated files
    if _retry_fix_packet and _retry_count > 0 and current_role in ROLES_REQUIRING_FILE_WRITES:
        _fix_files = list(
            dict.fromkeys(
                item.get("file_path", "")
                for item in _retry_fix_packet.get("items", [])
                if item.get("file_path")
            )
        )
        _files_str = ", ".join(_fix_files[:4]) if _fix_files else "the violated files"
        action_imperative = (
            f"SURGICAL FIX: Read {_files_str} and apply the fixes in SURGICAL FIX MODE above. "
            "call write_file for every changed file. Do not read any other files."
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Task: {state['description']}\n\n"
                f"Intent: {intent}\n"
                f"Workspace mode: {workspace_mode}\n"
                f"Target mode: {target_mode}\n"
                f"Target root: {target_root}\n"
                f"Current objective: {_step_objective(state, agent_config, current_role)}\n"
                f"START NOW: {action_imperative}\n"
                "Do not describe what you will do. Do it."
            ),
        },
    ]

    # Retry acknowledgement — the full fix details are already in the system prompt
    # (SURGICAL FIX MODE block injected above).  We add only a short user-turn
    # reminder so the conversation starts with the right framing; the system-prompt
    # block carries the authoritative constraint.
    active_fix_packet = _active_fix_packet(state)
    if active_fix_packet and _retry_count > 0:
        violation_count = len(active_fix_packet.get("items", []))
        messages.append(
            {
                "role": "user",
                "content": (
                    f"RETRY {_retry_count}/{_max_retries}: "
                    f"Fix the {violation_count} violation(s) listed in SURGICAL FIX MODE "
                    "in your system prompt. Apply fixes now."
                ),
            }
        )

    mandatory_consults = _required_consultations(state, current_role)
    if mandatory_consults:
        messages.append(
            {
                "role": "user",
                "content": (
                    "MANDATORY CONSULTATIONS: "
                    + _format_jsonish(mandatory_consults)
                    + ". If the current work materially touches these areas, "
                    "consult before final handoff."
                ),
            }
        )

    return messages


def _parse_state_uuid(value: Any) -> UUID | None:
    """Parse UUID values from state fields safely."""
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _resolve_memory_context_for_role(
    state: TaskState,
    current_role: str,
    memory_repo: MemoryRepository | None,
    embedding_provider: EmbeddingProvider | None,
    memory_retriever: MemoryRetriever | None,
) -> tuple[str, dict[str, str], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Retrieve, rank, and render relevant memory context for one role."""
    existing = state.get("memory_context_by_role", {}) or {}
    memory_context_by_role: dict[str, str] = {}
    if isinstance(existing, dict):
        memory_context_by_role = {str(role): str(text) for role, text in existing.items()}
    existing_log = state.get("memory_retrieval_log", {}) or {}
    memory_retrieval_log: dict[str, list[dict[str, Any]]] = {}
    if isinstance(existing_log, dict):
        for role, entries in existing_log.items():
            if isinstance(entries, list):
                memory_retrieval_log[str(role)] = [e for e in entries if isinstance(e, dict)]
    if current_role in memory_context_by_role:
        return (
            memory_context_by_role[current_role],
            memory_context_by_role,
            memory_retrieval_log,
            [],
        )

    if not memory_repo or not embedding_provider:
        return "", memory_context_by_role, memory_retrieval_log, []

    workspace_id = _parse_state_uuid(state.get("workspace_id"))
    if workspace_id is None:
        return "", memory_context_by_role, memory_retrieval_log, []

    task_description = str(state.get("description", "")).strip()
    if not task_description:
        return "", memory_context_by_role, memory_retrieval_log, []

    retriever = memory_retriever or MemoryRetriever()
    runtime = RigourMemoryRuntime(
        memory_repo=memory_repo,
        embedding_provider=embedding_provider,
        memory_retriever=retriever,
    )
    events: list[dict[str, Any]] = []
    try:
        recall = await runtime.rigour_recall(
            workspace_id=workspace_id,
            task_description=task_description,
            role=current_role,
            limit=24,
        )
        memory_section_text = recall.context_text
        memory_context_by_role[current_role] = memory_section_text
        memory_retrieval_log[current_role] = list(recall.retrieval_log)

        events.append(
            {
                "type": "memories_retrieved",
                "role": current_role,
                "count": int(recall.count),
                "avg_score": round(float(recall.avg_score), 3),
                "top_score": round(float(recall.top_score), 3),
            }
        )
        return memory_section_text, memory_context_by_role, memory_retrieval_log, events
    except Exception as exc:
        logger.warning("Memory retrieval failed for role '%s': %s", current_role, exc)
        events.append(
            {
                "type": "memory_retrieval_failed",
                "role": current_role,
                "error": str(exc),
            }
        )
        memory_context_by_role[current_role] = ""
        return "", memory_context_by_role, memory_retrieval_log, events


def _check_budget_guards(state: TaskState, current_role: str) -> dict[str, Any] | None:
    """Check budget and token limits with soft warnings and auto-compaction.

    Returns error state dict if token limit exceeded, None otherwise.
    Cost overruns are logged as warnings — user should be informed, not blocked.
    """
    accumulated_cost = sum(v.get("cost", 0) for v in state.get("cost_accumulator", {}).values())
    budget_limit = state.get("budget_max_cost_per_task", 0)
    if budget_limit > 0 and accumulated_cost >= budget_limit:
        logger.warning(
            "Budget warning: $%.4f spent (soft limit $%.2f) — continuing task. "
            "Adjust budget.max_cost_per_task in rigovo.yml to change the limit.",
            accumulated_cost,
            budget_limit,
        )

    accumulated_tokens = sum(v.get("tokens", 0) for v in state.get("cost_accumulator", {}).values())
    token_limit = state.get("budget_max_tokens_per_task", 0)
    budget_policy = state.get("budget_policy", {}) or {}
    warning_ratio = float(budget_policy.get("token_warning_ratio", 0.85) or 0.85)
    warning_ratio = min(0.99, max(0.50, warning_ratio))
    warning_threshold = int(token_limit * warning_ratio) if token_limit > 0 else 0
    warned_at = int(state.get("budget_warning_emitted_at_tokens", 0) or 0)
    if (
        token_limit > 0
        and accumulated_tokens >= warning_threshold
        and accumulated_tokens > warned_at
    ):
        events = list(state.get("events", []))
        events.append(
            {
                "type": "budget_warning_internal",
                "role": current_role,
                "tokens_used": int(accumulated_tokens),
                "token_limit": int(token_limit),
                "warning_ratio": warning_ratio,
            }
        )
        state["events"] = events
        state["budget_warning_emitted_at_tokens"] = int(accumulated_tokens)

    if token_limit > 0 and accumulated_tokens >= token_limit:
        if _apply_auto_compaction_on_pressure(state, current_role, accumulated_tokens, token_limit):
            return None

        max_soft_extensions = int(budget_policy.get("max_soft_extensions_per_task", 3) or 3)
        soft_fail = bool(budget_policy.get("soft_fail_on_token_limit", False))
        extensions_used = int(state.get("budget_soft_extensions_used", 0) or 0)
        extension_step = int(
            budget_policy.get("compaction_token_extension_step", TOKEN_EXTENSION_STEP)
            or TOKEN_EXTENSION_STEP
        )
        extension_step = max(10_000, extension_step)
        if soft_fail and extensions_used < max_soft_extensions:
            new_limit = int(token_limit + extension_step)
            events = list(state.get("events", []))
            events.append(
                {
                    "type": "budget_soft_extension_applied",
                    "role": current_role,
                    "tokens_used": int(accumulated_tokens),
                    "previous_limit": int(token_limit),
                    "new_limit": int(new_limit),
                    "soft_extensions_used": int(extensions_used + 1),
                }
            )
            state["events"] = events
            state["budget_max_tokens_per_task"] = int(new_limit)
            state["budget_soft_extensions_used"] = int(extensions_used + 1)
            return None

        requested_extension = max(TOKEN_EXTENSION_STEP, int(token_limit * 0.25))
        summary = (
            "Token limit reached. Approve an extension to continue this run "
            f"for '{current_role}'. Used {accumulated_tokens:,}/{token_limit:,} tokens."
        )
        return {
            "status": "awaiting_budget_approval",
            "error": (
                f"Token limit exceeded: {accumulated_tokens:,} tokens (limit {token_limit:,})"
            ),
            "approval_status": "pending",
            "approval_data": {
                "checkpoint": "token_budget_exceeded",
                "summary": summary,
                "token_limit": int(token_limit),
                "tokens_used": int(accumulated_tokens),
                "requested_extension_tokens": int(requested_extension),
                "current_role": current_role,
            },
            "events": [
                *state.get("events", []),
                {
                    "type": "budget_exceeded",
                    "role": current_role,
                    "tokens_used": accumulated_tokens,
                    "token_limit": token_limit,
                },
                {
                    "type": "approval_requested",
                    "checkpoint": "token_budget_exceeded",
                    "summary": {
                        "token_limit": int(token_limit),
                        "tokens_used": int(accumulated_tokens),
                        "requested_extension_tokens": int(requested_extension),
                        "role": current_role,
                    },
                },
            ],
        }
    return None


def _apply_auto_compaction_on_pressure(
    state: TaskState,
    current_role: str,
    accumulated_tokens: int,
    token_limit: int,
) -> bool:
    """Apply multi-stage auto-compaction and token replay pointer updates."""
    budget_policy = state.get("budget_policy", {}) or {}
    enabled = bool(budget_policy.get("auto_compact_on_token_pressure", False))
    if not enabled:
        return False

    max_compactions = int(budget_policy.get("max_auto_compactions_per_task", 3) or 3)
    used_compactions = int(state.get("budget_auto_compactions", 0) or 0)
    if used_compactions >= max_compactions:
        return False

    extension_step = int(
        budget_policy.get("compaction_token_extension_step", TOKEN_EXTENSION_STEP)
        or TOKEN_EXTENSION_STEP
    )
    extension_step = max(10_000, extension_step)

    # Stage A: remove low-signal events/artifacts.
    original_events = list(state.get("events", []))
    drop_types = {
        "token_stream",
        "tool_output_chunk",
        "debug",
    }
    filtered_events = [
        ev
        for ev in original_events
        if not (isinstance(ev, dict) and str(ev.get("type", "")) in drop_types)
    ]
    if len(filtered_events) > 160:
        filtered_events = filtered_events[-160:]
    dropped_events = max(0, len(original_events) - len(filtered_events))

    # Stage B: compact agent outputs into bounded summaries.
    compacted_agent_outputs: dict[str, dict[str, Any]] = {}
    for role, output in (state.get("agent_outputs", {}) or {}).items():
        if not isinstance(output, dict):
            continue
        summary = str(output.get("summary", "")).strip()
        compacted_agent_outputs[str(role)] = {
            "summary": (summary[:280] + "...") if len(summary) > 280 else summary,
            "files_changed": list(output.get("files_changed", []))[:10],
            "tokens": int(output.get("tokens", 0) or 0),
        }

    # Stage C: cross-agent synthesis + contradiction preservation hints.
    contradiction_flags: list[str] = []
    synth_lines: list[str] = []
    for role, compact in compacted_agent_outputs.items():
        line = f"{role}: {compact.get('summary', '')}".strip()
        synth_lines.append(line)
        text = str(compact.get("summary", "")).lower()
        if "failed" in text and "complete" in text:
            contradiction_flags.append(role)
    synthesis = " | ".join(synth_lines)[:1200]

    next_limit = int(token_limit + extension_step)
    checkpoints = list(state.get("compaction_checkpoints", []))
    checkpoint_id = f"cmp-{int(time.time() * 1000)}-{used_compactions + 1}"
    checkpoint = {
        "id": checkpoint_id,
        "role": current_role,
        "tokens_used": int(accumulated_tokens),
        "token_limit_before": int(token_limit),
        "token_limit_after": int(next_limit),
        "dropped_events": int(dropped_events),
        "replay_pointer": {
            "events_kept": len(filtered_events),
            "agent_outputs_kept": len(compacted_agent_outputs),
        },
        "contradiction_flags": contradiction_flags,
        "created_at": time.time(),
    }
    checkpoints.append(checkpoint)

    events = filtered_events
    events.append(
        {
            "type": "auto_compaction_applied",
            "role": current_role,
            "checkpoint_id": checkpoint_id,
            "dropped_events": int(dropped_events),
            "new_token_limit": int(next_limit),
            "stage_a": "low_signal_prune",
            "stage_b": "semantic_compaction",
            "stage_c": "cross_agent_synthesis",
        }
    )

    state["events"] = events
    state["budget_max_tokens_per_task"] = int(next_limit)
    state["budget_auto_compactions"] = int(used_compactions + 1)
    state["compaction_checkpoints"] = checkpoints
    state["compaction_synthesis"] = synthesis
    return True


def _resolve_tool_definitions(
    agent_config: dict[str, Any], current_role: str
) -> list[dict[str, Any]]:
    """Resolve tool names in agent_config to full tool definitions for the LLM."""
    role_defs = get_engineering_tools(current_role)
    configured = agent_config.get("tools")
    if configured is None:
        return role_defs
    if not isinstance(configured, list) or not configured:
        return []

    by_name = {tool.get("name", ""): tool for tool in role_defs if tool.get("name")}
    # Allow explicitly-configured ecosystem tool when policy enables it,
    # even if not part of legacy role defaults.
    if "invoke_integration" in configured and "invoke_integration" in TOOL_DEFINITIONS:
        by_name.setdefault("invoke_integration", TOOL_DEFINITIONS["invoke_integration"])

    resolved: list[dict[str, Any]] = []
    for name in configured:
        tool_def = by_name.get(str(name))
        if tool_def:
            resolved.append(tool_def)
    return resolved


def _derive_project_id(project_root: Any) -> UUID | None:
    root = str(project_root or "").strip()
    if not root:
        return None
    return uuid5(NAMESPACE_URL, root)


def _new_message_id(agent_messages: list[dict[str, Any]]) -> str:
    """Generate a stable message id for inter-agent consult records."""
    return f"msg-{int(time.time() * 1000)}-{len(agent_messages) + 1}"


def _handle_consult_agent(
    state: TaskState,
    from_role: str,
    tool_input: dict[str, Any],
    agent_messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> str:
    """
    Handle an inter-agent consultation request.

    Phase 5: Multi-turn consultation support.
    - Agents can consult up to MAX_CONSULTS_PER_AGENT different targets
    - Per-target limit: MAX_CONSULTS_PER_TARGET (1 initial + 1 follow-up)
    - Follow-ups reference a prior consultation via thread_id

    The consultation is asynchronous by design:
    - If the target role already has output, return it immediately.
    - Otherwise enqueue a pending request that the target role will see
      in its context and auto-fulfill when it completes.
    """
    (
        enabled,
        max_question_chars,
        max_response_chars,
        policy_targets,
        max_per_agent,
        max_per_target,
    ) = _resolve_consult_policy(state)
    if not enabled:
        return json.dumps({"status": "error", "error": "Consultation is disabled by policy"})

    # Count total consultations from this agent
    consults_so_far = sum(
        1
        for m in agent_messages
        if m.get("type") == "consult_request" and m.get("from_role") == from_role
    )
    if consults_so_far >= max_per_agent:
        return json.dumps(
            {
                "status": "blocked",
                "reason": "consultation_limit_reached",
                "note": (
                    f"'{from_role}' has already consulted {consults_so_far} time(s). "
                    f"Max is {max_per_agent}. Proceed with your work using "
                    "the information you have."
                ),
            }
        )

    team_agents = state.get("team_config", {}).get("agents", {})
    to_target = str(tool_input.get("to_role", "")).strip()
    question = str(tool_input.get("question", "")).strip()

    if not to_target:
        return json.dumps({"status": "error", "error": "Missing required field: to_role"})
    if not question:
        return json.dumps({"status": "error", "error": "Missing required field: question"})

    # Resolve to_target: could be an instance_id or a base role name.
    # If it's a base role, find the first instance of that role.
    # Only the first instance is consulted; other instances of the same role are ignored.
    to_role = to_target
    if to_target not in team_agents:
        # Try to find an instance by role name
        for iid, cfg in team_agents.items():
            if cfg.get("role") == to_target:
                to_role = iid
                break
        else:
            return json.dumps({"status": "error", "error": f"Unknown agent: {to_target}"})

    # Gap #1: Prevent self-consultation — agents cannot consult themselves
    if to_role == from_role:
        return json.dumps(
            {
                "status": "error",
                "error": "Agents cannot consult themselves. Seek guidance from a different role.",
            }
        )

    # Resolve the base role of from_role for policy checking
    from_base_role = team_agents.get(from_role, {}).get("role", from_role)
    to_base_role = team_agents.get(to_role, {}).get("role", to_role)

    # Also block same-base-role consultation (e.g., coder-1 consulting coder-2)
    if from_base_role == to_base_role:
        return json.dumps(
            {
                "status": "error",
                "error": (
                    f"Cannot consult another '{to_base_role}' instance. "
                    "Consult a different role for independent perspective."
                ),
            }
        )

    allowed_targets = policy_targets.get(from_base_role, set())
    if to_base_role not in allowed_targets and to_role not in allowed_targets:
        return json.dumps(
            {
                "status": "error",
                "error": (
                    f"Consultation from role '{from_base_role}' to role '{to_base_role}' "
                    f"is not allowed by policy. Proceed with your work independently."
                ),
            }
        )

    # Phase 5: Per-target limit — prevents chatbot loops with a single agent.
    # Count using both instance_id match (exact) and base-role match (backward compat)
    consults_to_target = sum(
        1
        for m in agent_messages
        if m.get("type") == "consult_request"
        and m.get("from_role") == from_role
        and (m.get("to_role") == to_role or m.get("to_role") == to_base_role)
    )
    if consults_to_target >= max_per_target:
        return json.dumps(
            {
                "status": "blocked",
                "reason": "per_target_limit_reached",
                "note": (
                    f"'{from_role}' has already consulted '{to_role}' "
                    f"{consults_to_target} time(s). "
                    f"Max per target is {max_per_target}. Use the information you already received."
                ),
            }
        )

    # Thread ID for follow-up tracking. Must reference a valid prior consult request
    # to the same target, if provided.
    thread_id = str(tool_input.get("thread_id", "")).strip()
    if thread_id:
        linked = next(
            (
                m
                for m in agent_messages
                if m.get("id") == thread_id and m.get("type") == "consult_request"
            ),
            None,
        )
        if not linked:
            thread_id = ""  # Silently discard invalid thread_id
        elif linked.get("to_role") != to_role:
            # Thread_id references a different target — ignore it
            thread_id = ""

    if len(question) > max_question_chars:
        # Truncate at last sentence boundary if possible
        truncated = question[:max_question_chars]
        last_period = truncated.rfind(".")
        if last_period > int(max_question_chars * 0.8):
            question = truncated[: last_period + 1]
        else:
            question = truncated + "..."

    request_id = _new_message_id(agent_messages)
    request: dict[str, Any] = {
        "id": request_id,
        "type": "consult_request",
        "from_role": from_role,
        "to_role": to_role,
        "content": question,
        "status": "pending",
        "created_at": time.time(),
    }
    if thread_id:
        request["thread_id"] = thread_id  # Links to prior consultation for follow-ups
    agent_messages.append(request)
    events.append(
        {
            "type": "agent_consult_requested",
            "from_role": from_role,
            "to_role": to_role,
            "message_id": request_id,
            "question_preview": question[:220],
        }
    )
    events.append(
        {
            "type": "consultation_visible",
            "status": "pending",
            "from_role": from_role,
            "to_role": to_role,
            "message_id": request_id,
            "question_preview": question[:220],
        }
    )

    existing_output = state.get("agent_outputs", {}).get(to_role, {})
    existing_summary = existing_output.get("summary", "")
    if existing_summary:
        answer = existing_summary[:max_response_chars]
        request["status"] = "answered"

        response_id = _new_message_id(agent_messages)
        agent_messages.append(
            {
                "id": response_id,
                "type": "consult_response",
                "from_role": to_role,
                "to_role": from_role,
                "content": answer,
                "status": "answered",
                "linked_to": request_id,
                "created_at": time.time(),
            }
        )
        events.append(
            {
                "type": "agent_consult_completed",
                "from_role": from_role,
                "to_role": to_role,
                "message_id": request_id,
                "response_preview": answer[:220],
            }
        )
        events.append(
            {
                "type": "consultation_visible",
                "status": "answered",
                "from_role": from_role,
                "to_role": to_role,
                "message_id": request_id,
                "response_preview": answer[:220],
            }
        )
        return json.dumps(
            {
                "status": "answered",
                "to_role": to_role,
                "message_id": request_id,
                "response": f"[ADVISORY] {answer}",
                "advisory_only": True,
            }
        )

    return json.dumps(
        {
            "status": "pending",
            "to_role": to_role,
            "message_id": request_id,
            "note": (
                f"Consult request queued for '{to_role}'. "
                "Response will be attached when that role completes."
            ),
            "advisory_only": True,
        }
    )


def _fulfill_pending_consults(
    current_role: str,
    final_text: str,
    state: TaskState,
    agent_messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    """Auto-respond to pending consult requests addressed to the current role.

    Consultation is advisory-only by design:
    - Requests are asynchronous: agent asks, target responds when it finishes.
    - If target never runs, requests remain pending forever.
    - A pending request counts toward the per-target limit.
    - Responses are truncated to max_response_chars and prefixed with [ADVISORY].
    """
    enabled, _, max_response_chars, _, _, _ = _resolve_consult_policy(state)
    if not enabled:
        return
    answer = (
        final_text[:max_response_chars] if final_text else "Completed work. No summary provided."
    )
    # Resolve base role using team_config for robust matching
    team_agents = state.get("team_config", {}).get("agents", {})
    current_base_role = team_agents.get(current_role, {}).get("role", current_role)
    for msg in agent_messages:
        # Match by instance_id (exact) or by base role (backward compat)
        msg_target = msg.get("to_role", "")
        msg_target_base = team_agents.get(msg_target, {}).get("role", msg_target)
        if (
            msg.get("type") == "consult_request"
            and (msg_target == current_role or msg_target_base == current_base_role)
            and msg.get("status") == "pending"
        ):
            msg["status"] = "answered"
            response_id = _new_message_id(agent_messages)
            agent_messages.append(
                {
                    "id": response_id,
                    "type": "consult_response",
                    "from_role": current_role,
                    "to_role": msg.get("from_role", ""),
                    "content": f"[ADVISORY] {answer}",
                    "status": "answered",
                    "linked_to": msg.get("id", ""),
                    "created_at": time.time(),
                }
            )
            events.append(
                {
                    "type": "agent_consult_completed",
                    "from_role": msg.get("from_role", ""),
                    "to_role": current_role,
                    "message_id": msg.get("id", ""),
                    "response_preview": answer[:220],
                }
            )
            events.append(
                {
                    "type": "consultation_visible",
                    "status": "answered",
                    "from_role": msg.get("from_role", ""),
                    "to_role": current_role,
                    "message_id": msg.get("id", ""),
                    "response_preview": answer[:220],
                }
            )


def _specialist_branch_system_prompt(
    *,
    specialist_role: str,
    parent_role: str,
    system_prompt: str,
    merge_back_contract: dict[str, Any],
) -> str:
    """Build a dedicated system prompt for bounded specialist branches."""
    branch_contract = _role_contract_block(specialist_role)
    merge_text = _format_jsonish(merge_back_contract) if merge_back_contract else "{}"
    return (
        f"{system_prompt}\n\n"
        "SPECIALIST BRANCH MODE: You are a bounded child branch operating "
        "under a parent agent. Stay inside the assigned scope, avoid "
        "unrelated exploration, and return merge-ready output.\n"
        f"PARENT ROLE: {parent_role}\n"
        f"MERGE-BACK CONTRACT: {merge_text}\n\n"
        f"{branch_contract}"
    )


async def _run_specialist_branch(
    *,
    llm: LLMProvider,
    tool_executor: ToolExecutor,
    description: str,
    specialist_role: str,
    files_context: list[str],
    system_prompt: str,
    parent_role: str,
    parent_state: TaskState | None,
    stream_callback: Any | None = None,
    batch_timeout: int = DEFAULT_BATCH_TIMEOUT,
    max_rounds: int = SUBAGENT_MAX_ROUNDS,
    merge_back_contract: dict[str, Any] | None = None,
    branch_id: str = "",
) -> dict[str, Any]:
    """Run a bounded specialist branch with its own role contract and event log."""
    # Build context from files
    context_parts = []
    for fp in files_context:
        try:
            result = await tool_executor.execute("read_file", {"path": fp})
            context_parts.append(f"--- {fp} ---\n{result}")
        except Exception as exc:
            logger.debug("Subtask context read failed for %s: %s", fp, exc)

    context_text = "\n\n".join(context_parts) if context_parts else ""

    branch_contract = merge_back_contract or {}
    branch_system_prompt = _specialist_branch_system_prompt(
        specialist_role=specialist_role,
        parent_role=parent_role,
        system_prompt=system_prompt,
        merge_back_contract=branch_contract,
    )
    sub_messages: list[dict[str, Any]] = [
        {"role": "system", "content": branch_system_prompt},
        {
            "role": "user",
            "content": (
                f"BOUNDED ASSIGNMENT: {description}\n"
                f"SPECIALIST ROLE: {specialist_role}\n"
                f"PARENT ROLE: {parent_role}\n\n"
                + (f"CONTEXT FILES:\n{context_text}" if context_text else "")
            ),
        },
    ]

    branch_tool_defs = [
        t for t in get_engineering_tools(specialist_role) if t["name"] != "spawn_subtask"
    ]
    branch_events: list[dict[str, Any]] = []
    branch_agent_messages: list[dict[str, Any]] = []
    branch_state: TaskState = {
        **(parent_state or {}),
        "description": description,
        "current_agent_role": specialist_role,
        "current_instance_id": branch_id or specialist_role,
        "required_approval_actions": [],
        "risk_action_queue": [],
        "spawn_history": [],
        "supervisory_decisions": [],
        "active_consultations": [],
        "events": [],
        "agent_messages": [],
        "retry_count": 0,
        "active_fix_packet": {},
    }

    if stream_callback:
        try:
            stream_callback(branch_id or specialist_role, f"\n  🔀 Branch: {description[:60]}...\n")
        except Exception as exc:
            logger.debug("Stream callback failed for subtask start: %s", exc)

    text, inp_tok, out_tok, files, loop_metrics = await _run_agentic_loop(
        llm=llm,
        messages=sub_messages,
        tool_defs=branch_tool_defs,
        tool_executor=tool_executor,
        agent_config={"temperature": 0.0, "max_tokens": ROLE_MAX_TOKENS.get(specialist_role, 8192)},
        role=specialist_role,
        stream_identity=branch_id or specialist_role,
        state=branch_state,
        agent_messages=branch_agent_messages,
        events=branch_events,
        stream_callback=stream_callback,
        batch_timeout=batch_timeout,
        max_rounds=max_rounds,
    )
    _fulfill_pending_consults(
        current_role=branch_id or specialist_role,
        final_text=text,
        state=branch_state,
        agent_messages=branch_agent_messages,
        events=branch_events,
    )
    execution_log = loop_metrics.get("execution_log", [])
    execution_verified = (
        specialist_role in {"coder", "qa", "devops", "sre"} and len(execution_log) > 0
    )
    pending_consults = _pending_consultations(branch_agent_messages)

    return {
        "summary": text[:2000],
        "files_changed": files,
        "input_tokens": inp_tok,
        "output_tokens": out_tok,
        "cached_input_tokens": int(loop_metrics.get("cached_input_tokens", 0) or 0),
        "cache_write_tokens": int(loop_metrics.get("cache_write_tokens", 0) or 0),
        "status": "complete",
        "role": specialist_role,
        "branch_id": branch_id or specialist_role,
        "execution_log": execution_log,
        "execution_verified": execution_verified,
        "agent_messages": branch_agent_messages[-20:],
        "events": branch_events[-40:],
        "pending_consults": pending_consults,
        "merge_back_contract": branch_contract,
    }


async def _run_agentic_loop(
    llm: LLMProvider,
    messages: list[dict[str, Any]],
    tool_defs: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    agent_config: dict[str, Any],
    role: str,
    stream_identity: str | None = None,
    state: TaskState | None = None,
    agent_messages: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    stream_callback: Any | None = None,
    batch_timeout: int = DEFAULT_BATCH_TIMEOUT,
    max_rounds: int = HARD_SAFETY_CAP,
    soft_target_rounds: int = MAX_TOOL_ROUNDS,
    rigour_session: RigourSession | None = None,
) -> tuple[str, int, int, list[str], dict[str, Any]]:
    """
    Run the agentic tool loop: LLM calls tools → execute → feed back → repeat.

    Returns:
        (final_text, total_input_tokens, total_output_tokens, files_changed, subtask_metrics)
    """
    total_input_tokens = 0
    total_output_tokens = 0
    total_cached_input_tokens = 0
    total_cache_write_tokens = 0
    provider_cache_hits = 0
    all_text_parts: list[str] = []
    subtask_count_ref = {"value": 0}
    subtask_token_total_ref = {"value": 0}
    execution_log: list[dict[str, Any]] = []  # Track run_command calls with exit codes
    run_command_counts: dict[str, int] = {}  # Guard against repeated shell loops
    agent_messages = agent_messages if agent_messages is not None else []
    events = events if events is not None else []
    stream_role = str(stream_identity or role or "agent")
    temperature = agent_config.get("temperature", DEFAULT_TEMPERATURE)

    # ── Resolve base role for eligibility checks ──
    # `role` is the instance_id (e.g. "software-engineer-1") but eligibility sets
    # like ROLES_REQUIRING_FILE_WRITES use base roles (e.g. "coder").  Without
    # this resolution, inline gates, stuck detection, mid-execution checks, and
    # file-write enforcement silently skip instance-based agents.
    _base_role = role
    if state:
        from rigovo.application.graph.agent_identity import resolve_base_role as _resolve_br

        _base_role = _resolve_br(state, role)

    # Use per-role max_tokens for smarter token allocation
    max_tokens = agent_config.get("max_tokens") or ROLE_MAX_TOKENS.get(
        _base_role, DEFAULT_MAX_TOKENS
    )
    subagent_enabled, max_subtasks_per_step, max_subtask_rounds = _resolve_subagent_policy(state)
    require_file_write = _base_role in ROLES_REQUIRING_FILE_WRITES
    retry_count = int((state or {}).get("retry_count", 0) or 0)
    fix_packets = list((state or {}).get("fix_packets", []) or [])
    latest_fix_packet = str(fix_packets[-1]).lower() if fix_packets else ""
    no_files_fix_active = (
        "no-files" in latest_fix_packet
        or "wrote 0 files" in latest_fix_packet
        or "no files" in latest_fix_packet
    )
    enforce_file_write_on_retry = require_file_write and (retry_count > 0 or no_files_fix_active)
    write_file_calls = 0
    successful_write_file_calls = 0
    no_file_nudges_sent = 0
    # Stuck detection: consecutive rounds with no file writes for code-producing roles
    consecutive_idle_rounds = 0
    budget_warning_sent = False
    inline_gate_attempts = 0
    max_inline_gate_attempts = 3
    _prev_inline_violations: list[dict[str, Any]] | None = None  # track for persistence detection

    # Intent-aware file read cap — prevents planner from reading entire codebase
    # for brainstorming/research tasks.  0 = unlimited.
    intent_profile = (state or {}).get("intent_profile") or {}
    max_file_reads = int(intent_profile.get("max_file_reads", 0))
    file_read_count = 0

    round_num = 0
    while round_num < max_rounds:
        writes_at_round_start = successful_write_file_calls
        logger.info(
            "Agent %s: tool loop round %d/%d (soft target: %d, messages: %d)",
            role,
            round_num + 1,
            max_rounds,
            soft_target_rounds,
            len(messages),
        )

        # Call LLM with tools (retry once on timeout/transient error)
        _llm_attempts = 0
        _llm_max_attempts = 2
        while True:
            _llm_attempts += 1
            try:
                response: LLMResponse = await asyncio.wait_for(
                    llm.invoke(
                        messages=messages,
                        tools=tool_defs,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ),
                    timeout=batch_timeout,
                )
                break
            except (asyncio.TimeoutError, OSError, ConnectionError) as _llm_err:
                if _llm_attempts >= _llm_max_attempts:
                    raise
                logger.warning(
                    "Agent %s LLM call failed (%s), retrying (%d/%d)...",
                    role,
                    type(_llm_err).__name__,
                    _llm_attempts,
                    _llm_max_attempts,
                )
                await asyncio.sleep(2)

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        cached_tokens = int(getattr(response.usage, "cached_input_tokens", 0) or 0)
        cache_write_tokens = int(getattr(response.usage, "cache_write_tokens", 0) or 0)
        total_cached_input_tokens += cached_tokens
        total_cache_write_tokens += cache_write_tokens
        if cached_tokens > 0 or cache_write_tokens > 0:
            provider_cache_hits += 1

        # Collect any text from this response
        if response.content:
            all_text_parts.append(response.content)
            # Stream the text to the callback if available
            if stream_callback:
                try:
                    stream_callback(stream_role, response.content)
                except Exception:
                    logger.debug("Stream callback error for %s", role)

        # Check if LLM wants to call tools
        if not response.tool_calls:
            if (
                enforce_file_write_on_retry
                and successful_write_file_calls == 0
                and round_num + 1 < max_rounds
                and no_file_nudges_sent < 2
            ):
                no_file_nudges_sent += 1
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "BLOCKER: You are a code-producing role and have not "
                            "written any files yet. Call write_file now and produce "
                            "at least one concrete file change before continuing."
                        ),
                    }
                )
                events.append(
                    {
                        "type": "no_files_nudge",
                        "role": role,
                        "round": int(round_num + 1),
                        "reason": "no_tool_calls_without_write_file",
                    }
                )
                continue
            # No tool calls — agent thinks it's done.
            # Run inline quality gates BEFORE accepting "done" signal.
            if (
                _base_role in ROLES_REQUIRING_FILE_WRITES
                and successful_write_file_calls > 0
                and inline_gate_attempts < max_inline_gate_attempts
            ):
                _inline_files = _extract_written_files(messages)
                if _inline_files:
                    try:
                        from rigovo.application.graph.nodes.inline_gates import (
                            run_inline_quality_gates,
                        )

                        _project_root_str = str(
                            (state or {}).get("target_root")
                            or (state or {}).get("project_root")
                            or "."
                        )
                        _classification = (state or {}).get("classification", {})
                        _is_critical = _classification.get("complexity") == "critical"
                        _gate_result = await run_inline_quality_gates(
                            project_root=_project_root_str,
                            files_changed=_inline_files,
                            agent_role=_base_role,
                            attempt=inline_gate_attempts + 1,
                            is_critical=_is_critical,
                            prev_violations=_prev_inline_violations,
                        )
                        inline_gate_attempts += 1
                        if not _gate_result.passed:
                            # Track violations for next attempt's persistence detection
                            _prev_inline_violations = _gate_result.violations
                            logger.info(
                                "Agent %s: inline gate failed (attempt %d/%d), "
                                "injecting %d violations for self-correction",
                                role,
                                inline_gate_attempts,
                                max_inline_gate_attempts,
                                len(_gate_result.violations),
                            )
                            messages.append(
                                {"role": "user", "content": _gate_result.violation_summary}
                            )
                            events.append(
                                {
                                    "type": "inline_quality_gate",
                                    "role": role,
                                    "instance_id": stream_role,
                                    "round": round_num + 1,
                                    "passed": False,
                                    "attempt": inline_gate_attempts,
                                    "violations": len(_gate_result.violations),
                                    "gate_ran": _gate_result.gate_ran,
                                    "deep_mode": _gate_result.deep_mode,
                                }
                            )
                            continue  # Agent self-corrects in same context
                        # Gates passed — only emit event if CLI actually ran
                        events.append(
                            {
                                "type": "inline_quality_gate",
                                "role": role,
                                "instance_id": stream_role,
                                "round": round_num + 1,
                                "passed": True,
                                "attempt": inline_gate_attempts,
                                "violations": 0,
                                "gate_ran": _gate_result.gate_ran,
                                "deep_mode": _gate_result.deep_mode,
                            }
                        )
                    except Exception:
                        pass  # Graceful degradation

            logger.info(
                "Agent %s: finished after %d rounds (no more tool calls)", role, round_num + 1
            )
            break

        # Execute each tool call
        logger.info(
            "Agent %s: executing %d tool call(s): %s",
            role,
            len(response.tool_calls),
            [tc.get("name", "?") for tc in response.tool_calls],
        )
        write_file_calls += sum(
            1 for tc in response.tool_calls if str(tc.get("name", "")) == "write_file"
        )

        # Build the assistant message with tool_use content blocks
        # This is needed so the LLM sees what it previously said
        assistant_content: list[dict[str, Any]] = []
        if response.content:
            assistant_content.append({"type": "text", "text": response.content})
        for tc in response.tool_calls:
            assistant_content.append(
                {
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                }
            )

        messages.append({"role": "assistant", "content": assistant_content})

        # Execute tools — handle spawn_subtask specially (it runs a child LLM loop)
        tool_results_content: list[dict[str, Any]] = []

        async def _exec_single_tool(tc: dict) -> tuple[dict, str]:
            """Execute a single tool call, handling spawn_subtask as a meta-tool."""
            nonlocal total_input_tokens
            nonlocal total_output_tokens
            nonlocal total_cached_input_tokens
            nonlocal total_cache_write_tokens
            nonlocal provider_cache_hits
            nonlocal successful_write_file_calls
            nonlocal soft_target_rounds
            nonlocal budget_warning_sent
            tool_name = str(tc.get("name", "")).strip()
            if (
                enforce_file_write_on_retry
                and successful_write_file_calls == 0
                and tool_name
                in {
                    "read_file",
                    "list_directory",
                    "search_codebase",
                    "run_command",
                    "spawn_subtask",
                }
            ):
                events.append(
                    {
                        "type": "no_files_nudge",
                        "role": role,
                        "round": (
                            sum(1 for event in events if event.get("type") == "no_files_nudge") + 1
                        ),
                        "reason": "blocked_non_write_tool_before_first_write",
                        "tool": tool_name,
                    }
                )
                return tc, json.dumps(
                    {
                        "status": "blocked_until_write_file",
                        "error": (
                            "Retry remediation requires at least one write_file call before "
                            f"using '{tool_name}'. Produce concrete file edits now."
                        ),
                    }
                )
            if tc["name"] == "spawn_subtask":
                if not subagent_enabled:
                    result_str = json.dumps(
                        {
                            "status": "blocked",
                            "reason": "subagents_disabled_by_policy",
                        }
                    )
                    events.append(
                        {
                            "type": "subtask_blocked",
                            "role": role,
                            "reason": "subagents_disabled_by_policy",
                        }
                    )
                elif subtask_count_ref["value"] >= max_subtasks_per_step:
                    result_str = json.dumps(
                        {
                            "status": "blocked",
                            "reason": "subtask_limit_reached",
                            "max_subtasks_per_agent_step": max_subtasks_per_step,
                        }
                    )
                    events.append(
                        {
                            "type": "subtask_blocked",
                            "role": role,
                            "reason": "subtask_limit_reached",
                            "max_subtasks_per_agent_step": max_subtasks_per_step,
                        }
                    )
                else:
                    subtask_count_ref["value"] += 1
                    subtask_description = str(tc["input"].get("description", "")).strip()
                    spawn_input = tc.get("input", {})
                    files_context = [
                        str(path)
                        for path in (spawn_input.get("files_context", []) or [])
                        if str(path).strip()
                    ]
                    specialist_role = str(
                        spawn_input.get("specialist_role")
                        or spawn_input.get("child_role")
                        or f"{role}-specialist"
                    ).strip()
                    requested_contract = spawn_input.get("merge_back_contract", {})
                    merge_back_contract = {
                        "parent_role": role,
                        "child_role": specialist_role,
                        "expected_artifacts": ["summary", "files_changed", "verification delta"],
                        "files_context": files_context[:8],
                        **(requested_contract if isinstance(requested_contract, dict) else {}),
                    }
                    estimated_cost_delta = round(
                        max(0.02, 0.02 + (len(files_context) * 0.005)),
                        4,
                    )
                    estimated_time_delta_ms = max(
                        30_000,
                        min(180_000, 30_000 + (len(files_context) * 12_000)),
                    )
                    branch_record = {
                        "spawn_id": f"{role}-spawn-{subtask_count_ref['value']}",
                        "role": role,
                        "parent_role": role,
                        "spawn_kind": "specialist_branch",
                        "specialist_role": specialist_role,
                        "subtask_index": subtask_count_ref["value"],
                        "bounded_assignment": subtask_description[:240],
                        "merge_back_contract": merge_back_contract,
                        "estimated_cost_delta_usd": estimated_cost_delta,
                        "estimated_time_delta_ms": estimated_time_delta_ms,
                        "files_context": files_context[:8],
                    }
                    events.append(
                        {
                            "type": "master_spawn_decision",
                            "role": role,
                            "summary": (
                                f"Spawned bounded specialist branch '{specialist_role}' "
                                "to accelerate a separable implementation segment."
                            ),
                            **branch_record,
                        }
                    )
                    events.append(
                        {
                            "type": "spawn_requested",
                            "description": subtask_description[:140],
                            **branch_record,
                        }
                    )
                    events.append(
                        {
                            "type": "subtask_spawned",
                            "description": subtask_description[:140],
                            **branch_record,
                        }
                    )
                    events.append(
                        {
                            "type": "spawn_started",
                            "description": subtask_description[:140],
                            **branch_record,
                        }
                    )
                    branch_system_prompt = agent_config.get(
                        "system_prompt",
                        "You are a coding agent.",
                    )
                    if state is not None:
                        team_agents = state.get("team_config", {}).get("agents", {}) or {}
                        sibling_cfg = next(
                            (
                                cfg
                                for cfg in team_agents.values()
                                if isinstance(cfg, dict)
                                and str(cfg.get("role", "")).strip() == specialist_role
                                and str(cfg.get("system_prompt", "")).strip()
                            ),
                            None,
                        )
                        if isinstance(sibling_cfg, dict):
                            branch_system_prompt = str(
                                sibling_cfg.get("system_prompt", branch_system_prompt)
                            )
                    sub_result = await _run_specialist_branch(
                        llm=llm,
                        tool_executor=tool_executor,
                        description=subtask_description,
                        specialist_role=specialist_role,
                        files_context=files_context,
                        system_prompt=branch_system_prompt,
                        parent_role=role,
                        parent_state=state,
                        stream_callback=stream_callback,
                        batch_timeout=batch_timeout,
                        max_rounds=max_subtask_rounds,
                        merge_back_contract=merge_back_contract,
                        branch_id=branch_record["spawn_id"],
                    )
                    sub_in = int(sub_result.get("input_tokens", 0) or 0)
                    sub_out = int(sub_result.get("output_tokens", 0) or 0)
                    sub_cached = int(sub_result.get("cached_input_tokens", 0) or 0)
                    sub_cache_write = int(sub_result.get("cache_write_tokens", 0) or 0)
                    subtask_token_total_ref["value"] += sub_in + sub_out
                    total_input_tokens += sub_in
                    total_output_tokens += sub_out
                    total_cached_input_tokens += sub_cached
                    total_cache_write_tokens += sub_cache_write
                    if sub_cached > 0 or sub_cache_write > 0:
                        provider_cache_hits += 1
                    for child_msg in list(sub_result.get("agent_messages", []) or []):
                        if isinstance(child_msg, dict):
                            agent_messages.append(child_msg)
                    for child_event in list(sub_result.get("events", []) or []):
                        if isinstance(child_event, dict):
                            events.append(
                                {
                                    **child_event,
                                    "branch_id": branch_record["spawn_id"],
                                    "parent_role": role,
                                    "specialist_role": specialist_role,
                                }
                            )
                    events.append(
                        {
                            "type": "subtask_complete",
                            "role": role,
                            "subtask_index": subtask_count_ref["value"],
                            "input_tokens": sub_in,
                            "output_tokens": sub_out,
                            "cached_input_tokens": sub_cached,
                            "cache_write_tokens": sub_cache_write,
                            "files_changed": len(sub_result.get("files_changed", []) or []),
                        }
                    )
                    events.append(
                        {
                            "type": "spawn_completed",
                            **branch_record,
                            "files_changed": len(sub_result.get("files_changed", []) or []),
                            "input_tokens": sub_in,
                            "output_tokens": sub_out,
                            "execution_verified": bool(sub_result.get("execution_verified", False)),
                            "pending_consults": len(sub_result.get("pending_consults", []) or []),
                            "merge_status": "ready_for_parent_merge",
                        }
                    )
                    result_str = json.dumps(sub_result, default=str)
            elif tc["name"] == "consult_agent":
                if state is None:
                    result_str = json.dumps(
                        {"status": "error", "error": "consult_agent unavailable without state"}
                    )
                else:
                    result_str = _handle_consult_agent(
                        state=state,
                        from_role=role,
                        tool_input=tc.get("input", {}),
                        agent_messages=agent_messages,
                        events=events,
                    )
            elif tc["name"] == "request_budget_extension":
                # Like a developer adjusting story points — log and extend soft target
                ext_reason = str(tc.get("input", {}).get("reason", "")).strip()
                old_target = soft_target_rounds
                soft_target_rounds = int(soft_target_rounds * 1.5)
                budget_warning_sent = False  # Reset so a new warning fires at new target
                logger.info(
                    "Agent %s: budget extension granted (%d -> %d rounds). Reason: %s",
                    role,
                    old_target,
                    soft_target_rounds,
                    ext_reason[:80],
                )
                events.append(
                    {
                        "type": "budget_extension_requested",
                        "role": role,
                        "round": round_num + 1,  # noqa: B023
                        "reason": ext_reason[:200],
                        "soft_target_before": old_target,
                        "soft_target_after": soft_target_rounds,
                    }
                )
                result_str = json.dumps(
                    {
                        "status": "approved",
                        "new_budget": soft_target_rounds,
                        "message": (
                            f"Budget extension granted: {old_target} -> "
                            f"{soft_target_rounds} rounds. Continue working."
                        ),
                    }
                )
            else:
                risk_event = _evaluate_risky_action(
                    role=role,
                    tool_name=tc["name"],
                    tool_input=tc.get("input", {}),
                    state=state,
                )
                if risk_event is not None:
                    events.append(risk_event)
                    if risk_event["decision"] == "notify_only":
                        events.append(
                            {
                                "type": "master_risk_escalation",
                                "role": role,
                                "summary": risk_event["summary"],
                                "policy": "notify_only",
                                "severity": risk_event["severity"],
                            }
                        )
                    elif risk_event["decision"] == "approval_required":
                        approval_event = {
                            "type": "approval_required",
                            "checkpoint": "risk_action_required",
                            "role": role,
                            "summary": risk_event["summary"],
                            "kind": risk_event["kind"],
                            "severity": risk_event["severity"],
                            "policy": "approval_required",
                            "tool_name": tc["name"],
                            "tool_input": tc.get("input", {}),
                            "requires_human_approval": True,
                        }
                        events.append(approval_event)
                        raise RuntimeApprovalRequiredError(approval_event)
                    elif risk_event["decision"] == "deny":
                        events.append(
                            {
                                "type": "approval_denied",
                                "role": role,
                                "summary": risk_event["summary"],
                                "kind": risk_event["kind"],
                            }
                        )
                        return tc, json.dumps(
                            {
                                "status": "denied_by_policy",
                                "error": risk_event["summary"],
                                "risk_action": risk_event,
                            }
                        )
                if tc["name"] == "run_command":
                    raw_cmd = str(tc.get("input", {}).get("command", "")).strip()
                    normalized_cmd = " ".join(raw_cmd.split())
                    if normalized_cmd:
                        seen_count = run_command_counts.get(normalized_cmd, 0) + 1
                        run_command_counts[normalized_cmd] = seen_count
                        if seen_count > 2:
                            logger.warning(
                                "Agent %s: blocking repeated run_command (%r) after %d attempts",
                                role,
                                normalized_cmd[:120],
                                seen_count - 1,
                            )
                            return tc, json.dumps(
                                {
                                    "status": "blocked_repetitive_command",
                                    "error": (
                                        f"Command '{normalized_cmd[:120]}' repeated too many times "
                                        f"({seen_count - 1}). Summarize findings and continue."
                                    ),
                                    "exit_code": 2,
                                }
                            )
                # Intent-aware file read cap — block reads beyond limit
                if tc["name"] in ("read_file", "list_directory", "search_codebase"):
                    nonlocal file_read_count
                    file_read_count += 1
                    if max_file_reads > 0 and file_read_count > max_file_reads:
                        result_str = json.dumps(
                            {
                                "error": (
                                    f"File read limit reached ({max_file_reads} max for "
                                    f"{intent_profile.get('intent', 'unknown')} intent). "
                                    "Focus on producing your output from what you've already read."
                                ),
                                "status": "blocked_by_intent",
                            }
                        )
                        logger.info(
                            "Agent %s: file read #%d blocked (limit %d for %s intent)",
                            role,
                            file_read_count,
                            max_file_reads,
                            intent_profile.get("intent", "unknown"),
                        )
                        return tc, result_str

                started = time.monotonic()
                result_str = await tool_executor.execute(tc["name"], tc["input"])

                # Track successful file writes (not just attempted write_file calls).
                if tc["name"] == "write_file":
                    try:
                        write_result = json.loads(result_str)
                    except json.JSONDecodeError:
                        write_result = {}
                    if (
                        isinstance(write_result, dict)
                        and write_result.get("path")
                        and not write_result.get("error")
                    ):
                        successful_write_file_calls += 1

                # Track execution for run_command calls (Phase 14)
                if tc["name"] == "run_command":
                    try:
                        cmd_result = json.loads(result_str)
                        exit_code = cmd_result.get("exit_code", -1)
                        summary = cmd_result.get("stdout", "")[:200]
                        if cmd_result.get("stderr"):
                            summary = cmd_result.get("stderr", "")[:200]
                        execution_log.append(
                            {
                                "command": str(tc["input"].get("command", "")).strip()[:100],
                                "exit_code": exit_code,
                                "summary": summary,
                            }
                        )
                    except (json.JSONDecodeError, AttributeError):
                        pass  # Not JSON — keep going

                if tc["name"] == "invoke_integration":
                    elapsed_ms = int((time.monotonic() - started) * MS_PER_SECOND)
                    try:
                        integration_result = json.loads(result_str)
                    except json.JSONDecodeError:
                        integration_result = {}
                    event_type = (
                        "integration_blocked"
                        if integration_result.get("blocked")
                        else "integration_invoked"
                    )
                    events.append(
                        {
                            "type": event_type,
                            "role": role,
                            "kind": str(tc.get("input", {}).get("kind", "")),
                            "plugin_id": str(tc.get("input", {}).get("plugin_id", "")),
                            "target_id": str(tc.get("input", {}).get("target_id", "")),
                            "operation": str(tc.get("input", {}).get("operation", "")),
                            "dry_run": bool(integration_result.get("dry_run", False)),
                            "blocked_reason": str(integration_result.get("error", "")),
                            "status": str(integration_result.get("status", "")),
                            "latency_ms": elapsed_ms,
                        }
                    )
            return tc, result_str

        if len(response.tool_calls) > 1:
            # Parallel execution — fire all tools simultaneously
            logger.info("Agent %s: executing %d tools in parallel", role, len(response.tool_calls))

            parallel_results = await asyncio.gather(
                *[_exec_single_tool(tc) for tc in response.tool_calls],
                return_exceptions=True,
            )

            for idx, result in enumerate(parallel_results):
                if isinstance(result, Exception):
                    tc = response.tool_calls[idx]
                    logger.error(
                        "Parallel tool execution error for %s: %s",
                        tc.get("name", "?"),
                        result,
                    )
                    result_str = json.dumps(
                        {
                            "status": "tool_execution_error",
                            "error": str(result),
                        }
                    )
                    tool_results_content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc["id"],
                            "content": result_str,
                        }
                    )
                    continue
                tc, result_str = result
                if stream_callback:
                    try:
                        stream_callback(
                            stream_role,
                            f"\n  ⚡ {tc['name']}({_summarize_input(tc['input'])})\n",
                        )
                    except Exception as exc:
                        logger.debug("Stream callback failed for parallel tool result: %s", exc)
                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": result_str,
                    }
                )
        else:
            # Single tool call — execute directly
            tc = response.tool_calls[0]
            _, result_str = await _exec_single_tool(tc)
            if stream_callback:
                try:
                    stream_callback(
                        stream_role,
                        f"\n  ⚡ {tc['name']}({_summarize_input(tc['input'])})\n",
                    )
                except Exception as exc:
                    logger.debug("Stream callback failed for tool result: %s", exc)
            tool_results_content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result_str,
                }
            )

        messages.append({"role": "user", "content": tool_results_content})

        # Rigour checkpoint — emit progress/quality snapshot for governance
        if (
            round_num > 0
            and round_num % RIGOUR_CHECKPOINT_INTERVAL == 0
            and successful_write_file_calls > 0
            and rigour_session is not None
        ):
            try:
                _checkpoint_files = _extract_written_files(messages)
                _progress_pct = min(100, int((round_num / max_rounds) * 100))
                rigour_session.checkpoint(
                    progress_pct=_progress_pct,
                    files_changed=_checkpoint_files,
                    summary=f"Round {round_num}/{max_rounds}",
                    quality_score=100,
                )
            except Exception:
                pass

        # Mid-execution Rigour deep checkpoint — catch quality drift early
        # Runs every MID_EXECUTION_CHECK_INTERVAL rounds for code-producing roles
        if (
            round_num > 0
            and round_num % MID_EXECUTION_CHECK_INTERVAL == 0
            and _base_role in ROLES_REQUIRING_FILE_WRITES
            and successful_write_file_calls > 0
        ):
            files_written_so_far = _extract_written_files(messages)
            if files_written_so_far:
                project_root_str = str(
                    (state or {}).get("target_root") or (state or {}).get("project_root") or "."
                )
                try:
                    drift_violations = await _run_mid_execution_check(
                        project_root_str, files_written_so_far
                    )
                    if drift_violations:
                        violation_count = len(drift_violations)
                        violation_msgs = "; ".join(
                            str(v.get("message", "")) for v in drift_violations[:3]
                        )
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"MID-EXECUTION QUALITY CHECK ({violation_count} issues): "
                                    f"{violation_msgs}\n"
                                    "Fix these NOW before writing more files."
                                ),
                            }
                        )
                        events.append(
                            {
                                "type": "mid_execution_quality_check",
                                "role": role,
                                "round": round_num + 1,
                                "violations": violation_count,
                            }
                        )
                except Exception:
                    pass  # Graceful degradation — never break the agentic loop

        if (
            enforce_file_write_on_retry
            and successful_write_file_calls == 0
            and round_num + 1 < max_rounds
            and no_file_nudges_sent < 2
        ):
            no_file_nudges_sent += 1
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "BLOCKER: stop reconnaissance. Your next action must include write_file. "
                        "Produce at least one real file modification now."
                    ),
                }
            )
            events.append(
                {
                    "type": "no_files_nudge",
                    "role": role,
                    "round": int(round_num + 1),
                    "reason": "read_only_round_without_write_file",
                }
            )

        # ── Stuck detection ──────────────────────────────────────────────
        # If code-producing role goes 5+ rounds without writing files, nudge.
        if _base_role in ROLES_REQUIRING_FILE_WRITES:
            if successful_write_file_calls == writes_at_round_start:
                consecutive_idle_rounds += 1
            else:
                consecutive_idle_rounds = 0
            if consecutive_idle_rounds >= 5:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "WARNING: You have spent 5+ consecutive rounds without writing "
                            "any files. If you are stuck, explain what is blocking you. "
                            "If you have enough context, start writing files NOW."
                        ),
                    }
                )
                events.append(
                    {
                        "type": "stuck_detection",
                        "role": role,
                        "round": round_num + 1,
                        "idle_rounds": consecutive_idle_rounds,
                    }
                )
                consecutive_idle_rounds = 0  # Reset to avoid spamming

        # ── Budget approaching — soft warning, NOT hard kill ─────────────
        if (
            not budget_warning_sent
            and soft_target_rounds > 0
            and round_num + 1 >= soft_target_rounds
        ):
            budget_warning_sent = True
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"BUDGET UPDATE: You have used {round_num + 1} of ~{soft_target_rounds} "
                        "expected rounds. If your work is not complete, CONTINUE — quality "
                        "matters more than speed. Focus on completing your assignment."
                    ),
                }
            )
            events.append(
                {
                    "type": "budget_warning",
                    "role": role,
                    "round": round_num + 1,
                    "soft_target": soft_target_rounds,
                }
            )

        round_num += 1

    else:
        logger.warning(
            "Agent %s: hit hard safety cap (%d rounds). Soft target was %d.",
            role,
            max_rounds,
            soft_target_rounds,
        )

    # Extract files changed from write_file tool calls in message history
    files_changed = _extract_written_files(messages)

    final_text = "\n".join(all_text_parts)
    return (
        final_text,
        total_input_tokens,
        total_output_tokens,
        files_changed,
        {
            "subtask_count": subtask_count_ref["value"],
            "subtask_tokens": subtask_token_total_ref["value"],
            "cached_input_tokens": total_cached_input_tokens,
            "cache_write_tokens": total_cache_write_tokens,
            "provider_cache_hits": provider_cache_hits,
            "execution_log": execution_log,  # Phase 14
        },
    )


def _is_internal_runtime_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized == ".rigovo" or normalized.startswith(".rigovo/")


def _extract_written_files(messages: list[dict[str, Any]]) -> list[str]:
    """Extract file paths from write_file tool calls in message history."""
    files = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == "write_file"
            ):
                path = block.get("input", {}).get("path", "")
                if path and not _is_internal_runtime_path(path) and path not in files:
                    files.append(path)
    return files


def _summarize_input(tool_input: dict[str, Any]) -> str:
    """Create a short summary of tool input for display."""
    if "path" in tool_input:
        path = tool_input["path"]
        if "content" in tool_input:
            content_len = len(tool_input["content"])
            return f'"{path}", {content_len} chars'
        return f'"{path}"'
    if "command" in tool_input:
        return f'"{tool_input["command"]}"'
    if "pattern" in tool_input:
        return f'"{tool_input["pattern"]}"'
    return json.dumps(tool_input)[:60]


def _git_tracked_changes(root: Path) -> set[str] | None:
    """Return changed/untracked paths from git status, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    changed: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if not path:
            continue
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if _is_internal_runtime_path(path):
            continue
        changed.add(path)
    return changed


def _scan_tree_signature(root: Path) -> dict[str, tuple[int, int]]:
    """Return lightweight signature map of project files for fallback diff.

    Uses os.walk with early directory pruning instead of rglob to avoid
    traversing into node_modules/vendor/.git (which can have 100K+ files
    and paths with special characters that cause InterruptedError).
    """
    import os

    signature: dict[str, tuple[int, int]] = {}
    count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            # Early prune — os.walk skips pruned dirs entirely
            dirnames[:] = [d for d in dirnames if d not in _FS_IGNORE_DIRS]
            if count >= MAX_FS_SCAN_FILES:
                break
            for fname in filenames:
                if count >= MAX_FS_SCAN_FILES:
                    break
                try:
                    full = os.path.join(dirpath, fname)
                    rel = os.path.relpath(full, root)
                    if _is_internal_runtime_path(rel):
                        continue
                    st = os.stat(full)
                except OSError:
                    continue
                signature[rel] = (int(st.st_mtime_ns), int(st.st_size))
                count += 1
    except (OSError, InterruptedError):
        pass  # Graceful degradation — partial signature is fine
    return signature


def _fallback_fs_changes(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> list[str]:
    changed: list[str] = []
    keys = set(before) | set(after)
    for rel in sorted(keys):
        if before.get(rel) != after.get(rel):
            changed.append(rel)
    return changed


async def execute_agent_node(
    state: TaskState,
    llm_factory: Any,
    cost_calculator: CostCalculator,
    stream_callback: Any | None = None,
    memory_repo: MemoryRepository | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    memory_retriever: MemoryRetriever | None = None,
) -> dict[str, Any]:
    """
    Execute the current agent with context isolation and tool calling.

    This now implements the full agentic loop:
    1. Send messages + tool definitions to LLM
    2. LLM returns text + tool_calls
    3. Execute tool calls (read_file, write_file, run_command, etc.)
    4. Feed tool results back to LLM
    5. Repeat until LLM has no more tool calls

    Args:
        state: Current graph state.
        llm_factory: Creates LLM providers for given model names.
        cost_calculator: Calculates token costs.
        stream_callback: Optional callback(role, chunk) for streaming text.
    """
    team_config = state.get("team_config", {})
    agents = team_config.get("agents", {})

    # Instance-ID aware: prefer current_instance_id, fall back to current_agent_role
    current_instance = state.get("current_instance_id", "") or state.get("current_agent_role", "")
    # The agent config is keyed by instance_id in the new system
    if current_instance not in agents:
        # Backward compat: try current_agent_role
        current_instance = state.get("current_agent_role", "")
    if current_instance not in agents:
        return {
            "status": f"agent_{current_instance}_error",
            "error": f"Agent instance '{current_instance}' not found in team config",
            "events": [
                *list(state.get("events", [])),
                {
                    "type": "agent_timeout",
                    "role": current_instance,
                    "error": f"Instance '{current_instance}' not configured",
                },
            ],
        }
    agent_config = agents[current_instance]
    # The base role (coder, reviewer, etc.) for tool resolution
    current_role = agent_config.get("role", current_instance)

    # --- Contract guards (input) ---
    input_contract = agent_config.get("input_contract", {}) or {}
    input_payload = {
        "task_description": state.get("description", ""),
        "role": current_role,
        "project_root": state.get("project_root", ""),
        "classification": state.get("classification", {}),
        "previous_outputs": state.get("agent_outputs", {}),
        "fix_packets": state.get("fix_packets", []),
    }
    input_violations = _validate_contract(input_contract, input_payload)
    if input_violations:
        return _contract_failure_result(state, current_role, "input", input_violations)

    # --- Budget guards ---
    budget_error = _check_budget_guards(state, current_role)
    if budget_error:
        return budget_error

    # --- Memory retrieval and context assembly ---
    (
        memory_section_text,
        memory_context_by_role,
        memory_retrieval_log,
        memory_events,
    ) = await _resolve_memory_context_for_role(
        state=state,
        current_role=current_role,
        memory_repo=memory_repo,
        embedding_provider=embedding_provider,
        memory_retriever=memory_retriever,
    )
    state_for_messages: TaskState = {
        **state,
        "memory_context_by_role": memory_context_by_role,
        "memory_retrieval_log": memory_retrieval_log,
    }

    # --- Validate required agent config fields (prevent KeyError crashes) ---
    runtime_agent_config = dict(agent_config)
    if "system_prompt" not in runtime_agent_config:
        runtime_agent_config["system_prompt"] = (
            f"You are a {current_role} agent. Complete your assigned task."
        )
        logger.warning("Agent %s missing system_prompt — using default", current_instance)
    if "name" not in runtime_agent_config:
        runtime_agent_config["name"] = current_role.title()
        logger.warning("Agent %s missing name — using '%s'", current_instance, current_role.title())

    # --- Runtime token pressure controls ---
    intent_profile = state.get("intent_profile") or {}
    intent_max_rounds = int(
        intent_profile.get("max_tool_rounds", MAX_TOOL_ROUNDS) or MAX_TOOL_ROUNDS
    )

    # Per-role round caps: planner does recon (keep it tight), coder/sre do real work (give room).
    # Decouples "avoid planner reconnaissance loops" from "give coder enough turns to finish".
    _role_round_caps: dict[str, int] = {
        "planner": 10,  # survey + plan, then hand off
        "lead": 10,
        "coder": MAX_TOOL_ROUNDS,  # read -> write -> verify across multiple files
        "reviewer": 12,
        "security": 12,
        "qa": 12,
        "devops": 15,
        "sre": 15,
    }
    role_cap = _role_round_caps.get(current_role, MAX_TOOL_ROUNDS)
    intent_max_rounds = min(intent_max_rounds, role_cap)

    # ── Token budget pressure — soft signal, not hard kill ──────────────
    # Reduce per-response max_tokens to push completion-first behavior,
    # but do NOT reduce round count — the agentic loop's budget warning
    # and inline quality gates handle termination.
    _token_pressure_warning: str | None = None
    token_limit = int(state.get("budget_max_tokens_per_task", 0) or 0)
    accumulated_tokens = sum(v.get("tokens", 0) for v in state.get("cost_accumulator", {}).values())
    if token_limit > 0:
        remaining_tokens = max(0, token_limit - accumulated_tokens)
        if remaining_tokens <= 60_000:
            # Reduce per-response output tokens (still useful for cost control)
            role_cap = int(ROLE_MAX_TOKENS.get(current_role, DEFAULT_MAX_TOKENS))
            hard_cap = max(1024, min(role_cap, int(remaining_tokens * 0.20)))
            configured = int(runtime_agent_config.get("max_tokens", role_cap) or role_cap)
            runtime_agent_config["max_tokens"] = min(configured, hard_cap)
            _token_pressure_warning = (
                f"TOKEN BUDGET: ~{remaining_tokens:,} tokens remaining out of {token_limit:,}. "
                "Be concise in your responses. Focus on completing your assignment efficiently."
            )
            events_for_pressure = list(state.get("events", []))
            events_for_pressure.append(
                {
                    "type": "token_pressure_mode",
                    "role": current_role,
                    "remaining_tokens": remaining_tokens,
                    "max_tokens_cap": int(runtime_agent_config["max_tokens"]),
                }
            )
            state = {**state, "events": events_for_pressure}

    # --- Build messages ---
    system_prompt = runtime_agent_config["system_prompt"]
    messages = _build_agent_messages(
        state_for_messages,
        system_prompt,
        runtime_agent_config,
        current_role,
        memory_section_text=memory_section_text,
    )

    # Inject token pressure warning as first user context (soft signal, not hard cap)
    if _token_pressure_warning:
        messages.append({"role": "user", "content": _token_pressure_warning})

    # --- Resolve tool definitions ---
    tool_defs = _resolve_tool_definitions(runtime_agent_config, current_role)

    # --- Create ToolExecutor ---
    project_root = Path(str(state.get("target_root") or state.get("project_root") or "."))
    project_root.mkdir(parents=True, exist_ok=True)
    # Extract scope_boundaries from context_package for write enforcement
    _ctx_pkg = runtime_agent_config.get("context_package", {}) or {}
    _scope_boundaries = _ctx_pkg.get("scope_boundaries", {}) or {}

    # Server-side tool allow-list: only tools in the LLM tool_defs can execute.
    # This prevents prompt-injection or LLM drift from invoking tools the role
    # shouldn't have (e.g., planner calling write_file).
    _allowed_tool_names = {t.get("name", "") for t in tool_defs if t.get("name")}

    tool_executor = ToolExecutor(
        project_root,
        integration_catalog=state.get("integration_catalog", {}),
        integration_policy=state.get("integration_policy", {}),
        worktree_mode=str(state.get("worktree_mode", "project")),
        worktree_root=str(state.get("worktree_root", "")),
        filesystem_sandbox_mode=str(state.get("filesystem_sandbox_mode", "project_root")),
        knowledge_graph=state.get("code_knowledge_graph"),
        scope_boundaries=_scope_boundaries,
        allowed_tools=_allowed_tool_names or None,
    )

    # --- LLM setup ---
    llm_model = runtime_agent_config.get("llm_model", DEFAULT_LLM_MODEL)
    llm: LLMProvider = llm_factory(llm_model)
    batch_timeout = runtime_agent_config.get("timeout_seconds", DEFAULT_BATCH_TIMEOUT)

    # Increment global execution counter (never resets across debate/replan cycles)
    total_execution_count = int(state.get("total_execution_count", 0) or 0) + 1

    # Register agent with Rigour session for scope conflict detection
    _rigour_project_root = str(state.get("target_root") or state.get("project_root") or ".")
    _rigour_scope_files = list(
        dict.fromkeys(
            item.get("file_path", "")
            for item in (state.get("active_fix_packet", {}) or {}).get("items", [])
            if item.get("file_path")
        )
    )
    _rigour_session: RigourSession | None = None
    try:
        _rigour_session = RigourSession(_rigour_project_root)
        _scope_conflicts = _rigour_session.agent_register(
            current_instance,
            _rigour_scope_files,
        )
        if _scope_conflicts:
            logger.warning("Rigour scope conflicts: %s", _scope_conflicts)
        _rigour_session.log_event(
            {
                "type": "agent_started",
                "agentId": current_instance,
                "role": current_role,
            }
        )
    except Exception:
        _rigour_session = None  # Graceful degradation

    # Emit agent_started event
    events = list(state.get("events", []))
    events.extend(memory_events)
    agent_messages_log = list(state.get("agent_messages", []))
    events.append(
        {
            "type": "agent_started",
            "role": current_role,
            "instance_id": current_instance,
            "name": runtime_agent_config["name"],
            "specialisation": runtime_agent_config.get("specialisation", ""),
        }
    )
    events.append(
        {
            "type": "master_decision",
            "role": current_role,
            "instance_id": current_instance,
            "execution_mode": str(
                state.get("classification", {}).get("execution_mode", "linear") or "linear"
            ),
            "workspace_type": str(
                state.get("classification", {}).get("workspace_type", "existing_project")
                or "existing_project"
            ),
            "step_objective": _step_objective(state, runtime_agent_config, current_role),
        }
    )
    required_consults = _required_consultations(state, current_role)
    if required_consults:
        events.append(
            {
                "type": "master_consult_decision",
                "role": current_role,
                "consultations": required_consults,
            }
        )

    start_time = time.monotonic()
    # Baseline filesystem state to capture file writes made outside write_file tool
    # (e.g. generated by run_command scripts).
    execution_root = Path(getattr(tool_executor, "_execution_root", project_root))
    git_changed_before = _git_tracked_changes(execution_root)
    fs_signature_before = (
        _scan_tree_signature(execution_root) if git_changed_before is None else None
    )
    cached_input_tokens = 0
    cache_write_tokens = 0
    cache_source = "none"
    cache_saved_tokens = 0
    cache_saved_cost_usd = 0.0
    final_input_tokens = 0
    final_output_tokens = 0

    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _baseline_cost_or_actual(
        *,
        input_tok: int,
        output_tok: int,
        cached_tok: int,
        cache_write_tok: int,
        actual_cost: float,
    ) -> float:
        baseline_fn = getattr(cost_calculator, "calculate_uncached_baseline", None)
        if callable(baseline_fn):
            try:
                return _safe_float(
                    baseline_fn(
                        model=llm_model,
                        input_tokens=input_tok,
                        output_tokens=output_tok,
                        cached_input_tokens=cached_tok,
                        cache_write_tokens=cache_write_tok,
                    ),
                    default=actual_cost,
                )
            except Exception:
                return actual_cost
        return actual_cost

    try:
        if tool_defs:
            # --- Agentic tool loop (for agents with tools) ---
            # Always use batch invoke for tool-calling agents.
            # This is the standard pattern: invoke → tools → invoke → tools → done.
            # Intent-aware: use max_tool_rounds from intent profile if available
            (
                final_text,
                input_tokens,
                output_tokens,
                files_changed,
                subtask_metrics,
            ) = await _run_agentic_loop(
                llm=llm,
                messages=messages,
                tool_defs=tool_defs,
                tool_executor=tool_executor,
                agent_config=runtime_agent_config,
                role=current_role,
                state=state,
                agent_messages=agent_messages_log,
                events=events,
                stream_callback=stream_callback,
                batch_timeout=batch_timeout,
                max_rounds=HARD_SAFETY_CAP,
                soft_target_rounds=intent_max_rounds,
                stream_identity=current_instance or current_role,
                rigour_session=_rigour_session,
            )
            cached_input_tokens = int(subtask_metrics.get("cached_input_tokens", 0) or 0)
            cache_write_tokens = int(subtask_metrics.get("cache_write_tokens", 0) or 0)
            if cached_input_tokens > 0 or cache_write_tokens > 0:
                cache_source = "provider"
            final_input_tokens = int(input_tokens)
            final_output_tokens = int(output_tokens)
            total_tokens = input_tokens + output_tokens + cached_input_tokens + cache_write_tokens

            # Calculate cost
            cost = _safe_float(
                cost_calculator.calculate(
                    model=llm_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_input_tokens=cached_input_tokens,
                    cache_write_tokens=cache_write_tokens,
                ),
                default=0.0,
            )
            uncached_baseline_cost = _baseline_cost_or_actual(
                input_tok=input_tokens,
                output_tok=output_tokens,
                cached_tok=cached_input_tokens,
                cache_write_tok=cache_write_tokens,
                actual_cost=cost,
            )
            cache_saved_tokens = cached_input_tokens
            cache_saved_cost_usd = round(max(0.0, uncached_baseline_cost - cost), 6)

            if not files_changed:
                git_changed_after = _git_tracked_changes(execution_root)
                if git_changed_before is not None and git_changed_after is not None:
                    files_changed = sorted(list(git_changed_after - git_changed_before))
                elif fs_signature_before is not None:
                    fs_signature_after = _scan_tree_signature(execution_root)
                    files_changed = _fallback_fs_changes(fs_signature_before, fs_signature_after)
        elif stream_callback:
            # --- Streaming mode for text-only agents (no tools) ---
            idle_timeout = runtime_agent_config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT)
            response = await _execute_streaming(
                llm,
                messages,
                runtime_agent_config,
                idle_timeout,
                current_role,
                stream_callback,
            )
            final_text = response.content
            total_tokens = response.usage.total_tokens
            files_changed = []
            cached_input_tokens = int(getattr(response.usage, "cached_input_tokens", 0) or 0)
            cache_write_tokens = int(getattr(response.usage, "cache_write_tokens", 0) or 0)
            final_input_tokens = int(response.usage.input_tokens)
            final_output_tokens = int(response.usage.output_tokens)
            cache_source = (
                str(getattr(response.usage, "cache_source", "") or "none")
                if (cached_input_tokens > 0 or cache_write_tokens > 0)
                else "none"
            )
            cost = _safe_float(
                cost_calculator.calculate(
                    model=llm_model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cached_input_tokens=cached_input_tokens,
                    cache_write_tokens=cache_write_tokens,
                ),
                default=0.0,
            )
            uncached_baseline_cost = _baseline_cost_or_actual(
                input_tok=response.usage.input_tokens,
                output_tok=response.usage.output_tokens,
                cached_tok=cached_input_tokens,
                cache_write_tok=cache_write_tokens,
                actual_cost=cost,
            )
            cache_saved_tokens = cached_input_tokens
            cache_saved_cost_usd = round(max(0.0, uncached_baseline_cost - cost), 6)
            subtask_metrics = {"subtask_count": 0, "subtask_tokens": 0}
        else:
            # --- Batch mode for text-only agents (no tools, no streaming) ---
            response = await asyncio.wait_for(
                llm.invoke(
                    messages=messages,
                    temperature=runtime_agent_config.get("temperature", DEFAULT_TEMPERATURE),
                    max_tokens=runtime_agent_config.get("max_tokens", DEFAULT_MAX_TOKENS),
                ),
                timeout=batch_timeout,
            )
            final_text = response.content
            total_tokens = response.usage.total_tokens
            files_changed = []
            cached_input_tokens = int(getattr(response.usage, "cached_input_tokens", 0) or 0)
            cache_write_tokens = int(getattr(response.usage, "cache_write_tokens", 0) or 0)
            final_input_tokens = int(response.usage.input_tokens)
            final_output_tokens = int(response.usage.output_tokens)
            cache_source = (
                str(getattr(response.usage, "cache_source", "") or "none")
                if (cached_input_tokens > 0 or cache_write_tokens > 0)
                else "none"
            )
            cost = _safe_float(
                cost_calculator.calculate(
                    model=llm_model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cached_input_tokens=cached_input_tokens,
                    cache_write_tokens=cache_write_tokens,
                ),
                default=0.0,
            )
            uncached_baseline_cost = _baseline_cost_or_actual(
                input_tok=response.usage.input_tokens,
                output_tok=response.usage.output_tokens,
                cached_tok=cached_input_tokens,
                cache_write_tok=cache_write_tokens,
                actual_cost=cost,
            )
            cache_saved_tokens = cached_input_tokens
            cache_saved_cost_usd = round(max(0.0, uncached_baseline_cost - cost), 6)
            subtask_metrics = {"subtask_count": 0, "subtask_tokens": 0}

    except RuntimeApprovalRequiredError as exc:
        duration_ms = int((time.monotonic() - start_time) * MS_PER_SECOND)
        approval_event = dict(exc.approval_event)
        risk_action_queue, required_approval_actions = _approval_records_from_events(state, events)
        return {
            "status": "awaiting_runtime_approval",
            "error": approval_event.get(
                "summary",
                f"Risky runtime action requires approval for '{current_role}'.",
            ),
            "approval_status": "pending",
            "approval_data": {
                "checkpoint": str(approval_event.get("checkpoint", "risk_action_required")),
                "summary": str(
                    approval_event.get(
                        "summary",
                        f"Risky runtime action requires approval for '{current_role}'.",
                    )
                ),
                "current_role": current_role,
                "instance_id": current_instance,
                "tool_name": str(approval_event.get("tool_name", "")),
                "kind": str(approval_event.get("kind", "")),
                "severity": str(approval_event.get("severity", "")),
                "tool_input": approval_event.get("tool_input", {}),
                "requires_human_approval": bool(
                    approval_event.get("requires_human_approval", True)
                ),
                "approval_mode": "runtime_risk",
            },
            "agent_messages": agent_messages_log,
            "memory_context_by_role": memory_context_by_role,
            "memory_retrieval_log": memory_retrieval_log,
            "risk_action_queue": risk_action_queue,
            "required_approval_actions": required_approval_actions,
            "events": events,
            "duration_ms": duration_ms,
        }
    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start_time) * MS_PER_SECOND)
        logger.warning("Agent %s timed out after %ds", current_role, batch_timeout)
        events.append(
            {
                "type": "agent_timeout",
                "role": current_role,
                "timeout_seconds": batch_timeout,
                "duration_ms": duration_ms,
            }
        )
        return {
            "status": f"agent_{current_role}_timeout",
            "error": f"Agent '{current_role}' timed out after {batch_timeout}s",
            "events": events,
        }
    except Exception as exc:
        # Catch-all for LLM API errors, network failures, parsing errors, etc.
        # Without this, any unhandled exception crashes the entire graph node.
        duration_ms = int((time.monotonic() - start_time) * MS_PER_SECOND)
        err_type = type(exc).__name__
        err_msg = str(exc) or "(no message)"
        logger.error(
            "Agent %s failed with %s: %s",
            current_role,
            err_type,
            err_msg,
        )
        events.append(
            {
                "type": "agent_error",
                "role": current_role,
                "instance_id": current_instance,
                "error_type": err_type,
                "error": err_msg[:500],
                "duration_ms": duration_ms,
            }
        )
        return {
            "status": f"agent_{current_role}_error",
            "error": f"Agent '{current_role}' failed: {err_type}: {err_msg[:200]}",
            "events": events,
            "agent_outputs": state.get("agent_outputs", {}),
            "duration_ms": duration_ms,
        }

    duration_ms = int((time.monotonic() - start_time) * MS_PER_SECOND)

    # If this role had pending consultations, auto-respond with latest summary.
    _fulfill_pending_consults(
        current_role=current_role,
        final_text=final_text,
        state=state,
        agent_messages=agent_messages_log,
        events=events,
    )

    # --- Build output ---
    # Extract execution log from subtask_metrics (added by _run_agentic_loop)
    execution_log = subtask_metrics.get("execution_log", [])

    # Add execution verification status (Phase 14)
    # True if this role executed commands and should have verification results
    execution_verified = current_role in {"coder", "qa", "devops", "sre"} and len(execution_log) > 0

    agent_output: AgentOutput = {
        "summary": final_text,
        "files_changed": files_changed,
        "input_tokens": int(final_input_tokens),
        "output_tokens": int(final_output_tokens),
        "tokens": total_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
        "subtask_count": int(subtask_metrics.get("subtask_count", 0) or 0),
        "subtask_tokens": int(subtask_metrics.get("subtask_tokens", 0) or 0),
        "cached_input_tokens": int(cached_input_tokens),
        "cache_write_tokens": int(cache_write_tokens),
        "cache_source": cache_source,
        "cache_saved_tokens": int(cache_saved_tokens),
        "cache_saved_cost_usd": float(cache_saved_cost_usd),
        "execution_log": execution_log,  # Phase 14
        "execution_verified": execution_verified,  # Phase 14
    }

    # --- Contract guards (output) ---
    output_contract = agent_config.get("output_contract", {}) or {}
    output_payload = {
        "summary": final_text,
        "files_changed": files_changed,
        "tokens": total_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
        "status": f"agent_{current_role}_complete",
    }
    output_violations = _validate_contract(output_contract, output_payload)
    if output_violations:
        return _contract_failure_result(state, current_role, "output", output_violations)

    events.append(
        {
            "type": "agent_complete",
            "role": current_role,
            "instance_id": current_instance,
            "name": runtime_agent_config["name"],
            "specialisation": runtime_agent_config.get("specialisation", ""),
            "input_tokens": int(final_input_tokens),
            "output_tokens": int(final_output_tokens),
            "tokens": total_tokens,
            "cost": cost,
            "duration_ms": duration_ms,
            "files_changed": files_changed,
            "summary": final_text,
            "subtask_count": int(subtask_metrics.get("subtask_count", 0) or 0),
            "cached_input_tokens": int(cached_input_tokens),
            "cache_write_tokens": int(cache_write_tokens),
            "cache_source": cache_source,
            "cache_saved_tokens": int(cache_saved_tokens),
            "cache_saved_cost_usd": float(cache_saved_cost_usd),
            "execution_log": execution_log,
            "execution_verified": execution_verified,
        }
    )

    pending_consults = _pending_consultations(agent_messages_log)
    supervisory_decisions = _collect_event_records(
        state.get("supervisory_decisions"),
        events,
        {
            "master_decision",
            "master_spawn_decision",
            "master_consult_decision",
            "master_risk_escalation",
            "master_completion_judgment",
        },
    )
    spawn_history = _collect_event_records(
        state.get("spawn_history"),
        events,
        {"spawn_requested", "spawn_started", "spawn_completed"},
    )
    risk_action_queue = _collect_event_records(
        state.get("risk_action_queue"),
        events,
        {"risk_action_evaluated", "approval_required", "approval_denied"},
    )
    required_approval_actions = _collect_event_records(
        state.get("required_approval_actions"),
        events,
        {"approval_required"},
    )

    # Deregister agent from Rigour session
    if _rigour_session is not None:
        try:
            _rigour_session.agent_deregister(current_instance)
            _rigour_session.log_event(
                {
                    "type": "agent_completed",
                    "agentId": current_instance,
                    "role": current_role,
                }
            )
        except Exception:
            pass

    # ── Detect RECLASSIFY signal in agent output ──────────────────
    reclassify_detected, reclassify_type, reclassify_reason = _detect_reclassify_signal(
        final_text,
        current_role,
    )
    reclassify_fields: dict[str, Any] = {}
    if reclassify_detected:
        reclassify_count = int(state.get("reclassify_count", 0) or 0)
        if reclassify_count < 1:  # Budget check
            logger.info(
                "RECLASSIFY signal detected from %s: type=%s reason=%r",
                current_instance,
                reclassify_type,
                reclassify_reason[:200],
            )
            reclassify_fields = {
                "reclassify_requested": True,
                "reclassify_reason": reclassify_reason[:500],
                "reclassify_suggested_type": reclassify_type,
            }
            events.append(
                {
                    "type": "reclassify_signal",
                    "source_instance": current_instance,
                    "source_role": current_role,
                    "suggested_type": reclassify_type,
                    "reason": reclassify_reason[:200],
                }
            )
        else:
            logger.warning(
                "RECLASSIFY signal from %s ignored — budget exhausted (%d)",
                current_instance,
                reclassify_count,
            )

    return {
        "agent_outputs": {
            **state.get("agent_outputs", {}),
            # Key by instance_id so multiple agents of same role don't overwrite
            current_instance: agent_output,
        },
        "cost_accumulator": {
            **state.get("cost_accumulator", {}),
            agent_config["id"]: {
                "tokens": total_tokens,
                "cost": cost,
                "cached_input_tokens": int(cached_input_tokens),
                "cache_write_tokens": int(cache_write_tokens),
                "cache_saved_tokens": int(cache_saved_tokens),
                "cache_saved_cost_usd": float(cache_saved_cost_usd),
            },
        },
        "total_execution_count": total_execution_count,
        "status": f"agent_{current_instance}_complete",
        "agent_messages": agent_messages_log,
        "memory_context_by_role": memory_context_by_role,
        "memory_retrieval_log": memory_retrieval_log,
        "active_consultations": pending_consults,
        "spawn_history": spawn_history,
        "supervisory_decisions": supervisory_decisions,
        "risk_action_queue": risk_action_queue,
        "required_approval_actions": required_approval_actions,
        "events": events,
        **reclassify_fields,
    }


async def _execute_streaming(
    llm: LLMProvider,
    messages: list[dict[str, Any]],
    agent_config: dict[str, Any],
    idle_timeout: int,
    role: str,
    stream_callback: Any,
) -> LLMResponse:
    """Execute agent with streaming using idle timeout (text-only, no tools).

    Unlike a wall-clock timeout, this only triggers if NO tokens arrive
    for `idle_timeout` seconds. As long as the LLM is actively streaming,
    it runs indefinitely (like Claude Code, Cursor, Aider).
    """
    collected_text = ""
    stream = llm.stream(
        messages=messages,
        temperature=agent_config.get("temperature", DEFAULT_TEMPERATURE),
        max_tokens=agent_config.get("max_tokens", DEFAULT_MAX_TOKENS),
    )
    stream_iter = stream.__aiter__()

    while True:
        try:
            chunk = await asyncio.wait_for(
                stream_iter.__anext__(),
                timeout=idle_timeout,
            )
        except StopAsyncIteration:
            break  # Stream finished normally
        except asyncio.TimeoutError:
            logger.warning(
                "Agent %s idle for %ds (no tokens), aborting stream",
                role,
                idle_timeout,
            )
            break

        collected_text += chunk
        try:
            stream_callback(role, chunk)
        except Exception:
            logger.debug("Stream callback error for %s", role)

    # Build a synthetic LLMResponse from streamed content
    estimated_input = sum(
        len(m.get("content", "")) // 4 for m in messages if isinstance(m.get("content"), str)
    )
    estimated_output = len(collected_text) // 4

    return LLMResponse(
        content=collected_text,
        usage=LLMUsage(
            input_tokens=estimated_input,
            output_tokens=estimated_output,
        ),
        model=agent_config.get("llm_model", DEFAULT_LLM_MODEL),
        stop_reason="end_turn",
    )


async def execute_agents_parallel(
    state: TaskState,
    instance_ids: list[str],
    llm_factory: Any,
    cost_calculator: CostCalculator,
    stream_callback: Any | None = None,
    memory_repo: MemoryRepository | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    memory_retriever: MemoryRetriever | None = None,
) -> dict[str, Any]:
    """
    Execute multiple independent agent instances in parallel.

    Instance-ID aware: ``instance_ids`` are instance_ids like
    "reviewer-1", "qa-unit-1", not bare role names.

    Only used for agents that have no dependencies on each other's output.
    Each agent sees the SAME state — they don't see each other's results.
    """

    def _build_instance_state(base: TaskState, instance_id: str) -> TaskState:
        """Create an isolated task state for one parallel instance execution."""
        inst_state: TaskState = dict(base)
        inst_state["current_agent_role"] = instance_id  # Config key = instance_id
        inst_state["current_instance_id"] = instance_id
        # Isolate mutable collections so parallel agents can't cross-contaminate.
        inst_state["events"] = []
        inst_state["agent_messages"] = []
        inst_state["agent_outputs"] = dict(base.get("agent_outputs", {}))
        inst_state["cost_accumulator"] = dict(base.get("cost_accumulator", {}))
        inst_state["memory_context_by_role"] = dict(base.get("memory_context_by_role", {}))
        inst_state["memory_retrieval_log"] = dict(base.get("memory_retrieval_log", {}))
        inst_state["active_consultations"] = list(base.get("active_consultations", []))
        inst_state["spawn_history"] = list(base.get("spawn_history", []))
        inst_state["supervisory_decisions"] = list(base.get("supervisory_decisions", []))
        inst_state["risk_action_queue"] = list(base.get("risk_action_queue", []))
        inst_state["required_approval_actions"] = list(base.get("required_approval_actions", []))
        return inst_state

    tasks = []
    for iid in instance_ids:
        inst_state = _build_instance_state(state, iid)
        tasks.append(
            execute_agent_node(
                inst_state,
                llm_factory,
                cost_calculator,
                stream_callback,
                memory_repo=memory_repo,
                embedding_provider=embedding_provider,
                memory_retriever=memory_retriever,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge results
    merged_outputs = dict(state.get("agent_outputs", {}))
    merged_costs = dict(state.get("cost_accumulator", {}))
    merged_memory_context = dict(state.get("memory_context_by_role", {}))
    merged_memory_log = dict(state.get("memory_retrieval_log", {}))
    merged_events = list(state.get("events", []))
    merged_consults = list(state.get("active_consultations", []))
    merged_spawn_history = list(state.get("spawn_history", []))
    merged_supervisory = list(state.get("supervisory_decisions", []))
    merged_risk_actions = list(state.get("risk_action_queue", []))
    merged_required_approvals = list(state.get("required_approval_actions", []))

    for i, result in enumerate(results):
        iid = instance_ids[i]
        if isinstance(result, Exception):
            logger.error("Parallel agent %s failed: %s", iid, result)
            merged_events.append(
                {
                    "type": "agent_timeout",
                    "instance_id": iid,
                    "role": state.get("team_config", {})
                    .get("agents", {})
                    .get(iid, {})
                    .get("role", iid),
                    "error": str(result),
                }
            )
            continue
        if isinstance(result, dict):
            # Merge agent outputs keyed by instance_id
            role_outputs = result.get("agent_outputs", {})
            if iid in role_outputs:
                merged_outputs[iid] = role_outputs[iid]

            # Merge cost entry
            agent_id = str(
                state.get("team_config", {}).get("agents", {}).get(iid, {}).get("id", "")
            )
            role_costs = result.get("cost_accumulator", {})
            if agent_id and agent_id in role_costs:
                merged_costs[agent_id] = role_costs[agent_id]
            elif iid in merged_outputs:
                merged_costs[agent_id or iid] = {
                    "tokens": merged_outputs[iid].get("tokens", 0),
                    "cost": merged_outputs[iid].get("cost", 0.0),
                }
            merged_memory_context.update(result.get("memory_context_by_role", {}))
            merged_consults.extend(result.get("active_consultations", []))
            merged_spawn_history.extend(result.get("spawn_history", []))
            merged_supervisory.extend(result.get("supervisory_decisions", []))
            merged_risk_actions.extend(result.get("risk_action_queue", []))
            merged_required_approvals.extend(result.get("required_approval_actions", []))
            role_memory_log = result.get("memory_retrieval_log", {})
            if isinstance(role_memory_log, dict):
                for role_key, entries in role_memory_log.items():
                    if not isinstance(entries, list):
                        continue
                    existing_entries = merged_memory_log.get(role_key, [])
                    if not isinstance(existing_entries, list):
                        existing_entries = []
                    seen = {
                        str(e.get("memory_id", "")) for e in existing_entries if isinstance(e, dict)
                    }
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        mem_id = str(entry.get("memory_id", ""))
                        if not mem_id or mem_id in seen:
                            continue
                        existing_entries.append(entry)
                        seen.add(mem_id)
                    merged_memory_log[role_key] = existing_entries

            # Child instance states start with events=[], so this extends only new events.
            merged_events.extend(result.get("events", []))

    return {
        "agent_outputs": merged_outputs,
        "cost_accumulator": merged_costs,
        "memory_context_by_role": merged_memory_context,
        "memory_retrieval_log": merged_memory_log,
        "active_consultations": merged_consults,
        "spawn_history": merged_spawn_history,
        "supervisory_decisions": merged_supervisory,
        "risk_action_queue": merged_risk_actions,
        "required_approval_actions": merged_required_approvals,
        "events": merged_events,
        "status": "parallel_complete",
    }
