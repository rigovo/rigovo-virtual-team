"""Tests for graph edge routing functions."""

from rigovo.application.graph.edges import (
    check_approval,
    check_gates_and_route,
    check_pipeline_complete,
    check_parallel_postprocess,
    advance_to_next_agent,
    prepare_debate_round,
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

    def test_failed_triggers_replan_by_retry_policy(self):
        state = {
            "gate_results": {"passed": False, "violation_count": 1},
            "retry_count": 3,
            "max_retries": 5,
            "replan_count": 0,
            "replan_policy": {
                "enabled": True,
                "max_replans_per_task": 2,
                "trigger_retry_count": 3,
                "trigger_gate_violation_count": 10,
                "trigger_contract_failures": True,
            },
        }
        assert check_gates_and_route(state) == "trigger_replan"

    def test_failed_triggers_replan_by_contract_failure(self):
        state = {
            "gate_results": {"passed": False, "reason": "contract_failed"},
            "retry_count": 0,
            "max_retries": 5,
            "contract_stage": "output",
            "replan_count": 0,
            "replan_policy": {
                "enabled": True,
                "max_replans_per_task": 1,
                "trigger_retry_count": 99,
                "trigger_gate_violation_count": 99,
                "trigger_contract_failures": True,
            },
        }
        assert check_gates_and_route(state) == "trigger_replan"

    def test_failed_no_replan_when_budget_exhausted(self):
        state = {
            "gate_results": {"passed": False, "violation_count": 999},
            "retry_count": 5,
            "max_retries": 5,
            "replan_count": 1,
            "replan_policy": {
                "enabled": True,
                "max_replans_per_task": 1,
                "trigger_retry_count": 1,
                "trigger_gate_violation_count": 1,
                "trigger_contract_failures": True,
            },
        }
        assert check_gates_and_route(state) == "fail_max_retries"

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

    def test_ready_roles_parallel(self):
        state = {
            "ready_roles": ["reviewer", "qa"],
        }
        assert check_pipeline_complete(state) == "parallel_fan_out"

    def test_pipeline_dependency_failure(self):
        state = {"status": "pipeline_failed_dependency"}
        assert check_pipeline_complete(state) == "pipeline_failed"


class TestCheckParallelPostprocess:
    def test_debate_needed_when_pipeline_done_and_reviewer_requests_changes(self):
        state = {
            "ready_roles": [],
            "agent_outputs": {"reviewer": {"summary": "CHANGES_REQUESTED: fix auth checks"}},
            "debate_round": 0,
            "max_debate_rounds": 2,
        }
        assert check_parallel_postprocess(state) == "debate_needed"

    def test_pipeline_route_preserved_when_more_agents_remain(self):
        state = {"ready_roles": ["coder"]}
        assert check_parallel_postprocess(state) == "more_agents"


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

    def test_dag_advance_uses_dependencies(self):
        state = {
            "team_config": {
                "pipeline_order": ["planner", "coder", "reviewer"],
                "execution_dag": {
                    "planner": [],
                    "coder": ["planner"],
                    "reviewer": ["coder"],
                },
            },
            "current_agent_role": "planner",
            "completed_roles": [],
            "blocked_roles": [],
            "events": [],
        }
        result = advance_to_next_agent(state)
        assert result["completed_roles"] == ["planner"]
        assert result["ready_roles"] == ["coder"]
        assert result["current_agent_role"] == "coder"

    def test_dag_advance_detects_dependency_deadlock(self):
        state = {
            "team_config": {
                "pipeline_order": ["reviewer"],
                "execution_dag": {"reviewer": ["coder"]},
            },
            "current_agent_role": "",
            "completed_roles": [],
            "blocked_roles": [],
            "events": [],
        }
        result = advance_to_next_agent(state)
        assert result["status"] == "pipeline_failed_dependency"
        assert result["ready_roles"] == []

    def test_dag_advance_forces_reviewer_rerun_in_debate_mode(self):
        state = {
            "team_config": {
                "pipeline_order": ["planner", "coder", "reviewer"],
                "execution_dag": {
                    "planner": [],
                    "coder": ["planner"],
                    "reviewer": ["coder"],
                },
            },
            "current_agent_role": "coder",
            "debate_target_role": "reviewer",
            "completed_roles": ["planner"],
            "blocked_roles": [],
            "events": [],
        }
        result = advance_to_next_agent(state)
        assert result["current_agent_role"] == "reviewer"
        assert result["ready_roles"] == ["reviewer"]
        assert any(e.get("type") == "debate_reviewer_rerun" for e in result["events"])


class TestPrepareDebateRound:
    def test_prepare_debate_round_resets_reviewer_for_regeneration(self):
        state = {
            "team_config": {"pipeline_order": ["planner", "coder", "reviewer"]},
            "agent_outputs": {
                "coder": {"summary": "updated code"},
                "reviewer": {"summary": "CHANGES_REQUESTED: tighten validation"},
            },
            "completed_roles": ["planner", "coder", "reviewer"],
            "ready_roles": [],
            "debate_round": 0,
            "events": [],
        }
        result = prepare_debate_round(state)
        assert result["current_agent_role"] == "coder"
        assert result["debate_target_role"] == "reviewer"
        assert "reviewer" not in result["completed_roles"]
        assert "reviewer" not in result["agent_outputs"]
