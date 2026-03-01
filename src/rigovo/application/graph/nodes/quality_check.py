"""Quality check node — runs deterministic gates on agent output.

Phase 7: Now includes persona boundary enforcement and role-aware
gate filtering. The quality check pipeline is:

1. Contract failure check (hard stop)
2. Skip check for non-code-producing roles
3. No-files-produced check for code-producing roles
4. Run Rigour quality gates (AST analysis)
5. Incorporate execution verification results (Phase 4)
6. Persona boundary enforcement (Phase 7) — check agent stayed in scope
7. Build fix packet with role-aware severity (Phase 7)
"""

from __future__ import annotations

from typing import Any

from rigovo.application.context.rigour_supervisor import (
    CODE_PRODUCING_ROLES,
    PERSONA_BOUNDARIES,
    PersonaViolation,
    RigourSupervisor,
)
from rigovo.application.graph.state import TaskState
from rigovo.domain.entities.quality import (
    FixItem,
    FixPacket,
    GateStatus,
    Violation,
    ViolationSeverity,
)
from rigovo.domain.interfaces.quality_gate import GateInput, QualityGate


def _serialize_violation(violation: Violation) -> dict[str, Any]:
    return {
        "rule": violation.gate_id,
        "gate_id": violation.gate_id,
        "file_path": violation.file_path,
        "message": violation.message,
        "suggestion": violation.suggestion,
        "severity": str(
            violation.severity.value if hasattr(violation.severity, "value") else violation.severity
        ),
        "line": violation.line,
    }


def _resolve_deep_mode(state: TaskState, current_role: str) -> tuple[bool, bool]:
    """
    Decide whether to enable Rigour deep analysis for this gate run.

    Modes:
    - never: disable always
    - always: enable on every gated agent step
    - ci: enable only when task is launched in CI mode
    - critical_only: enable only for critical tasks
    - final (default): enable only for the final gated role in the pipeline
    """
    mode = str(state.get("deep_mode", "final")).strip().lower()
    use_pro = bool(state.get("deep_pro", False))

    if mode == "never":
        return False, use_pro
    if mode == "always":
        return True, use_pro
    if mode == "ci":
        return bool(state.get("ci_mode", False)), use_pro
    if mode == "critical_only":
        classification = state.get("classification", {})
        return classification.get("complexity") == "critical", use_pro

    # final (default): run deep only on the last code-gated role.
    team_config = state.get("team_config", {})
    pipeline_order = team_config.get("pipeline_order", [])
    gates_after = set(team_config.get("gates_after", []))
    gated_in_order = [r for r in pipeline_order if r in gates_after]
    if not gated_in_order:
        return False, use_pro
    return current_role == gated_in_order[-1], use_pro


def _check_persona_boundaries(
    current_role: str,
    base_role: str,
    files_changed: list[str],
    output_summary: str,
) -> list[PersonaViolation]:
    """Run persona boundary checks (Phase 7).

    Uses the base role for boundary lookup (so "backend-engineer-1"
    maps to "coder" boundaries).
    """
    supervisor = RigourSupervisor()
    return supervisor.check_persona_boundaries(
        role=base_role,
        files_changed=files_changed,
        output_summary=output_summary,
    )


def _persona_violations_to_gate_violations(
    persona_violations: list[PersonaViolation],
) -> list[Violation]:
    """Convert persona boundary violations to standard Violation objects."""
    severity_map = {
        "critical": ViolationSeverity.ERROR,
        "high": ViolationSeverity.ERROR,
        "medium": ViolationSeverity.WARNING,
        "low": ViolationSeverity.WARNING,
        "info": ViolationSeverity.INFO,
    }
    result: list[Violation] = []
    for pv in persona_violations:
        result.append(Violation(
            gate_id=f"persona-{pv.violation_type}",
            message=pv.message,
            severity=severity_map.get(pv.severity, ViolationSeverity.WARNING),
            file_path=pv.file_path or None,
            category="persona",
            suggestion=f"Stay within the '{pv.role}' role scope.",
        ))
    return result


