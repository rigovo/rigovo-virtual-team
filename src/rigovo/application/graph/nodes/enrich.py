"""Enrich node — closes the learning loop after task execution.

This node runs AFTER the pipeline completes. It:
1. Analyzes what happened (successes, failures, gate results)
2. Extracts patterns from Rigour violations
3. Updates agent enrichment contexts for future tasks
4. Converts gate feedback into permanent learning

The key insight: quality gate failures are not just errors to fix —
they are TRAINING DATA for the agent. If the coder keeps making
the same mistake, the enrichment system ensures they never make
it again.

This is the difference between a tool that generates code and an
agent that LEARNS from its mistakes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID, NAMESPACE_DNS, uuid5

from rigovo.application.context.rigour_supervisor import RigourSupervisor, FixPacket
from rigovo.application.graph.state import TaskState
from rigovo.application.master.enricher import ContextEnricher, EnrichmentUpdate
from rigovo.application.master.evaluator import AgentEvaluator
from rigovo.domain.entities.agent import Agent
from rigovo.domain.entities.quality import GateResult, GateStatus, Violation, ViolationSeverity

logger = logging.getLogger(__name__)

# Minimum violations before we generate enrichment (avoid noise)
MIN_VIOLATIONS_FOR_ENRICHMENT = 1

# Categories of enrichment extracted from gate failures
GATE_TO_PITFALL_MAP: dict[str, str] = {
    "file_size": "Keep files under 400 lines. Split large files into focused modules.",
    "magic_number": "Extract magic numbers to named constants with clear names.",
    "async_safety": "All async functions must await something. Use await asyncio.sleep(0) for abstract methods.",
    "import_check": "Only import packages that exist in the project's dependencies.",
    "naming": "Follow PEP 8: snake_case for functions/variables, PascalCase for classes.",
    "error_handling": "Never use bare except. Always specify the exception type.",
    "type_hints": "Add type hints to all function signatures.",
    "forbidden_content": "No placeholder comments in production code. Resolve or create a tracked issue.",
}


async def enrich_node(
    state: TaskState,
    enricher: ContextEnricher | None = None,
    evaluator: AgentEvaluator | None = None,
    supervisor: RigourSupervisor | None = None,
) -> dict[str, Any]:
    """Extract learnings from the completed pipeline and update enrichment.

    This node runs after all agents have completed. It analyzes
    gate results across the entire pipeline and extracts patterns
    that become permanent enrichment for future tasks.
    """
    await asyncio.sleep(0)  # Yield to event loop
    supervisor = supervisor or RigourSupervisor()
    events = list(state.get("events", []))

    # Collect gate results across the pipeline (history preferred).
    gate_results_raw = state.get("gate_results", {})
    gate_history = state.get("gate_history", [])
    gate_payloads: list[dict[str, Any]] = []
    if isinstance(gate_history, list):
        gate_payloads = [g for g in gate_history if isinstance(g, dict)]
    if not gate_payloads and isinstance(gate_results_raw, dict):
        gate_payloads = [gate_results_raw]
    enrichment_updates: list[dict[str, Any]] = []

    # 1. Extract patterns from gate violations
    patterns_from_gates = _extract_gate_patterns(gate_payloads)

    # 2. Extract patterns from retry loops
    retry_count = state.get("retry_count", 0)
    retry_patterns: list[str] = []
    if retry_count > 0:
        retry_patterns.append(
            f"Code required {retry_count} retry(s) to pass quality gates. "
            "Write cleaner code on the first attempt."
        )

    # 3. Extract patterns from fix packets
    fix_packets = state.get("fix_packets", [])
    fix_patterns: list[str] = []
    for packet_text in fix_packets:
        if isinstance(packet_text, str) and "violation" in packet_text.lower():
            fix_patterns.append(
                f"Previous fix required: {packet_text[:200]}"
            )

    # 4. Combine all patterns into enrichment update
    all_pitfalls = patterns_from_gates + retry_patterns
    all_patterns = fix_patterns

    if all_pitfalls or all_patterns:
        enrichment_updates.append({
            "known_pitfalls": all_pitfalls[:5],
            "domain_knowledge": all_patterns[:5],
            "source": "rigour_gates",
        })

    # 5. Extract success patterns (what worked well)
    success_patterns = _extract_success_patterns(state)
    if success_patterns:
        enrichment_updates.append({
            "domain_knowledge": success_patterns[:3],
            "source": "pipeline_success",
        })

    # 6. Master-service enrichment/evaluation (if wired)
    if enricher is not None or evaluator is not None:
        master_updates, eval_events = await _run_master_learning_loop(
            state=state,
            enricher=enricher,
            evaluator=evaluator,
        )
        enrichment_updates.extend(master_updates)
        events.extend(eval_events)

    events.append({
        "type": "enrichment_extracted",
        "pitfall_count": len(all_pitfalls),
        "pattern_count": len(all_patterns) + len(success_patterns),
        "retry_count": retry_count,
    })

    return {
        "enrichment_updates": enrichment_updates,
        "status": "enrichment_complete",
        "events": events,
    }


async def _run_master_learning_loop(
    state: TaskState,
    enricher: ContextEnricher | None,
    evaluator: AgentEvaluator | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    updates: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    team_agents = state.get("team_config", {}).get("agents", {})
    gate_history = state.get("gate_history", [])
    gate_by_role = {}
    if isinstance(gate_history, list):
        for entry in gate_history:
            if isinstance(entry, dict):
                role = str(entry.get("role", ""))
                if role:
                    gate_by_role[role] = entry

    for role, output in (state.get("agent_outputs", {}) or {}).items():
        if not isinstance(output, dict):
            continue

        agent_cfg = team_agents.get(role, {}) if isinstance(team_agents, dict) else {}
        agent = _build_agent_for_role(state, role, agent_cfg)
        gate_result = _gate_result_from_payload(gate_by_role.get(role, {}))

        if evaluator is not None:
            evaluation = evaluator.evaluate(
                agent=agent,
                gate_result=gate_result,
                duration_ms=int(output.get("duration_ms", 0) or 0),
                retry_count=int(state.get("retry_count", 0) or 0),
                files_changed=len(output.get("files_changed", []) or []),
            )
            events.append(
                {
                    "type": "agent_evaluated",
                    "role": role,
                    "quality_score": evaluation.quality_score,
                    "speed_score": evaluation.speed_score,
                    "needs_enrichment": evaluation.needs_enrichment,
                }
            )

        if enricher is not None:
            try:
                result = await enricher.analyze_execution(
                    agent=agent,
                    execution_summary=str(output.get("summary", "")),
                    gate_result=gate_result,
                    files_changed=list(output.get("files_changed", []) or []),
                )
                updates.append(
                    {
                        "known_pitfalls": result.known_pitfalls,
                        "domain_knowledge": result.domain_knowledge,
                        "pre_check_rules": result.pre_check_rules,
                        "workspace_conventions": result.workspace_conventions,
                        "source": "master_enricher",
                        "role": role,
                        "reasoning": result.reasoning,
                    }
                )
            except Exception as exc:
                events.append(
                    {
                        "type": "enrichment_service_failed",
                        "role": role,
                        "error": str(exc),
                    }
                )

    return updates, events


def _build_agent_for_role(
    state: TaskState,
    role: str,
    agent_cfg: dict[str, Any],
) -> Agent:
    workspace_id = _parse_uuid(state.get("workspace_id")) or UUID(int=0)
    team_id = uuid5(NAMESPACE_DNS, str(state.get("team_config", {}).get("team_id", "default-team")))
    return Agent(
        id=_parse_uuid(agent_cfg.get("id")) or uuid5(NAMESPACE_DNS, f"{team_id}:{role}"),
        workspace_id=workspace_id,
        team_id=team_id,
        role=role,
        name=str(agent_cfg.get("name", role.title())),
        system_prompt=str(agent_cfg.get("system_prompt", "")),
        llm_model=str(agent_cfg.get("llm_model", "claude-sonnet-4-6")),
        tools=list(agent_cfg.get("tools", []) or []),
    )


def _gate_result_from_payload(payload: dict[str, Any]) -> GateResult | None:
    if not isinstance(payload, dict) or not payload:
        return None
    violations_raw = payload.get("violations", [])
    violations: list[Violation] = []
    if isinstance(violations_raw, list):
        for item in violations_raw:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity", "error")).lower()
            if sev not in {"error", "warning", "info"}:
                sev = "error"
            violations.append(
                Violation(
                    gate_id=str(item.get("gate_id") or item.get("rule") or "unknown"),
                    message=str(item.get("message", "")),
                    severity=ViolationSeverity(sev),
                    file_path=str(item.get("file_path", "")) or None,
                    line=item.get("line"),
                    suggestion=str(item.get("suggestion", "")),
                )
            )
    status = GateStatus.PASSED if bool(payload.get("passed", False)) else GateStatus.FAILED
    return GateResult(
        status=status,
        violations=violations,
        gates_run=int(payload.get("gates_run", 0) or 0),
        gates_passed=int(payload.get("gates_passed", 0) or 0),
    )


def _parse_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _extract_gate_patterns(gate_payloads: list[dict[str, Any]]) -> list[str]:
    """Extract known pitfalls from gate results."""
    patterns: list[str] = []

    # Count violations by rule
    rule_counts: dict[str, int] = {}
    for payload in gate_payloads:
        violations = payload.get("violations", [])
        if isinstance(violations, list):
            for v in violations:
                rule = v.get("rule", "unknown") if isinstance(v, dict) else "unknown"
                rule_counts[rule] = rule_counts.get(rule, 0) + 1
            continue
        # Fallback when only counts are available (legacy states).
        if int(payload.get("violation_count", 0) or 0) > 0:
            rule_counts["unknown"] = rule_counts.get("unknown", 0) + int(payload.get("violation_count", 0) or 0)

    if not rule_counts:
        return patterns

    # Convert frequent violations to pitfalls
    for rule, count in rule_counts.items():
        mapped = GATE_TO_PITFALL_MAP.get(rule)
        if mapped:
            patterns.append(mapped)
        elif rule == "contract_failed":
            patterns.append("Respect declared input/output contracts strictly; fail fast on mismatch.")
        elif count >= 2:
            patterns.append(
                f"Repeated violation of '{rule}' ({count}x). Fix this pattern."
            )

    return patterns


def _extract_success_patterns(state: TaskState) -> list[str]:
    """Extract patterns from successful executions."""
    patterns: list[str] = []

    agent_outputs = state.get("agent_outputs", {})
    gate_results = state.get("gate_results", {})

    # If all gates passed on first try, note what worked
    retry_count = state.get("retry_count", 0)
    if retry_count == 0 and gate_results.get("passed", False):
        for role, output in agent_outputs.items():
            files = output.get("files_changed", [])
            if files:
                patterns.append(
                    f"{role.title()} passed all gates on first attempt "
                    f"({len(files)} files changed). Maintain this quality level."
                )

    return patterns
