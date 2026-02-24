"""Shared test fixtures."""

from __future__ import annotations

from uuid import uuid4

import pytest

from rigovo.domain.entities.workspace import Workspace, Plan
from rigovo.domain.entities.team import Team
from rigovo.domain.entities.agent import Agent, AgentRole, AgentStats, EnrichmentContext
from rigovo.domain.entities.task import Task, TaskType, TaskComplexity


@pytest.fixture
def workspace_id():
    return uuid4()


@pytest.fixture
def workspace(workspace_id):
    return Workspace(
        id=workspace_id,
        name="Acme Corp",
        slug="acme",
        owner_id="user-123",
        plan=Plan.PRO,
    )


@pytest.fixture
def team(workspace_id):
    return Team(
        workspace_id=workspace_id,
        name="Payment Team",
        domain="engineering",
    )


@pytest.fixture
def agents(team, workspace_id):
    """A realistic payment team agent set."""
    return [
        Agent(
            team_id=team.id,
            workspace_id=workspace_id,
            role=AgentRole.PLANNER,
            name="Planner",
            pipeline_order=0,
        ),
        Agent(
            team_id=team.id,
            workspace_id=workspace_id,
            role=AgentRole.CODER,
            name="Backend Coder",
            pipeline_order=1,
        ),
        Agent(
            team_id=team.id,
            workspace_id=workspace_id,
            role=AgentRole.REVIEWER,
            name="Code Reviewer",
            pipeline_order=2,
        ),
        Agent(
            team_id=team.id,
            workspace_id=workspace_id,
            role=AgentRole.SECURITY,
            name="Security Expert",
            pipeline_order=3,
        ),
        Agent(
            team_id=team.id,
            workspace_id=workspace_id,
            role=AgentRole.QA,
            name="QA Engineer",
            pipeline_order=4,
        ),
    ]


@pytest.fixture
def task(workspace_id):
    return Task(
        workspace_id=workspace_id,
        description="Add Stripe payment integration",
    )
