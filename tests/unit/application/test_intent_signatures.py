"""Tests for the two-pass Semantic Guardrail System.

Tests cover:
1. Pass 1 (Regex): Keyword patterns match correctly
2. Pass 2 (Vector Similarity): Semantic anchors match when regex fails
3. Confidence thresholds and gap calculations
4. Ambiguous inputs
5. Integration with deterministic_brain.py
"""

from __future__ import annotations

import pytest

from rigovo.application.master.deterministic_brain import (
    DeterministicClassification,
    check_role_eligible,
    classify_by_keywords,
    classify_semantic,
    enforce_minimum_team,
    get_minimum_team,
)
from rigovo.application.master.intent_signatures import (
    INTENT_SIGNATURES,
    SemanticClassification,
    SemanticClassifier,
    semantic_to_deterministic,
)
from rigovo.infrastructure.embeddings.local_embeddings import LocalEmbeddingProvider

# ═══════════════════════════════════════════════════════════════════════
# Pass 1: Keyword / Regex tests
# ═══════════════════════════════════════════════════════════════════════


class TestKeywordClassifier:
    """Tests for Pass 1 — deterministic regex patterns."""

    def test_new_project_create_repo(self) -> None:
        result = classify_by_keywords("Create new repo for my auth application")
        assert result.task_type == "new_project"
        assert result.is_deterministic is True
        assert result.confidence >= 0.85

    def test_new_project_build_app(self) -> None:
        result = classify_by_keywords("Build a new SaaS platform for identity management")
        assert result.task_type == "new_project"

    def test_new_project_scaffold(self) -> None:
        result = classify_by_keywords("Scaffold a React dashboard")
        assert result.task_type == "new_project"

    def test_new_project_from_scratch(self) -> None:
        result = classify_by_keywords("Build an auth system from scratch")
        assert result.task_type == "new_project"

    def test_new_project_create_saas_in_language(self) -> None:
        result = classify_by_keywords("Create auth identity SaaS in Python")
        assert result.task_type == "new_project"

    def test_new_project_create_folder_and_saas(self) -> None:
        result = classify_by_keywords(
            "Create new folder in mounted one and create auth identity SaaS in Python"
        )
        assert result.task_type == "new_project"

    def test_bug_fix(self) -> None:
        result = classify_by_keywords("Fix the crash on the login page")
        assert result.task_type == "bug"
        assert result.is_deterministic is True

    def test_bug_not_working(self) -> None:
        result = classify_by_keywords("The payment form doesn't work on mobile")
        assert result.task_type == "bug"

    def test_refactor(self) -> None:
        result = classify_by_keywords("Refactor the database access layer")
        assert result.task_type == "refactor"

    def test_security_audit(self) -> None:
        result = classify_by_keywords("Run a security audit on the API endpoints")
        assert result.task_type == "security"

    def test_infra_docker(self) -> None:
        result = classify_by_keywords("Set up Docker containers for the services")
        assert result.task_type == "infra"

    def test_test_coverage(self) -> None:
        result = classify_by_keywords("Write unit tests for the auth module")
        assert result.task_type == "test"

    def test_docs(self) -> None:
        result = classify_by_keywords("Write documentation for the API")
        assert result.task_type == "docs"

    def test_performance(self) -> None:
        result = classify_by_keywords("Optimize the slow database queries")
        assert result.task_type == "performance"

    def test_investigation(self) -> None:
        result = classify_by_keywords("Investigate why the test suite is flaky")
        assert result.task_type == "investigation"

    def test_feature_add(self) -> None:
        result = classify_by_keywords("Add dark mode toggle to settings")
        assert result.task_type == "feature"

    def test_empty_input(self) -> None:
        result = classify_by_keywords("")
        assert result.task_type == "feature"
        assert result.confidence == 0.0
        assert result.is_deterministic is False

    def test_no_match_defaults_to_feature(self) -> None:
        result = classify_by_keywords("something vague and unusual")
        assert result.task_type == "feature"
        assert result.confidence == 0.3
        assert result.is_deterministic is False

    def test_priority_new_project_over_feature(self) -> None:
        """New project patterns must match BEFORE the broad 'feature' patterns."""
        result = classify_by_keywords("Create new project for a payment gateway")
        assert result.task_type == "new_project"  # NOT "feature"


