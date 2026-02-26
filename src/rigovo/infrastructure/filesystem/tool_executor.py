"""Tool executor — dispatches LLM tool calls to actual implementations."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from rigovo.infrastructure.filesystem.project_reader import ProjectReader
from rigovo.infrastructure.filesystem.code_writer import CodeWriter
from rigovo.infrastructure.filesystem.command_runner import CommandRunner

logger = logging.getLogger(__name__)

# Maximum characters in a tool result before truncation.
# Prevents 50KB+ file reads from blowing up context windows.
MAX_TOOL_RESULT_CHARS = 30_000
MAX_INTEGRATION_PAYLOAD_CHARS = 20_000
OPERATION_PATTERN = re.compile(r"^[a-zA-Z0-9_.:-]{1,64}$")


def _truncate_result(result_str: str) -> str:
    """Truncate tool result if it exceeds MAX_TOOL_RESULT_CHARS."""
    if len(result_str) <= MAX_TOOL_RESULT_CHARS:
        return result_str
    truncated = result_str[:MAX_TOOL_RESULT_CHARS]
    return truncated + f"\n... [truncated, {len(result_str):,} chars total]"


class ToolExecutor:
    """
    Executes agent tool calls against the local filesystem.

    Maps tool names to implementations. Called by the execute_agent node
    when the LLM returns tool_use responses.

    This is the bridge between LLM function calling and actual I/O.
    """

    TRUST_LEVEL_ORDER = {
        "community": 0,
        "verified": 1,
        "internal": 2,
    }

    def __init__(
        self,
        project_root: Path,
        integration_catalog: dict[str, Any] | None = None,
        integration_policy: dict[str, Any] | None = None,
        worktree_mode: str = "project",
        worktree_root: str = "",
        filesystem_sandbox_mode: str = "project_root",
    ) -> None:
        self._integration_catalog = integration_catalog or {}
        self._integration_policy = integration_policy or {}
        self._project_root = project_root.resolve()
        self._worktree_mode = str(worktree_mode or "project").strip().lower()
        self._worktree_root = str(worktree_root or "").strip()
        self._filesystem_sandbox_mode = str(filesystem_sandbox_mode or "project_root").strip().lower()
        self._execution_root = self._resolve_execution_root()
        allowed_commands = set(self._integration_policy.get("allowed_shell_commands", []) or [])

        self._reader = ProjectReader(self._execution_root)
        self._writer = CodeWriter(self._execution_root)
        self._runner = CommandRunner(self._execution_root, allowed_commands=allowed_commands or None)

        self._handlers: dict[str, Any] = {
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "list_directory": self._handle_list_directory,
            "search_codebase": self._handle_search_codebase,
            "run_command": self._handle_run_command,
            "read_dependencies": self._handle_read_dependencies,
            "invoke_integration": self._handle_invoke_integration,
        }

    def _resolve_execution_root(self) -> Path:
        """Resolve effective filesystem sandbox root based on worktree policy."""
        if self._filesystem_sandbox_mode not in {"project_root", "worktree"}:
            raise ValueError(
                f"Invalid filesystem_sandbox_mode '{self._filesystem_sandbox_mode}'"
            )
        if self._worktree_mode not in {"project", "git_worktree"}:
            raise ValueError(f"Invalid worktree_mode '{self._worktree_mode}'")

        if self._filesystem_sandbox_mode == "project_root" or self._worktree_mode == "project":
            return self._project_root

        # worktree sandbox requested
        if not self._worktree_root:
            raise ValueError("worktree_root is required when using git_worktree mode")
        candidate = Path(self._worktree_root).expanduser().resolve()
        try:
            candidate.relative_to(self._project_root)
        except ValueError as exc:
            raise PermissionError(
                "worktree_root must stay within project_root sandbox"
            ) from exc
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"Configured worktree_root does not exist: {candidate}")
        return candidate

    async def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """
        Execute a tool call and return the result as a string.

        Args:
            tool_name: The tool to call (e.g., "read_file").
            tool_input: The parameters from the LLM.

        Returns:
            JSON string result for feeding back to the LLM.
        """
        await asyncio.sleep(0)
        handler = self._handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        try:
            result = handler(tool_input)
            result_str = json.dumps(result, default=str)
            return _truncate_result(result_str)
        except Exception as e:
            logger.exception("Tool execution error: %s", tool_name)
            return json.dumps({"error": f"Tool execution failed: {e}"})

    def execute_batch(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute multiple tool calls sequentially. Returns results in order."""
        results = []
        files_changed: list[str] = []

        for call in tool_calls:
            name = call.get("name", "")
            inputs = call.get("input", {})

            handler = self._handlers.get(name)
            if not handler:
                results.append({"tool": name, "error": f"Unknown tool: {name}"})
                continue

            try:
                result = handler(inputs)
                results.append({"tool": name, "result": result})

                # Track file changes
                if name == "write_file" and "path" in result:
                    files_changed.append(result["path"])
            except Exception as e:
                results.append({"tool": name, "error": str(e)})

        return results

    def get_files_changed(self, tool_results: list[dict[str, Any]]) -> list[str]:
        """Extract file paths that were written to from tool results."""
        files = []
        for result in tool_results:
            if result.get("tool") == "write_file":
                inner = result.get("result", {})
                if "path" in inner:
                    files.append(inner["path"])
        return files

    def reset(self) -> None:
        """Reset per-execution state (file write counter, etc.)."""
        self._writer.reset_counter()

    # --- Tool handlers ---

    def _handle_read_file(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self._reader.read_file(
            path=inputs["path"],
            start_line=inputs.get("start_line"),
            end_line=inputs.get("end_line"),
        )

    def _handle_write_file(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self._writer.write_file(
            path=inputs["path"],
            content=inputs["content"],
        )

    def _handle_list_directory(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self._reader.list_directory(
            path=inputs.get("path", "."),
            recursive=inputs.get("recursive", False),
            max_depth=inputs.get("max_depth", 3),
        )

    def _handle_search_codebase(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self._reader.search_codebase(
            pattern=inputs["pattern"],
            file_glob=inputs.get("file_glob"),
            max_results=inputs.get("max_results", 50),
        )

    def _handle_run_command(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self._runner.run(
            command=inputs["command"],
            timeout_seconds=inputs.get("timeout_seconds", 60),
        )

    def _handle_read_dependencies(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self._reader.read_dependencies()

    def _handle_invoke_integration(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Invoke a plugin capability after enforcing trust/policy gates."""
        kind = str(inputs.get("kind", "")).strip().lower()
        plugin_id = str(inputs.get("plugin_id", "")).strip()
        target_id = str(inputs.get("target_id", "")).strip()
        operation = str(inputs.get("operation", "")).strip()
        payload = inputs.get("payload", {})

        policy_error = self._validate_integration_policy(
            kind=kind,
            plugin_id=plugin_id,
            target_id=target_id,
            operation=operation,
            payload=payload,
        )
        if policy_error:
            return {
                "error": policy_error,
                "blocked": True,
                "kind": kind,
                "plugin_id": plugin_id,
                "target_id": target_id,
                "operation": operation,
            }

        # Runtime currently keeps integrations side-effect free in CLI mode.
        # The control-plane can replace this with actual connector/MCP routing.
        return {
            "status": "accepted",
            "blocked": False,
            "dry_run": bool(self._integration_policy.get("dry_run", True)),
            "kind": kind,
            "plugin_id": plugin_id,
            "target_id": target_id,
            "operation": operation,
            "payload": payload,
            "message": "Integration request accepted by policy gate.",
        }

    def _validate_integration_policy(
        self,
        kind: str,
        plugin_id: str,
        target_id: str,
        operation: str,
        payload: Any,
    ) -> str | None:
        if kind not in {"connector", "mcp", "action"}:
            return "Invalid integration kind; expected connector|mcp|action"
        if not plugin_id:
            return "Missing required field: plugin_id"
        if not target_id:
            return "Missing required field: target_id"
        if not operation:
            return "Missing required field: operation"
        if not OPERATION_PATTERN.match(operation):
            return "Invalid operation format; use alnum/._:- and max 64 chars"
        if not isinstance(payload, dict):
            return "Payload must be an object"
        if len(json.dumps(payload, default=str)) > MAX_INTEGRATION_PAYLOAD_CHARS:
            return (
                f"Payload too large; max {MAX_INTEGRATION_PAYLOAD_CHARS} chars"
            )

        policy_flag_by_kind = {
            "connector": "enable_connector_tools",
            "mcp": "enable_mcp_tools",
            "action": "enable_action_tools",
        }
        if not bool(self._integration_policy.get(policy_flag_by_kind[kind], False)):
            return f"{kind} tools are disabled by policy"

        allowed_plugins = set(self._integration_policy.get("allowed_plugin_ids", []) or [])
        if allowed_plugins and plugin_id not in allowed_plugins:
            return f"Plugin '{plugin_id}' is not allow-listed"

        plugin = self._integration_catalog.get(plugin_id)
        if not isinstance(plugin, dict):
            return f"Plugin '{plugin_id}' not found in integration catalog"
        if not bool(plugin.get("enabled", True)):
            return f"Plugin '{plugin_id}' is disabled"
        declared_capabilities = set(plugin.get("capabilities", []) or [])
        required_cap = {"connector": "connector", "mcp": "mcp", "action": "action"}[kind]
        if declared_capabilities and required_cap not in declared_capabilities:
            return (
                f"Plugin '{plugin_id}' does not declare '{required_cap}' capability"
            )

        min_trust = str(self._integration_policy.get("min_trust_level", "verified")).lower()
        plugin_trust = str(plugin.get("trust_level", "community")).lower()
        min_rank = self.TRUST_LEVEL_ORDER.get(min_trust, 1)
        plugin_rank = self.TRUST_LEVEL_ORDER.get(plugin_trust, 0)
        if plugin_rank < min_rank:
            return (
                f"Plugin '{plugin_id}' trust '{plugin_trust}' below required '{min_trust}'"
            )

        targets_by_kind = {
            "connector": set(plugin.get("connectors", []) or []),
            "mcp": set(plugin.get("mcp_servers", []) or []),
            "action": set(plugin.get("actions", []) or []),
        }
        if target_id not in targets_by_kind[kind]:
            return (
                f"Target '{target_id}' not exposed by plugin '{plugin_id}' for kind '{kind}'"
            )
        if kind == "connector":
            connector_ops = plugin.get("connector_operations", {}) or {}
            allowed_ops = connector_ops.get(target_id, [])
            if isinstance(allowed_ops, list) and allowed_ops and operation not in set(allowed_ops):
                return (
                    f"Operation '{operation}' not allowed for connector target '{target_id}'"
                )
        if kind == "action":
            if operation not in {"run", target_id}:
                return (
                    f"Operation '{operation}' not allowed for action target '{target_id}'"
                )
        return None
