"""Tests for graph edge routing functions."""

from rigovo.application.graph.edges import (
    check_approval,
    check_gates_and_route,
    check_pipeline_complete,
    check_parallel_postprocess,
    advance_to_next_agent,
    check_debate_needed,
    prepare_debate_round,
    _find_all_feedback_sources,
    _find_feedback_source,
    _DEFAULT_MAX_ROUNDS_BY_ROLE,
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

    def test_mid_retry_does_NOT_trigger_replan(self):
        """Replan must never interrupt an agent's retry cycle.

        Even when retry_count exceeds the old trigger_retry_count,
        the agent keeps retrying until max_retries is exhausted.
        """
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
        # Agent still has retries 3 and 4 → fix_loop, NOT replan
        assert check_gates_and_route(state) == "fail_fix_loop"

    def test_replan_fires_after_retries_exhausted(self):
        """Replan is an escalation AFTER all retries are exhausted."""
        state = {
            "gate_results": {"passed": False, "violation_count": 1},
            "retry_count": 5,
            "max_retries": 5,
            "replan_count": 0,
            "replan_policy": {
                "enabled": True,
                "max_replans_per_task": 2,
                "trigger_retry_count": 5,
                "trigger_gate_violation_count": 10,
                "trigger_contract_failures": True,
            },
        }
        assert check_gates_and_route(state) == "trigger_replan"

    def test_contract_failure_still_gets_retries_first(self):
        """Even contract failures get retries before replan escalation."""
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
        # Retries still available → fix_loop first
        assert check_gates_and_route(state) == "fail_fix_loop"

    def test_contract_failure_replan_after_retries_exhausted(self):
        """Contract failure escalates to replan when retries are exhausted."""
        state = {
            "gate_results": {"passed": False, "reason": "contract_failed"},
            "retry_count": 5,
            "max_retries": 5,
            "contract_stage": "output",
            "replan_count": 0,
            "replan_policy": {
                "enabled": True,
                "max_replans_per_task": 1,
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


# ══════════════════════════════════════════════════════════════════════════
# Phase 5: Generic debate protocol + multi-source feedback tests
# ══════════════════════════════════════════════════════════════════════════


class TestFindAllFeedbackSources:
    """Test _find_all_feedback_sources discovers multiple feedback sources."""

    def test_single_reviewer_changes_requested(self):
        state = {
            "team_config": {"agents": {"reviewer-1": {"role": "reviewer"}}},
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: fix auth checks"},
            },
        }
        sources = _find_all_feedback_sources(state)
        assert len(sources) == 1
        assert sources[0] == ("reviewer-1", "reviewer", "CHANGES_REQUESTED: fix auth checks")

    def test_multiple_sources_reviewer_and_qa(self):
        state = {
            "team_config": {
                "agents": {
                    "reviewer-1": {"role": "reviewer"},
                    "qa-unit-1": {"role": "qa"},
                    "coder-1": {"role": "coder"},
                },
            },
            "agent_outputs": {
                "coder-1": {"summary": "Implementation complete"},
                "reviewer-1": {"summary": "CHANGES_REQUESTED: improve error handling"},
                "qa-unit-1": {"summary": "ISSUES_FOUND: 3 tests failing"},
            },
        }
        sources = _find_all_feedback_sources(state)
        assert len(sources) == 2
        roles = {s[1] for s in sources}
        assert roles == {"reviewer", "qa"}

    def test_security_as_feedback_source(self):
        """Phase 5: security can also trigger debate."""
        state = {
            "team_config": {
                "agents": {
                    "security-1": {"role": "security"},
                    "reviewer-1": {"role": "reviewer"},
                },
            },
            "agent_outputs": {
                "security-1": {"summary": "BLOCKED: SQL injection vulnerability in user input"},
                "reviewer-1": {"summary": "LGTM: code is clean"},
            },
        }
        sources = _find_all_feedback_sources(state)
        assert len(sources) == 1
        assert sources[0][1] == "security"

    def test_triple_source_reviewer_qa_security(self):
        """All three feedback sources raise issues simultaneously."""
        state = {
            "team_config": {
                "agents": {
                    "reviewer-1": {"role": "reviewer"},
                    "qa-1": {"role": "qa"},
                    "security-1": {"role": "security"},
                },
            },
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: refactor auth module"},
                "qa-1": {"summary": "tests failed: integration suite"},
                "security-1": {"summary": "FAILED: XSS vulnerability detected"},
            },
        }
        sources = _find_all_feedback_sources(state)
        assert len(sources) == 3
        roles = {s[1] for s in sources}
        assert roles == {"reviewer", "qa", "security"}

    def test_no_feedback_when_all_pass(self):
        state = {
            "team_config": {
                "agents": {
                    "reviewer-1": {"role": "reviewer"},
                    "qa-1": {"role": "qa"},
                },
            },
            "agent_outputs": {
                "reviewer-1": {"summary": "APPROVED: looks good"},
                "qa-1": {"summary": "PASS: all tests green"},
            },
        }
        sources = _find_all_feedback_sources(state)
        assert len(sources) == 0

    def test_backward_compat_bare_role_keys(self):
        """When agents config is missing, fall back to key=role."""
        state = {
            "team_config": {"agents": {}},
            "agent_outputs": {
                "reviewer": {"summary": "CHANGES_REQUESTED: fix it"},
            },
        }
        sources = _find_all_feedback_sources(state)
        assert len(sources) == 1
        assert sources[0][1] == "reviewer"

    def test_coder_output_not_treated_as_feedback(self):
        """Coder is NOT in _FEEDBACK_SOURCE_ROLES — even with marker text."""
        state = {
            "team_config": {
                "agents": {"coder-1": {"role": "coder"}},
            },
            "agent_outputs": {
                "coder-1": {"summary": "CHANGES_REQUESTED: I need to redo this"},
            },
        }
        sources = _find_all_feedback_sources(state)
        assert len(sources) == 0


class TestCheckDebateNeeded:
    """Phase 5: per-source-role round limits and multi-source debate detection."""

    def test_debate_needed_first_round(self):
        state = {
            "team_config": {"agents": {"reviewer-1": {"role": "reviewer"}}},
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: fix validation"},
            },
            "debate_round": 0,
            "max_debate_rounds": 3,
            "feedback_loops": [],
        }
        assert check_debate_needed(state) == "debate_needed"

    def test_debate_done_when_global_cap_reached(self):
        """Global debate_round cap stops all feedback, even if per-source allows more."""
        state = {
            "team_config": {"agents": {"reviewer-1": {"role": "reviewer"}}},
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: still not right"},
            },
            "debate_round": 3,
            "max_debate_rounds": 3,
            "feedback_loops": [],
        }
        assert check_debate_needed(state) == "debate_done"

    def test_security_gets_one_round_only(self):
        """Security has max 1 round. After 1 round of feedback, debate_done."""
        state = {
            "team_config": {"agents": {"security-1": {"role": "security"}}},
            "agent_outputs": {
                "security-1": {"summary": "BLOCKED: vulnerability found"},
            },
            "debate_round": 1,
            "max_debate_rounds": 5,
            "feedback_loops": [
                {"round": 1, "source_instance": "security-1", "source_role": "security"},
            ],
        }
        assert check_debate_needed(state) == "debate_done"

    def test_reviewer_gets_two_rounds(self):
        """Reviewer has max 2 rounds. After 1 round, debate still needed."""
        state = {
            "team_config": {"agents": {"reviewer-1": {"role": "reviewer"}}},
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: still needs work"},
            },
            "debate_round": 1,
            "max_debate_rounds": 5,
            "feedback_loops": [
                {"round": 1, "source_instance": "reviewer-1", "source_role": "reviewer"},
            ],
        }
        assert check_debate_needed(state) == "debate_needed"

    def test_reviewer_exhausted_after_two_rounds(self):
        """After 2 feedback rounds from reviewer, debate_done even if markers remain."""
        state = {
            "team_config": {"agents": {"reviewer-1": {"role": "reviewer"}}},
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: still broken"},
            },
            "debate_round": 2,
            "max_debate_rounds": 5,
            "feedback_loops": [
                {"round": 1, "source_instance": "reviewer-1", "source_role": "reviewer"},
                {"round": 2, "source_instance": "reviewer-1", "source_role": "reviewer"},
            ],
        }
        assert check_debate_needed(state) == "debate_done"

    def test_mixed_sources_security_done_reviewer_still_active(self):
        """Security is exhausted (1 round) but reviewer still has rounds left."""
        state = {
            "team_config": {
                "agents": {
                    "reviewer-1": {"role": "reviewer"},
                    "security-1": {"role": "security"},
                },
            },
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: fix edge cases"},
                "security-1": {"summary": "BLOCKED: new finding"},
            },
            "debate_round": 1,
            "max_debate_rounds": 5,
            "feedback_loops": [
                {"round": 1, "source_instance": "security-1", "source_role": "security"},
            ],
        }
        # reviewer still has rounds (0 < 2), so debate is needed
        assert check_debate_needed(state) == "debate_needed"

    def test_no_feedback_markers_means_debate_done(self):
        state = {
            "team_config": {"agents": {"reviewer-1": {"role": "reviewer"}}},
            "agent_outputs": {
                "reviewer-1": {"summary": "APPROVED: all good now"},
            },
            "debate_round": 0,
            "max_debate_rounds": 3,
            "feedback_loops": [],
        }
        assert check_debate_needed(state) == "debate_done"

    def test_qa_gets_two_rounds(self):
        """QA role gets 2 rounds like reviewer."""
        state = {
            "team_config": {"agents": {"qa-1": {"role": "qa"}}},
            "agent_outputs": {
                "qa-1": {"summary": "ISSUES_FOUND: test regression"},
            },
            "debate_round": 1,
            "max_debate_rounds": 5,
            "feedback_loops": [
                {"round": 1, "source_instance": "qa-1", "source_role": "qa"},
            ],
        }
        assert check_debate_needed(state) == "debate_needed"


