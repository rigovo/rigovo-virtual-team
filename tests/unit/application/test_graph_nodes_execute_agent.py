"""Unit tests for execute agent graph node."""

from __future__ import annotations

import asyncio
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from rigovo.application.graph.nodes.execute_agent import execute_agent_node
from rigovo.application.graph.state import TaskState
from rigovo.domain.entities.memory import Memory, MemoryType
from rigovo.domain.interfaces.llm_provider import LLMResponse, LLMUsage


class MockLLMProvider:
    """Mock LLM provider for testing."""

    def __init__(self, response_content: str = ""):
        self.response_content = response_content
        self.model_name = "test-model"

    async def invoke(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Return a mock response with token counts."""
        await asyncio.sleep(0)  # Yield to event loop as real LLM providers do
        return LLMResponse(
            content=self.response_content,
            usage=LLMUsage(input_tokens=100, output_tokens=50),
            model=self.model_name,
        )

    async def stream(self, *args, **kwargs):
        """Mock stream method."""
        return []


class TestExecuteAgentNode(unittest.IsolatedAsyncioTestCase):
    """Test the execute_agent_node function."""

    async def test_execute_agent_node_basic_execution(self):
        """Test execute_agent_node executes agent with context."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Fix the login bug",
            "team_config": {
                "agents": {
                    "backend": {
                        "id": "agent-1",
                        "name": "Backend",
                        "role": "backend",
                        "system_prompt": "You are a backend engineer.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                        "enrichment_context": "Context here",
                    }
                }
            },
            "current_agent_role": "backend",
            "agent_outputs": {},
            "events": [],
        }

        mock_response = LLMResponse(
            content="Fixed the login issue",
            usage=LLMUsage(input_tokens=200, output_tokens=100),
            model="claude-sonnet-4-6",
        )

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.10

        result = await execute_agent_node(
            state, mock_llm_factory, mock_cost_calculator
        )

        assert "agent_outputs" in result
        assert "backend" in result["agent_outputs"]
        output = result["agent_outputs"]["backend"]
        assert output["summary"] == "Fixed the login issue"
        assert output["tokens"] == 300
        assert output["cost"] == 0.10
        assert "agent_backend_complete" in result["status"]
        assert len(result["events"]) == 2  # agent_started + agent_complete
        assert result["events"][0]["type"] == "agent_started"
        assert result["events"][1]["type"] == "agent_complete"

    async def test_execute_agent_node_with_previous_outputs(self):
        """Test execute_agent_node includes previous agent outputs in context."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Implement feature",
            "team_config": {
                "agents": {
                    "frontend": {
                        "id": "agent-2",
                        "name": "Frontend",
                        "role": "frontend",
                        "system_prompt": "You are a frontend engineer.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                        "enrichment_context": "",
                    }
                }
            },
            "current_agent_role": "frontend",
            "agent_outputs": {
                "backend": {
                    "summary": "Backend API ready at /api/feature",
                }
            },
            "events": [],
        }

        mock_response = LLMResponse(
            content="UI implemented",
            usage=LLMUsage(input_tokens=250, output_tokens=75),
            model="claude-sonnet-4-6",
        )

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.07

        result = await execute_agent_node(
            state, mock_llm_factory, mock_cost_calculator
        )

        # Verify the mock was called with messages including previous output
        call_args = mock_llm.invoke.call_args
        messages = call_args.kwargs["messages"]

        # System prompt should contain previous outputs via ContextBuilder
        # Previous outputs are now injected into system prompt, not as separate messages
        assert len(messages) >= 2  # system + user task
        system_content = messages[0]["content"]
        assert "BACKEND" in system_content
        assert "Backend API ready" in system_content

    async def test_execute_agent_node_injects_retrieved_memories(self):
        """Retrieved memory context should be injected into agent system prompt."""
        state: TaskState = {
            "task_id": str(uuid4()),
            "workspace_id": str(uuid4()),
            "description": "Harden API retry behavior",
            "team_config": {
                "agents": {
                    "coder": {
                        "id": "agent-2",
                        "name": "Coder",
                        "role": "coder",
                        "system_prompt": "You are a coder.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                        "enrichment_context": "",
                    }
                }
            },
            "current_agent_role": "coder",
            "agent_outputs": {},
            "events": [],
        }

        memory = Memory(
            workspace_id=uuid4(),
            content="Use exponential backoff for transient HTTP 429 failures.",
            memory_type=MemoryType.ERROR_FIX,
            embedding=[0.9, 0.1],
        )
        memory_repo = AsyncMock()
        memory_repo.search.return_value = [memory]
        embedding_provider = AsyncMock()
        embedding_provider.embed.return_value = [0.8, 0.2]

        mock_response = LLMResponse(
            content="Added retry jitter and capped backoff.",
            usage=LLMUsage(input_tokens=150, output_tokens=60),
            model="claude-sonnet-4-6",
        )
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.06

        result = await execute_agent_node(
            state,
            mock_llm_factory,
            mock_cost_calculator,
            memory_repo=memory_repo,
            embedding_provider=embedding_provider,
        )

        system_content = mock_llm.invoke.call_args.kwargs["messages"][0]["content"]
        assert "MEMORIES (lessons from past tasks)" in system_content
        assert "backoff" in system_content.lower()
        assert "memory_context_by_role" in result
        assert result["memory_context_by_role"]["coder"] != ""
        assert any(e.get("type") == "memories_retrieved" for e in result["events"])
        memory_event = next(e for e in result["events"] if e.get("type") == "memories_retrieved")
        assert "avg_score" in memory_event
        assert "top_score" in memory_event

    async def test_execute_agent_node_with_fix_packet(self):
        """Test execute_agent_node includes fix packet in retry context."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Fix code",
            "team_config": {
                "agents": {
                    "backend": {
                        "id": "agent-1",
                        "name": "Backend",
                        "role": "backend",
                        "system_prompt": "Fix the code.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                    }
                }
            },
            "current_agent_role": "backend",
            "agent_outputs": {},
            "fix_packets": ["Fix violation in src/app.py line 15"],
            "events": [],
        }

        mock_response = LLMResponse(
            content="Fixed",
            usage=LLMUsage(input_tokens=300, output_tokens=50),
            model="claude-sonnet-4-6",
        )

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.08

        result = await execute_agent_node(
            state, mock_llm_factory, mock_cost_calculator
        )

        call_args = mock_llm.invoke.call_args
        messages = call_args.kwargs["messages"]

        # Should include fix packet
        assert any("[FIX REQUIRED]" in msg.get("content", "") for msg in messages)

    async def test_execute_agent_node_updates_cost_accumulator(self):
        """Test execute_agent_node updates cost accumulator."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Task",
            "team_config": {
                "agents": {
                    "backend": {
                        "id": "agent-1",
                        "name": "Backend",
                        "role": "backend",
                        "system_prompt": "Prompt",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                    }
                }
            },
            "current_agent_role": "backend",
            "cost_accumulator": {"previous": {"tokens": 100, "cost": 0.02}},
            "events": [],
        }

        mock_response = LLMResponse(
            content="Output",
            usage=LLMUsage(input_tokens=100, output_tokens=50),
            model="claude-sonnet-4-6",
        )

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.05

        result = await execute_agent_node(
            state, mock_llm_factory, mock_cost_calculator
        )

        assert "previous" in result["cost_accumulator"]
        assert "agent-1" in result["cost_accumulator"]
        assert result["cost_accumulator"]["agent-1"]["tokens"] == 150

    async def test_execute_agent_node_blocks_on_input_contract_failure(self):
        """Input contract violations should fail before LLM execution."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Task",
            "team_config": {
                "agents": {
                    "backend": {
                        "id": "agent-1",
                        "name": "Backend",
                        "role": "backend",
                        "system_prompt": "Prompt",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                        "input_contract": {
                            "type": "object",
                            "required": ["task_description", "classification"],
                            "properties": {
                                "task_description": {"type": "string"},
                                "classification": {"type": "object", "required": ["task_type"]},
                            },
                        },
                    }
                }
            },
            "current_agent_role": "backend",
            "agent_outputs": {},
            "events": [],
        }

        mock_llm = AsyncMock()

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        result = await execute_agent_node(state, mock_llm_factory, mock_cost_calculator)

        assert result["status"] == "contract_failed_backend"
        assert result["contract_stage"] == "input"
        assert any(e.get("type") == "contract_failed" for e in result["events"])
        mock_llm.invoke.assert_not_called()

    async def test_execute_agent_node_blocks_on_output_contract_failure(self):
        """Output contract violations should fail after generation."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Task",
            "classification": {"task_type": "feature"},
            "team_config": {
                "agents": {
                    "backend": {
                        "id": "agent-1",
                        "name": "Backend",
                        "role": "backend",
                        "system_prompt": "Prompt",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                        "output_contract": {
                            "type": "object",
                            "required": ["status"],
                            "properties": {
                                "status": {"type": "string", "enum": ["done"]},
                            },
                        },
                    }
                }
            },
            "current_agent_role": "backend",
            "agent_outputs": {},
            "events": [],
        }

        mock_response = LLMResponse(
            content="Output",
            usage=LLMUsage(input_tokens=100, output_tokens=50),
            model="claude-sonnet-4-6",
        )
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = mock_response

        def mock_llm_factory(model: str):
            return mock_llm

        mock_cost_calculator = MagicMock()
        mock_cost_calculator.calculate.return_value = 0.05
        result = await execute_agent_node(state, mock_llm_factory, mock_cost_calculator)

        assert result["status"] == "contract_failed_backend"
        assert result["contract_stage"] == "output"
        assert "agent_outputs" not in result

    async def test_consult_agent_returns_existing_output_immediately(self):
        """consult_agent returns immediate answer when target output already exists."""
        state: TaskState = {
            "task_id": "task-1",
            "description": "Finish implementation",
            "team_config": {
                "agents": {
                    "coder": {
                        "id": "agent-coder",
                        "name": "Coder",
                        "role": "coder",
                        "system_prompt": "You are a coder.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": ["consult_agent"],
                    },
                    "security": {
                        "id": "agent-security",
                        "name": "Security",
                        "role": "security",
                        "system_prompt": "You are security.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                    },
                }
            },
            "current_agent_role": "coder",
            "agent_outputs": {
                "security": {"summary": "PASS: No high-severity findings."},
            },
            "agent_messages": [],
            "events": [],
        }

        mock_llm = AsyncMock()
        mock_llm.invoke.side_effect = [
            LLMResponse(
                content="",
                usage=LLMUsage(input_tokens=100, output_tokens=50),
                model="claude-sonnet-4-6",
                tool_calls=[{
                    "id": "toolu_consult_1",
                    "name": "consult_agent",
                    "input": {
                        "to_role": "security",
                        "question": "Any blockers?",
                    },
                }],
            ),
            LLMResponse(
                content="Proceeding with implementation.",
                usage=LLMUsage(input_tokens=80, output_tokens=40),
                model="claude-sonnet-4-6",
            ),
        ]

        def llm_factory(model: str):
            return mock_llm

        cost_calc = MagicMock()
        cost_calc.calculate.return_value = 0.10

        result = await execute_agent_node(state, llm_factory, cost_calc)

        messages = result.get("agent_messages", [])
        assert len(messages) >= 2
        assert messages[0]["type"] == "consult_request"
        assert messages[0]["status"] == "answered"
        assert messages[1]["type"] == "consult_response"
        assert messages[1]["from_role"] == "security"
        assert any(e.get("type") == "agent_consult_completed" for e in result["events"])

    async def test_pending_consult_is_fulfilled_when_target_role_completes(self):
        """Pending consults are auto-answered when the target role finishes."""
        coder_state: TaskState = {
            "task_id": "task-2",
            "description": "Implement and ask security",
            "team_config": {
                "agents": {
                    "coder": {
                        "id": "agent-coder",
                        "name": "Coder",
                        "role": "coder",
                        "system_prompt": "You are a coder.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": ["consult_agent"],
                    },
                    "security": {
                        "id": "agent-security",
                        "name": "Security",
                        "role": "security",
                        "system_prompt": "You are security.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                    },
                }
            },
            "current_agent_role": "coder",
            "agent_outputs": {},
            "agent_messages": [],
            "events": [],
        }

        coder_llm = AsyncMock()
        coder_llm.invoke.side_effect = [
            LLMResponse(
                content="",
                usage=LLMUsage(input_tokens=100, output_tokens=30),
                model="claude-sonnet-4-6",
                tool_calls=[{
                    "id": "toolu_consult_2",
                    "name": "consult_agent",
                    "input": {
                        "to_role": "security",
                        "question": "Please review auth flow.",
                    },
                }],
            ),
            LLMResponse(
                content="Coder completed core changes.",
                usage=LLMUsage(input_tokens=60, output_tokens=40),
                model="claude-sonnet-4-6",
            ),
        ]

        def coder_factory(model: str):
            return coder_llm

        cost_calc = MagicMock()
        cost_calc.calculate.return_value = 0.09
        coder_result = await execute_agent_node(coder_state, coder_factory, cost_calc)

        pending = [
            m for m in coder_result.get("agent_messages", [])
            if m.get("type") == "consult_request"
        ]
        assert pending and pending[0]["status"] == "pending"

        security_state: TaskState = {
            **coder_state,
            "current_agent_role": "security",
            "agent_outputs": coder_result.get("agent_outputs", {}),
            "agent_messages": coder_result.get("agent_messages", []),
            "events": coder_result.get("events", []),
        }

        security_llm = AsyncMock()
        security_llm.invoke.return_value = LLMResponse(
            content="Security review complete: no blockers.",
            usage=LLMUsage(input_tokens=70, output_tokens=30),
            model="claude-sonnet-4-6",
        )

        def security_factory(model: str):
            return security_llm

        security_result = await execute_agent_node(security_state, security_factory, cost_calc)
        consult_messages = security_result.get("agent_messages", [])

        requests = [m for m in consult_messages if m.get("type") == "consult_request"]
        responses = [m for m in consult_messages if m.get("type") == "consult_response"]
        assert requests and requests[0]["status"] == "answered"
        assert responses
        assert responses[-1]["from_role"] == "security"
        assert responses[-1]["to_role"] == "coder"

    async def test_consult_agent_blocks_disallowed_target_by_policy(self):
        """Consultation policy blocks invalid role-to-role requests."""
        state: TaskState = {
            "task_id": "task-3",
            "description": "Implement and consult devops",
            "team_config": {
                "agents": {
                    "coder": {
                        "id": "agent-coder",
                        "name": "Coder",
                        "role": "coder",
                        "system_prompt": "You are a coder.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": ["consult_agent"],
                    },
                    "devops": {
                        "id": "agent-devops",
                        "name": "DevOps",
                        "role": "devops",
                        "system_prompt": "You are devops.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                    },
                }
            },
            "current_agent_role": "coder",
            "agent_outputs": {},
            "agent_messages": [],
            "events": [],
        }

        mock_llm = AsyncMock()
        mock_llm.invoke.side_effect = [
            LLMResponse(
                content="",
                usage=LLMUsage(input_tokens=100, output_tokens=20),
                model="claude-sonnet-4-6",
                tool_calls=[{
                    "id": "toolu_consult_3",
                    "name": "consult_agent",
                    "input": {
                        "to_role": "devops",  # blocked for coder by policy
                        "question": "Can you validate deployment now?",
                    },
                }],
            ),
            LLMResponse(
                content="Continuing without external consult.",
                usage=LLMUsage(input_tokens=60, output_tokens=40),
                model="claude-sonnet-4-6",
            ),
        ]

        def llm_factory(model: str):
            return mock_llm

        cost_calc = MagicMock()
        cost_calc.calculate.return_value = 0.08
        result = await execute_agent_node(state, llm_factory, cost_calc)

        assert result.get("agent_messages", []) == []
        assert not any(e.get("type") == "agent_consult_requested" for e in result["events"])

    async def test_consult_agent_respects_state_policy_override(self):
        """State consultation_policy can override allowed target matrix."""
        state: TaskState = {
            "task_id": "task-4",
            "description": "Custom consultation policy",
            "team_config": {
                "agents": {
                    "coder": {
                        "id": "agent-coder",
                        "name": "Coder",
                        "role": "coder",
                        "system_prompt": "You are a coder.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": ["consult_agent"],
                    },
                    "devops": {
                        "id": "agent-devops",
                        "name": "DevOps",
                        "role": "devops",
                        "system_prompt": "You are devops.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": [],
                    },
                }
            },
            "current_agent_role": "coder",
            "agent_outputs": {"devops": {"summary": "Deployment constraints documented."}},
            "agent_messages": [],
            "consultation_policy": {
                "enabled": True,
                "max_question_chars": 500,
                "max_response_chars": 500,
                "allowed_targets": {
                    "coder": ["devops"],
                },
            },
            "events": [],
        }

        mock_llm = AsyncMock()
        mock_llm.invoke.side_effect = [
            LLMResponse(
                content="",
                usage=LLMUsage(input_tokens=90, output_tokens=20),
                model="claude-sonnet-4-6",
                tool_calls=[{
                    "id": "toolu_consult_4",
                    "name": "consult_agent",
                    "input": {
                        "to_role": "devops",
                        "question": "Any release gating concerns?",
                    },
                }],
            ),
            LLMResponse(
                content="Proceeding with devops advisory.",
                usage=LLMUsage(input_tokens=50, output_tokens=30),
                model="claude-sonnet-4-6",
            ),
        ]

        def llm_factory(model: str):
            return mock_llm

        cost_calc = MagicMock()
        cost_calc.calculate.return_value = 0.07
        result = await execute_agent_node(state, llm_factory, cost_calc)

        consult_messages = result.get("agent_messages", [])
        assert consult_messages
        assert consult_messages[0]["to_role"] == "devops"

    async def test_execute_agent_emits_integration_blocked_event(self):
        """invoke_integration should emit blocked event when trust policy denies."""
        state: TaskState = {
            "task_id": "task-5",
            "description": "Notify slack channel",
            "team_config": {
                "agents": {
                    "devops": {
                        "id": "agent-devops",
                        "name": "DevOps",
                        "role": "devops",
                        "system_prompt": "You are devops.",
                        "llm_model": "claude-sonnet-4-6",
                        "tools": ["invoke_integration"],
                    },
                }
            },
            "current_agent_role": "devops",
            "agent_outputs": {},
            "integration_policy": {
                "enable_connector_tools": True,
                "enable_mcp_tools": False,
                "enable_action_tools": False,
                "min_trust_level": "verified",
            },
            "integration_catalog": {
                "acme-slack": {
                    "enabled": True,
                    "trust_level": "community",
                    "connectors": ["slack"],
                    "mcp_servers": [],
                    "actions": [],
                }
            },
            "events": [],
        }

        mock_llm = AsyncMock()
        mock_llm.invoke.side_effect = [
            LLMResponse(
                content="",
                usage=LLMUsage(input_tokens=100, output_tokens=20),
                model="claude-sonnet-4-6",
                tool_calls=[{
                    "id": "toolu_integration_1",
                    "name": "invoke_integration",
                    "input": {
                        "kind": "connector",
                        "plugin_id": "acme-slack",
                        "target_id": "slack",
                        "operation": "post_message",
                        "payload": {"channel": "alerts"},
                    },
                }],
            ),
            LLMResponse(
                content="Integration step handled.",
                usage=LLMUsage(input_tokens=60, output_tokens=30),
                model="claude-sonnet-4-6",
            ),
        ]

        def llm_factory(model: str):
            return mock_llm

        cost_calc = MagicMock()
        cost_calc.calculate.return_value = 0.08
        result = await execute_agent_node(state, llm_factory, cost_calc)
        assert any(e.get("type") == "integration_blocked" for e in result["events"])


if __name__ == "__main__":
    unittest.main()
