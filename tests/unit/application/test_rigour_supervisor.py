"""Tests for RigourSupervisor — per-role quality gate enforcement."""

from __future__ import annotations

import pytest

from rigovo.application.context.rigour_supervisor import (
    RigourSupervisor,
    FixPacket,
    FixItem,
    MAX_RETRIES_BY_ROLE,
)
from rigovo.domain.entities.quality import (
    GateResult,
    GateStatus,
    Violation,
    ViolationSeverity,
)


@pytest.fixture
def supervisor() -> RigourSupervisor:
    return RigourSupervisor()


def _make_gate_result(
    status: GateStatus,
    violations: list[tuple[str, str, str]] | None = None,
) -> GateResult:
    """Helper: (severity, gate_id, message) tuples → GateResult."""
    vs = []
    if violations:
        for sev, gate_id, msg in violations:
            vs.append(Violation(
                severity=ViolationSeverity(sev),
                gate_id=gate_id,
                message=msg,
                category=gate_id,
            ))
    return GateResult(status=status, violations=vs)


class TestFixPacketCreation:

    def test_passed_gates_empty_packet(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.PASSED)]
        packet = supervisor.evaluate(results, role="coder")
        assert packet.count == 0

    def test_failed_gates_produce_fix_items(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.FAILED, [
            ("error", "file_size", "File exceeds 400 lines"),
            ("warning", "magic_number", "Magic number 42 found"),
        ])]
        packet = supervisor.evaluate(results, role="coder")
        assert packet.count == 2

    def test_role_specific_max_retries(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.FAILED, [
            ("error", "test", "Missing assertion"),
        ])]
        qa_packet = supervisor.evaluate(results, role="qa")
        coder_packet = supervisor.evaluate(results, role="coder")
        assert qa_packet.max_attempts == MAX_RETRIES_BY_ROLE["qa"]
        assert coder_packet.max_attempts == MAX_RETRIES_BY_ROLE["coder"]


class TestFixPacketMessages:

    def test_message_includes_violations(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.FAILED, [
            ("error", "file_size", "app.py exceeds 400 lines"),
        ])]
        packet = supervisor.evaluate(results, role="coder")
        msg = packet.to_agent_message()
        assert "FIX REQUIRED" in msg
        assert "file_size" in msg

    def test_message_includes_attempt_count(self, supervisor: RigourSupervisor) -> None:
        results = [_make_gate_result(GateStatus.FAILED, [
            ("error", "test", "No assertions"),
        ])]
        packet = supervisor.evaluate(results, role="coder", attempt=2)
        msg = packet.to_agent_message()
        assert "Attempt 2/" in msg


class TestRetryDecision:

    def test_no_violations_no_retry(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(role="coder")
        assert not supervisor.should_retry(packet)

    def test_blocking_violations_trigger_retry(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(
            items=[FixItem(gate_id="rigour", file_path="x.py",
                           rule="file_size", message="Too long", severity="high")],
            role="coder", attempt=1, max_attempts=3,
        )
        assert supervisor.should_retry(packet)

    def test_max_retries_exhausted_no_retry(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(
            items=[FixItem(gate_id="rigour", file_path="x.py",
                           rule="file_size", message="Too long", severity="high")],
            role="coder", attempt=3, max_attempts=3,
        )
        assert not supervisor.should_retry(packet)


class TestPatternExtraction:

    def test_repeated_violations_become_patterns(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(items=[
            FixItem(gate_id="r", file_path="a.py", rule="magic_number",
                    message="42 found", severity="warning"),
            FixItem(gate_id="r", file_path="b.py", rule="magic_number",
                    message="99 found", severity="warning"),
        ], role="coder")
        patterns = supervisor.extract_patterns(packet)
        assert len(patterns) >= 1
        assert "magic_number" in patterns[0]

    def test_single_violations_not_patterns(self, supervisor: RigourSupervisor) -> None:
        packet = FixPacket(items=[
            FixItem(gate_id="r", file_path="a.py", rule="file_size",
                    message="Too long", severity="error"),
        ], role="coder")
        patterns = supervisor.extract_patterns(packet)
        assert len(patterns) == 0
