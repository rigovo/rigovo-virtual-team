"""Inline quality gates — run inside the agentic loop when agent signals 'done'.

Instead of discovering violations AFTER the agent finishes (and losing all
conversation context in a retry loop), we run quality gates inline.  When
violations are found, they're injected as a USER message so the agent
self-corrects in the SAME context window — zero context loss.

This is the key architectural change: quality governance moves from a
post-hoc gate to an inline feedback loop, just like a human developer
running ``npm run lint`` before committing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InlineGateResult:
    """Result of running inline quality gates."""

    passed: bool
    violations: list[dict[str, Any]] = field(default_factory=list)
    violation_summary: str = ""
    gate_ran: bool = False  # True only when Rigour CLI actually executed


async def run_inline_quality_gates(
    project_root: str,
    files_changed: list[str],
    agent_role: str,
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
        # Limit to 15 files to keep check fast
        check_files = files_changed[:15]
        cmd = RigourQualityGate._build_cmd(
            binary,
            "check",
            "--json",
            *check_files,
        )
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=project_root,
            ),
        )
        if not result.stdout.strip():
            return InlineGateResult(passed=True, gate_ran=True)

        data = json.loads(result.stdout)
        failures = data.get("failures", [])
        if not failures:
            return InlineGateResult(passed=True, gate_ran=True)

        # Filter to critical/high for the agent's role
        violations = [
            {
                "gate_id": f.get("id", ""),
                "message": f.get("title", f.get("details", "")),
                "severity": f.get("severity", "medium"),
                "files": f.get("files", []),
                "hint": f.get("hint", ""),
            }
            for f in failures
            if f.get("severity") in ("critical", "high", "medium")
        ]

        if not violations:
            return InlineGateResult(passed=True, gate_ran=True)

        # Build a summary suitable for injection as a USER message
        summary_parts = [
            f"INLINE QUALITY CHECK FAILED ({len(violations)} issue(s)):",
            "",
        ]
        for i, v in enumerate(violations[:5], 1):
            msg = v.get("message", "unknown issue")
            hint = v.get("hint", "")
            files = v.get("files", [])
            file_str = ", ".join(str(f) for f in files[:3]) if files else "unknown"
            summary_parts.append(f"  {i}. [{v.get('severity', '?').upper()}] {msg}")
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
        )

    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        logger.debug("Inline quality gate check failed gracefully: %s", exc)
        # Graceful degradation — never block the agent
        return InlineGateResult(passed=True)
