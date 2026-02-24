"""Comprehensive tests for rigovo.config_schema module.

Tests cover:
- RigovoConfig defaults
- YAML I/O (load, save)
- Project auto-detection for multiple tech stacks
- Smart agent rules based on language/framework
- Smart quality rules
- Monorepo, framework, and test framework detection
"""

import json
from pathlib import Path

import pytest
import yaml

from rigovo.config_schema import (
    RigovoConfig,
    ProjectSchema,
    AgentOverride,
    TeamSchema,
    QualitySchema,
    CustomRule,
    load_rigovo_yml,
    save_rigovo_yml,
    detect_project_config,
    _detect_project_name,
    _detect_framework,
    _detect_test_framework,
    _detect_monorepo,
    _detect_source_dir,
    _detect_test_dir,
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


class TestDetectProjectConfigPython:
    """Test project detection for Python projects."""

    def test_detect_python_with_pyproject_toml(self, tmp_path):
        """detect_project_config recognizes Python via pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "my-python-project"\n'
        )

        config = detect_project_config(tmp_path)

        assert config.project.language == "python"
        assert config.project.package_manager == "poetry"

    def test_detect_python_with_requirements_txt(self, tmp_path):
        """detect_project_config recognizes Python via requirements.txt."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("fastapi==0.100.0\n")

        config = detect_project_config(tmp_path)

        assert config.project.language == "python"
        assert config.project.package_manager == "pip"

    def test_detect_python_with_setup_py(self, tmp_path):
        """detect_project_config recognizes Python via setup.py."""
        setup = tmp_path / "setup.py"
        setup.write_text("from setuptools import setup\n")

        config = detect_project_config(tmp_path)

        assert config.project.language == "python"
        assert config.project.package_manager == "setuptools"

    def test_detect_pytest_in_python_project(self, tmp_path):
        """detect_project_config finds pytest in Python projects."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest==7.0.0\nfastapi==0.100.0\n")

        config = detect_project_config(tmp_path)

        assert config.project.language == "python"
        assert config.project.test_framework == "pytest"

    def test_detect_fastapi_framework(self, tmp_path):
        """detect_project_config detects FastAPI framework."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("fastapi==0.100.0\nuvicorn==0.23.0\n")

        config = detect_project_config(tmp_path)

        assert config.project.language == "python"
        assert config.project.framework == "fastapi"

    def test_detect_django_framework(self, tmp_path):
        """detect_project_config detects Django framework."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "django-app"\ndependencies = ["django>=4.0"]\n')

        config = detect_project_config(tmp_path)

        assert config.project.language == "python"
        assert config.project.framework == "django"


class TestDetectProjectConfigTypeScript:
    """Test project detection for TypeScript/JavaScript projects."""

    def test_detect_typescript_with_tsconfig(self, tmp_path):
        """detect_project_config recognizes TypeScript via tsconfig.json."""
        tsconfig = tmp_path / "tsconfig.json"
        tsconfig.write_text('{"compilerOptions": {}}')

        config = detect_project_config(tmp_path)

        assert config.project.language == "typescript"

    def test_detect_javascript_with_package_json(self, tmp_path):
        """detect_project_config recognizes JavaScript via package.json."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "my-js-project",
                "version": "1.0.0",
                "dependencies": {}
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.language == "javascript"

    def test_detect_nextjs_framework(self, tmp_path):
        """detect_project_config detects Next.js framework."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "nextjs-app",
                "dependencies": {"next": "13.0.0"}
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.language == "javascript"
        assert config.project.framework == "nextjs"

    def test_detect_jest_test_framework(self, tmp_path):
        """detect_project_config detects Jest test framework."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "test-app",
                "devDependencies": {"jest": "29.0.0"}
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.test_framework == "jest"

    def test_detect_vitest_test_framework(self, tmp_path):
        """detect_project_config detects Vitest test framework."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "test-app",
                "devDependencies": {"vitest": "0.34.0"}
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.test_framework == "vitest"

    def test_detect_npm_package_manager(self, tmp_path):
        """detect_project_config defaults to npm for JS/TS."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(json.dumps({"name": "test-app"}))

        config = detect_project_config(tmp_path)

        assert config.project.package_manager == "npm"

    def test_detect_pnpm_package_manager(self, tmp_path):
        """detect_project_config detects pnpm via lockfile."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(json.dumps({"name": "test-app"}))

        lock_file = tmp_path / "pnpm-lock.yaml"
        lock_file.write_text("lockfileVersion: 5.4\n")

        config = detect_project_config(tmp_path)

        assert config.project.package_manager == "pnpm"

    def test_detect_yarn_package_manager(self, tmp_path):
        """detect_project_config detects yarn via lockfile."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(json.dumps({"name": "test-app"}))

        lock_file = tmp_path / "yarn.lock"
        lock_file.write_text("")

        config = detect_project_config(tmp_path)

        assert config.project.package_manager == "yarn"


class TestDetectProjectConfigEmpty:
    """Test project detection for empty/minimal projects."""

    def test_detect_empty_project(self, tmp_path):
        """detect_project_config returns defaults for empty project."""
        config = detect_project_config(tmp_path)

        assert config.project.language == ""
        assert config.project.framework == ""
        assert config.project.test_framework == ""
        assert config.project.source_dir == "src"
        assert config.project.test_dir == "tests"


class TestSmartAgentRulesPython:
    """Test smart agent rules for Python projects."""

    def test_coder_rules_python(self, tmp_path):
        """Coder agent gets Python-specific rules."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest==7.0.0\n")

        config = detect_project_config(tmp_path)

        coder = config.teams["engineering"].agents.get("coder")
        assert coder is not None
        assert len(coder.rules) > 0
        assert any("type hints" in rule for rule in coder.rules)
        assert any("PEP 8" in rule for rule in coder.rules)

    def test_qa_rules_pytest(self, tmp_path):
        """QA agent gets pytest-specific rules."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest==7.0.0\n")

        config = detect_project_config(tmp_path)

        qa = config.teams["engineering"].agents.get("qa")
        assert qa is not None
        assert any("pytest" in rule.lower() for rule in qa.rules)

    def test_reviewer_rules_always_present(self, tmp_path):
        """Reviewer agent gets standard security rules."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest==7.0.0\n")

        config = detect_project_config(tmp_path)

        reviewer = config.teams["engineering"].agents.get("reviewer")
        assert reviewer is not None
        assert any("security" in rule.lower() for rule in reviewer.rules)


class TestSmartAgentRulesTypeScript:
    """Test smart agent rules for TypeScript projects."""

    def test_coder_rules_typescript(self, tmp_path):
        """Coder agent gets TypeScript-specific rules."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(json.dumps({"name": "ts-app"}))

        tsconfig = tmp_path / "tsconfig.json"
        tsconfig.write_text('{"compilerOptions": {}}')

        config = detect_project_config(tmp_path)

        coder = config.teams["engineering"].agents.get("coder")
        assert coder is not None
        assert any("strict mode" in rule for rule in coder.rules)
        assert any("JSDoc" in rule for rule in coder.rules)

    def test_coder_rules_nextjs(self, tmp_path):
        """Coder agent gets Next.js-specific rules when framework detected."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "nextjs-app",
                "dependencies": {"next": "13.0.0"}
            })
        )

        config = detect_project_config(tmp_path)

        coder = config.teams["engineering"].agents.get("coder")
        assert coder is not None
        assert any("App Router" in rule for rule in coder.rules)
        assert any("Server Components" in rule for rule in coder.rules)

    def test_qa_rules_jest(self, tmp_path):
        """QA agent gets Jest-specific rules."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "jest-app",
                "devDependencies": {"jest": "29.0.0"}
            })
        )

        config = detect_project_config(tmp_path)

        qa = config.teams["engineering"].agents.get("qa")
        assert qa is not None
        assert any("jest" in rule.lower() for rule in qa.rules)

    def test_qa_rules_vitest(self, tmp_path):
        """QA agent gets Vitest-specific rules."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "vitest-app",
                "devDependencies": {"vitest": "0.34.0"}
            })
        )

        config = detect_project_config(tmp_path)

        qa = config.teams["engineering"].agents.get("qa")
        assert qa is not None
        # Vitest shares rules with Jest in the codebase
        assert any("describe/it" in rule or "mock" in rule.lower() for rule in qa.rules)


class TestSmartQualityRules:
    """Test smart quality rules."""

    def test_custom_rules_python(self, tmp_path):
        """Python projects get custom quality rules."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest==7.0.0\n")

        config = detect_project_config(tmp_path)

        assert len(config.quality.custom_rules) > 0
        rule_ids = [r.id for r in config.quality.custom_rules]
        assert "no-print-statements" in rule_ids or "no-bare-except" in rule_ids

    def test_custom_rules_typescript(self, tmp_path):
        """TypeScript projects get custom quality rules."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(json.dumps({"name": "ts-app"}))

        tsconfig = tmp_path / "tsconfig.json"
        tsconfig.write_text('{"compilerOptions": {}}')

        config = detect_project_config(tmp_path)

        rule_ids = [r.id for r in config.quality.custom_rules]
        assert "no-any-type" in rule_ids or "no-console-log" in rule_ids

    def test_custom_rule_structure(self, tmp_path):
        """Custom rules have required fields."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest==7.0.0\n")

        config = detect_project_config(tmp_path)

        if config.quality.custom_rules:
            rule = config.quality.custom_rules[0]
            assert rule.id != ""
            assert rule.pattern != ""
            assert rule.message != ""
            assert rule.severity in ("error", "warning", "info")
            assert len(rule.file_types) > 0


