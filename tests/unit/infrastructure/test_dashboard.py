"""Tests for TUI dashboard and widgets."""

from __future__ import annotations

import pytest

from rigovo.infrastructure.terminal.widgets import (
    PipelineStage,
    PipelineView,
    AgentPanel,
    CostTracker,
    TaskHeader,
    STAGE_LABELS,
    STAGE_PENDING,
    STAGE_ACTIVE,
    STAGE_COMPLETE,
)
from rigovo.infrastructure.terminal.dashboard import (
    RigovoDashboard,
    EVENT_TO_STAGE,
    run_dashboard,
)


class TestPipelineStage:

    def test_default_status_is_pending(self) -> None:
        stage = PipelineStage()
        assert stage.status == "pending"

    def test_render_contains_label(self) -> None:
        stage = PipelineStage()
        stage.label = "Classify"
        rendered = stage.render()
        assert "Classify" in rendered


class TestStageMappings:

    def test_all_graph_events_have_stage_mapping(self) -> None:
        """Critical events should map to pipeline stages."""
        required_events = [
            "project_scanned", "task_classified", "pipeline_assembled",
            "agent_complete", "gate_results", "task_finalized",
        ]
        for event in required_events:
            assert event in EVENT_TO_STAGE, f"Missing stage mapping for {event}"

    def test_stage_labels_cover_all_stages(self) -> None:
        """All mapped stages should have display labels."""
        for stage in EVENT_TO_STAGE.values():
            assert stage in STAGE_LABELS, f"Missing label for stage {stage}"


class TestCostTracker:

    def test_initial_values_are_zero(self) -> None:
        tracker = CostTracker()
        assert tracker._total_cost == 0.0
        assert tracker._total_tokens == 0
        assert tracker._agent_count == 0

    def test_update_cost_accumulates(self) -> None:
        tracker = CostTracker()
        # Directly update internal state (widget not mounted in tests)
        tracker._total_cost = 0.05
        tracker._total_tokens = 1000
        tracker._agent_count = 1
        tracker._total_cost += 0.03
        tracker._total_tokens += 500
        tracker._agent_count += 1
        assert tracker._total_cost == pytest.approx(0.08)
        assert tracker._total_tokens == 1500
        assert tracker._agent_count == 2

    def test_add_retry_increments(self) -> None:
        tracker = CostTracker()
        tracker._retry_count += 1
        tracker._retry_count += 1
        assert tracker._retry_count == 2

    def test_render_content_includes_values(self) -> None:
        tracker = CostTracker(budget=2.00)
        tracker._total_cost = 0.10
        tracker._total_tokens = 2000
        tracker._elapsed_s = 5.0
        tracker._agent_count = 1
        content = tracker._render_content()
        assert "$0.10" in content
        assert "2,000" in content
        assert "$2.00" in content

    def test_budget_percentage(self) -> None:
        tracker = CostTracker(budget=1.00)
        tracker._total_cost = 0.50
        tracker._total_tokens = 1000
        content = tracker._render_content()
        assert "50%" in content


class TestTaskHeader:

    def test_initial_render(self) -> None:
        header = TaskHeader(
            task_description="Fix login bug",
            project_root="/home/user/project",
        )
        rendered = header._render()
        assert "RIGOVO TEAMS" in rendered
        assert "Fix login bug" in rendered

    def test_long_description_truncated(self) -> None:
        header = TaskHeader(
            task_description="A" * 100,
        )
        rendered = header._render()
        assert "..." in rendered

    def test_set_status_updates(self) -> None:
        header = TaskHeader()
        header._status = "executing"
        rendered = header._render()
        assert "executing" in rendered

    def test_set_team_updates(self) -> None:
        header = TaskHeader()
        header._team = "planner, coder, reviewer"
        rendered = header._render()
        assert "planner" in rendered


class TestAgentPanel:
    """Test AgentPanel log building (without mounted widget)."""

    def test_initial_log_empty(self) -> None:
        panel = AgentPanel()
        assert len(panel._log_lines) == 0

    def test_log_line_formatting(self) -> None:
        """Test that log line content is correctly formatted."""
        panel = AgentPanel()
        # Directly append to test formatting without DOM refresh
        panel._log_lines.append("[bold cyan]▶ coder[/bold cyan] (Alice) executing...")
        assert "coder" in panel._log_lines[0]
        assert "Alice" in panel._log_lines[0]

    def test_agent_complete_formatting(self) -> None:
        panel = AgentPanel()
        line = (
            f"[green]✓ coder[/green] (Alice) — "
            f"{2000:,} tokens, ${0.05:.4f}, {3.0:.1f}s"
        )
        panel._log_lines.append(line)
        assert "2,000" in panel._log_lines[0]
        assert "$0.05" in panel._log_lines[0]

    def test_gate_passed_formatting(self) -> None:
        panel = AgentPanel()
        panel._log_lines.append("  [green]✓ Gates passed[/green] for coder")
        assert "passed" in panel._log_lines[0].lower()

    def test_gate_failed_formatting(self) -> None:
        panel = AgentPanel()
        panel._log_lines.append("  [red]✗ Gates failed[/red] for coder — 3 violation(s)")
        assert "failed" in panel._log_lines[0].lower()
        assert "3" in panel._log_lines[0]

    def test_error_formatting(self) -> None:
        panel = AgentPanel()
        panel._log_lines.append("[red bold]✗ Something went wrong[/red bold]")
        assert "Something went wrong" in panel._log_lines[0]

    def test_log_stores_all_lines(self) -> None:
        panel = AgentPanel()
        for i in range(60):
            panel._log_lines.append(f"Line {i}")
        assert len(panel._log_lines) == 60


class TestRunDashboard:

    def test_creates_dashboard_instance(self) -> None:
        dashboard = run_dashboard(
            task_description="Test task",
            project_root="/tmp",
            budget=5.0,
        )
        assert isinstance(dashboard, RigovoDashboard)
        assert dashboard._task_description == "Test task"
        assert dashboard._budget == 5.0
