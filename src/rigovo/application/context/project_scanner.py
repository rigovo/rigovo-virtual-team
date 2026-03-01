"""Project scanner — reads the codebase before agents act.

This is the PERCEPTION layer. Before any agent executes, the scanner
reads the project structure, identifies key files, detects the tech
stack, and builds a snapshot that gets injected into agent context.

A chatbot guesses. An intelligent agent READS FIRST.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Scan limits to prevent blowup on huge repos ---
MAX_TREE_DEPTH = 4

# Minimum source files to consider a project "existing" (has established patterns)
NEW_PROJECT_SOURCE_FILE_THRESHOLD = 5

# Files that indicate this is Rigovo's own installation directory — self-scan guard
_RIGOVO_FOOTPRINT = {"rigovo.yml", "rigovo.yaml"}
_RIGOVO_SRC_PACKAGE = "rigovo"
MAX_FILES_IN_TREE = 500
MAX_KEY_FILE_SIZE_BYTES = 50_000  # 50KB — enough for most source files
MAX_KEY_FILES_TO_READ = 10
TRUNCATION_SUFFIX = "\n... (truncated)"

# Files that reveal project architecture (sorted by priority)
ARCHITECTURE_FILES = [
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Makefile",
    "CMakeLists.txt",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "rigovo.yml",
    "rigovo.yaml",
    ".rigour.yml",
    "rigour.yml",
    "tsconfig.json",
    "setup.py",
    "setup.cfg",
]

# Directories to always skip
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
    ".next",
    ".nuxt",
    "coverage",
    "htmlcov",
    ".terraform",
    ".serverless",
}

# Extensions that indicate source code
SOURCE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".swift",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".sql",
    ".sh",
    ".bash",
}


@dataclass
class ProjectSnapshot:
    """Immutable snapshot of a project's structure and key content.

    This is what agents SEE before they act — their perception
    of the codebase at task start time.
    """

    root: str
    tree: str  # ASCII file tree
    tech_stack: list[str]  # ["Python 3.11", "FastAPI", "SQLite"]
    key_file_contents: dict[str, str]  # {path: content} for architecture files
    source_file_count: int
    total_file_count: int
    entry_points: list[str]  # ["src/main.py", "app/index.ts"]
    test_directories: list[str]  # ["tests/", "spec/"]
    workspace_type: str = field(default="existing_project")  # new_project | existing_project
    is_rigovo_self: bool = field(default=False)  # True if scanning Rigovo's own directory

    def to_context_section(self) -> str:
        """Render as a context section for injection into agent prompts."""
        parts = ["--- PROJECT CONTEXT (scanned at task start) ---"]

        # Workspace type — critical for agents to know whether to match patterns
        # or build from scratch
        if self.workspace_type == "new_project":
            parts.append(
                "\n⚠️  WORKSPACE TYPE: NEW PROJECT\n"
                "This is a blank or nearly-blank workspace. There are no established\n"
                "patterns to follow. You must create the full project structure from\n"
                "scratch. Choose sensible defaults for the tech stack and layout."
            )
        else:
            parts.append(
                "\nWORKSPACE TYPE: EXISTING PROJECT\n"
                "This workspace has an established codebase. Match the existing code\n"
                "style, naming conventions, directory structure, and tech stack.\n"
                "Do NOT introduce new frameworks or patterns unless the plan says to."
            )

        # Rigovo self-scan guard — prevents agents from applying Rigovo's own
        # patterns to user tasks when run from Rigovo's installation directory
        if self.is_rigovo_self:
            parts.append(
                "\n⛔ WORKSPACE GUARD: This appears to be the Rigovo installation directory.\n"
                "The files you see (rigovo.yml, src/rigovo/, pyproject.toml, etc.) are\n"
                "Rigovo's OWN source code — NOT the user's project. Do NOT apply Rigovo's\n"
                "internal patterns (LangGraph, FastAPI, SQLite) to the user's task.\n"
                "The user's target workspace should be mounted separately via --project."
            )

        parts.append(
            f"\nProject root: {self.root}"
            f"\nSource files: {self.source_file_count} | Total: {self.total_file_count}"
        )

        if self.tech_stack:
            parts.append(f"Tech stack: {', '.join(self.tech_stack)}")

        if self.entry_points:
            parts.append(f"Entry points: {', '.join(self.entry_points)}")

        if self.test_directories:
            parts.append(f"Test dirs: {', '.join(self.test_directories)}")

        parts.append(f"\nFile tree:\n{self.tree}")

        if self.key_file_contents:
            parts.append("\n--- KEY FILES ---")
            for path, content in self.key_file_contents.items():
                parts.append(f"\n[{path}]:\n{content}")

        return "\n".join(parts)


class ProjectScanner:
    """Scans a project directory and produces a snapshot.

    This runs ONCE at task start — not per agent. The snapshot
    is shared across all agents in the pipeline.
    """

    def scan(self, project_root: str) -> ProjectSnapshot:
        """Scan the project and return an immutable snapshot."""
        root = Path(project_root)
        if not root.is_dir():
            return self._empty_snapshot(project_root)

        tree_lines, source_count, total_count = self._build_tree(root)
        tech_stack = self._detect_tech_stack(root)
        key_contents = self._read_key_files(root)
        entry_points = self._find_entry_points(root)
        test_dirs = self._find_test_directories(root)

        workspace_type = self._classify_workspace(root, source_count)
        is_rigovo_self = self._detect_rigovo_self(root)

        return ProjectSnapshot(
            root=project_root,
            tree="\n".join(tree_lines),
            tech_stack=tech_stack,
            key_file_contents=key_contents,
            source_file_count=source_count,
            total_file_count=total_count,
            entry_points=entry_points,
            test_directories=test_dirs,
            workspace_type=workspace_type,
            is_rigovo_self=is_rigovo_self,
        )

    def _classify_workspace(self, root: Path, source_count: int) -> str:
        """Classify workspace as new_project or existing_project.

        A project is considered NEW if it has fewer than threshold source files.
        This controls whether agents build from scratch or match existing patterns.
        """
        if source_count < NEW_PROJECT_SOURCE_FILE_THRESHOLD:
            return "new_project"
        return "existing_project"

    def _detect_rigovo_self(self, root: Path) -> bool:
        """Detect if the scanned root is Rigovo's own installation directory.

        When someone runs `rigovo run ...` from the Rigovo repo itself, the
        scanner sees Rigovo's own code. This guard prevents agents from
        applying Rigovo's internal patterns to the user's task.
        """
        # Check for Rigovo footprint files at the root
        has_rigovo_yml = any((root / f).is_file() for f in _RIGOVO_FOOTPRINT)
        # Check for Rigovo source package directory
        has_rigovo_src = (root / "src" / _RIGOVO_SRC_PACKAGE).is_dir()
        return has_rigovo_yml and has_rigovo_src

    def _build_tree(
        self,
        root: Path,
        depth: int = 0,
    ) -> tuple[list[str], int, int]:
        """Build ASCII file tree with depth limit."""
        lines: list[str] = []
        source_count = 0
        total_count = 0

        if depth > MAX_TREE_DEPTH:
            return lines, source_count, total_count

        try:
            entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            return lines, source_count, total_count

        indent = "  " * depth
        for entry in entries:
            if entry.name in SKIP_DIRS:
                continue
            if entry.name.startswith(".") and depth == 0 and entry.is_dir():
                continue  # Skip hidden dirs at root

            total_count += 1
            if len(lines) >= MAX_FILES_IN_TREE:
                lines.append(f"{indent}... ({total_count}+ files)")
                break

            if entry.is_dir():
                lines.append(f"{indent}{entry.name}/")
                sub_lines, sub_src, sub_total = self._build_tree(entry, depth + 1)
                lines.extend(sub_lines)
                source_count += sub_src
                total_count += sub_total
            else:
                lines.append(f"{indent}{entry.name}")
                if entry.suffix in SOURCE_EXTENSIONS:
                    source_count += 1

        return lines, source_count, total_count

    def _detect_tech_stack(self, root: Path) -> list[str]:
        """Detect technologies used in the project."""
        stack: list[str] = []

        indicators = {
            "pyproject.toml": "Python",
            "setup.py": "Python",
            "requirements.txt": "Python",
            "package.json": "Node.js",
            "tsconfig.json": "TypeScript",
            "Cargo.toml": "Rust",
            "go.mod": "Go",
            "pom.xml": "Java (Maven)",
            "build.gradle": "Java (Gradle)",
            "Gemfile": "Ruby",
            "composer.json": "PHP",
            "Dockerfile": "Docker",
            "docker-compose.yml": "Docker Compose",
            "terraform.tf": "Terraform",
            ".github/workflows": "GitHub Actions",
        }

        for indicator, tech in indicators.items():
            path = root / indicator
            if path.exists():
                stack.append(tech)

        return stack

    def _read_key_files(self, root: Path) -> dict[str, str]:
        """Read architecture files that reveal project structure."""
        contents: dict[str, str] = {}
        read_count = 0

        for filename in ARCHITECTURE_FILES:
            if read_count >= MAX_KEY_FILES_TO_READ:
                break

            path = root / filename
            if not path.is_file():
                continue

            try:
                size = path.stat().st_size
                if size > MAX_KEY_FILE_SIZE_BYTES:
                    text = path.read_text(encoding="utf-8", errors="replace")[
                        :MAX_KEY_FILE_SIZE_BYTES
                    ]
                    text += TRUNCATION_SUFFIX
                else:
                    text = path.read_text(encoding="utf-8", errors="replace")

                contents[filename] = text
                read_count += 1

            except (OSError, UnicodeDecodeError) as exc:
                logger.debug("Skipping %s: %s", filename, exc)

        return contents

    def _find_entry_points(self, root: Path) -> list[str]:
        """Find likely entry points (main files, index files)."""
        candidates = [
            "src/main.py",
            "src/app.py",
            "main.py",
            "app.py",
            "src/index.ts",
            "src/index.js",
            "index.ts",
            "index.js",
            "src/server.ts",
            "src/server.js",
            "cmd/main.go",
            "main.go",
            "src/main.rs",
            "src/lib.rs",
        ]
        return [c for c in candidates if (root / c).is_file()]

    def _find_test_directories(self, root: Path) -> list[str]:
        """Find test directories."""
        candidates = ["tests", "test", "spec", "__tests__", "src/tests", "src/test"]
        return [c + "/" for c in candidates if (root / c).is_dir()]

    def _empty_snapshot(self, project_root: str) -> ProjectSnapshot:
        """Return empty snapshot for invalid roots."""
        return ProjectSnapshot(
            root=project_root,
            tree="(project root not found)",
            tech_stack=[],
            key_file_contents={},
            source_file_count=0,
            total_file_count=0,
            entry_points=[],
            test_directories=[],
        )
