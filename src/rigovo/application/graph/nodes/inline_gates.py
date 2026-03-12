"""Inline quality gates — run inside the agentic loop when agent signals 'done'.

Instead of discovering violations AFTER the agent finishes (and losing all
conversation context in a retry loop), we run quality gates inline.  When
violations are found, they're injected as a USER message so the agent
self-corrects in the SAME context window — zero context loss.

This is the key architectural change: quality governance moves from a
post-hoc gate to an inline feedback loop, just like a human developer
running ``npm run lint`` before committing.

Deep/Pro smart escalation (mirrors quality_check._resolve_deep_mode):
  attempt 1: deterministic only (fast, ~2s)
  attempt 2: --deep (AST + lite model, ~10s)
  attempt 3+: --deep --pro (full Qwen2.5-Coder-1.5B, ~20s)
  critical/security: always --deep --pro
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Timeout per deep tier (seconds)
_TIMEOUT_DETERMINISTIC = 30
_TIMEOUT_DEEP = 60
_TIMEOUT_DEEP_PRO = 90

# Max files per tier (deep analysis is slower, so fewer files)
_MAX_FILES_DETERMINISTIC = 15
_MAX_FILES_DEEP = 10
_MAX_FILES_DEEP_PRO = 8


@dataclass
class InlineGateResult:
    """Result of running inline quality gates."""

    passed: bool
    violations: list[dict[str, Any]] = field(default_factory=list)
    violation_summary: str = ""
    gate_ran: bool = False  # True only when Rigour CLI actually executed
    deep_mode: str = "off"  # "off", "deep", "deep+pro"


def _resolve_inline_deep(
    attempt: int,
    agent_role: str,
    is_critical: bool = False,
) -> tuple[bool, bool, int, int]:
    """Decide deep/pro flags for inline gate based on attempt and context.

    Returns:
        (use_deep, use_pro, timeout, max_files)
    """
    # Critical tasks or security roles: always deep + pro
    if is_critical or agent_role in ("security", "qa"):
        return True, True, _TIMEOUT_DEEP_PRO, _MAX_FILES_DEEP_PRO

    # Progressive escalation with attempts
    if attempt >= 3:
        return True, True, _TIMEOUT_DEEP_PRO, _MAX_FILES_DEEP_PRO
    if attempt >= 2:
        return True, False, _TIMEOUT_DEEP, _MAX_FILES_DEEP

    # First pass: deterministic only (fast)
    return False, False, _TIMEOUT_DETERMINISTIC, _MAX_FILES_DETERMINISTIC


async def run_inline_quality_gates(
    project_root: str,
    files_changed: list[str],
    agent_role: str,
    *,
    attempt: int = 1,
    is_critical: bool = False,
    prev_violations: list[dict[str, Any]] | None = None,
) -> InlineGateResult:
    """Run quality gates inline and return result for conversation injection.

    This reuses the Rigour CLI (same as mid-execution checks and the
    quality_check node) but runs at the "agent done" boundary — when the
    agent has no more tool calls.  If violations are found, the caller
    injects the summary as a USER message and continues the loop.

    Args:
        project_root: Absolute path to the project root.
        files_changed: List of file paths written by the agent.
        agent_role: The agent's role (coder, qa, etc.) for filtering.
        attempt: Current inline gate attempt number (1-based) for escalation.
        is_critical: Whether the task is classified as critical complexity.
        prev_violations: Violations from the previous inline attempt (if any).
            Used to detect persistent violations and inject targeted guidance
            so the agent doesn't repeat the same failed approach.

    Returns:
        InlineGateResult with pass/fail, violations, and a summary string
        suitable for injection as a USER message.
    """
    if not files_changed:
        return InlineGateResult(passed=True)

    from rigovo.infrastructure.quality.rigour_gate import RigourQualityGate

    binary = RigourQualityGate._find_binary(project_root)
    if not binary:
        # No Rigour binary — pass by default (graceful degradation)
        return InlineGateResult(passed=True)

    try:
        use_deep, use_pro, timeout, max_files = _resolve_inline_deep(
            attempt, agent_role, is_critical
        )

        # Build deep mode label for logging/events
        deep_label = "off"
        if use_deep and use_pro:
            deep_label = "deep+pro"
        elif use_deep:
            deep_label = "deep"

        check_files = files_changed[:max_files]
        cmd_args = ["check", "--json"]
        if use_deep:
            cmd_args.append("--deep")
        if use_pro:
            cmd_args.append("--pro")
        cmd_args.extend(check_files)

        cmd = RigourQualityGate._build_cmd(binary, *cmd_args)

        logger.debug(
            "Inline gate: attempt=%d, deep=%s, files=%d, timeout=%ds",
            attempt,
            deep_label,
            len(check_files),
            timeout,
        )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=project_root,
            ),
        )
        if not result.stdout.strip():
            return InlineGateResult(passed=True, gate_ran=True, deep_mode=deep_label)

        data = json.loads(result.stdout)
        failures = data.get("failures", [])
        if not failures:
            return InlineGateResult(passed=True, gate_ran=True, deep_mode=deep_label)

        # Filter to critical/high/medium severity violations
        violations = [
            {
                "gate_id": f.get("id", ""),
                "message": f.get("title", f.get("details", "")),
                "severity": f.get("severity", "medium"),
                "files": f.get("files", []),
                "hint": f.get("hint", ""),
                "provenance": f.get("provenance", "traditional"),
            }
            for f in failures
            if f.get("severity") in ("critical", "high", "medium")
        ]

        if not violations:
            return InlineGateResult(passed=True, gate_ran=True, deep_mode=deep_label)

        # ── Detect persistent violations ──────────────────────────────────
        # Compare current violations against previous attempt to identify
        # which issues the agent's last fix attempt did NOT resolve.
        persistent_ids: set[str] = set()
        if prev_violations:
            prev_fps = {
                (v.get("gate_id", ""), tuple(sorted(str(f) for f in v.get("files", []))))
                for v in prev_violations
            }
            for v in violations:
                fp = (v.get("gate_id", ""), tuple(sorted(str(f) for f in v.get("files", []))))
                if fp in prev_fps:
                    persistent_ids.add(v.get("gate_id", ""))

        # Build a summary suitable for injection as a USER message
        mode_note = ""
        if use_deep:
            mode_note = f" [deep{'+ pro' if use_pro else ''} analysis]"

        summary_parts: list[str] = []

        # Lead with persistence warning — agent MUST change approach
        if persistent_ids:
            summary_parts += [
                f"⚠️  SAME VIOLATIONS FOUND AGAIN (attempt {attempt}) — "
                "your previous fix did NOT work.",
                "You MUST use a COMPLETELY DIFFERENT approach for the persisting issues below.",
                "Do NOT repeat what you already tried. Consider:",
                "  • Simplify the code instead of restructuring it",
                "  • Delete or inline the offending code rather than refactoring",
                "  • Reduce function/file size by extracting helpers",
                "  • Remove unnecessary abstractions that trigger complexity gates",
                "",
            ]

        summary_parts += [
            f"INLINE QUALITY CHECK FAILED ({len(violations)} issue(s)){mode_note}:",
            "",
        ]
        for i, v in enumerate(violations[:5], 1):
            msg = v.get("message", "unknown issue")
            hint = v.get("hint", "")
            files = v.get("files", [])
            prov = v.get("provenance", "")
            file_str = ", ".join(str(f) for f in files[:3]) if files else "unknown"
            prov_tag = f" [{prov}]" if prov and prov != "traditional" else ""
            persisting_tag = " ⚠️ PERSISTING" if v.get("gate_id", "") in persistent_ids else ""
            summary_parts.append(
                f"  {i}. [{v.get('severity', '?').upper()}]{prov_tag} {msg}{persisting_tag}"
            )
            if hint:
                summary_parts.append(f"     Hint: {hint}")
            summary_parts.append(f"     Files: {file_str}")

        if len(violations) > 5:
            summary_parts.append(f"  ... and {len(violations) - 5} more issues")

        summary_parts.append("")
        summary_parts.append(
            "Fix these issues NOW using write_file, then run_command to verify. "
            "Do NOT stop until all quality checks pass."
        )

        return InlineGateResult(
            passed=False,
            violations=violations,
            violation_summary="\n".join(summary_parts),
            gate_ran=True,
            deep_mode=deep_label,
        )

    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        logger.debug("Inline quality gate check failed gracefully: %s", exc)
        # Graceful degradation — never block the agent
        return InlineGateResult(passed=True)
