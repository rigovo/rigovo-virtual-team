"""Engineering domain tool definitions for agent function calling."""

from __future__ import annotations

from typing import Any


def get_engineering_tools(role_id: str) -> list[dict[str, Any]]:
    """
    Return tool definitions available to an engineering agent of a given role.

    These are LLM tool/function-calling definitions, not implementations.
    The implementations live in infrastructure/filesystem.
    """
    role_tools = TOOLS_BY_ROLE.get(role_id, [])
    return [TOOL_DEFINITIONS[t] for t in role_tools if t in TOOL_DEFINITIONS]


# Which tools each role has access to
TOOLS_BY_ROLE: dict[str, list[str]] = {
    "planner": ["read_file", "list_directory", "search_codebase", "read_dependencies"],
    "coder": [
        "read_file", "write_file", "list_directory", "search_codebase",
        "run_command", "read_dependencies",
    ],
    "reviewer": ["read_file", "list_directory", "search_codebase"],
    "security": ["read_file", "search_codebase", "run_command"],
    "qa": ["read_file", "write_file", "list_directory", "search_codebase", "run_command"],
    "devops": ["read_file", "write_file", "list_directory", "run_command"],
    "sre": ["read_file", "write_file", "list_directory", "run_command"],
    "lead": ["read_file", "list_directory", "search_codebase"],
}

# Tool definitions for LLM function calling
TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "read_file": {
        "name": "read_file",
        "description": "Read the contents of a file at the given path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from project root."},
                "start_line": {"type": "integer", "description": "Optional start line number."},
                "end_line": {"type": "integer", "description": "Optional end line number."},
            },
            "required": ["path"],
        },
    },
    "write_file": {
        "name": "write_file",
        "description": "Write content to a file. Creates parent directories if needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from project root."},
                "content": {"type": "string", "description": "Full file content to write."},
            },
            "required": ["path", "content"],
        },
    },
    "list_directory": {
        "name": "list_directory",
        "description": "List files and directories at a path. Returns names with type indicators.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from project root. Default: '.'",
                    "default": ".",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list recursively. Default: false",
                    "default": False,
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Max recursion depth. Default: 3",
                    "default": 3,
                },
            },
        },
    },
    "search_codebase": {
        "name": "search_codebase",
        "description": "Search for text/regex patterns across the codebase. Returns matching lines.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex supported)."},
                "file_glob": {
                    "type": "string",
                    "description": "File glob to filter (e.g. '*.ts', '**/*.py'). Default: all files.",
                },
                "max_results": {"type": "integer", "description": "Max results. Default: 50."},
            },
            "required": ["pattern"],
        },
    },
    "run_command": {
        "name": "run_command",
        "description": "Run a shell command in the project root. Use for tests, builds, linting.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute (e.g. 'npm test', 'pytest').",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Command timeout. Default: 60.",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
    },
    "read_dependencies": {
        "name": "read_dependencies",
        "description": "Read project dependency files (package.json, pyproject.toml, requirements.txt, etc.).",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}
