"""Tests for Python project detection."""

import pytest

from rigovo.config_schema import detect_project_config


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

    def test_detect_flask_framework(self, tmp_path):
        """detect_project_config detects Flask framework."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("flask==2.3.0\n")

        config = detect_project_config(tmp_path)

        assert config.project.framework == "flask"


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
