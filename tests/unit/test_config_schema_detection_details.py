"""Tests for detailed project detection features (monorepo, framework, test framework, directories, project name)."""

import json

import pytest

from rigovo.config_schema import detect_project_config
from rigovo.config_detection import (
    detect_project_name as _detect_project_name,
    detect_framework as _detect_framework,
    detect_test_framework as _detect_test_framework,
    detect_monorepo as _detect_monorepo,
    detect_source_dir as _detect_source_dir,
    detect_test_dir as _detect_test_dir,
)


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
