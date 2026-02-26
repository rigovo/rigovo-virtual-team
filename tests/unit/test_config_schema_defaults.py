"""Tests for RigovoConfig and schema defaults."""

import pytest

from rigovo.config_schema import (
    ConsultationSchema,
    RigovoConfig,
    ProjectSchema,
    TeamSchema,
    QualitySchema,
)


class TestRigovoConfigDefaults:
    """Test RigovoConfig default values."""

    def test_config_defaults(self):
        """RigovoConfig should initialize with sensible defaults."""
        config = RigovoConfig()

        assert config.version == "1"
        assert isinstance(config.project, ProjectSchema)
        assert isinstance(config.teams, dict)
        assert "engineering" in config.teams
        assert isinstance(config.quality, QualitySchema)
        assert config.quality.rigour_enabled is True
        assert config.quality.rigour_timeout == 120
        assert config.database.backend == "sqlite"
        assert config.database.local_path == ".rigovo/local.db"
        assert config.plugins.enabled is True
        assert config.plugins.paths == [".rigovo/plugins"]
        assert config.plugins.allow_unsigned is False
        assert config.identity.sso_enabled is False
        assert "admin" in config.identity.personas
        assert "tasks.approve" in config.identity.personas["operator"]

    def test_project_schema_defaults(self):
        """ProjectSchema should have defaults."""
        project = ProjectSchema()

        assert project.name == ""
        assert project.language == ""
        assert project.framework == ""
        assert project.monorepo is False
        assert project.test_framework == ""
        assert project.package_manager == ""
        assert project.source_dir == "src"
        assert project.test_dir == "tests"

    def test_team_schema_defaults(self):
        """TeamSchema should have defaults."""
        team = TeamSchema()

        assert team.enabled is True
        assert team.domain == "engineering"
        assert isinstance(team.agents, dict)

    def test_quality_schema_defaults(self):
        """QualitySchema should have default gates."""
        quality = QualitySchema()

        assert quality.rigour_enabled is True
        assert "hardcoded-secrets" in quality.gates
        assert quality.gates["hardcoded-secrets"].severity == "error"
        assert quality.gates["hardcoded-secrets"].threshold == 0

        assert "file-size" in quality.gates
        assert quality.gates["file-size"].severity == "warning"

        assert "function-length" in quality.gates
        assert quality.gates["function-length"].severity == "warning"

        assert "hallucinated-imports" in quality.gates
        assert quality.gates["hallucinated-imports"].severity == "error"

    def test_approval_schema_defaults(self):
        """ApprovalSchema should have defaults."""
        config = RigovoConfig()

        assert config.approval.after_planning is True
        assert config.approval.after_coding is False
        assert config.approval.after_review is False
        assert config.approval.before_commit is True

    def test_consultation_schema_defaults(self):
        """Consultation policy defaults should be present and sane."""
        consult = ConsultationSchema()

        assert consult.enabled is True
        assert consult.max_question_chars == 1200
        assert consult.max_response_chars == 1200
        assert "reviewer" in consult.allowed_targets
        assert "security" in consult.allowed_targets["coder"]

    def test_consultation_policy_from_root_config(self):
        """Root config should include orchestration consultation defaults."""
        config = RigovoConfig()
        consult = config.orchestration.consultation

        assert consult.enabled is True
        assert "reviewer" in consult.allowed_targets