class TestPrepareDebateRoundPhase5:
    """Phase 5: multi-source debate preparation."""

    def _base_team_config(self):
        return {
            "pipeline_order": ["planner-1", "coder-1", "reviewer-1", "qa-1", "security-1"],
            "execution_dag": {
                "planner-1": [],
                "coder-1": ["planner-1"],
                "reviewer-1": ["coder-1"],
                "qa-1": ["coder-1"],
                "security-1": ["coder-1"],
            },
            "agents": {
                "planner-1": {"role": "planner", "name": "Planner"},
                "coder-1": {"role": "coder", "name": "Coder"},
                "reviewer-1": {"role": "reviewer", "name": "Reviewer"},
                "qa-1": {"role": "qa", "name": "QA"},
                "security-1": {"role": "security", "name": "Security"},
            },
        }

    def test_multi_source_debate_combines_feedback(self):
        """When both reviewer and QA raise issues, combine feedback into fix_packets."""
        state = {
            "team_config": self._base_team_config(),
            "agent_outputs": {
                "coder-1": {"summary": "Implementation complete"},
                "reviewer-1": {"summary": "CHANGES_REQUESTED: improve error handling"},
                "qa-1": {"summary": "ISSUES_FOUND: 3 integration tests failing"},
            },
            "completed_roles": ["planner-1", "coder-1", "reviewer-1", "qa-1", "security-1"],
            "ready_roles": [],
            "debate_round": 0,
            "feedback_loops": [],
            "events": [],
        }
        result = prepare_debate_round(state)

        # Coder should be the target
        assert result["current_agent_role"] == "coder-1"
        assert result["debate_round"] == 1

        # Both sources should be removed from completed so they re-run
        assert "reviewer-1" not in result["completed_roles"]
        assert "qa-1" not in result["completed_roles"]
        assert "coder-1" not in result["completed_roles"]

        # Both source outputs should be removed
        assert "reviewer-1" not in result["agent_outputs"]
        assert "qa-1" not in result["agent_outputs"]

        # Combined fix packets should contain both feedbacks
        fix_packets = result["fix_packets"]
        assert len(fix_packets) == 2
        all_text = "\n".join(fix_packets)
        assert "REVIEWER FEEDBACK" in all_text
        assert "QA FEEDBACK" in all_text

        # active_feedback should list all sources
        active = result["active_feedback"]
        assert len(active["all_sources"]) == 2

        # feedback_loops should record both
        assert len(result["feedback_loops"]) == 2

    def test_triple_source_debate_reviewer_qa_security(self):
        """All three sources raise issues — all combined into one fix round."""
        state = {
            "team_config": self._base_team_config(),
            "agent_outputs": {
                "coder-1": {"summary": "Code written"},
                "reviewer-1": {"summary": "CHANGES_REQUESTED: code quality issues"},
                "qa-1": {"summary": "tests failed: unit suite broken"},
                "security-1": {"summary": "FAILED: SQL injection in user input handler"},
            },
            "completed_roles": ["planner-1", "coder-1", "reviewer-1", "qa-1", "security-1"],
            "ready_roles": [],
            "debate_round": 0,
            "feedback_loops": [],
            "events": [],
        }
        result = prepare_debate_round(state)

        assert result["current_agent_role"] == "coder-1"
        assert len(result["fix_packets"]) == 3
        all_text = "\n".join(result["fix_packets"])
        assert "REVIEWER FEEDBACK" in all_text
        assert "QA FEEDBACK" in all_text
        assert "SECURITY FEEDBACK" in all_text
        assert len(result["feedback_loops"]) == 3
        assert len(result["active_feedback"]["all_sources"]) == 3

    def test_per_source_round_limit_filters_exhausted_sources(self):
        """If security already had 1 round (its max), only reviewer is active."""
        state = {
            "team_config": self._base_team_config(),
            "agent_outputs": {
                "coder-1": {"summary": "Fixed code"},
                "reviewer-1": {"summary": "CHANGES_REQUESTED: still needs work"},
                "security-1": {"summary": "BLOCKED: still vulnerable"},
            },
            "completed_roles": ["planner-1", "coder-1", "reviewer-1", "security-1"],
            "ready_roles": [],
            "debate_round": 1,
            "feedback_loops": [
                {"round": 1, "source_instance": "security-1", "source_role": "security",
                 "target_coder": "coder-1", "feedback": "SQL injection"},
            ],
            "events": [],
        }
        result = prepare_debate_round(state)

        # Only reviewer should be active (security exhausted its 1 round)
        assert len(result["fix_packets"]) == 1
        assert "REVIEWER FEEDBACK" in result["fix_packets"][0]
        assert len(result["active_feedback"]["all_sources"]) == 1
        assert result["active_feedback"]["all_sources"][0]["role"] == "reviewer"

    def test_events_record_all_feedback_sources(self):
        """Each feedback loop should generate an event."""
        state = {
            "team_config": self._base_team_config(),
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: fix imports"},
                "qa-1": {"summary": "ISSUES_FOUND: snapshot mismatch"},
            },
            "completed_roles": ["planner-1", "coder-1", "reviewer-1", "qa-1"],
            "ready_roles": [],
            "debate_round": 0,
            "feedback_loops": [],
            "events": [],
        }
        result = prepare_debate_round(state)
        loop_events = [e for e in result["events"] if e.get("type") == "feedback_loop"]
        assert len(loop_events) == 2
        sources = {e["source_role"] for e in loop_events}
        assert sources == {"reviewer", "qa"}

    def test_feedback_loops_history_accumulates_across_rounds(self):
        """feedback_loops list accumulates entries from successive rounds."""
        state = {
            "team_config": self._base_team_config(),
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: round 2 issues"},
            },
            "completed_roles": ["planner-1", "coder-1", "reviewer-1"],
            "ready_roles": [],
            "debate_round": 1,
            "feedback_loops": [
                {"round": 1, "source_instance": "reviewer-1", "source_role": "reviewer",
                 "target_coder": "coder-1", "feedback": "round 1 feedback"},
            ],
            "events": [],
        }
        result = prepare_debate_round(state)
        assert len(result["feedback_loops"]) == 2
        assert result["feedback_loops"][0]["round"] == 1
        assert result["feedback_loops"][1]["round"] == 2

    def test_target_coder_resolved_via_dag_deps(self):
        """Target coder is found through DAG dependency chain of feedback source."""
        state = {
            "team_config": self._base_team_config(),
            "agent_outputs": {
                "reviewer-1": {"summary": "CHANGES_REQUESTED: fix coder-1's work"},
            },
            "completed_roles": ["planner-1", "coder-1", "reviewer-1"],
            "ready_roles": [],
            "debate_round": 0,
            "feedback_loops": [],
            "events": [],
        }
        result = prepare_debate_round(state)
        assert result["current_instance_id"] == "coder-1"
        assert result["active_feedback"]["target_coder"] == "coder-1"

    def test_debate_with_instance_ids_not_bare_roles(self):
        """Instance-aware debate: uses reviewer-1, coder-1, not 'reviewer', 'coder'."""
        state = {
            "team_config": self._base_team_config(),
            "agent_outputs": {
                "reviewer-1": {"summary": "needs revision: tighten validation"},
            },
            "completed_roles": ["planner-1", "coder-1", "reviewer-1"],
            "ready_roles": [],
            "debate_round": 0,
            "feedback_loops": [],
            "events": [],
        }
        result = prepare_debate_round(state)
        # debate_target_role is the instance_id of the primary source
        assert result["debate_target_role"] == "reviewer-1"
        assert result["current_instance_id"] == "coder-1"


