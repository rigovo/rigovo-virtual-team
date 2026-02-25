"""Tests for ContextBuilder — verifying per-agent context assembly."""

from __future__ import annotations

import pytest

from rigovo.application.context.context_builder import (
    ContextBuilder,
    AgentContext,
    ROLE_QUALITY_CONTRACT,
    MAX_TOTAL_CONTEXT_CHARS,
)
from rigovo.application.context.project_scanner import ProjectSnapshot
from rigovo.application.context.memory_retriever import RetrievedMemories


@pytest.fixture
def builder() -> ContextBuilder:
    return ContextBuilder()


@pytest.fixture
def sample_snapshot() -> ProjectSnapshot:
    return ProjectSnapshot(
        root="/tmp/test-project",
        tree="src/\n  main.py\n  utils.py\ntests/\n  test_main.py",
        tech_stack=["Python", "Docker"],
        key_file_contents={"pyproject.toml": '[project]\nname = "test"'},
        source_file_count=10,
        total_file_count=15,
        entry_points=["src/main.py"],
        test_directories=["tests/"],
    )


class TestContextBuilderBasic:
    """Test basic context assembly."""

    def test_build_returns_agent_context(self, builder: ContextBuilder) -> None:
        ctx = builder.build(role="coder")
        assert isinstance(ctx, AgentContext)
        assert ctx.role == "coder"

    def test_quality_contract_injected(self, builder: ContextBuilder) -> None:
        ctx = builder.build(role="coder")
        assert ctx.quality_contract != ""
        assert "quality gates" in ctx.quality_contract.lower()

    def test_planner_gets_quality_contract(self, builder: ContextBuilder) -> None:
        ctx = builder.build(role="planner")
        assert "specific" in ctx.quality_contract.lower()

    def test_unknown_role_gets_empty_contract(self, builder: ContextBuilder) -> None:
        ctx = builder.build(role="unknown_role")
        assert ctx.quality_contract == ""


class TestContextBuilderProjectContext:
    """Test project context injection."""

    def test_project_snapshot_injected(
        self, builder: ContextBuilder, sample_snapshot: ProjectSnapshot,
    ) -> None:
        ctx = builder.build(role="coder", project_snapshot=sample_snapshot)
        assert ctx.project_section != ""
        assert "PROJECT CONTEXT" in ctx.project_section

    def test_planner_gets_full_context(
        self, builder: ContextBuilder, sample_snapshot: ProjectSnapshot,
    ) -> None:
        planner_ctx = builder.build(role="planner", project_snapshot=sample_snapshot)
        coder_ctx = builder.build(role="coder", project_snapshot=sample_snapshot)
        # Planner should get at least as much context as coder
        assert len(planner_ctx.project_section) >= len(coder_ctx.project_section)

    def test_no_snapshot_no_project_section(self, builder: ContextBuilder) -> None:
        ctx = builder.build(role="coder")
        assert ctx.project_section == ""


class TestContextBuilderPipelineContext:
    """Test previous agent output injection."""

    def test_pipeline_outputs_injected(self, builder: ContextBuilder) -> None:
        outputs = {
            "planner": {"summary": "Plan: 1. Create user model 2. Add endpoints"},
            "coder": {"summary": "Created user.py with User class and CRUD endpoints"},
        }
        ctx = builder.build(role="reviewer", previous_outputs=outputs)
        assert ctx.pipeline_section != ""
        assert "PLANNER" in ctx.pipeline_section
        assert "CODER" in ctx.pipeline_section

    def test_empty_outputs_no_pipeline_section(self, builder: ContextBuilder) -> None:
        ctx = builder.build(role="reviewer", previous_outputs={})
        assert ctx.pipeline_section == ""

    def test_no_outputs_no_pipeline_section(self, builder: ContextBuilder) -> None:
        ctx = builder.build(role="reviewer")
        assert ctx.pipeline_section == ""


class TestContextBuilderEnrichment:
    """Test enrichment context injection."""

    def test_enrichment_injected(self, builder: ContextBuilder) -> None:
        enrichment = "--- KNOWN PITFALLS ---\n- Always add type hints"
        ctx = builder.build(role="coder", enrichment_text=enrichment)
        assert ctx.enrichment_section == enrichment

    def test_empty_enrichment_no_section(self, builder: ContextBuilder) -> None:
        ctx = builder.build(role="coder", enrichment_text="")
        assert ctx.enrichment_section == ""


class TestContextBuilderFullContext:
    """Test complete context assembly."""

    def test_full_context_assembles_all_sections(
        self, builder: ContextBuilder, sample_snapshot: ProjectSnapshot,
    ) -> None:
        ctx = builder.build(
            role="coder",
            project_snapshot=sample_snapshot,
            enrichment_text="--- ENRICHMENT ---\nTest enrichment",
            previous_outputs={"planner": {"summary": "Plan here"}},
        )
        full = ctx.to_full_context()
        assert "QUALITY CONTRACT" in full
        assert "PROJECT CONTEXT" in full
        assert "ENRICHMENT" in full
        assert "PREVIOUS AGENT OUTPUTS" in full

    def test_full_context_respects_total_budget(
        self, builder: ContextBuilder,
    ) -> None:
        # Create huge enrichment to trigger truncation
        huge = "x" * (MAX_TOTAL_CONTEXT_CHARS + 1000)
        ctx = builder.build(role="coder", enrichment_text=huge)
        full = ctx.to_full_context()
        assert len(full) <= MAX_TOTAL_CONTEXT_CHARS + 100  # Allow for truncation message

    def test_all_roles_have_quality_contracts(self) -> None:
        """Every defined role should have a quality contract."""
        expected_roles = {"planner", "coder", "reviewer", "security", "qa", "devops", "sre", "lead"}
        for role in expected_roles:
            assert role in ROLE_QUALITY_CONTRACT, f"Missing contract for {role}"
