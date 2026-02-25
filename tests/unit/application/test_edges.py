"""Tests for graph edge routing functions."""

from rigovo.application.graph.edges import (
    check_approval,
    check_gates_and_route,
    check_pipeline_complete,
    advance_to_next_agent,
)


class TestCheckApproval:
    def test_approved(self):
        assert check_approval({"approval_status": "approved"}) == "approved"

    def test_rejected(self):
        assert check_approval({"approval_status": "rejected"}) == "rejected"

    def test_pending_defaults_approved(self):
        assert check_approval({"approval_status": "pending"}) == "approved"


class TestCheckGatesAndRoute:
    def test_passed(self):
        state = {"gate_results": {"passed": True}, "retry_count": 0, "max_retries": 3}
        assert check_gates_and_route(state) == "pass_next_agent"

    def test_skipped(self):
        state = {"gate_results": {"status": "skipped"}, "retry_count": 0, "max_retries": 3}
        assert check_gates_and_route(state) == "pass_next_agent"

    def test_failed_with_retries(self):
        state = {"gate_results": {"passed": False}, "retry_count": 1, "max_retries": 3}
        assert check_gates_and_route(state) == "fail_fix_loop"

    def test_failed_max_retries(self):
        state = {"gate_results": {"passed": False}, "retry_count": 3, "max_retries": 3}
        assert check_gates_and_route(state) == "fail_max_retries"


class TestCheckPipelineComplete:
    def test_more_agents(self):
        state = {
            "team_config": {"pipeline_order": ["planner", "coder", "reviewer"]},
            "current_agent_index": 0,
        }
        assert check_pipeline_complete(state) == "more_agents"

    def test_last_agent(self):
        state = {
            "team_config": {"pipeline_order": ["planner", "coder", "reviewer"]},
            "current_agent_index": 2,
        }
        assert check_pipeline_complete(state) == "pipeline_done"


class TestAdvanceToNextAgent:
    def test_advances_index(self):
        state = {
            "team_config": {"pipeline_order": ["planner", "coder", "reviewer"]},
            "current_agent_index": 0,
        }
        result = advance_to_next_agent(state)
        assert result["current_agent_index"] == 1
        assert result["current_agent_role"] == "coder"
        assert result["fix_packets"] == []
        assert result["retry_count"] == 0