class TestMonorepoDetection:
    """Test monorepo detection."""

    def test_detect_lerna_monorepo(self, tmp_path):
        """detect_project_config detects Lerna monorepo."""
        lerna_file = tmp_path / "lerna.json"
        lerna_file.write_text('{"version": "0.0.0"}')

        config = detect_project_config(tmp_path)

        assert config.project.monorepo is True

    def test_detect_nx_monorepo(self, tmp_path):
        """detect_project_config detects Nx monorepo."""
        nx_file = tmp_path / "nx.json"
        nx_file.write_text('{"npmScope": "myorg"}')

        config = detect_project_config(tmp_path)

        assert config.project.monorepo is True

    def test_detect_turbo_monorepo(self, tmp_path):
        """detect_project_config detects Turbo monorepo."""
        turbo_file = tmp_path / "turbo.json"
        turbo_file.write_text('{"pipeline": {}}')

        config = detect_project_config(tmp_path)

        assert config.project.monorepo is True

    def test_detect_pnpm_workspace_monorepo(self, tmp_path):
        """detect_project_config detects pnpm workspace monorepo."""
        workspace_file = tmp_path / "pnpm-workspace.yaml"
        workspace_file.write_text("packages:\n  - 'packages/*'\n")

        config = detect_project_config(tmp_path)

        assert config.project.monorepo is True

    def test_detect_workspaces_in_package_json(self, tmp_path):
        """detect_project_config detects workspaces in package.json."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "root",
                "workspaces": ["packages/*"]
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.monorepo is True

    def test_no_monorepo_detected(self, tmp_path):
        """detect_project_config returns False when no monorepo indicators."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(json.dumps({"name": "single-pkg"}))

        config = detect_project_config(tmp_path)

        assert config.project.monorepo is False