class TestCheckParallelPostprocessPhase5:
    """Phase 5: security can also trigger debate from parallel postprocess."""

    def test_security_changes_requested_triggers_debate(self):
        state = {
            "ready_roles": [],
            "team_config": {"agents": {"security-1": {"role": "security"}}},
            "agent_outputs": {
                "security-1": {"summary": "BLOCKED: critical vulnerability found"},
            },
            "debate_round": 0,
            "max_debate_rounds": 2,
            "feedback_loops": [],
        }
        assert check_parallel_postprocess(state) == "debate_needed"

    def test_qa_issues_found_triggers_debate(self):
        state = {
            "ready_roles": [],
            "team_config": {"agents": {"qa-1": {"role": "qa"}}},
            "agent_outputs": {
                "qa-1": {"summary": "ISSUES_FOUND: 5 failing tests"},
            },
            "debate_round": 0,
            "max_debate_rounds": 2,
            "feedback_loops": [],
        }
        assert check_parallel_postprocess(state) == "debate_needed"


class TestDefaultMaxRoundsByRole:
    """Verify the per-role round limit constants."""

    def test_reviewer_gets_two(self):
        assert _DEFAULT_MAX_ROUNDS_BY_ROLE["reviewer"] == 2

    def test_qa_gets_two(self):
        assert _DEFAULT_MAX_ROUNDS_BY_ROLE["qa"] == 2

    def test_security_gets_one(self):
        assert _DEFAULT_MAX_ROUNDS_BY_ROLE["security"] == 1


