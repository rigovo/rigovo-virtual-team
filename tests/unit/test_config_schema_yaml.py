"""Tests for YAML loading and saving."""

import pytest
import yaml

from rigovo.config_schema import (
    RigovoConfig,
    load_rigovo_yml,
    save_rigovo_yml,
)


class TestYAMLIO:
    """Test YAML loading and saving."""

    def test_load_rigovo_yml_no_file(self, tmp_path):
        """load_rigovo_yml returns defaults when file doesn't exist."""
        config = load_rigovo_yml(tmp_path)

        assert config.version == "1"
        assert config.project.name == ""
        assert "engineering" in config.teams

    def test_load_rigovo_yml_valid_file(self, tmp_path):
        """load_rigovo_yml loads and parses a valid YAML file."""
        yml_path = tmp_path / "rigovo.yml"
        yml_path.write_text('version: "1"\nproject:\n  name: "my-project"\n  language: "python"\n  framework: "fastapi"\n  test_framework: "pytest"\nquality:\n  rigour_enabled: true\n')
        config = load_rigovo_yml(tmp_path)
        assert isinstance(config, RigovoConfig), "Should return RigovoConfig instance"
        assert hasattr(config, "project"), "Config should have project attribute"
        assert hasattr(config, "quality"), "Config should have quality attribute"
        assert config.version == "1", "Version should be loaded"
        assert config.project.name == "my-project", "Project name should be loaded"
        assert config.project.language == "python", "Language should be loaded"
        assert config.project.framework == "fastapi", "Framework should be loaded"
        assert config.project.test_framework == "pytest", "Test framework should be loaded"
        assert config.quality.rigour_enabled is True, "Rigour should be enabled"
        assert config.project.source_dir == "src", "Should have default source_dir"
        assert config.project.test_dir == "tests", "Should have default test_dir"
        assert config.project.monorepo is False, "Should have default monorepo"

    def test_load_rigovo_yml_empty_file(self, tmp_path):
        """load_rigovo_yml handles empty YAML file."""
        yml_path = tmp_path / "rigovo.yml"
        yml_path.write_text("")

        config = load_rigovo_yml(tmp_path)

        assert config.version == "1"
        assert isinstance(config.project, ProjectSchema)

    def test_save_rigovo_yml_writes_valid_yaml(self, tmp_path):
        """save_rigovo_yml writes a valid YAML file."""
        config = RigovoConfig()
        config.project.name = "test-project"
        config.project.language = "python"
        config.project.framework = "fastapi"

        saved_path = save_rigovo_yml(config, tmp_path)

        assert saved_path.exists()
        assert saved_path.name == "rigovo.yml"

        # Verify the YAML is readable and has correct content
        content = saved_path.read_text()
        assert "rigovo.yml" in content
        assert "test-project" in content
        assert "python" in content
        assert "fastapi" in content

        # Verify it's valid YAML by loading it back
        reloaded = yaml.safe_load(content)
        assert reloaded is not None
        assert reloaded["project"]["name"] == "test-project"

    def test_save_and_load_roundtrip(self, tmp_path):
        """Test that save and load are symmetric."""
        original = RigovoConfig()
        original.project.name = "roundtrip-test"
        original.project.language = "typescript"
        original.quality.rigour_enabled = False

        save_rigovo_yml(original, tmp_path)
        reloaded = load_rigovo_yml(tmp_path)

        assert reloaded.project.name == original.project.name
        assert reloaded.project.language == original.project.language
        assert reloaded.quality.rigour_enabled == original.quality.rigour_enabled

    def test_save_rigovo_yml_includes_full_orchestration_defaults(self, tmp_path):
        """Generated rigovo.yml should include all orchestration defaults."""
        config = RigovoConfig()
        saved_path = save_rigovo_yml(config, tmp_path)
        reloaded = yaml.safe_load(saved_path.read_text(encoding="utf-8"))

        orchestration = reloaded["orchestration"]
        assert "max_retries" in orchestration
        assert "max_agents_per_task" in orchestration
        assert "timeout_per_agent" in orchestration
        assert "idle_timeout" in orchestration
        assert "parallel_agents" in orchestration
        assert "deep_mode" in orchestration
        assert "deep_pro" in orchestration
        assert "budget" in orchestration
        assert "consultation" in orchestration

        consultation = orchestration["consultation"]
        assert "enabled" in consultation
        assert "max_question_chars" in consultation
        assert "max_response_chars" in consultation
        assert "allowed_targets" in consultation

        assert "database" in reloaded
        database = reloaded["database"]
        assert database["backend"] == "sqlite"
        assert database["local_path"] == ".rigovo/local.db"

        assert "plugins" in reloaded
        plugins = reloaded["plugins"]
        assert plugins["enabled"] is True
        assert plugins["paths"] == [".rigovo/plugins"]
        assert plugins["allow_unsigned"] is False

        assert "identity" in reloaded
        identity = reloaded["identity"]
        assert identity["sso_enabled"] is False
        assert "personas" in identity
        assert "admin" in identity["personas"]


# Import ProjectSchema for empty file test
from rigovo.config_schema import ProjectSchema
