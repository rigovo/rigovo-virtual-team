"""Tool executor — dispatches LLM tool calls to actual implementations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from rigovo.domain.services.code_knowledge_graph import CodeKnowledgeGraph
from rigovo.infrastructure.filesystem.code_writer import CodeWriter
from rigovo.infrastructure.filesystem.command_runner import CommandRunner
from rigovo.infrastructure.filesystem.project_reader import ProjectReader

logger = logging.getLogger(__name__)

# Maximum characters in a tool result before truncation.
# Prevents 50KB+ file reads from blowing up context windows.
MAX_TOOL_RESULT_CHARS = 30_000
MAX_INTEGRATION_PAYLOAD_CHARS = 20_000
OPERATION_PATTERN = re.compile(r"^[a-zA-Z0-9_.:-]{1,64}$")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|api[_-]?key|private[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)


def _truncate_result(result_str: str) -> str:
    """Truncate tool result if it exceeds MAX_TOOL_RESULT_CHARS."""
    if len(result_str) <= MAX_TOOL_RESULT_CHARS:
        return result_str
    truncated = result_str[:MAX_TOOL_RESULT_CHARS]
    return truncated + f"\n... [truncated, {len(result_str):,} chars total]"


def _collect_sensitive_payload_keys(payload: Any, prefix: str = "") -> list[str]:
    """Collect payload key paths that look like sensitive material."""
    hits: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_str = str(key)
            path = f"{prefix}.{key_str}" if prefix else key_str
            if SENSITIVE_KEY_PATTERN.search(key_str):
                hits.append(path)
            hits.extend(_collect_sensitive_payload_keys(value, path))
    elif isinstance(payload, list):
        for idx, value in enumerate(payload):
            path = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
            hits.extend(_collect_sensitive_payload_keys(value, path))
    return hits


class FileReadCache:
    """In-memory cache for file reads with mtime-based invalidation.

    Eliminates redundant disk I/O when agents re-read the same files
    (especially during retry cycles). Cache entries are keyed by path
    and validated against file mtime — stale entries are automatically
    evicted on read. Write operations invalidate the relevant entry.
    """

    MAX_ENTRIES = 200

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        # Maps relative_path → (mtime_ns, sha256_digest, result_dict)
        self._cache: dict[str, tuple[int, str, dict[str, Any]]] = {}

    def get(self, relative_path: str) -> dict[str, Any] | None:
        """Return cached result if path exists and mtime matches, else None."""
        entry = self._cache.get(relative_path)
        if entry is None:
            return None
        cached_mtime_ns, _, cached_result = entry
        try:
            current_mtime_ns = (self._root / relative_path).stat().st_mtime_ns
        except OSError:
            # File disappeared — evict
            self._cache.pop(relative_path, None)
            return None
        if current_mtime_ns != cached_mtime_ns:
            # Stale — evict
            self._cache.pop(relative_path, None)
            return None
        return cached_result

    def put(self, relative_path: str, result: dict[str, Any]) -> None:
        """Cache a full-file read result."""
        try:
            mtime_ns = (self._root / relative_path).stat().st_mtime_ns
        except OSError:
            return
        content = result.get("content", "")
        digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        # Evict oldest entries if over capacity
        if len(self._cache) >= self.MAX_ENTRIES and relative_path not in self._cache:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[relative_path] = (mtime_ns, digest, result)

    def invalidate(self, relative_path: str) -> None:
        """Remove cache entry for a path (called after write_file)."""
        self._cache.pop(relative_path, None)

    def get_file_digests(self) -> dict[str, str]:
        """Return {relative_path: sha256_digest} for all cached files."""
        return {path: entry[1] for path, entry in self._cache.items()}

    def get_cached_contents(self, max_total_bytes: int = 30_000) -> dict[str, str]:
        """Return {relative_path: content} for cached files within size budget."""
        result: dict[str, str] = {}
        total = 0
        for path, (_, _, cached_result) in self._cache.items():
            content = cached_result.get("content", "")
            if total + len(content) > max_total_bytes:
                continue
            result[path] = content
            total += len(content)
        return result


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
        knowledge_graph: CodeKnowledgeGraph | None = None,
        scope_boundaries: dict[str, Any] | None = None,
    ) -> None:
        self._integration_catalog = integration_catalog or {}
        self._integration_policy = integration_policy or {}
        self._project_root = project_root.resolve()
        self._scope_boundaries = scope_boundaries or {}
        self._worktree_mode = str(worktree_mode or "project").strip().lower()
        self._worktree_root = str(worktree_root or "").strip()
        self._filesystem_sandbox_mode = (
            str(filesystem_sandbox_mode or "project_root").strip().lower()
        )
        self._execution_root = self._resolve_execution_root()
        allowed_commands = set(self._integration_policy.get("allowed_shell_commands", []) or [])

        self._reader = ProjectReader(self._execution_root)
        self._writer = CodeWriter(self._execution_root)
        self._runner = CommandRunner(
            self._execution_root, allowed_commands=allowed_commands or None
        )
        self._knowledge_graph = knowledge_graph
        self._file_cache = FileReadCache(self._execution_root)

        # Cache Rigour binary for real-time hooks check on file writes
        self._rigour_binary: str | None = None
        try:
            from rigovo.infrastructure.quality.rigour_gate import RigourQualityGate
            self._rigour_binary = RigourQualityGate._find_binary(
                str(self._project_root),
            )
        except Exception:
            pass

        self._handlers: dict[str, Any] = {
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "list_directory": self._handle_list_directory,
            "search_codebase": self._handle_search_codebase,
            "run_command": self._handle_run_command,
            "read_dependencies": self._handle_read_dependencies,
            "invoke_integration": self._handle_invoke_integration,
            "get_component_map": self._handle_get_component_map,
            "get_impact_radius": self._handle_get_impact_radius,
            "probe_environment": self._handle_probe_environment,
        }

    def _resolve_execution_root(self) -> Path:
        """Resolve effective filesystem sandbox root based on worktree policy."""
        if self._filesystem_sandbox_mode not in {"project_root", "worktree"}:
            raise ValueError(f"Invalid filesystem_sandbox_mode '{self._filesystem_sandbox_mode}'")
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
            raise PermissionError("worktree_root must stay within project_root sandbox") from exc
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"Configured worktree_root does not exist: {candidate}")
        return candidate

    def _check_scope_violation(self, write_path: str) -> dict[str, Any] | None:
        """Check if a write path violates scope boundaries set by Master Agent.

        Returns an error dict if the path is blocked, or None if allowed.
        Scope boundaries are soft enforcement — they warn and block writes
        to paths outside the agent's focus area.
        """
        if not self._scope_boundaries:
            return None

        # Normalise the path for prefix matching
        normalised = write_path.lstrip("/").lstrip("./")

        # Check exclude_paths first — explicit blocks
        for excl in self._scope_boundaries.get("exclude_paths", []):
            excl_norm = excl.lstrip("/").lstrip("./").rstrip("/")
            if normalised.startswith(excl_norm):
                logger.warning(
                    "SCOPE VIOLATION: write to '%s' blocked (exclude: %s)",
                    write_path,
                    excl,
                )
                return {
                    "error": (
                        f"SCOPE VIOLATION: You cannot write to '{write_path}' — "
                        f"it falls under excluded path '{excl}'. "
                        "Another specialist agent owns this domain. "
                        "Focus on your assigned scope."
                    ),
                    "status": "scope_blocked",
                }

        # Check focus_paths — if defined, only allow writes within focus areas
        focus_paths = self._scope_boundaries.get("focus_paths", [])
        if focus_paths:
            in_scope = any(
                normalised.startswith(fp.lstrip("/").lstrip("./").rstrip("/"))
                for fp in focus_paths
            )
            if not in_scope:
                # Allow common config files at project root
                root_exceptions = {
                    "package.json", "tsconfig.json", "pyproject.toml",
                    "setup.py", "setup.cfg", "Makefile", "Dockerfile",
                    ".env.example", "requirements.txt",
                }
                if normalised not in root_exceptions:
                    logger.warning(
                        "SCOPE VIOLATION: write to '%s' outside focus %s",
                        write_path,
                        focus_paths,
                    )
                    return {
                        "error": (
                            f"SCOPE VIOLATION: '{write_path}' is outside "
                            f"your focus area {focus_paths}. "
                            "Write to files within your assigned scope."
                        ),
                        "status": "scope_blocked",
                    }

        return None

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

    def get_file_digests(self) -> dict[str, str]:
        """Return SHA-256 digests for all cached files (for retry context injection)."""
        return self._file_cache.get_file_digests()

    def get_cached_contents(self, max_total_bytes: int = 30_000) -> dict[str, str]:
        """Return cached file contents within size budget (for retry prompt injection)."""
        return self._file_cache.get_cached_contents(max_total_bytes)

    def _handle_read_file(self, inputs: dict[str, Any]) -> dict[str, Any]:
        path = inputs.get("path")
        if not path:
            return {
                "error": "read_file requires a 'path' parameter.",
                "status": "error",
            }
        start_line = inputs.get("start_line")
        end_line = inputs.get("end_line")

        # Cache full-file reads only (not line-ranged)
        is_full_read = start_line is None and end_line is None
        if is_full_read:
            cached = self._file_cache.get(path)
            if cached is not None:
                return cached

        result = self._reader.read_file(
            path=path,
            start_line=start_line,
            end_line=end_line,
        )

        # Cache successful full-file reads
        if is_full_read and "error" not in result:
            self._file_cache.put(path, result)

        return result

    def _handle_write_file(self, inputs: dict[str, Any]) -> dict[str, Any]:
        content = inputs.get("content")
        if content is None:
            # LLM sometimes omits the "content" key — defensive guard
            return {
                "error": (
                    "write_file requires a 'content' parameter. "
                    "Please call write_file with both 'path' and 'content'."
                ),
                "status": "error",
            }

        # Scope boundary enforcement — Master Agent restricts file access
        write_path = str(inputs.get("path", ""))
        scope_violation = self._check_scope_violation(write_path)
        if scope_violation:
            return scope_violation

        result = self._writer.write_file(
            path=inputs["path"],
            content=content,
        )
        # Invalidate cache for the written path
        self._file_cache.invalidate(inputs["path"])

        # Real-time Rigour hooks check — catch secrets, hallucinated imports, etc.
        if self._rigour_binary and result.get("status") != "error":
            hook_warnings = self._run_hooks_check(inputs["path"])
            if hook_warnings:
                result["rigour_warnings"] = hook_warnings
                result["status_note"] = (
                    f"File written but Rigour detected {len(hook_warnings)} issue(s): "
                    + "; ".join(hook_warnings[:3])
                )

        # Pattern reinvention check — warn if creating duplicate code
        if result.get("status") != "error":
            reinvention = self._check_pattern_reinvention(content)
            if reinvention:
                existing_warnings = result.get("rigour_warnings", [])
                result["rigour_warnings"] = existing_warnings + reinvention

        return result

    def _run_hooks_check(self, file_path: str) -> list[str] | None:
        """Run rigour hooks check on a single file (<200ms).

        Returns a list of warning strings or None if clean / unavailable.
        """
        import subprocess

        try:
            from rigovo.infrastructure.quality.rigour_gate import RigourQualityGate

            cmd = RigourQualityGate._build_cmd(
                self._rigour_binary, "hooks", "check", "--files", file_path,
            )
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(self._project_root),
            )
            if proc.returncode != 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                failures = data.get("failures", [])
                if failures:
                    return [
                        f"[{f.get('severity', '?')}] {f.get('message', '')}"
                        for f in failures[:5]
                    ]
        except Exception:
            pass  # Graceful degradation — never block file writes
        return None

    def _check_pattern_reinvention(self, content: str) -> list[str] | None:
        """Check new function/class names against Rigour pattern index.

        Reads ``.rigour/pattern-index.json`` (created by ``rigour index``)
        to detect if a newly created pattern already exists in the codebase.
        """
        index_path = self._project_root / ".rigour" / "pattern-index.json"
        if not index_path.exists():
            return None
        try:
            # Quick heuristic: extract function/class names from content
            new_patterns = re.findall(
                r"(?:def|function|class|const)\s+(\w+)", content,
            )
            if not new_patterns:
                return None
            index_data = json.loads(index_path.read_text())
            existing_names = {
                p.get("name", "").lower()
                for p in index_data.get("patterns", [])
                if p.get("name")
            }
            warnings: list[str] = []
            for name in new_patterns[:5]:
                if name.lower() in existing_names:
                    warnings.append(
                        f"Pattern '{name}' already exists in codebase — "
                        "consider reusing instead of reinventing"
                    )
            return warnings or None
        except (json.JSONDecodeError, OSError):
            return None

    def _handle_list_directory(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self._reader.list_directory(
            path=inputs.get("path", "."),
            recursive=inputs.get("recursive", False),
            max_depth=inputs.get("max_depth", 3),
        )

    def _handle_search_codebase(self, inputs: dict[str, Any]) -> dict[str, Any]:
        pattern = inputs.get("pattern")
        if not pattern:
            return {
                "error": "search_codebase requires a 'pattern' parameter.",
                "status": "error",
            }
        return self._reader.search_codebase(
            pattern=pattern,
            file_glob=inputs.get("file_glob"),
            max_results=inputs.get("max_results", 50),
        )

    def _handle_run_command(self, inputs: dict[str, Any]) -> dict[str, Any]:
        command = inputs.get("command")
        if not command:
            return {
                "error": "run_command requires a 'command' parameter.",
                "status": "error",
            }
        return self._runner.run(
            command=command,
            timeout_seconds=inputs.get("timeout_seconds", 60),
        )

    def _handle_read_dependencies(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self._reader.read_dependencies()

    # --- Knowledge Graph tool handlers ---

    def _handle_get_component_map(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Return components grouped by domain from the code knowledge graph."""
        if self._knowledge_graph is None:
            return {"error": "Code knowledge graph not available. Project scan may not have run."}
        domain_filter = str(inputs.get("domain_filter", "") or "").strip()
        clusters = self._knowledge_graph.get_component_map(domain_filter)
        return {
            "domains": clusters,
            "total_domains": len(clusters),
            "graph_nodes": self._knowledge_graph.node_count,
            "graph_edges": self._knowledge_graph.edge_count,
        }

    def _handle_get_impact_radius(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Return impact radius for a file from the code knowledge graph."""
        if self._knowledge_graph is None:
            return {"error": "Code knowledge graph not available. Project scan may not have run."}
        file_path = str(inputs.get("file_path", "")).strip()
        if not file_path:
            return {"error": "file_path is required"}
        max_depth = int(inputs.get("max_depth", 3) or 3)
        return self._knowledge_graph.get_impact_radius(file_path, max_depth)

    def _handle_probe_environment(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Semantic probe over the code knowledge graph."""
        if self._knowledge_graph is None:
            return {"error": "Code knowledge graph not available. Project scan may not have run."}
        query = str(inputs.get("query", "")).strip()
        if not query:
            return {"error": "query is required"}
        return self._knowledge_graph.probe_environment(query)

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
            return f"Payload too large; max {MAX_INTEGRATION_PAYLOAD_CHARS} chars"

        if not bool(self._integration_policy.get("allow_sensitive_payload_keys", False)):
            sensitive_keys = _collect_sensitive_payload_keys(payload)
            if sensitive_keys:
                preview = ", ".join(sensitive_keys[:5])
                return (
                    f"Sensitive payload keys require explicit policy allow-list (found: {preview})"
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
            return f"Plugin '{plugin_id}' does not declare '{required_cap}' capability"

        min_trust = str(self._integration_policy.get("min_trust_level", "verified")).lower()
        plugin_trust = str(plugin.get("trust_level", "community")).lower()
        min_rank = self.TRUST_LEVEL_ORDER.get(min_trust, 1)
        plugin_rank = self.TRUST_LEVEL_ORDER.get(plugin_trust, 0)
        if plugin_rank < min_rank:
            return f"Plugin '{plugin_id}' trust '{plugin_trust}' below required '{min_trust}'"

        targets_by_kind = {
            "connector": set(plugin.get("connectors", []) or []),
            "mcp": set(plugin.get("mcp_servers", []) or []),
            "action": set(plugin.get("actions", []) or []),
        }
        if target_id not in targets_by_kind[kind]:
            return f"Target '{target_id}' not exposed by plugin '{plugin_id}' for kind '{kind}'"
        global_ops_by_kind = {
            "connector": set(
                self._integration_policy.get("allowed_connector_operations", []) or []
            ),
            "mcp": set(self._integration_policy.get("allowed_mcp_operations", []) or []),
            "action": set(self._integration_policy.get("allowed_action_operations", []) or []),
        }
        global_ops = global_ops_by_kind[kind]
        if global_ops and operation not in global_ops:
            return f"Operation '{operation}' is not allowed by global {kind} policy"
        if kind == "connector":
            connector_ops = plugin.get("connector_operations", {}) or {}
            allowed_ops = connector_ops.get(target_id, [])
            if isinstance(allowed_ops, list) and allowed_ops and operation not in set(allowed_ops):
                return f"Operation '{operation}' not allowed for connector target '{target_id}'"
        if kind == "mcp":
            mcp_ops = plugin.get("mcp_operations", {}) or {}
            allowed_ops = mcp_ops.get(target_id, [])
            if isinstance(allowed_ops, list) and allowed_ops and operation not in set(allowed_ops):
                return f"Operation '{operation}' not allowed for MCP target '{target_id}'"
        if kind == "action":
            requires_approval = (plugin.get("action_requires_approval", {}) or {}).get(
                target_id, False
            )
            if bool(requires_approval) and not bool(
                self._integration_policy.get("allow_approval_required_actions", False)
            ):
                return f"Action '{target_id}' requires approval and is blocked by policy"
            if operation not in {"run", target_id}:
                return f"Operation '{operation}' not allowed for action target '{target_id}'"
        return None
