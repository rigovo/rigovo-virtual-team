"""Project reader — reads project structure, files, and metadata."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Files that indicate project tech stack
DEPENDENCY_FILES = [
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "composer.json",
    "mix.exs",
    "CMakeLists.txt",
    "Makefile",
]

# Directories to skip during search
SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".rigovo",
    ".rigour",
    "target",
    "vendor",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "coverage",
    "htmlcov",
    ".eggs",
}

# Max file size to read (1MB)
MAX_FILE_SIZE = 1_048_576


class ProjectReader:
    """
    Reads project files and structure for agent tool calls.

    All file operations are sandboxed to the project root.
    No path traversal allowed.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()

    def _safe_path(self, relative_path: str) -> Path:
        """Resolve and validate a path is within the project root."""
        resolved = (self._root / relative_path).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise PermissionError(f"Path traversal detected: {relative_path} escapes project root")
        return resolved

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        """Read a file's contents. Returns {path, content, lines, size}."""
        safe = self._safe_path(path)
        if not safe.is_file():
            return {"error": f"File not found: {path}"}
        if safe.stat().st_size > MAX_FILE_SIZE:
            return {"error": f"File too large: {safe.stat().st_size} bytes (max {MAX_FILE_SIZE})"}

        try:
            content = safe.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": f"Cannot read file: {e}"}

        lines = content.splitlines()
        if start_line is not None or end_line is not None:
            start = (start_line or 1) - 1
            end = end_line or len(lines)
            lines = lines[start:end]
            content = "\n".join(lines)

        return {
            "path": path,
            "content": content,
            "lines": len(lines),
            "size": safe.stat().st_size,
        }

    def list_directory(
        self,
        path: str = ".",
        recursive: bool = False,
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """List directory contents. Returns {path, entries: [{name, type, size}]}."""
        safe = self._safe_path(path)
        if not safe.is_dir():
            return {"error": f"Not a directory: {path}"}

        entries: list[dict[str, Any]] = []
        self._collect_entries(safe, entries, recursive, max_depth, 0)

        return {"path": path, "entries": entries, "total": len(entries)}

    def _collect_entries(
        self,
        directory: Path,
        entries: list[dict[str, Any]],
        recursive: bool,
        max_depth: int,
        current_depth: int,
    ) -> None:
        if current_depth > max_depth:
            return

        try:
            for item in sorted(directory.iterdir()):
                if item.name.startswith(".") and item.name not in (".env.example",):
                    continue
                if item.name in SKIP_DIRS:
                    continue

                relative = str(item.relative_to(self._root))
                entry: dict[str, Any] = {"name": relative}

                if item.is_dir():
                    entry["type"] = "directory"
                    entries.append(entry)
                    if recursive and current_depth < max_depth:
                        self._collect_entries(
                            item, entries, recursive, max_depth, current_depth + 1
                        )
                else:
                    entry["type"] = "file"
                    entry["size"] = item.stat().st_size
                    entries.append(entry)

                if len(entries) > 500:
                    return
        except PermissionError:
            pass

    def search_codebase(
        self,
        pattern: str,
        file_glob: str | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """
        Search for a regex pattern across all project source files.

        Walks the file tree respecting SKIP_DIRS and MAX_FILE_SIZE limits.
        Returns matches with file path, line number, and truncated content.

        Args:
            pattern: Regex pattern to search for (case-insensitive).
            file_glob: Optional glob to filter which files to search.
            max_results: Cap on returned matches to avoid huge payloads.

        Returns:
            Dict with 'pattern', 'matches' list, and 'truncated' boolean.
        """
        import re

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return {"error": f"Invalid regex: {e}"}

        matches: list[dict[str, Any]] = []
        glob_pattern = file_glob or "**/*"

        for filepath in self._root.glob(glob_pattern):
            if not filepath.is_file():
                continue
            if any(skip in filepath.parts for skip in SKIP_DIRS):
                continue
            if filepath.stat().st_size > MAX_FILE_SIZE:
                continue

            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                # Skip files that can't be read (permissions, encoding issues)
                continue

            for i, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    matches.append(
                        {
                            "file": str(filepath.relative_to(self._root)),
                            "line": i,
                            "content": line.strip()[:200],
                        }
                    )
                    if len(matches) >= max_results:
                        return {"pattern": pattern, "matches": matches, "truncated": True}

        return {"pattern": pattern, "matches": matches, "truncated": False}

    def read_dependencies(self) -> dict[str, Any]:
        """Read all dependency files to understand tech stack."""
        found: dict[str, str] = {}
        for filename in DEPENDENCY_FILES:
            filepath = self._root / filename
            if filepath.is_file():
                try:
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                    found[filename] = content[:5000]  # Truncate large lock files
                except (OSError, UnicodeDecodeError):
                    # Mark files that can't be read due to permissions or encoding
                    found[filename] = "<unreadable>"

        return {"project_root": str(self._root), "dependency_files": found}

    def detect_tech_stack(self) -> dict[str, Any]:
        """
        Auto-detect the project's technology stack from manifest files.

        Checks for known config files (package.json, pyproject.toml, Cargo.toml,
        go.mod, etc.) and infers languages, frameworks, and build tools.

        Returns:
            Dict with 'languages', 'frameworks', and 'build_tools' lists.
        """
        stack: dict[str, Any] = {"languages": [], "frameworks": [], "build_tools": []}

        checks = [
            ("package.json", "javascript", "node"),
            ("tsconfig.json", "typescript", "node"),
            ("pyproject.toml", "python", "python"),
            ("requirements.txt", "python", "python"),
            ("Cargo.toml", "rust", "cargo"),
            ("go.mod", "go", "go"),
            ("Gemfile", "ruby", "bundler"),
            ("pom.xml", "java", "maven"),
            ("build.gradle", "java", "gradle"),
        ]

        for filename, lang, tool in checks:
            if (self._root / filename).is_file():
                if lang not in stack["languages"]:
                    stack["languages"].append(lang)
                if tool not in stack["build_tools"]:
                    stack["build_tools"].append(tool)

        # Framework detection from package.json
        pkg_json = self._root / "package.json"
        if pkg_json.is_file():
            import json

            try:
                pkg = json.loads(pkg_json.read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                framework_checks = [
                    ("next", "Next.js"),
                    ("react", "React"),
                    ("vue", "Vue"),
                    ("express", "Express"),
                    ("fastify", "Fastify"),
                    ("@angular/core", "Angular"),
                    ("svelte", "Svelte"),
                ]
                for dep, name in framework_checks:
                    if dep in deps:
                        stack["frameworks"].append(name)
            except (json.JSONDecodeError, OSError, KeyError):
                # Skip malformed or unreadable package.json files
                pass

        return stack
