"""Command runner — executes shell commands in the project safely."""

from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Shell control operators are blocked to prevent command chaining/injection.
BLOCKED_SHELL_TOKENS = ("|", "&&", "||", ";", "$(", "`", ">", "<", "\n", "\r")

# Binary-level deny list. Blocks destructive or privilege-escalation commands.
BLOCKED_BINARIES = {
    "rm",
    "sudo",
    "su",
    "chmod",
    "chown",
    "mkfs",
    "dd",
    "shutdown",
    "reboot",
    "poweroff",
    "kill",
    "pkill",
    "killall",
}

# Prevent inline script execution that bypasses command policy review.
BLOCKED_INLINE_EXEC_FLAGS: dict[str, set[str]] = {
    "python": {"-c"},
    "python3": {"-c"},
    "node": {"-e"},
    "bash": {"-c"},
    "sh": {"-c"},
    "zsh": {"-c"},
    "ruby": {"-e"},
    "perl": {"-e"},
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
    - Shell injection/operator blocking
    - Blocked binary list
    - Timeout enforcement
    - Output size limits
    - Working directory locked to project root
    - No shell=True (argv execution only)
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
        parse_error = self._validate_command(command)
        if parse_error:
            return {
                "command": command,
                "error": parse_error,
                "exit_code": -1,
            }

        try:
            argv = shlex.split(command, posix=True)
        except ValueError as exc:
            return {
                "command": command,
                "error": f"Invalid command syntax: {exc}",
                "exit_code": -1,
            }

        logger.info("Running: %s (timeout=%ds)", command, timeout_seconds)

        try:
            result = subprocess.run(
                argv,
                shell=False,
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

    def _validate_command(self, command: str) -> str | None:
        """Validate command syntax and dangerous patterns before execution."""
        stripped = command.strip()
        if not stripped:
            return "Command cannot be empty"

        for token in BLOCKED_SHELL_TOKENS:
            if token in stripped:
                return f"Blocked shell operator detected: {token}"

        try:
            argv = shlex.split(stripped, posix=True)
        except ValueError as exc:
            return f"Invalid command syntax: {exc}"
        if not argv:
            return "Command cannot be empty"

        binary = Path(argv[0]).name.lower()
        if binary in BLOCKED_BINARIES:
            return f"Blocked command: {binary}"
        for flag in argv[1:]:
            if flag in BLOCKED_INLINE_EXEC_FLAGS.get(binary, set()):
                return f"Blocked inline execution flag '{flag}' for {binary}"

        return None

    def _safe_env(self) -> dict[str, str] | None:
        """Build a safe environment for command execution."""
        import os
        env = os.environ.copy()
        # Ensure agent commands can't access rigovo internals
        env.pop("RIGOVO_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("GOOGLE_API_KEY", None)
        env.pop("DEEPSEEK_API_KEY", None)
        env.pop("GROQ_API_KEY", None)
        env.pop("MISTRAL_API_KEY", None)
        return env
