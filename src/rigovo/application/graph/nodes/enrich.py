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

from rigovo.application.context.rigour_supervisor import RigourSupervisor, FixPacket
from rigovo.application.graph.state import TaskState
from rigovo.application.master.enricher import ContextEnricher, EnrichmentUpdate
from rigovo.domain.entities.quality import GateResult, GateStatus

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

    # Collect all gate results from the pipeline
    gate_results_raw = state.get("gate_results", {})
    enrichment_updates: list[dict[str, Any]] = []

    # 1. Extract patterns from gate violations
    patterns_from_gates = _extract_gate_patterns(gate_results_raw)

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


def _extract_gate_patterns(gate_results_raw: dict[str, Any]) -> list[str]:
    """Extract known pitfalls from gate results."""
    patterns: list[str] = []

    violations = gate_results_raw.get("violations", [])
    if not violations:
        return patterns

    # Count violations by rule
    rule_counts: dict[str, int] = {}
    for v in violations:
        rule = v.get("rule", "unknown") if isinstance(v, dict) else "unknown"
        rule_counts[rule] = rule_counts.get(rule, 0) + 1

    # Convert frequent violations to pitfalls
    for rule, count in rule_counts.items():
        mapped = GATE_TO_PITFALL_MAP.get(rule)
        if mapped:
            patterns.append(mapped)
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
