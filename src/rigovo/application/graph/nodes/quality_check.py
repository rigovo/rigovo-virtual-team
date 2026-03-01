"""Quality check node — runs deterministic gates on agent output."""

from __future__ import annotations

from typing import Any

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


async def quality_check_node(
    state: TaskState,
    quality_gates: list[QualityGate],
) -> dict[str, Any]:
    """
    Run deterministic quality gates on the current agent's output.

    No LLM opinions. Pure AST analysis. Same input → same output.
    """
    current_role = state["current_agent_role"]
    team_config = state["team_config"]
    gates_after = team_config.get("gates_after", [])

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
        return {
            "gate_results": {"status": "skipped", "passed": True},
            "status": f"gates_skipped_{current_role}",
            "events": state.get("events", [])
            + [
                {
                    "type": "gate_results",
                    "role": current_role,
                    "status": "skipped",
                    "passed": True,
                }
            ],
        }

    # Get files changed by the current agent
    agent_output = state.get("agent_outputs", {}).get(current_role, {})
    files_changed = agent_output.get("files_changed", [])

    # Code-producing agents MUST produce files. If they didn't, that's a failure.
    code_producing_roles = {"coder", "qa", "devops", "sre"}
    if current_role in code_producing_roles and not files_changed:
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

    structured_violations = [_serialize_violation(v) for v in all_violations]
    gate_summary = {
        "status": GateStatus.PASSED if all_passed else GateStatus.FAILED,
        "passed": all_passed,
        "gates_run": total_gates_run,
        "gates_passed": total_gates_passed,
        "violation_count": len(all_violations),
        "violations": structured_violations,
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
                "violations": len(all_violations),
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
            all_violations.append(
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
            structured_violations = [_serialize_violation(v) for v in all_violations]
            gate_summary["violations"] = structured_violations
            gate_summary["violation_count"] = len(all_violations)
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
            for v in all_violations
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
