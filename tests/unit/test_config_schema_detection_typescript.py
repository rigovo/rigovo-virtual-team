"""Tests for TypeScript/JavaScript project detection."""

import json

import pytest

from rigovo.config_schema import detect_project_config


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