class TestFrameworkDetection:
    """Test framework detection for various languages."""

    def test_detect_express_framework(self, tmp_path):
        """detect_project_config detects Express framework."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "express-app",
                "dependencies": {"express": "4.18.0"}
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.framework == "express"

    def test_detect_vue_framework(self, tmp_path):
        """detect_project_config detects Vue framework."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "vue-app",
                "dependencies": {"vue": "3.0.0"}
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.framework == "vue"

    def test_detect_flask_framework(self, tmp_path):
        """detect_project_config detects Flask framework."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("flask==2.3.0\n")

        config = detect_project_config(tmp_path)

        assert config.project.framework == "flask"

    def test_framework_priority_ordering(self, tmp_path):
        """detect_project_config respects framework priority."""
        pkg_json = tmp_path / "package.json"
        # Next.js should be detected before React
        pkg_json.write_text(
            json.dumps({
                "name": "app",
                "dependencies": {
                    "next": "13.0.0",
                    "react": "18.0.0"
                }
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.framework == "nextjs"


class TestTestFrameworkDetection:
    """Test test framework detection."""

    def test_detect_mocha_test_framework(self, tmp_path):
        """detect_project_config detects Mocha test framework."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "test-app",
                "devDependencies": {"mocha": "10.0.0"}
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.test_framework == "mocha"

    def test_detect_playwright_test_framework(self, tmp_path):
        """detect_project_config detects Playwright test framework."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "test-app",
                "devDependencies": {"@playwright/test": "1.40.0"}
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.test_framework == "playwright"

    def test_detect_unittest_python(self, tmp_path):
        """detect_project_config detects unittest in Python."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("unittest-xml-reporting==3.2.0\n")

        config = detect_project_config(tmp_path)

        assert config.project.test_framework == "unittest"

    def test_vitest_prioritized_over_jest(self, tmp_path):
        """Vitest should be detected before Jest."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "app",
                "devDependencies": {
                    "vitest": "0.34.0",
                    "jest": "29.0.0"
                }
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.test_framework == "vitest"


class TestProjectNameDetection:
    """Test project name detection from manifest files."""

    def test_project_name_from_package_json(self, tmp_path):
        """_detect_project_name reads from package.json."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({"name": "my-awesome-app"})
        )

        name = _detect_project_name(tmp_path, "javascript")

        assert name == "my-awesome-app"

    def test_project_name_from_pyproject_toml(self, tmp_path):
        """_detect_project_name reads from pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "my-python-pkg"\n')

        name = _detect_project_name(tmp_path, "python")

        assert name == "my-python-pkg"

    def test_project_name_from_cargo_toml(self, tmp_path):
        """_detect_project_name reads from Cargo.toml."""
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text('[package]\nname = "my-rust-app"\n')

        name = _detect_project_name(tmp_path, "rust")

        assert name == "my-rust-app"

    def test_project_name_fallback_to_directory(self, tmp_path):
        """_detect_project_name falls back to directory name."""
        name = _detect_project_name(tmp_path, "python")

        assert name == tmp_path.name


class TestSourceAndTestDirDetection:
    """Test source and test directory detection."""

    def test_detect_src_directory(self, tmp_path):
        """_detect_source_dir finds src directory."""
        (tmp_path / "src").mkdir()

        source_dir = _detect_source_dir(tmp_path, "python")

        assert source_dir == "src"

    def test_detect_lib_directory(self, tmp_path):
        """_detect_source_dir finds lib directory."""
        (tmp_path / "lib").mkdir()

        source_dir = _detect_source_dir(tmp_path, "javascript")

        assert source_dir == "lib"

    def test_detect_app_directory(self, tmp_path):
        """_detect_source_dir finds app directory."""
        (tmp_path / "app").mkdir()

        source_dir = _detect_source_dir(tmp_path, "javascript")

        assert source_dir == "app"

    def test_source_dir_default(self, tmp_path):
        """_detect_source_dir defaults to 'src' if none found."""
        source_dir = _detect_source_dir(tmp_path, "python")

        assert source_dir == "src"

    def test_detect_tests_directory(self, tmp_path):
        """_detect_test_dir finds tests directory."""
        (tmp_path / "tests").mkdir()

        test_dir = _detect_test_dir(tmp_path, "python")

        assert test_dir == "tests"

    def test_detect_test_directory(self, tmp_path):
        """_detect_test_dir finds test directory."""
        (tmp_path / "test").mkdir()

        test_dir = _detect_test_dir(tmp_path, "python")

        assert test_dir == "test"

    def test_detect___tests___directory(self, tmp_path):
        """_detect_test_dir finds __tests__ directory."""
        (tmp_path / "__tests__").mkdir()

        test_dir = _detect_test_dir(tmp_path, "typescript")

        assert test_dir == "__tests__"

    def test_test_dir_default_python(self, tmp_path):
        """_detect_test_dir defaults to 'tests' for Python."""
        test_dir = _detect_test_dir(tmp_path, "python")

        assert test_dir == "tests"

    def test_test_dir_default_typescript(self, tmp_path):
        """_detect_test_dir defaults to '__tests__' for TypeScript."""
        test_dir = _detect_test_dir(tmp_path, "typescript")

        assert test_dir == "__tests__"


class TestIntegrationComplexProjects:
    """Integration tests for realistic project scenarios."""

    def test_full_python_fastapi_project(self, tmp_path):
        """Full detection for a Python FastAPI project."""
        # Create file structure
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "my-api"\nrequires-python = ">=3.9"\n'
            'dependencies = ["fastapi", "uvicorn", "sqlalchemy"]\n'
        )

        config = detect_project_config(tmp_path)

        assert config.project.name == "my-api"
        assert config.project.language == "python"
        assert config.project.framework == "fastapi"
        assert config.project.source_dir == "src"
        assert config.project.test_dir == "tests"
        assert config.project.package_manager == "poetry"

        coder = config.teams["engineering"].agents.get("coder")
        # FastAPI rules should be present (Pydantic models, OpenAPI descriptions, etc)
        assert any("Pydantic" in rule or "OpenAPI" in rule or "dependency injection" in rule for rule in coder.rules)

    def test_full_typescript_nextjs_project(self, tmp_path):
        """Full detection for a TypeScript Next.js project."""
        # Create file structure
        (tmp_path / "app").mkdir()
        (tmp_path / "__tests__").mkdir()

        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "next-commerce",
                "version": "1.0.0",
                "dependencies": {
                    "next": "14.0.0",
                    "react": "18.2.0"
                },
                "devDependencies": {
                    "typescript": "5.0.0",
                    "jest": "29.0.0"
                }
            })
        )

        tsconfig = tmp_path / "tsconfig.json"
        tsconfig.write_text('{"compilerOptions": {"strict": true}}')

        config = detect_project_config(tmp_path)

        assert config.project.name == "next-commerce"
        assert config.project.language == "typescript"
        assert config.project.framework == "nextjs"
        assert config.project.test_framework == "jest"
        assert config.project.source_dir == "app"
        assert config.project.test_dir == "__tests__"

        coder = config.teams["engineering"].agents.get("coder")
        assert any("nextjs" in rule.lower() or "next.js" in rule.lower() or "App Router" in rule for rule in coder.rules)

    def test_monorepo_nextjs_project(self, tmp_path):
        """Full detection for a Next.js monorepo."""
        # Create monorepo structure
        (tmp_path / "packages" / "api").mkdir(parents=True)
        (tmp_path / "packages" / "web").mkdir(parents=True)

        # Root package.json with workspaces
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(
            json.dumps({
                "name": "monorepo",
                "workspaces": ["packages/*"]
            })
        )

        # API package
        (tmp_path / "packages" / "api" / "package.json").write_text(
            json.dumps({
                "name": "@monorepo/api",
                "dependencies": {"express": "4.18.0"}
            })
        )

        # Web package
        (tmp_path / "packages" / "web" / "package.json").write_text(
            json.dumps({
                "name": "@monorepo/web",
                "dependencies": {"next": "14.0.0"}
            })
        )

        config = detect_project_config(tmp_path)

        assert config.project.monorepo is True
        assert config.project.language == "javascript"

    def test_django_python_project(self, tmp_path):
        """Full detection for a Django project."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "django-app"\ndependencies = ["django>=4.0", "djangorestframework"]\n'
        )

        config = detect_project_config(tmp_path)

        assert config.project.language == "python"
        assert config.project.framework == "django"

        coder = config.teams["engineering"].agents.get("coder")
        assert any("django" in rule.lower() for rule in coder.rules)
