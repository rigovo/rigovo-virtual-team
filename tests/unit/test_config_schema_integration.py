"""Integration tests for realistic project scenarios."""

import json

import pytest

from rigovo.config_schema import detect_project_config


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