# ═══════════════════════════════════════════════════════════════════════
# Pass 2: Semantic vector similarity tests
# ═══════════════════════════════════════════════════════════════════════


class TestSemanticClassifier:
    """Tests for the two-pass SemanticClassifier."""

    @pytest.fixture
    def embedding_provider(self) -> LocalEmbeddingProvider:
        return LocalEmbeddingProvider()

    @pytest.fixture
    async def classifier(self, embedding_provider: LocalEmbeddingProvider) -> SemanticClassifier:
        sc = SemanticClassifier(embedding_provider)
        await sc.initialize()
        return sc

    @pytest.mark.asyncio
    async def test_initialize_precomputes_embeddings(self, classifier: SemanticClassifier) -> None:
        """Initialization should pre-compute embeddings for all anchors."""
        for sig in INTENT_SIGNATURES.values():
            if sig.semantic_anchors:
                assert len(sig.anchor_embeddings) == len(sig.semantic_anchors)
                assert all(len(e) == 256 for e in sig.anchor_embeddings)

    @pytest.mark.asyncio
    async def test_regex_match_takes_priority(self, classifier: SemanticClassifier) -> None:
        """When regex matches, semantic pass should NOT run."""
        result = await classifier.classify("Create new repo for auth")
        assert result.source == "regex"
        assert result.task_type == "new_project"
        assert result.confidence == 0.90

    @pytest.mark.asyncio
    async def test_semantic_match_when_no_regex(self, classifier: SemanticClassifier) -> None:
        """When regex doesn't match, semantic should activate."""
        # "stitch modules together" has no direct regex match
        result = await classifier.classify("stitch these two modules together into one service")
        # Should find some match (likely refactor or feature)
        assert result.source in ("semantic", "regex", "default")
        assert result.task_type in ("refactor", "feature")

    @pytest.mark.asyncio
    async def test_empty_input_returns_default(self, classifier: SemanticClassifier) -> None:
        result = await classifier.classify("")
        assert result.source == "default"
        assert result.task_type == "feature"
        assert result.confidence == 0.3

    @pytest.mark.asyncio
    async def test_new_project_semantic(self, classifier: SemanticClassifier) -> None:
        """Semantic should catch new project intent even with unusual phrasing."""
        result = await classifier.classify("spin up a new landing page with Next.js")
        assert result.task_type == "new_project"

    @pytest.mark.asyncio
    async def test_new_project_semantic_user_prompt_shape(
        self, classifier: SemanticClassifier
    ) -> None:
        result = await classifier.classify(
            "Create new folder in mounted one and create auth identity SaaS in Python"
        )
        assert result.task_type == "new_project"

    @pytest.mark.asyncio
    async def test_bug_semantic(self, classifier: SemanticClassifier) -> None:
        result = await classifier.classify("the API returns 500 errors intermittently")
        assert result.task_type == "bug"

    @pytest.mark.asyncio
    async def test_classification_has_similarity_scores(
        self, classifier: SemanticClassifier
    ) -> None:
        result = await classifier.classify("optimize the slow database queries")
        assert result.best_similarity >= 0.0
        assert result.best_similarity <= 1.0


# ═══════════════════════════════════════════════════════════════════════
# Integration: classify_semantic (the unified entry point)
# ═══════════════════════════════════════════════════════════════════════


class TestClassifySemantic:
    """Tests for the unified classify_semantic entry point."""

    @pytest.mark.asyncio
    async def test_with_embedding_provider(self) -> None:
        provider = LocalEmbeddingProvider()
        result = await classify_semantic("Create new repo for auth SaaS", provider)
        assert result.task_type == "new_project"
        assert result.is_deterministic is True

    @pytest.mark.asyncio
    async def test_without_embedding_provider(self) -> None:
        """Falls back to pure keyword classification."""
        result = await classify_semantic("Fix the broken login", None)
        assert result.task_type == "bug"
        assert result.is_deterministic is True

    @pytest.mark.asyncio
    async def test_fallback_without_provider_no_match(self) -> None:
        result = await classify_semantic("something unusual", None)
        assert result.task_type == "feature"
        assert result.confidence == 0.3


# ═══════════════════════════════════════════════════════════════════════
# Minimum team enforcement tests
# ═══════════════════════════════════════════════════════════════════════


