"""Project auto-detection — infer stack, framework, test runner, and conventions.

Called by `rigovo init` to generate smart defaults for rigovo.yml.
Detects: language, framework, test runner, package manager, monorepo,
source/test directories.
"""

from __future__ import annotations

import json
from pathlib import Path


def detect_project_name(root: Path, language: str) -> str:
    """Extract project name from manifest files.

    Tries manifest files in order: package.json, pyproject.toml, Cargo.toml.
    Falls back to directory name if no manifest is found.

    Args:
        root: Project root directory path.
        language: Detected language (unused, kept for consistency).

    Returns:
        Project name from manifest, or directory name as fallback.
    """
    # Try Node.js package.json first
    if (root / "package.json").is_file():
        try:
            pkg = json.loads((root / "package.json").read_text())
            return pkg.get("name", root.name)
        except (json.JSONDecodeError, OSError):
            pass

    # Try Python pyproject.toml
    if (root / "pyproject.toml").is_file():
        try:
            content = (root / "pyproject.toml").read_text()
            for line in content.splitlines():
                if line.strip().startswith("name"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except (OSError, IndexError):
            pass

    # Try Rust Cargo.toml
    if (root / "Cargo.toml").is_file():
        try:
            content = (root / "Cargo.toml").read_text()
            for line in content.splitlines():
                if line.strip().startswith("name"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except (OSError, IndexError):
            pass

    # Fallback: use directory name
    return root.name


def detect_framework(root: Path, language: str) -> str:
    """Detect the primary framework for the detected language.

    Searches dependency files in order of framework popularity.
    Returns the first matching framework, or empty string if none detected.

    Args:
        root: Project root directory path.
        language: Detected language.

    Returns:
        Framework name (lowercase), or empty string.
    """
    # JavaScript/TypeScript frameworks
    if language in ("javascript", "typescript"):
        if (root / "package.json").is_file():
            try:
                pkg = json.loads((root / "package.json").read_text())
                deps = {
                    **pkg.get("dependencies", {}),
                    **pkg.get("devDependencies", {}),
                }

                # Framework detection priority (first match wins)
                fw_map = [
                    ("next", "nextjs"),
                    ("nuxt", "nuxt"),
                    ("@angular/core", "angular"),
                    ("svelte", "svelte"),
                    ("vue", "vue"),
                    ("react", "react"),
                    ("express", "express"),
                    ("fastify", "fastify"),
                    ("hono", "hono"),
                    ("@nestjs/core", "nestjs"),
                    ("koa", "koa"),
                ]
                for dep, name in fw_map:
                    if dep in deps:
                        return name
            except (json.JSONDecodeError, OSError):
                pass

    # Python frameworks
    if language == "python":
        for depfile in ("pyproject.toml", "requirements.txt"):
            if (root / depfile).is_file():
                try:
                    content = (root / depfile).read_text().lower()
                    fw_map = [
                        ("fastapi", "fastapi"),
                        ("django", "django"),
                        ("flask", "flask"),
                        ("starlette", "starlette"),
                        ("tornado", "tornado"),
                        ("aiohttp", "aiohttp"),
                        ("litestar", "litestar"),
                    ]
                    for dep, name in fw_map:
                        if dep in content:
                            return name
                except OSError:
                    pass

    # Rust frameworks
    if language == "rust":
        if (root / "Cargo.toml").is_file():
            try:
                content = (root / "Cargo.toml").read_text().lower()
                if "actix" in content:
                    return "actix"
                if "axum" in content:
                    return "axum"
                if "rocket" in content:
                    return "rocket"
            except OSError:
                pass

    # Go frameworks
    if language == "go":
        if (root / "go.mod").is_file():
            try:
                content = (root / "go.mod").read_text().lower()
                if "gin-gonic" in content:
                    return "gin"
                if "fiber" in content:
                    return "fiber"
                if "echo" in content:
                    return "echo"
            except OSError:
                pass

    return ""


def detect_test_framework(root: Path, language: str) -> str:
    """Detect the test runner for the detected language.

    Args:
        root: Project root directory path.
        language: Detected language.

    Returns:
        Test framework name (lowercase), or empty string.
    """
    # JavaScript/TypeScript test runners
    if language in ("javascript", "typescript"):
        if (root / "package.json").is_file():
            try:
                pkg = json.loads((root / "package.json").read_text())
                deps = {
                    **pkg.get("dependencies", {}),
                    **pkg.get("devDependencies", {}),
                }
                if "vitest" in deps:
                    return "vitest"
                if "jest" in deps or "@jest/core" in deps:
                    return "jest"
                if "mocha" in deps:
                    return "mocha"
                if "playwright" in deps or "@playwright/test" in deps:
                    return "playwright"
            except (json.JSONDecodeError, OSError):
                pass

    # Python test runners
    if language == "python":
        for depfile in ("pyproject.toml", "requirements.txt"):
            if (root / depfile).is_file():
                try:
                    content = (root / depfile).read_text().lower()
                    if "pytest" in content:
                        return "pytest"
                    if "unittest" in content:
                        return "unittest"
                except OSError:
                    pass

    # Rust uses cargo test (built-in)
    if language == "rust":
        return "cargo-test"

    # Go uses go test (built-in)
    if language == "go":
        return "go-test"

    return ""


def detect_monorepo(root: Path) -> bool:
    """Check if the project is a monorepo.

    Args:
        root: Project root directory path.

    Returns:
        True if monorepo indicators found, False otherwise.
    """
    # Check for explicit monorepo tool configs
    indicators = [
        "lerna.json",
        "nx.json",
        "turbo.json",
        "pnpm-workspace.yaml",
        "rush.json",
    ]
    if any((root / f).is_file() for f in indicators):
        return True

    # Check for workspaces in package.json (npm/yarn workspaces)
    if (root / "package.json").is_file():
        try:
            pkg = json.loads((root / "package.json").read_text())
            if "workspaces" in pkg:
                return True
        except (json.JSONDecodeError, OSError):
            pass

    # Check for multiple packages with their own package.json
    try:
        dirs_with_pkg = sum(
            1
            for d in (root / "packages").iterdir()
            if d.is_dir() and (d / "package.json").is_file()
        ) if (root / "packages").is_dir() else 0
        return dirs_with_pkg > 1
    except OSError:
        return False


def detect_source_dir(root: Path, language: str) -> str:
    """Find the conventional source directory.

    Args:
        root: Project root directory path.
        language: Detected language (unused, kept for consistency).

    Returns:
        Source directory name.
    """
    candidates = ["src", "lib", "app", "source"]
    for c in candidates:
        if (root / c).is_dir():
            return c
    return "src"


def detect_test_dir(root: Path, language: str) -> str:
    """Find the conventional test directory.

    Args:
        root: Project root directory path.
        language: Detected language.

    Returns:
        Test directory name.
    """
    candidates = ["tests", "test", "__tests__", "spec", "specs"]
    for c in candidates:
        if (root / c).is_dir():
            return c

    # Language-specific defaults
    if language in ("javascript", "typescript"):
        return "__tests__"
    return "tests"


def detect_language_and_package_manager(
    root: Path,
) -> tuple[str, str]:
    """Detect primary language and package manager from project files.

    Args:
        root: Project root directory path.

    Returns:
        Tuple of (language, package_manager). Either may be empty string.
    """
    language = ""
    package_manager = ""

    lang_indicators = [
        ("pyproject.toml", "python", "poetry"),
        ("requirements.txt", "python", "pip"),
        ("Pipfile", "python", "pipenv"),
        ("setup.py", "python", "setuptools"),
        ("tsconfig.json", "typescript", ""),
        ("package.json", "javascript", ""),
        ("Cargo.toml", "rust", "cargo"),
        ("go.mod", "go", "go"),
        ("Gemfile", "ruby", "bundler"),
        ("pom.xml", "java", "maven"),
        ("build.gradle", "java", "gradle"),
        ("composer.json", "php", "composer"),
        ("mix.exs", "elixir", "mix"),
    ]

    for filename, lang, pkg_mgr in lang_indicators:
        if (root / filename).is_file():
            if not language:
                language = lang
            if pkg_mgr and not package_manager:
                package_manager = pkg_mgr
            break

    # JS/TS package manager detection
    if language in ("javascript", "typescript"):
        if (root / "pnpm-lock.yaml").is_file():
            package_manager = "pnpm"
        elif (root / "yarn.lock").is_file():
            package_manager = "yarn"
        elif (root / "bun.lockb").is_file():
            package_manager = "bun"
        else:
            package_manager = "npm"

    return language, package_manager
