"""Structured logging configuration for Rigovo CLI.

Provides JSON-structured logging for machine readability and
Rich-formatted logging for terminal display.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import Any


class StructuredFormatter(logging.Formatter):
    """
    JSON-structured log formatter for machine-readable output.

    Used for log files and CI environments. Each log line is valid JSON.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra context if available
        if hasattr(record, "task_id"):
            log_entry["task_id"] = record.task_id
        if hasattr(record, "agent_role"):
            log_entry["agent_role"] = record.agent_role
        if hasattr(record, "workspace_id"):
            log_entry["workspace_id"] = record.workspace_id
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if hasattr(record, "cost_usd"):
            log_entry["cost_usd"] = record.cost_usd

        # Add exception info
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown",
                "message": str(record.exc_info[1]),
            }

        return json.dumps(log_entry, default=str)


class HumanFormatter(logging.Formatter):
    """
    Human-readable formatter for terminal output.

    Color-coded by level, with minimal noise.
    """

    COLORS = {
        "DEBUG": "\033[36m",    # Cyan
        "INFO": "\033[32m",     # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[35m", # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET if color else ""

        # Shorten logger name
        name = record.name
        if name.startswith("rigovo."):
            name = name[7:]

        return f"{color}{record.levelname:>8}{reset} [{name}] {record.getMessage()}"


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_file: str | None = None,
) -> None:
    """
    Configure logging for the Rigovo CLI.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: Use JSON formatter for stdout
        log_file: Optional file path for structured JSON logs
    """
    root_logger = logging.getLogger("rigovo")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    if json_output:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(HumanFormatter())
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.addHandler(console_handler)

    # File handler (always JSON structured)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(StructuredFormatter())
        file_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)

    # Quiet noisy libraries
    for lib in ("httpx", "httpcore", "anthropic", "openai", "urllib3"):
        logging.getLogger(lib).setLevel(logging.WARNING)


class TaskLogger:
    """
    Contextual logger for task execution.

    Automatically includes task_id and agent_role in all log messages.
    """

    def __init__(self, logger: logging.Logger, task_id: str, agent_role: str = "") -> None:
        self._logger = logger
        self._task_id = task_id
        self._agent_role = agent_role

    def _extra(self, **kwargs: Any) -> dict[str, Any]:
        extra = {"task_id": self._task_id}
        if self._agent_role:
            extra["agent_role"] = self._agent_role
        extra.update(kwargs)
        return extra

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info(msg, extra=self._extra(**kwargs))

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._logger.debug(msg, extra=self._extra(**kwargs))

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning(msg, extra=self._extra(**kwargs))

    def error(self, msg: str, **kwargs: Any) -> None:
        self._logger.error(msg, extra=self._extra(**kwargs))

    def with_role(self, agent_role: str) -> TaskLogger:
        """Create a child logger with a specific agent role."""
        return TaskLogger(self._logger, self._task_id, agent_role)
