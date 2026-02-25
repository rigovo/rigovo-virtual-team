"""Tool executor — dispatches LLM tool calls to actual implementations."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from rigovo.infrastructure.filesystem.project_reader import ProjectReader
from rigovo.infrastructure.filesystem.code_writer import CodeWriter
from rigovo.infrastructure.filesystem.command_runner import CommandRunner

logger = logging.getLogger(__name__)

# Maximum characters in a tool result before truncation.
# Prevents 50KB+ file reads from blowing up context windows.
MAX_TOOL_RESULT_CHARS = 30_000


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

    def __init__(self, project_root: Path) -> None:
        self._reader = ProjectReader(project_root)
        self._writer = CodeWriter(project_root)
        self._runner = CommandRunner(project_root)

        self._handlers: dict[str, Any] = {
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "list_directory": self._handle_list_directory,
            "search_codebase": self._handle_search_codebase,
            "run_command": self._handle_run_command,
            "read_dependencies": self._handle_read_dependencies,
        }

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
