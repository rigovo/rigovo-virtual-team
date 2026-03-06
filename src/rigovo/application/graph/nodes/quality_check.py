"""Quality check node — runs deterministic gates on agent output.

Phase 7: Now includes persona boundary enforcement and role-aware
gate filtering.

Phase 9: Adds structural validation for Master Agent (classify role) output.

The quality check pipeline is:

1. Master Agent validation (Phase 9) — if current role is classify/master
2. Contract failure check (hard stop)
3. Skip check for non-code-producing roles
4. No-files-produced check for code-producing roles
5. Run Rigour quality gates (AST analysis)
6. Incorporate execution verification results (Phase 4)
7. Persona boundary enforcement (Phase 7) — check agent stayed in scope
8. Build fix packet with role-aware severity (Phase 7)
"""

from __future__ import annotations

from typing import Any

from rigovo.application.context.rigour_supervisor import (
    CODE_PRODUCING_ROLES,
    PersonaViolation,
    RigourSupervisor,
)
from rigovo.application.graph.agent_identity import (
    resolve_agent_output,
    resolve_base_role,
    resolve_current_instance_id,
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


def _serialize_fix_packet(
    packet: FixPacket,
    *,
    role: str,
    gate_source: str,
    affected_files: list[str],
    remediation_phase: str,
    allowed_patch_scope: list[str] | None = None,
    required_verification_commands: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize a FixPacket for graph state, persistence, and UI."""
    return {
        "role": role,
        "gate_source": gate_source,
        "attempt": packet.attempt,
        "max_attempts": packet.max_attempts,
        "affected_files": affected_files,
        "allowed_patch_scope": list(allowed_patch_scope or affected_files),
        "required_verification_commands": list(required_verification_commands or []),
        "remediation_phase": remediation_phase,
        "items": [
            {
                "gate_id": item.gate_id,
                "file_path": item.file_path,
                "message": item.message,
                "suggestion": item.suggestion,
                "severity": str(
                    item.severity.value if hasattr(item.severity, "value") else item.severity
                ),
                "line": item.line,
            }
            for item in packet.items
        ],
        "prompt": packet.to_prompt(),
    }


def _remediation_update(
    state: TaskState,
    *,
    current_role: str,
    gate_summary: dict[str, Any],
    fix_packet: FixPacket,
    gate_source: str,
    affected_files: list[str],
    remediation_phase: str,
    retry_count: int,
    max_retries: int,
    extra_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the common remediation state payload for failed gate runs."""
    active_fix_packet = _serialize_fix_packet(
        fix_packet,
        role=current_role,
        gate_source=gate_source,
        affected_files=affected_files,
        remediation_phase=remediation_phase,
    )
    events = list(state.get("events", [])) + [
        {
            "type": "fix_packet_created",
            "role": current_role,
            "gate_source": gate_source,
            "attempt": retry_count,
            "max_attempts": max_retries,
            "affected_files": affected_files,
            "violation_count": len(active_fix_packet["items"]),
        },
        {
            "type": "remediation_started",
            "role": current_role,
            "attempt": retry_count,
            "phase": remediation_phase,
        },
        {
            "type": "downstream_locked",
            "role": current_role,
            "reason": f"awaiting gate remediation by {current_role}",
        },
        *list(extra_events or []),
    ]
    return {
        "gate_results": gate_summary,
        "active_fix_packet": active_fix_packet,
        "fix_packets": state.get("fix_packets", []) + [active_fix_packet["prompt"]],
        "retry_count": retry_count,
        "downstream_lock_reason": f"awaiting gate remediation by {current_role}",
        "events": events,
        "status": f"gate_failed_{current_role}",
    }


def _resolve_deep_mode(state: TaskState, current_role: str) -> tuple[bool, bool]:
    """
    Decide whether to enable Rigour deep analysis for this gate run.

    Modes:
    - never: disable always
    - always: enable on every gated agent step
    - ci: enable only when task is launched in CI mode
    - critical_only: enable only for critical tasks
    - smart (default): intelligent per-step analysis
    - final: enable only for the final gated role in the pipeline

    Smart mode logic:
    - If retry_count > 0: enable deep (catching subtle issues on retry)
    - If complexity == "critical": enable deep
    - If base_role == "security": enable deep (security is non-negotiable)
    - If this is the last code-gated role in pipeline: enable deep
    - Otherwise: standard gates only (fast first pass)
    """
    mode = str(state.get("deep_mode", "smart")).strip().lower()
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

    if mode == "smart":
        # Smart mode: enable deep analysis when it matters most
        retry_count = state.get("retry_count", 0)
        if retry_count > 0:
            # On retry, use deep to catch subtle issues
            return True, use_pro

        # Check task complexity
        classification = state.get("classification", {})
        if classification.get("complexity") == "critical":
            return True, use_pro

        # Check base role — security is non-negotiable
        team_config = state.get("team_config", {})
        agents = team_config.get("agents", {})
        agent_config = agents.get(current_role, {})
        base_role = agent_config.get("role", current_role)
        if base_role == "security":
            return True, use_pro

        # Check if this is the last code-gated role in pipeline
        pipeline_order = team_config.get("pipeline_order", [])
        gates_after = set(team_config.get("gates_after", []))
        gated_in_order = [r for r in pipeline_order if r in gates_after]
        if gated_in_order and current_role == gated_in_order[-1]:
            return True, use_pro

        # Otherwise: standard gates only (fast first pass)
        return False, use_pro

    # final: run deep only on the last code-gated role.
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
        result.append(
            Violation(
                gate_id=f"persona-{pv.violation_type}",
                message=pv.message,
                severity=severity_map.get(pv.severity, ViolationSeverity.WARNING),
                file_path=pv.file_path or None,
                category="persona",
                suggestion=f"Stay within the '{pv.role}' role scope.",
            )
        )
    return result


async def _validate_master_agent_output(
    state: TaskState,
    current_role: str,
) -> dict[str, Any]:
    """Validate Master Agent (classify role) structural output.

    The Master Agent produces a staffing plan that must satisfy:
    1. At least 1 agent assigned
    2. All depends_on references must exist in the agent list
    3. No circular dependencies in the pipeline
    4. Has domain_analysis and architecture_notes

    This is NOT a quality gate in the traditional sense — it's a structural
    validation that the Master Agent's output is logically sound.
    """
    staffing_plan = state.get("staffing_plan", {})
    agent_list = staffing_plan.get("agents", [])
    execution_dag = staffing_plan.get("execution_dag", {})

    violations: list[Violation] = []

    # Check 1: At least one agent
    if not agent_list:
        violations.append(
            Violation(
                gate_id="master-no-agents",
                message="Staffing plan must include at least 1 agent",
                severity=ViolationSeverity.ERROR,
                suggestion="Master Agent must assign at least a planner and a coder",
                category="structural",
            )
        )

    # Check 2: Validate all depends_on references exist
    instance_ids = {a.get("instance_id") for a in agent_list if isinstance(a, dict)}
    for agent in agent_list:
        if not isinstance(agent, dict):
            continue
        instance_id = agent.get("instance_id")
        depends_on = agent.get("depends_on", [])
        for dep in depends_on:
            if dep not in instance_ids:
                violations.append(
                    Violation(
                        gate_id="master-invalid-dependency",
                        message=f"Agent '{instance_id}' depends on '{dep}' which does not exist",
                        severity=ViolationSeverity.ERROR,
                        suggestion="Ensure all dependencies reference existing agents in the plan",
                        category="structural",
                        file_path=None,
                    )
                )

    # Check 3: Detect circular dependencies (simple cycle detection)
    if execution_dag:
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def has_cycle(node: str) -> bool:
            """DFS to detect cycles."""
            visited.add(node)
            rec_stack.add(node)

            for neighbor in execution_dag.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.discard(node)
            return False

        for agent_id in execution_dag:
            if agent_id not in visited:
                if has_cycle(agent_id):
                    violations.append(
                        Violation(
                            gate_id="master-circular-dependency",
                            message=f"Circular dependency detected in pipeline involving '{agent_id}'",
                            severity=ViolationSeverity.ERROR,
                            suggestion="Fix the dependency graph so no agent waits (directly or indirectly) on its own work",
                            category="structural",
                        )
                    )
                    break

    # Check 4: Verify domain_analysis and architecture_notes exist
    if not staffing_plan.get("domain_analysis"):
        violations.append(
            Violation(
                gate_id="master-missing-analysis",
                message="Staffing plan must include domain_analysis (2-3 sentences)",
                severity=ViolationSeverity.WARNING,
                suggestion="Add a brief analysis of the engineering domain and key constraints",
                category="structural",
            )
        )

    if not staffing_plan.get("architecture_notes"):
        violations.append(
            Violation(
                gate_id="master-missing-architecture",
                message="Staffing plan should include architecture_notes (key architectural decisions)",
                severity=ViolationSeverity.WARNING,
                suggestion="Add architectural guidance for the team",
                category="structural",
            )
        )

    # Build gate result
    all_passed = not any(v.severity == ViolationSeverity.ERROR for v in violations)
    structured_violations = [_serialize_violation(v) for v in violations]

    gate_summary = {
        "status": GateStatus.PASSED if all_passed else GateStatus.FAILED,
        "passed": all_passed,
        "gates_run": 4,  # 4 structural checks
        "gates_passed": 4 - len([v for v in violations if v.severity == ViolationSeverity.ERROR]),
        "violation_count": len(violations),
        "violations": structured_violations,
        "deep": False,  # Structural validation is fast
        "pro": False,
    }

    gate_history = list(state.get("gate_history", []))
    gate_history.append({"role": current_role, **gate_summary})

    events = state.get("events", [])
    events.append(
        {
            "type": "gate_results",
            "role": current_role,
            "passed": all_passed,
            "gates_run": 4,
            "violations": len(violations),
            "reason": "gates_passed" if all_passed else "gates_failed",
        }
    )

    update: dict[str, Any] = {
        "gate_results": gate_summary,
        "gate_history": gate_history,
        "events": events,
    }

    if not all_passed:
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
            for v in violations
        ]
        retry_count = state.get("retry_count", 0) + 1
        max_retries = state.get("max_retries", 5)

        fix_packet = FixPacket(
            items=fix_items,
            attempt=retry_count,
            max_attempts=max_retries,
        )

        update.update(
            _remediation_update(
                state,
                current_role=current_role,
                gate_summary=gate_summary,
                fix_packet=fix_packet,
                gate_source="master_structural_validation",
                affected_files=[],
                remediation_phase="diagnose",
                retry_count=retry_count,
                max_retries=max_retries,
            )
        )
    else:
        update["active_fix_packet"] = {}
        update["downstream_lock_reason"] = ""
        update["status"] = f"gate_passed_{current_role}"

    return update


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
    current_instance = resolve_current_instance_id(state)
    team_config = state["team_config"]
    gates_after = team_config.get("gates_after", [])

    # Resolve base role for instance-based agents (e.g., "backend-engineer-1" → "coder")
    agents_cfg = team_config.get("agents", {})
    agent_cfg = agents_cfg.get(current_instance) or agents_cfg.get(current_role) or {}
    base_role = resolve_base_role(state, current_instance)

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

    # Special case: Master Agent (classify role) gets structural validation
    # The Master Agent must produce a valid staffing plan with correct structure
    if current_role == "classify" or base_role == "master":
        return await _validate_master_agent_output(state, current_role)

    # Only run gates on code-producing roles
    # Gates may be configured by instance-id (preferred) or base role (legacy).
    should_gate = (
        current_instance in gates_after or current_role in gates_after or base_role in gates_after
    )
    if not should_gate:
        # Phase 7: Still run persona checks on non-gated roles.
        # Forbidden file writes by non-code roles ARE enforced as failures.
        agent_output = resolve_agent_output(state, current_instance, current_role)
        output_summary = agent_output.get("summary", "")
        files_changed = agent_output.get("files_changed", [])
        persona_violations = _check_persona_boundaries(
            current_instance,
            base_role,
            files_changed,
            output_summary,
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
            events.append(
                {
                    "type": "gate_results",
                    "role": current_instance,
                    "passed": False,
                    "gates_run": 1,
                    "violations": len(hard_violations),
                    "reason": "persona_violation",
                }
            )
            gate_history = list(state.get("gate_history", []))
            gate_history.append({"role": current_instance, **gate_summary})

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
                "gate_history": gate_history,
                **_remediation_update(
                    state,
                    current_role=current_instance,
                    gate_summary=gate_summary,
                    fix_packet=fix_packet,
                    gate_source="persona_violation",
                    affected_files=files_changed,
                remediation_phase="diagnose",
                retry_count=retry_count,
                max_retries=max_retries,
                    extra_events=[
                        {
                            "type": "gate_results",
                            "role": current_instance,
                            "passed": False,
                            "gates_run": 1,
                            "violations": len(hard_violations),
                            "reason": "persona_violation",
                        }
                    ],
                ),
            }

        # No hard violations — log soft ones as advisory
        events.append(
            {
                "type": "gate_results",
                "role": current_instance,
                "status": "skipped",
                "passed": True,
            }
        )
        if soft_violations:
            events.append(
                {
                    "type": "persona_check",
                    "role": current_instance,
                    "violations": len(soft_violations),
                    "details": [pv.message for pv in soft_violations[:5]],
                }
            )

        # Record the skip in gate_history for audit completeness
        gate_history = list(state.get("gate_history", []))
        gate_history.append(
            {
                "role": current_instance,
                "status": GateStatus.SKIPPED,
                "passed": True,
                "reason": "gates_skipped",
                "gates_run": 0,
                "gates_passed": 0,
                "violation_count": 0,
                "violations": [],
                "deep": False,
                "pro": False,
            }
        )
        return {
            "gate_results": {"status": "skipped", "passed": True},
            "gate_history": gate_history,
            "active_fix_packet": {},
            "downstream_lock_reason": "",
            "status": f"gates_skipped_{current_instance}",
            "events": events,
        }

    # Get files changed by the current agent
    agent_output = resolve_agent_output(state, current_instance, current_role)
    files_changed = agent_output.get("files_changed", [])

    # Code-producing agents MUST produce files. If they didn't, that's a failure.
    if base_role in CODE_PRODUCING_ROLES and not files_changed:
        agent_label = str(agent_cfg.get("name", "")).strip() or current_instance
        violation = Violation(
            gate_id="no-files-produced",
            message=f"Agent '{agent_label}' ({current_instance}) is expected to produce code but wrote 0 files",
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
        gate_history.append({"role": current_instance, **gate_summary})
        events = list(state.get("events", []))
        events.append(
            {
                "type": "gate_results",
                "role": current_instance,
                "passed": False,
                "gates_run": 1,
                "violations": 1,
                "reason": "no_files_produced",
            }
        )
        events.append(
            {
                "type": (
                    "gate_remediation_scheduled"
                    if retry_count < max_retries
                    else "gate_retries_exhausted"
                ),
                "role": current_instance,
                "reason": "no_files_produced",
                "retry_count": retry_count,
                "max_retries": max_retries,
            }
        )
        return {
            "gate_history": gate_history,
            **_remediation_update(
                state,
                current_role=current_instance,
                gate_summary=gate_summary,
                fix_packet=fix_packet,
                gate_source="no_files_produced",
                affected_files=[],
                remediation_phase="patch",
                retry_count=retry_count,
                max_retries=max_retries,
                extra_events=[
                    {
                        "type": "gate_results",
                        "role": current_instance,
                        "passed": False,
                        "gates_run": 1,
                        "violations": 1,
                        "reason": "no_files_produced",
                    },
                    {
                        "type": (
                            "gate_remediation_scheduled"
                            if retry_count < max_retries
                            else "gate_retries_exhausted"
                        ),
                        "role": current_instance,
                        "reason": "no_files_produced",
                        "retry_count": retry_count,
                        "max_retries": max_retries,
                    },
                ],
            ),
        }

    run_deep, run_pro = _resolve_deep_mode(state, current_role)
    gate_input = GateInput(
        project_root=state.get("project_root", "."),
        files_changed=files_changed,
        agent_role=base_role,
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
        current_instance,
        base_role,
        files_changed,
        output_summary,
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
    gate_history.append({"role": current_instance, **gate_summary})

    update: dict[str, Any] = {
        "gate_results": gate_summary,
        "gate_history": gate_history,
        "active_fix_packet": {},
        "downstream_lock_reason": "",
        "events": state.get("events", [])
        + [
            {
                "type": "gate_results",
                "role": current_instance,
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

        update.update(
            _remediation_update(
                state,
                current_role=current_instance,
                gate_summary=gate_summary,
                fix_packet=fix_packet,
                gate_source="rigour",
                affected_files=files_changed,
                remediation_phase="verify",
                retry_count=retry_count,
                max_retries=max_retries,
                extra_events=[
                    {
                        "type": (
                            "gate_remediation_scheduled"
                            if retry_count < max_retries
                            else "gate_retries_exhausted"
                        ),
                        "role": current_instance,
                        "reason": "gates_failed",
                        "retry_count": retry_count,
                        "max_retries": max_retries,
                    }
                ],
            )
        )
    else:
        update["status"] = f"gate_passed_{current_instance}"

    return update
