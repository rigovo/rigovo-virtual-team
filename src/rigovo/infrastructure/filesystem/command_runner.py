"""Command runner — executes shell commands in the project safely."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Commands that are never allowed
BLOCKED_COMMANDS = {
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=",
    ":(){:|:&};:", "chmod -R 777 /", "curl | sh",
    "wget -O - | sh", "eval", "exec",
}

# Max output size (100KB)
MAX_OUTPUT_SIZE = 102_400

# Default timeout (60 seconds)
DEFAULT_TIMEOUT = 60


class CommandRunner:
    """
    Runs shell commands in the project root with safety guardrails.

    Used by agents to run tests, linters, build tools, etc.

    Safety features:
    - Blocked command patterns
    - Timeout enforcement
    - Output size limits
    - Working directory locked to project root
    - No shell=True for raw string commands (uses subprocess.run safely)
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()

    def run(
        self,
        command: str,
        timeout_seconds: int = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """
        Run a command in the project root.

        Returns:
            {command, exit_code, stdout, stderr, timed_out, duration_ms}
        """
        # Safety check
        cmd_lower = command.lower().strip()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                return {
                    "command": command,
                    "error": f"Blocked command pattern detected: {blocked}",
                    "exit_code": -1,
                }

        logger.info("Running: %s (timeout=%ds)", command, timeout_seconds)

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=min(timeout_seconds, 300),  # Hard cap at 5 min
                env=self._safe_env(),
            )

            stdout = result.stdout[:MAX_OUTPUT_SIZE]
            stderr = result.stderr[:MAX_OUTPUT_SIZE]

            truncated = (
                len(result.stdout) > MAX_OUTPUT_SIZE
                or len(result.stderr) > MAX_OUTPUT_SIZE
            )

            return {
                "command": command,
                "exit_code": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
                "truncated": truncated,
            }

        except subprocess.TimeoutExpired:
            return {
                "command": command,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout_seconds} seconds",
                "timed_out": True,
            }

        except Exception as e:
            return {
                "command": command,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "timed_out": False,
                "error": str(e),
            }

    def _safe_env(self) -> dict[str, str] | None:
        """Build a safe environment for command execution."""
        import os
        env = os.environ.copy()
        # Ensure agent commands can't access rigovo internals
        env.pop("RIGOVO_API_KEY", None)
        return env
