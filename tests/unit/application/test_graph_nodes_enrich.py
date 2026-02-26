"""Unit tests for enrich graph node learning extraction."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from rigovo.application.graph.nodes.enrich import enrich_node
from rigovo.application.graph.state import TaskState
from rigovo.application.master.enricher import EnrichmentUpdate


class TestEnrichNode(unittest.IsolatedAsyncioTestCase):
    async def test_enrich_uses_gate_history_violations(self):
        state: TaskState = {
            "task_id": "task-1",
            "retry_count": 1,
            "gate_history": [
                {
                    "role": "coder",
                    "passed": False,
                    "violation_count": 1,
                    "violations": [
                        {"rule": "magic_number", "message": "magic number found"},
                    ],
                }
            ],
            "events": [],
        }

        result = await enrich_node(state)
        updates = result.get("enrichment_updates", [])
        assert updates, "Expected enrichment updates from gate history"
        pitfalls = updates[0].get("known_pitfalls", [])
        assert any("magic numbers" in p.lower() for p in pitfalls)

    async def test_enrich_uses_master_services_when_provided(self):
        state: TaskState = {
            "task_id": "task-2",
            "workspace_id": str(uuid4()),
            "team_config": {
                "team_id": "engineering",
                "agents": {
                    "coder": {
                        "id": str(uuid4()),
                        "name": "Coder",
                        "role": "coder",
                        "system_prompt": "You are coder",
                        "llm_model": "mock-model",
                        "tools": [],
                    }
                },
            },
            "agent_outputs": {
                "coder": {
                    "summary": "Implemented auth middleware",
                    "files_changed": ["src/auth.py"],
                    "duration_ms": 1200,
                }
            },
            "gate_history": [
                {
                    "role": "coder",
                    "passed": False,
                    "gates_run": 1,
                    "gates_passed": 0,
                    "violations": [
                        {"rule": "error_handling", "message": "bare except", "severity": "error"},
                    ],
                }
            ],
            "events": [],
        }
        mock_enricher = AsyncMock()
        mock_enricher.analyze_execution.return_value = EnrichmentUpdate(
            known_pitfalls=["Avoid bare except blocks."],
            domain_knowledge=["Use explicit exception classes."],
            pre_check_rules=["Run static checks before submit."],
            workspace_conventions=["Team uses structured logging."],
            reasoning="Learned from review failures",
        )
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = MagicMock(
            quality_score=52.0,
            speed_score=90.0,
            needs_enrichment=True,
        )

        result = await enrich_node(
            state,
            enricher=mock_enricher,
            evaluator=mock_evaluator,
        )

        assert any(u.get("source") == "master_enricher" for u in result["enrichment_updates"])
        assert any(e.get("type") == "agent_evaluated" for e in result["events"])
        mock_enricher.analyze_execution.assert_awaited()
        mock_evaluator.evaluate.assert_called_once()
