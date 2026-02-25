"""Tests for ProjectScanner — verifying codebase perception."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from rigovo.application.context.project_scanner import (
    ProjectScanner,
    ProjectSnapshot,
    MAX_TREE_DEPTH,
    MAX_FILES_IN_TREE,
    ARCHITECTURE_FILES,
)


@pytest.fixture
def scanner() -> ProjectScanner:
    return ProjectScanner()


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a realistic project structure."""
    # Source files
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("def main():\n    pass\n")
    (src / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (src / "utils.py").write_text("def helper():\n    return 42\n")

    # Test directory
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_main():\n    assert True\n")

    # Config files
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "myapp"\n')
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
    (tmp_path / "rigovo.yml").write_text("domain: engineering\n")

    # Git directory (should be skipped)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("bare = false\n")

    # Node modules (should be skipped)
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "package.json").write_text("{}")

    return tmp_path


class TestProjectScannerBasic:
    """Test basic scanning functionality."""

    def test_scan_returns_snapshot(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert isinstance(snapshot, ProjectSnapshot)
        assert snapshot.root == str(sample_project)

    def test_scan_detects_tech_stack(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert "Python" in snapshot.tech_stack
        assert "Docker" in snapshot.tech_stack

    def test_scan_finds_source_files(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert snapshot.source_file_count >= 4  # main.py, app.py, utils.py, test_main.py

    def test_scan_finds_entry_points(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert "src/main.py" in snapshot.entry_points

    def test_scan_finds_test_directories(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert "tests/" in snapshot.test_directories


class TestProjectScannerTreeBuilding:
    """Test file tree generation."""

    def test_tree_excludes_git(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert ".git" not in snapshot.tree

    def test_tree_excludes_node_modules(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert "node_modules" not in snapshot.tree

    def test_tree_includes_source_dirs(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert "src/" in snapshot.tree

    def test_tree_includes_files(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert "main.py" in snapshot.tree


class TestProjectScannerKeyFiles:
    """Test key file reading."""

    def test_reads_pyproject_toml(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert "pyproject.toml" in snapshot.key_file_contents
        assert "myapp" in snapshot.key_file_contents["pyproject.toml"]

    def test_reads_dockerfile(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert "Dockerfile" in snapshot.key_file_contents

    def test_reads_rigovo_yml(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        assert "rigovo.yml" in snapshot.key_file_contents


class TestProjectScannerEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_root_returns_empty(self, scanner: ProjectScanner) -> None:
        snapshot = scanner.scan("/nonexistent/path/12345")
        assert snapshot.source_file_count == 0
        assert snapshot.total_file_count == 0
        assert snapshot.tech_stack == []

    def test_empty_directory(self, scanner: ProjectScanner, tmp_path: Path) -> None:
        snapshot = scanner.scan(str(tmp_path))
        assert snapshot.source_file_count == 0
        assert snapshot.total_file_count == 0

    def test_context_section_renders(
        self, scanner: ProjectScanner, sample_project: Path,
    ) -> None:
        snapshot = scanner.scan(str(sample_project))
        context = snapshot.to_context_section()
        assert "PROJECT CONTEXT" in context
        assert "Tech stack" in context
        assert "File tree" in context
        assert "KEY FILES" in context
