"""Master Agent — Agent Performance Evaluator.

Evaluates completed agent work and updates rolling performance
statistics. Used by the Master Agent to decide whether agents
need enrichment, re-prompting, or replacement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rigovo.domain.entities.agent import Agent, AgentStats
from rigovo.domain.entities.quality import GateResult, GateStatus

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Result of evaluating an agent's execution."""

    quality_score: float  # 0-100
    speed_score: float  # 0-100
    gate_pass_rate: float  # 0.0-1.0
    needs_enrichment: bool
    needs_attention: bool  # True if performance is degrading
    summary: str


class AgentEvaluator:
    """
    Evaluates agent execution quality and tracks performance trends.

    This is a deterministic evaluator — no LLM needed. It uses
    gate results, timing data, and retry counts to score agents.
    The Master Agent uses these scores to decide enrichment strategy.
    """

    # Thresholds
    POOR_QUALITY_THRESHOLD = 60.0
    DEGRADATION_THRESHOLD = 0.15  # 15% drop triggers attention
    RETRY_PENALTY_PER_ATTEMPT = 15.0
    SPEED_BASELINE_MS = 30_000  # 30s considered "normal"
    SPEED_SLOW_MS = 120_000  # 2min considered "slow"

    def evaluate(
        self,
        agent: Agent,
        gate_result: GateResult | None,
        duration_ms: int,
        retry_count: int,
        files_changed: int,
    ) -> EvaluationResult:
        """Evaluate a single agent execution."""
        # Quality score from gates
        quality_score = self._compute_quality_score(gate_result, retry_count)

        # Speed score (normalized)
        speed_score = self._compute_speed_score(duration_ms, files_changed)

        # Gate pass rate
        gate_passed = gate_result is not None and gate_result.status == GateStatus.PASSED
        gate_pass_rate = 1.0 if gate_passed else 0.0

        # Check for degradation
        needs_attention = False
        if agent.stats:
            prev_quality_proxy = agent.stats.first_pass_rate * 100
            if prev_quality_proxy > 0 and quality_score < prev_quality_proxy * (1 - self.DEGRADATION_THRESHOLD):
                needs_attention = True

        # Needs enrichment if quality is poor or retries happened
        needs_enrichment = (
            quality_score < self.POOR_QUALITY_THRESHOLD
            or retry_count > 0
            or needs_attention
        )

        summary = self._build_summary(
            quality_score, speed_score, gate_passed, retry_count, needs_attention
        )

        return EvaluationResult(
            quality_score=quality_score,
            speed_score=speed_score,
            gate_pass_rate=gate_pass_rate,
            needs_enrichment=needs_enrichment,
            needs_attention=needs_attention,
            summary=summary,
        )

    def update_agent_stats(
        self,
        agent: Agent,
        evaluation: EvaluationResult,
        duration_ms: int,
        tokens_used: int,
        cost_usd: float,
    ) -> AgentStats:
        """Update agent's rolling statistics with latest execution."""
        stats = agent.stats or AgentStats()

        passed_first_try = evaluation.gate_pass_rate >= 1.0
        stats.record_task(
            duration_ms=duration_ms,
            tokens=tokens_used,
            cost=cost_usd,
            passed_first_try=passed_first_try,
        )

        return stats

    def _compute_quality_score(
        self,
        gate_result: GateResult | None,
        retry_count: int,
    ) -> float:
        """Compute quality score from gate results and retries."""
        if gate_result is None:
            # No gates ran (e.g., non-code-producing role)
            return 85.0  # Reasonable default

        base_score = gate_result.score if gate_result.score is not None else (
            100.0 if gate_result.status == GateStatus.PASSED else 40.0
        )

        # Penalize retries
        retry_penalty = retry_count * self.RETRY_PENALTY_PER_ATTEMPT
        score = max(0.0, base_score - retry_penalty)

        return round(score, 1)

    def _compute_speed_score(self, duration_ms: int, files_changed: int) -> float:
        """Compute speed score normalized by work volume."""
        if duration_ms <= 0:
            return 100.0

        # Normalize: more files = more time allowed
        adjusted_baseline = self.SPEED_BASELINE_MS * max(1, files_changed)
        adjusted_slow = self.SPEED_SLOW_MS * max(1, files_changed)

        if duration_ms <= adjusted_baseline:
            return 100.0
        elif duration_ms >= adjusted_slow:
            return 30.0
        else:
            # Linear interpolation
            ratio = (duration_ms - adjusted_baseline) / (adjusted_slow - adjusted_baseline)
            return round(100.0 - (70.0 * ratio), 1)

    @staticmethod
    def _build_summary(
        quality: float,
        speed: float,
        gate_passed: bool,
        retries: int,
        needs_attention: bool,
    ) -> str:
        """Build human-readable evaluation summary."""
        parts = []

        if quality >= 90:
            parts.append("Excellent quality")
        elif quality >= 70:
            parts.append("Good quality")
        elif quality >= 50:
            parts.append("Fair quality")
        else:
            parts.append("Poor quality")

        parts.append(f"({quality:.0f}/100)")

        if not gate_passed:
            parts.append("— gates failed")
        if retries > 0:
            parts.append(f"— {retries} retry(ies)")
        if needs_attention:
            parts.append("⚠ performance degradation detected")

        return " ".join(parts)
