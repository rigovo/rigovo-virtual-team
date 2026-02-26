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
    "planner": ["read_file", "list_directory", "search_codebase", "read_dependencies", "consult_agent", "invoke_integration"],
    "coder": [
        "read_file", "write_file", "list_directory", "search_codebase",
        "run_command", "read_dependencies", "spawn_subtask", "consult_agent",
    ],
    "reviewer": ["read_file", "list_directory", "search_codebase", "consult_agent"],
    "security": ["read_file", "search_codebase", "run_command", "consult_agent", "invoke_integration"],
    "qa": ["read_file", "write_file", "list_directory", "search_codebase", "run_command", "consult_agent"],
    "devops": ["read_file", "write_file", "list_directory", "run_command", "consult_agent", "invoke_integration"],
    "sre": ["read_file", "write_file", "list_directory", "run_command", "consult_agent", "invoke_integration"],
    "lead": ["read_file", "list_directory", "search_codebase", "consult_agent", "invoke_integration"],
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
    "spawn_subtask": {
        "name": "spawn_subtask",
        "description": (
            "Spawn a sub-agent to handle a specific subtask in parallel. "
            "Use this when a task can be decomposed into independent pieces. "
            "For example, 'implement auth module' and 'add API endpoint' can "
            "run as separate sub-agents simultaneously. Each sub-agent has "
            "full access to read_file, write_file, search_codebase, and "
            "run_command. Returns the sub-agent's output when complete."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": (
                        "Clear description of the subtask. Be specific about "
                        "which files to create/modify and what the expected outcome is."
                    ),
                },
                "files_context": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of file paths the sub-agent should read for context "
                        "before starting work."
                    ),
                },
            },
            "required": ["description"],
        },
    },
    "consult_agent": {
        "name": "consult_agent",
        "description": (
            "Request targeted input from another agent role in the same task thread. "
            "If that role already produced output, returns it immediately. "
            "Otherwise queues a pending consult request that is auto-answered "
            "when the target role executes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to_role": {
                    "type": "string",
                    "description": "Target role to consult (e.g. reviewer, security, devops).",
                },
                "question": {
                    "type": "string",
                    "description": "Specific question for that role.",
                },
            },
            "required": ["to_role", "question"],
        },
    },
    "invoke_integration": {
        "name": "invoke_integration",
        "description": (
            "Invoke a trusted plugin capability (connector, MCP server, or action). "
            "Execution is policy-gated by trust level and enabled plugin allow-lists."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "One of: connector|mcp|action.",
                },
                "plugin_id": {
                    "type": "string",
                    "description": "Plugin manifest id exposing the capability.",
                },
                "target_id": {
                    "type": "string",
                    "description": "Capability id inside plugin (connector id, mcp server id, action id).",
                },
                "operation": {
                    "type": "string",
                    "description": "Operation name (e.g. post_message, query, run).",
                },
                "payload": {
                    "type": "object",
                    "description": "Structured input payload for the operation.",
                },
            },
            "required": ["kind", "plugin_id", "target_id", "operation"],
        },
    },
}
