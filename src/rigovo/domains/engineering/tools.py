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
    "planner": [
        "read_file",
        "list_directory",
        "search_codebase",
        "read_dependencies",
        "get_component_map",
        "get_impact_radius",
        "probe_environment",
        "consult_agent",
        "invoke_integration",
    ],
    "coder": [
        "read_file",
        "write_file",
        "list_directory",
        "search_codebase",
        "run_command",
        "read_dependencies",
        "get_component_map",
        "get_impact_radius",
        "probe_environment",
        "spawn_subtask",
        "consult_agent",
    ],
    "reviewer": [
        "read_file",
        "list_directory",
        "search_codebase",
        "get_component_map",
        "get_impact_radius",
        "probe_environment",
        "consult_agent",
    ],
    "security": [
        "read_file",
        "search_codebase",
        "run_command",
        "get_component_map",
        "get_impact_radius",
        "probe_environment",
        "consult_agent",
        "invoke_integration",
    ],
    "qa": [
        "read_file",
        "write_file",
        "list_directory",
        "search_codebase",
        "run_command",
        "get_component_map",
        "get_impact_radius",
        "probe_environment",
        "consult_agent",
    ],
    "devops": [
        "read_file",
        "write_file",
        "list_directory",
        "run_command",
        "get_impact_radius",
        "consult_agent",
        "invoke_integration",
    ],
    "sre": [
        "read_file",
        "write_file",
        "list_directory",
        "run_command",
        "get_impact_radius",
        "consult_agent",
        "invoke_integration",
    ],
    "lead": [
        "read_file",
        "list_directory",
        "search_codebase",
        "get_component_map",
        "get_impact_radius",
        "probe_environment",
        "consult_agent",
        "invoke_integration",
    ],
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
        "description": (
            "Search for text/regex patterns across the codebase. Returns matching lines."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex supported)."},
                "file_glob": {
                    "type": "string",
                    "description": (
                        "File glob to filter (e.g. '*.ts', '**/*.py'). Default: all files."
                    ),
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
        "description": (
            "Read project dependency files (package.json, pyproject.toml, requirements.txt, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    "spawn_subtask": {
        "name": "spawn_subtask",
        "description": (
            "Spawn a bounded specialist branch to handle an isolated piece of work. "
            "Use this only when the work can merge back cleanly into the parent step. "
            "Provide the specialist role, a narrow assignment, and files that define "
            "the merge boundary. The branch returns implementation and verification "
            "artifacts for the parent agent to merge."
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
                "specialist_role": {
                    "type": "string",
                    "description": (
                        "Canonical specialist role for the branch "
                        "(e.g. coder, qa, reviewer, security, devops, sre, docs)."
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
                "merge_back_contract": {
                    "type": "object",
                    "description": (
                        "Merge-back contract describing what the child branch must return, "
                        "such as expected artifacts or files it owns."
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
                    "description": (
                        "Capability id inside plugin (connector id, mcp server id, action id)."
                    ),
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
    # --- Environment Probing Tools (Code Knowledge Graph) ---
    # These tools give agents STRUCTURAL UNDERSTANDING of the codebase,
    # not just text search. An agent using these tools knows that
    # UserService depends on AuthProvider, that changing models.py
    # affects 12 files, and that the "auth" domain spans 5 files.
    "get_component_map": {
        "name": "get_component_map",
        "description": (
            "Get a map of code components grouped by domain/module. "
            "Shows which files belong to each domain (auth, api, models, etc.) "
            "and their key exported symbols (classes, functions, types). "
            "Use this FIRST to understand the codebase architecture before "
            "reading individual files. Optionally filter by domain name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain_filter": {
                    "type": "string",
                    "description": (
                        "Filter to a specific domain (e.g. 'auth', 'api', 'models'). "
                        "Leave empty to get all domains."
                    ),
                },
            },
        },
    },
    "get_impact_radius": {
        "name": "get_impact_radius",
        "description": (
            "Given a file path, return all files that would be affected by "
            "changes to that file. Shows direct dependents (files that import it), "
            "transitive dependents (files that import the dependents), and "
            "what the file itself depends on. Use this BEFORE modifying any file "
            "to understand the blast radius of your changes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Relative path to the file to analyze (e.g. 'src/auth/provider.py')."
                    ),
                },
                "max_depth": {
                    "type": "integer",
                    "description": (
                        "How many levels of transitive dependencies to follow. Default: 3."
                    ),
                    "default": 3,
                },
            },
            "required": ["file_path"],
        },
    },
    "probe_environment": {
        "name": "probe_environment",
        "description": (
            "Semantic search over the code architecture. Given a concept "
            "(e.g. 'authentication', 'database', 'user management'), returns "
            "all related files, symbols, and connected components. Unlike "
            "search_codebase which finds text matches, this tool understands "
            "RELATIONSHIPS — it finds files in the auth domain PLUS files "
            "that import/depend on auth components. Use this to map out "
            "a feature area before planning or implementing changes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Concept to probe for (e.g. 'authentication', 'payment', "
                        "'database models', 'API routes')."
                    ),
                },
            },
            "required": ["query"],
        },
    },
}