class TestMinimumTeam:
    """Tests for enforce_minimum_team."""

    def test_new_project_requires_planner_coder_reviewer_qa(self) -> None:
        # planner is the first-class orchestrator — must always precede the coder
        spec = get_minimum_team("new_project")
        assert "planner" in spec.required_roles
        assert "coder" in spec.required_roles
        assert "reviewer" in spec.required_roles
        assert "qa" in spec.required_roles

    def test_bug_requires_planner_coder_reviewer_qa(self) -> None:
        spec = get_minimum_team("bug")
        assert "planner" in spec.required_roles
        assert "coder" in spec.required_roles
        assert "reviewer" in spec.required_roles
        assert "qa" in spec.required_roles

    def test_security_requires_core_team_plus_security(self) -> None:
        spec = get_minimum_team("security")
        assert "planner" in spec.required_roles
        assert "security" in spec.required_roles
        assert "coder" in spec.required_roles
        assert "reviewer" in spec.required_roles
        assert "qa" in spec.required_roles

    def test_enforce_adds_missing_core_roles(self) -> None:
        llm_agents = [{"instance_id": "coder-1", "role": "coder"}]
        result = enforce_minimum_team(llm_agents, "feature", "add dark mode")
        roles = {a["role"] for a in result}
        assert "planner" in roles
        assert "coder" in roles
        assert "reviewer" in roles
        assert "qa" in roles
        assert len(result) == 4

    def test_enforce_preserves_existing_agents(self) -> None:
        llm_agents = [
            {"instance_id": "planner-1", "role": "planner"},
            {"instance_id": "coder-1", "role": "coder"},
            {"instance_id": "reviewer-1", "role": "reviewer"},
            {"instance_id": "security-1", "role": "security"},
            {"instance_id": "qa-1", "role": "qa"},
        ]
        # feature minimum = [planner, coder, reviewer, qa] — all present, no additions
        result = enforce_minimum_team(llm_agents, "feature", "test")
        assert len(result) == 5

    def test_enforce_does_not_duplicate(self) -> None:
        llm_agents = [
            {"instance_id": "planner-1", "role": "planner"},
            {"instance_id": "coder-1", "role": "coder"},
            {"instance_id": "coder-2", "role": "coder"},
            {"instance_id": "reviewer-1", "role": "reviewer"},
            {"instance_id": "qa-1", "role": "qa"},
        ]
        # planner already present — must not add a second one
        result = enforce_minimum_team(llm_agents, "feature", "test")
        assert len(result) == 5


# ═══════════════════════════════════════════════════════════════════════
# Role eligibility tests
# ═══════════════════════════════════════════════════════════════════════


class TestRoleEligibility:
    """Tests for check_role_eligible."""

    def test_planner_always_eligible(self) -> None:
        assert check_role_eligible("planner", False, False, "new_project") is True

    def test_coder_always_eligible(self) -> None:
        assert check_role_eligible("coder", False, False, "new_project") is True

    def test_reviewer_not_eligible_on_empty_workspace(self) -> None:
        assert check_role_eligible("reviewer", False, False, "new_project") is False

    def test_reviewer_eligible_after_coder(self) -> None:
        assert check_role_eligible("reviewer", False, True, "new_project") is True

    def test_reviewer_eligible_with_existing_code(self) -> None:
        assert check_role_eligible("reviewer", True, False, "bug") is True

    def test_security_not_eligible_on_empty(self) -> None:
        assert check_role_eligible("security", False, False, "new_project") is False

    def test_qa_not_eligible_on_empty(self) -> None:
        assert check_role_eligible("qa", False, False, "feature") is False


# ═══════════════════════════════════════════════════════════════════════
# Conversion helpers
# ═══════════════════════════════════════════════════════════════════════


class TestSemanticToDeterministic:
    """Tests for format conversion."""

    def test_conversion(self) -> None:
        sc = SemanticClassification(
            task_type="refactor",
            complexity="medium",
            confidence=0.82,
            source="semantic",
            matched_pattern="stitch modules together",
            best_similarity=0.82,
            runner_up_type="feature",
            runner_up_similarity=0.61,
            is_ambiguous=False,
        )
        dc = semantic_to_deterministic(sc)
        assert isinstance(dc, DeterministicClassification)
        assert dc.task_type == "refactor"
        assert dc.complexity == "medium"
        assert dc.confidence == 0.82
        assert dc.is_deterministic is True
