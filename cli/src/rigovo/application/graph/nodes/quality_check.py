"""Quality check node — runs deterministic gates on agent output."""

from __future__ import annotations

from typing import Any

from rigovo.application.graph.state import TaskState
from rigovo.domain.interfaces.quality_gate import QualityGate, GateInput
from rigovo.domain.entities.quality import GateStatus, FixPacket, FixItem


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

    # Only run gates on code-producing roles
    if current_role not in gates_after:
        return {
            "gate_results": {"status": "skipped", "passed": True},
            "status": f"gates_skipped_{current_role}",
            "events": state.get("events", []) + [{
                "type": "gate_results",
                "role": current_role,
                "status": "skipped",
                "passed": True,
            }],
        }

    # Get files changed by the current agent
    agent_output = state.get("agent_outputs", {}).get(current_role, {})
    files_changed = agent_output.get("files_changed", [])

    gate_input = GateInput(
        project_root=state.get("project_root", "."),
        files_changed=files_changed,
        agent_role=current_role,
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

    gate_summary = {
        "status": GateStatus.PASSED if all_passed else GateStatus.FAILED,
        "passed": all_passed,
        "gates_run": total_gates_run,
        "gates_passed": total_gates_passed,
        "violation_count": len(all_violations),
    }

    update: dict[str, Any] = {
        "gate_results": gate_summary,
        "events": state.get("events", []) + [{
            "type": "gate_results",
            "role": current_role,
            "passed": all_passed,
            "gates_run": total_gates_run,
            "violations": len(all_violations),
        }],
    }

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
        max_retries = state.get("max_retries", 3)

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
