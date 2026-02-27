"""Tests for RunTaskCommand team selection and routing inputs."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from rigovo.application.commands.run_task import RunTaskCommand
from rigovo.infrastructure.plugins.manifest import (
    ActionSpec,
    ConnectorSpec,
    MCPServerSpec,
    PluginManifest,
)


class _MockDomainPlugin:
    def __init__(self, roles):
        self._roles = roles

    def get_agent_roles(self):
        return self._roles


def _role(role_id: str, order: int = 0):
    return SimpleNamespace(
        role_id=role_id,
        name=role_id.title(),
        default_llm_model="claude-sonnet-4-6",
        default_system_prompt=f"You are {role_id}",
        default_tools=["read_file"],
        pipeline_order=order,
    )


def _team_cfg(domain: str = "engineering", enabled: bool = True):
    return SimpleNamespace(domain=domain, enabled=enabled, agents={})


def _make_cmd() -> RunTaskCommand:
    cmd = RunTaskCommand.__new__(RunTaskCommand)
    cmd._workspace_id = UUID(int=0)
    cmd._domain_plugins = {
        "engineering": _MockDomainPlugin([_role("planner", 1), _role("coder", 2)]),
    }
    cmd._team_configs = {
        "team-a": _team_cfg(),
        "team-b": _team_cfg(),
    }
    return cmd


def test_build_available_teams_filters_by_requested_team_name():
    cmd = _make_cmd()
    teams, pools = cmd._build_available_teams("team-b")

    assert len(teams) == 1
    assert teams[0]["id"] == "team-b"
    assert "team-b" in pools
    assert all(a.team_id == pools["team-b"][0].team_id for a in pools["team-b"])


def test_build_available_teams_raises_for_missing_requested_team():
    cmd = _make_cmd()
    with pytest.raises(ValueError, match="Requested team"):
        cmd._build_available_teams("missing-team")


def test_build_integration_catalog_exposes_action_and_mcp_policy_metadata():
    cmd = _make_cmd()
    cmd._plugin_registry = SimpleNamespace(
        load=lambda include_disabled=False: [
            PluginManifest(
                id="acme-suite",
                name="ACME Suite",
                version="1.0.0",
                trust_level="verified",
                capabilities=["connector", "mcp", "action"],
                connectors=[
                    ConnectorSpec(
                        id="slack",
                        provider="slack",
                        outbound_actions=["post_message"],
                    )
                ],
                mcp_servers=[
                    MCPServerSpec(
                        id="knowledge",
                        transport="stdio",
                        command="acme-mcp",
                        operations=["query", "fetch_context"],
                    )
                ],
                actions=[
                    ActionSpec(
                        id="delete_records",
                        description="Delete records",
                        requires_approval=True,
                    )
                ],
            )
        ]
    )

    catalog = cmd._build_integration_catalog()
    plugin = catalog["acme-suite"]

    assert plugin["connector_operations"]["slack"] == ["post_message"]
    assert plugin["mcp_operations"]["knowledge"] == ["query", "fetch_context"]
    assert plugin["action_requires_approval"]["delete_records"] is True