class TestSMEGapFixes:
    """Tests for SME review gap fixes in Phase 5."""

    def test_gap14_debate_target_cleared_after_routing(self):
        """Gap #14: debate_target_role should be cleared after routing to prevent re-trigger."""
        state = {
            "team_config": {
                "pipeline_order": ["planner", "coder", "reviewer"],
                "execution_dag": {
                    "planner": [],
                    "coder": ["planner"],
                    "reviewer": ["coder"],
                },
                "agents": {
                    "planner": {"role": "planner"},
                    "coder": {"role": "coder"},
                    "reviewer": {"role": "reviewer"},
                },
            },
            "current_agent_role": "coder",
            "current_instance_id": "coder",
            "debate_target_role": "reviewer",
            "completed_roles": ["planner"],
            "blocked_roles": [],
            "events": [],
        }
        result = advance_to_next_agent(state)
        assert result["current_agent_role"] == "reviewer"
        # debate_target_role should be cleared
        assert result["debate_target_role"] == ""

    def test_gap14_blocked_debate_target_skipped(self):
        """Gap #14: if debate target is blocked, skip debate routing."""
        state = {
            "team_config": {
                "pipeline_order": ["planner", "coder", "reviewer"],
                "execution_dag": {
                    "planner": [],
                    "coder": ["planner"],
                    "reviewer": ["coder"],
                },
                "agents": {
                    "planner": {"role": "planner"},
                    "coder": {"role": "coder"},
                    "reviewer": {"role": "reviewer"},
                },
            },
            "current_agent_role": "coder",
            "current_instance_id": "coder",
            "debate_target_role": "reviewer",
            "completed_roles": ["planner"],
            "blocked_roles": ["reviewer"],  # reviewer is blocked
            "events": [],
        }
        result = advance_to_next_agent(state)
        # Should NOT route to blocked reviewer — falls through to DAG-based routing
        assert result["current_agent_role"] != "reviewer" or result.get("status") == "pipeline_failed_dependency"

    def test_gap9_feedback_truncation_in_fix_packets(self):
        """Gap #9: Long feedback should be truncated in fix_packets."""
        long_summary = "CHANGES_REQUESTED: " + ("x" * 5000)
        state = {
            "team_config": {
                "pipeline_order": ["coder-1", "reviewer-1"],
                "execution_dag": {"coder-1": [], "reviewer-1": ["coder-1"]},
                "agents": {
                    "coder-1": {"role": "coder", "name": "Coder"},
                    "reviewer-1": {"role": "reviewer", "name": "Reviewer"},
                },
            },
            "agent_outputs": {
                "reviewer-1": {"summary": long_summary},
            },
            "completed_roles": ["coder-1", "reviewer-1"],
            "ready_roles": [],
            "debate_round": 0,
            "feedback_loops": [],
            "events": [],
        }
        result = prepare_debate_round(state)
        # Fix packets should be truncated (2000 char limit per source + overhead)
        for packet in result["fix_packets"]:
            assert len(packet) < 3000  # Header + 2000 char max + truncation notice

    def test_gap14_self_loop_prevented(self):
        """Gap #14: debate_target cannot be the coder itself."""
        state = {
            "team_config": {
                "pipeline_order": ["coder"],
                "execution_dag": {"coder": []},
                "agents": {"coder": {"role": "coder"}},
            },
            "current_agent_role": "coder",
            "current_instance_id": "coder",
            "debate_target_role": "coder",  # Invalid: self-loop
            "completed_roles": [],
            "blocked_roles": [],
            "events": [],
        }
        result = advance_to_next_agent(state)
        # Should NOT route coder back to itself
        assert result.get("ready_roles", []) == [] or result["current_agent_role"] != "coder"


