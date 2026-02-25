"""Tests for smart agent and quality rules."""

import json

import pytest

from rigovo.config_schema import detect_project_config


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