async def quality_check_node(
    state: TaskState,
    quality_gates: list[QualityGate],
) -> dict[str, Any]:
    """
    Run deterministic quality gates on the current agent's output.

    No LLM opinions. Pure AST analysis. Same input → same output.
    Phase 7: Now also enforces persona boundaries and role-aware severity.
    """
    current_role = state["current_agent_role"]
    team_config = state["team_config"]
    gates_after = team_config.get("gates_after", [])

    # Resolve base role for instance-based agents (e.g., "backend-engineer-1" → "coder")
    base_role = team_config.get("agents", {}).get(current_role, {}).get("role", current_role)

    # Contract failures are hard-stop gate failures (no retry loop).
    status = str(state.get("status", ""))
    if status.startswith("contract_failed_"):
        max_retries = state.get("max_retries", 5)
        contract_violations = list(state.get("contract_violations", []))
        structured_violations = [
            {
                "rule": "contract_failed",
                "gate_id": "contract_failed",
                "file_path": "",
                "message": str(v),
                "suggestion": "",
                "severity": "error",
                "line": None,
            }
            for v in contract_violations
        ]
        gate_summary = {
            "status": GateStatus.FAILED,
            "passed": False,
            "reason": "contract_failed",
            "gates_run": 1,
            "gates_passed": 0,
            "violation_count": len(contract_violations),
            "violations": structured_violations,
        }
        events = list(state.get("events", []))
        events.append(
            {
                "type": "gate_results",
                "role": current_role,
                "passed": False,
                "gates_run": 1,
                "violations": len(contract_violations),
                "reason": "contract_failed",
            }
        )
        gate_history = list(state.get("gate_history", []))
        gate_history.append({"role": current_role, **gate_summary})
        return {
            "gate_results": gate_summary,
            "gate_history": gate_history,
            "retry_count": max_retries,
            "status": f"gate_failed_{current_role}",
            "events": events,
        }

    # Only run gates on code-producing roles
    if current_role not in gates_after:
        # Phase 7: Still run persona checks on non-gated roles.
        # Forbidden file writes by non-code roles ARE enforced as failures.
        agent_output = state.get("agent_outputs", {}).get(current_role, {})
        output_summary = agent_output.get("summary", "")
        files_changed = agent_output.get("files_changed", [])
        persona_violations = _check_persona_boundaries(
            current_role, base_role, files_changed, output_summary,
        )

        # Separate hard violations (forbidden_file) from soft (missing_output_marker)
        hard_violations = [pv for pv in persona_violations if pv.violation_type == "forbidden_file"]
        soft_violations = [pv for pv in persona_violations if pv.violation_type != "forbidden_file"]

        events = list(state.get("events", []))

        if hard_violations:
            # Non-code roles writing files is a gate failure
            gate_violations = _persona_violations_to_gate_violations(hard_violations)
            structured_violations = [_serialize_violation(v) for v in gate_violations]
            gate_summary = {
                "status": GateStatus.FAILED,
                "passed": False,
                "reason": "persona_violation",
                "gates_run": 1,
                "gates_passed": 0,
                "violation_count": len(hard_violations),
                "violations": structured_violations,
            }
            events.append({
                "type": "gate_results",
                "role": current_role,
                "passed": False,
                "gates_run": 1,
                "violations": len(hard_violations),
                "reason": "persona_violation",
            })
            gate_history = list(state.get("gate_history", []))
            gate_history.append({"role": current_role, **gate_summary})

            # Build fix packet for retry
            fix_items = [
                FixItem(
                    gate_id=v.gate_id,
                    file_path=v.file_path or "",
                    message=v.message,
                    suggestion=v.suggestion,
                    severity=v.severity,
                    line=v.line,
                )
                for v in gate_violations
            ]
            retry_count = state.get("retry_count", 0) + 1
            max_retries = state.get("max_retries", 5)
            fix_packet = FixPacket(
                items=fix_items,
                attempt=retry_count,
                max_attempts=max_retries,
            )
            return {
                "gate_results": gate_summary,
                "gate_history": gate_history,
                "fix_packets": state.get("fix_packets", []) + [fix_packet.to_prompt()],
                "retry_count": retry_count,
                "status": f"gate_failed_{current_role}",
                "events": events,
            }

        # No hard violations — log soft ones as advisory
        events.append(
            {
                "type": "gate_results",
                "role": current_role,
                "status": "skipped",
                "passed": True,
            }
        )
        if soft_violations:
            events.append({
                "type": "persona_check",
                "role": current_role,
                "violations": len(soft_violations),
                "details": [pv.message for pv in soft_violations[:5]],
            })

        # Record the skip in gate_history for audit completeness
        gate_history = list(state.get("gate_history", []))
        gate_history.append({
            "role": current_role,
            "status": GateStatus.SKIPPED,
            "passed": True,
            "reason": "gates_skipped",
            "gates_run": 0,
            "gates_passed": 0,
            "violation_count": 0,
            "violations": [],
            "deep": False,
            "pro": False,
        })
        return {
            "gate_results": {"status": "skipped", "passed": True},
            "gate_history": gate_history,
            "status": f"gates_skipped_{current_role}",
            "events": events,
        }

    # Get files changed by the current agent
    agent_output = state.get("agent_outputs", {}).get(current_role, {})
    files_changed = agent_output.get("files_changed", [])

    # Code-producing agents MUST produce files. If they didn't, that's a failure.
    if base_role in CODE_PRODUCING_ROLES and not files_changed:
        violation = Violation(
            gate_id="no-files-produced",
            message=f"Agent '{current_role}' is expected to produce code but wrote 0 files",
            severity=ViolationSeverity.ERROR,
            suggestion="Use the write_file tool to create or modify files",
        )
        retry_count = state.get("retry_count", 0) + 1
        max_retries = state.get("max_retries", 5)

        fix_packet = FixPacket(
            items=[
                FixItem(
                    gate_id=violation.gate_id,
                    file_path="",
                    message=violation.message,
                    suggestion=violation.suggestion or "",
                    severity=violation.severity,
                )
            ],
            attempt=retry_count,
            max_attempts=max_retries,
        )

        gate_summary = {
            "status": GateStatus.FAILED,
            "passed": False,
            "reason": "no_files_produced",
            "gates_run": 1,
            "gates_passed": 0,
            "violation_count": 1,
            "violations": [_serialize_violation(violation)],
        }
        gate_history = list(state.get("gate_history", []))
        gate_history.append({"role": current_role, **gate_summary})
        return {
            "gate_results": gate_summary,
            "gate_history": gate_history,
            "fix_packets": state.get("fix_packets", []) + [fix_packet.to_prompt()],
            "retry_count": retry_count,
            "status": f"gate_failed_{current_role}",
            "events": state.get("events", [])
            + [
                {
                    "type": "gate_results",
                    "role": current_role,
                    "passed": False,
                    "gates_run": 1,
                    "violations": 1,
                }
            ],
        }

    run_deep, run_pro = _resolve_deep_mode(state, current_role)
    gate_input = GateInput(
        project_root=state.get("project_root", "."),
        files_changed=files_changed,
        agent_role=current_role,
        deep=run_deep,
        pro=run_pro,
    )

    # Run all quality gates
    all_passed = True
    all_violations = []
    total_gates_run = 0
    total_gates_passed = 0

    for gate in quality_gates:
        result = await gate.run(gate_input)
        total_gates_run += result.gates_run
        total_gates_passed += result.gates_passed

        if not result.passed:
            all_passed = False
            all_violations.extend(result.violations)

    # Phase 7: Apply role-aware violation filtering
    supervisor = RigourSupervisor()
    filtered_violations = supervisor.filter_violations_for_role(all_violations, base_role)

    # Phase 7: Check persona boundaries
    output_summary = agent_output.get("summary", "")
    persona_violations = _check_persona_boundaries(
        current_role, base_role, files_changed, output_summary,
    )
    persona_gate_violations = _persona_violations_to_gate_violations(persona_violations)
    if persona_gate_violations:
        filtered_violations.extend(persona_gate_violations)

    # Re-evaluate pass/fail with filtered violations
    has_errors = any(v.severity == ViolationSeverity.ERROR for v in filtered_violations)
    if has_errors:
        all_passed = False

    structured_violations = [_serialize_violation(v) for v in filtered_violations]
    gate_summary = {
        "status": GateStatus.PASSED if all_passed else GateStatus.FAILED,
        "passed": all_passed,
        "gates_run": total_gates_run,
        "gates_passed": total_gates_passed,
        "violation_count": len(filtered_violations),
        "violations": structured_violations,
        "deep": run_deep,
        "pro": run_pro,
    }
    gate_history = list(state.get("gate_history", []))
    gate_history.append({"role": current_role, **gate_summary})

    update: dict[str, Any] = {
        "gate_results": gate_summary,
        "gate_history": gate_history,
        "events": state.get("events", [])
        + [
            {
                "type": "gate_results",
                "role": current_role,
                "deep": run_deep,
                "pro": run_pro,
                "passed": all_passed,
                "gates_run": total_gates_run,
                "violations": len(filtered_violations),
                "reason": "gates_passed" if all_passed else "gates_failed",
            }
        ],
    }

    # ── Incorporate execution verification results (Phase 4) ──────────
    # If verify_execution_node ran before us, check its results too.
    exec_verification = state.get("execution_verification", {})
    if isinstance(exec_verification, dict) and exec_verification.get("passed") is False:
        # Execution verification failed — treat as gate failure
        failure_details = exec_verification.get("failure_details", [])
        for detail in failure_details:
            filtered_violations.append(
                Violation(
                    gate_id="execution-verification-failed",
                    message=str(detail)[:500],
                    severity=ViolationSeverity.ERROR,
                    suggestion="Fix the runtime errors. The code must compile, build, and pass tests.",
                    category="correctness",
                )
            )
        if failure_details:
            all_passed = False
            structured_violations = [_serialize_violation(v) for v in filtered_violations]
            gate_summary["violations"] = structured_violations
            gate_summary["violation_count"] = len(filtered_violations)
            gate_summary["passed"] = False
            gate_summary["status"] = GateStatus.FAILED

    # If failed, build a fix packet for the retry
    if not all_passed:
        fix_items = [
            FixItem(
                gate_id=v.gate_id,
                file_path=v.file_path or "",
                message=v.message,
                suggestion=v.suggestion,
                severity=v.severity,
                line=v.line,
            )
            for v in filtered_violations
        ]
        retry_count = state.get("retry_count", 0) + 1
        max_retries = state.get("max_retries", 5)

        fix_packet = FixPacket(
            items=fix_items,
            attempt=retry_count,
            max_attempts=max_retries,
        )

        update["fix_packets"] = state.get("fix_packets", []) + [fix_packet.to_prompt()]
        update["retry_count"] = retry_count
        update["status"] = f"gate_failed_{current_role}"
    else:
        update["status"] = f"gate_passed_{current_role}"

    return update