class TestSourceRoleFirstRemediationLock:
    """Ensure downstream roles wait until source coder remediation passes."""

    def test_lock_routes_back_to_coder_when_latest_gate_failed(self):
        state = {
            "team_config": {
                "pipeline_order": ["planner-1", "coder-1", "reviewer-1", "qa-1"],
                "execution_dag": {
                    "planner-1": [],
                    "coder-1": ["planner-1"],
                    "reviewer-1": ["coder-1"],
                    "qa-1": ["coder-1"],
                },
                "agents": {
                    "planner-1": {"role": "planner"},
                    "coder-1": {"role": "coder"},
                    "reviewer-1": {"role": "reviewer"},
                    "qa-1": {"role": "qa"},
                },
            },
            "current_agent_role": "reviewer-1",
            "current_instance_id": "reviewer-1",
            "completed_roles": ["planner-1"],
            "blocked_roles": [],
            "gate_history": [{"role": "coder-1", "passed": False}],
            "active_feedback": {"target_coder": "coder-1"},
            "events": [],
        }

        result = advance_to_next_agent(state)
        assert result["current_instance_id"] == "coder-1"
        assert result["ready_roles"] == ["coder-1"]
        assert any(e.get("type") == "remediation_lock" for e in result["events"])

    def test_lock_released_after_coder_subsequent_pass(self):
        state = {
            "team_config": {
                "pipeline_order": ["planner-1", "coder-1", "reviewer-1"],
                "execution_dag": {
                    "planner-1": [],
                    "coder-1": ["planner-1"],
                    "reviewer-1": ["coder-1"],
                },
                "agents": {
                    "planner-1": {"role": "planner"},
                    "coder-1": {"role": "coder"},
                    "reviewer-1": {"role": "reviewer"},
                },
            },
            "current_agent_role": "coder-1",
            "current_instance_id": "coder-1",
            "completed_roles": ["planner-1"],
            "blocked_roles": [],
            "gate_history": [
                {"role": "coder-1", "passed": False},
                {"role": "coder-1", "passed": True},
            ],
            "events": [],
        }

        result = advance_to_next_agent(state)
        assert result["current_instance_id"] == "reviewer-1"
