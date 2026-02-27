"""Tests for filesystem tools (project reader, code writer, command runner)."""

from __future__ import annotations

import pytest
from pathlib import Path

from rigovo.infrastructure.filesystem.project_reader import ProjectReader
from rigovo.infrastructure.filesystem.code_writer import CodeWriter
from rigovo.infrastructure.filesystem.command_runner import CommandRunner
from rigovo.infrastructure.filesystem.tool_executor import ToolExecutor


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello():\n    return 'world'\n")
    (tmp_path / "src" / "utils.py").write_text("# Utils\ndef add(a, b):\n    return a + b\n")
    (tmp_path / "requirements.txt").write_text("flask==3.0\nrequests>=2.31\n")
    return tmp_path


# --- ProjectReader ---

class TestProjectReader:

    def test_read_file(self, project_dir):
        reader = ProjectReader(project_dir)
        result = reader.read_file("src/main.py")
        assert "content" in result
        assert "hello" in result["content"]

    def test_read_file_not_found(self, project_dir):
        result = ProjectReader(project_dir).read_file("nonexistent.py")
        assert "error" in result

    def test_read_file_path_traversal_blocked(self, project_dir):
        with pytest.raises(PermissionError, match="Path traversal"):
            ProjectReader(project_dir).read_file("../../etc/passwd")

    def test_read_file_sibling_prefix_escape_blocked(self, project_dir):
        sibling = project_dir.parent / f"{project_dir.name}-escape"
        sibling.mkdir()
        (sibling / "secret.txt").write_text("nope\n")
        with pytest.raises(PermissionError, match="Path traversal"):
            ProjectReader(project_dir).read_file(f"../{sibling.name}/secret.txt")

    def test_list_directory(self, project_dir):
        result = ProjectReader(project_dir).list_directory(".")
        assert "entries" in result
        names = [e["name"] for e in result["entries"]]
        assert "src" in names

    def test_search_codebase(self, project_dir):
        result = ProjectReader(project_dir).search_codebase("def hello")
        assert len(result["matches"]) > 0

    def test_detect_tech_stack(self, project_dir):
        result = ProjectReader(project_dir).detect_tech_stack()
        assert len(result) > 0


# --- CodeWriter ---

class TestCodeWriter:

    def test_write_new_file(self, project_dir):
        writer = CodeWriter(project_dir)
        result = writer.write_file("new_file.py", "print('hello')\n")
        assert "error" not in result
        assert (project_dir / "new_file.py").exists()

    def test_write_creates_directories(self, project_dir):
        writer = CodeWriter(project_dir)
        result = writer.write_file("deep/nested/file.py", "x = 1\n")
        assert "error" not in result
        assert (project_dir / "deep" / "nested" / "file.py").exists()

    def test_write_overwrite_creates_backup(self, project_dir):
        writer = CodeWriter(project_dir)
        result = writer.write_file("src/main.py", "# new content\n")
        assert "error" not in result
        backups = list((project_dir / ".rigovo" / "backups").rglob("*main.py*"))
        assert len(backups) > 0

    def test_write_path_traversal_blocked(self, project_dir):
        result = CodeWriter(project_dir).write_file("../../evil.py", "bad\n")
        assert "error" in result

    def test_write_sibling_prefix_escape_blocked(self, project_dir):
        sibling = project_dir.parent / f"{project_dir.name}-escape"
        sibling.mkdir()
        result = CodeWriter(project_dir).write_file(f"../{sibling.name}/evil.py", "bad\n")
        assert "error" in result

    def test_write_protected_file_blocked(self, project_dir):
        (project_dir / ".env").write_text("SECRET=x\n")
        result = CodeWriter(project_dir).write_file(".env", "NEW=y\n")
        assert "error" in result

    def test_write_tracks_count(self, project_dir):
        writer = CodeWriter(project_dir)
        for i in range(3):
            writer.write_file(f"file_{i}.py", f"x = {i}\n")
        assert writer._files_written == 3

    def test_reset_counter(self, project_dir):
        writer = CodeWriter(project_dir)
        writer.write_file("test.py", "x = 1\n")
        assert writer._files_written == 1
        writer.reset_counter()
        assert writer._files_written == 0


# --- CommandRunner ---

class TestCommandRunner:

    def test_run_simple_command(self, project_dir):
        result = CommandRunner(project_dir).run("echo hello")
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    def test_run_blocked_command(self, project_dir):
        result = CommandRunner(project_dir).run("rm -rf /")
        assert "error" in result

    def test_run_blocked_shell_operator(self, project_dir):
        result = CommandRunner(project_dir).run("echo hello; uname -s")
        assert "error" in result

    def test_run_blocked_inline_exec_flag(self, project_dir):
        result = CommandRunner(project_dir).run("python3 -c \"print('x')\"")
        assert "error" in result

    def test_run_non_allowlisted_command_blocked(self, project_dir):
        result = CommandRunner(project_dir).run("curl --version")
        assert "error" in result
        assert "allow-listed" in result["error"]

    def test_run_timeout(self, project_dir):
        result = CommandRunner(project_dir).run("sleep 10", timeout_seconds=1)
        assert result.get("exit_code", -1) != 0 or "timeout" in str(result).lower()

    def test_run_with_cwd(self, project_dir):
        result = CommandRunner(project_dir).run("ls")
        assert result["exit_code"] == 0


# --- ToolExecutor ---

class TestToolExecutor:

    def test_read_file_tool(self, project_dir):
        result = ToolExecutor(project_dir)._handle_read_file({"path": "src/main.py"})
        assert "content" in result

    def test_write_file_tool(self, project_dir):
        result = ToolExecutor(project_dir)._handle_write_file({"path": "out.py", "content": "x=1\n"})
        assert "error" not in result

    def test_list_directory_tool(self, project_dir):
        result = ToolExecutor(project_dir)._handle_list_directory({"path": "."})
        assert "entries" in result

    def test_search_codebase_tool(self, project_dir):
        result = ToolExecutor(project_dir)._handle_search_codebase({"pattern": "def"})
        assert "matches" in result

    def test_execute_batch(self, project_dir):
        results = ToolExecutor(project_dir).execute_batch([
            {"name": "list_directory", "input": {"path": "."}},
            {"name": "read_file", "input": {"path": "src/main.py"}},
        ])
        assert len(results) == 2
        assert all("result" in r for r in results)

    def test_unknown_tool(self, project_dir):
        results = ToolExecutor(project_dir).execute_batch([{"name": "nonexistent", "input": {}}])
        assert "error" in results[0]

    def test_get_files_changed(self, project_dir):
        results = [
            {"tool": "write_file", "result": {"path": "a.py"}},
            {"tool": "read_file", "result": {"content": "x"}},
            {"tool": "write_file", "result": {"path": "b.py"}},
        ]
        assert ToolExecutor(project_dir).get_files_changed(results) == ["a.py", "b.py"]

    def test_invoke_integration_blocks_untrusted_plugin(self, project_dir):
        executor = ToolExecutor(
            project_dir,
            integration_catalog={
                "acme-slack": {
                    "enabled": True,
                    "trust_level": "community",
                    "connectors": ["slack"],
                    "mcp_servers": [],
                    "actions": [],
                }
            },
            integration_policy={
                "enable_connector_tools": True,
                "enable_mcp_tools": False,
                "enable_action_tools": False,
                "min_trust_level": "verified",
            },
        )
        result = executor._handle_invoke_integration(
            {
                "kind": "connector",
                "plugin_id": "acme-slack",
                "target_id": "slack",
                "operation": "post_message",
                "payload": {"channel": "alerts"},
            }
        )
        assert result["blocked"] is True
        assert "trust" in result["error"].lower()

    def test_invoke_integration_allows_verified_plugin(self, project_dir):
        executor = ToolExecutor(
            project_dir,
            integration_catalog={
                "acme-slack": {
                    "enabled": True,
                    "trust_level": "verified",
                    "capabilities": ["connector"],
                    "connectors": ["slack"],
                    "connector_operations": {"slack": ["post_message"]},
                    "mcp_servers": [],
                    "actions": [],
                }
            },
            integration_policy={
                "enable_connector_tools": True,
                "enable_mcp_tools": False,
                "enable_action_tools": False,
                "min_trust_level": "verified",
                "dry_run": True,
            },
        )
        result = executor._handle_invoke_integration(
            {
                "kind": "connector",
                "plugin_id": "acme-slack",
                "target_id": "slack",
                "operation": "post_message",
                "payload": {"channel": "alerts"},
            }
        )
        assert result["blocked"] is False
        assert result["dry_run"] is True

    def test_invoke_integration_blocks_disallowed_connector_operation(self, project_dir):
        executor = ToolExecutor(
            project_dir,
            integration_catalog={
                "acme-slack": {
                    "enabled": True,
                    "trust_level": "verified",
                    "capabilities": ["connector"],
                    "connectors": ["slack"],
                    "connector_operations": {"slack": ["post_message"]},
                    "mcp_servers": [],
                    "actions": [],
                }
            },
            integration_policy={
                "enable_connector_tools": True,
                "enable_mcp_tools": False,
                "enable_action_tools": False,
                "min_trust_level": "verified",
            },
        )
        result = executor._handle_invoke_integration(
            {
                "kind": "connector",
                "plugin_id": "acme-slack",
                "target_id": "slack",
                "operation": "delete_channel",
                "payload": {"channel": "alerts"},
            }
        )
        assert result["blocked"] is True
        assert "operation" in result["error"].lower()

    def test_invoke_integration_blocks_invalid_operation_format(self, project_dir):
        executor = ToolExecutor(
            project_dir,
            integration_catalog={
                "acme-slack": {
                    "enabled": True,
                    "trust_level": "verified",
                    "capabilities": ["connector"],
                    "connectors": ["slack"],
                    "connector_operations": {"slack": ["post_message"]},
                    "mcp_servers": [],
                    "actions": [],
                }
            },
            integration_policy={
                "enable_connector_tools": True,
                "enable_mcp_tools": False,
                "enable_action_tools": False,
                "min_trust_level": "verified",
            },
        )
        result = executor._handle_invoke_integration(
            {
                "kind": "connector",
                "plugin_id": "acme-slack",
                "target_id": "slack",
                "operation": "post message",  # invalid space
                "payload": {"channel": "alerts"},
            }
        )
        assert result["blocked"] is True
        assert "format" in result["error"].lower()

    def test_invoke_integration_blocks_payload_too_large(self, project_dir):
        executor = ToolExecutor(
            project_dir,
            integration_catalog={
                "acme-slack": {
                    "enabled": True,
                    "trust_level": "verified",
                    "capabilities": ["connector"],
                    "connectors": ["slack"],
                    "connector_operations": {"slack": ["post_message"]},
                    "mcp_servers": [],
                    "actions": [],
                }
            },
            integration_policy={
                "enable_connector_tools": True,
                "enable_mcp_tools": False,
                "enable_action_tools": False,
                "min_trust_level": "verified",
            },
        )
        result = executor._handle_invoke_integration(
            {
                "kind": "connector",
                "plugin_id": "acme-slack",
                "target_id": "slack",
                "operation": "post_message",
                "payload": {"blob": "x" * 25_000},
            }
        )
        assert result["blocked"] is True
        assert "payload" in result["error"].lower()

    def test_invoke_integration_blocks_action_requiring_approval(self, project_dir):
        executor = ToolExecutor(
            project_dir,
            integration_catalog={
                "acme-actions": {
                    "enabled": True,
                    "trust_level": "verified",
                    "capabilities": ["action"],
                    "connectors": [],
                    "mcp_servers": [],
                    "actions": ["delete_records"],
                    "action_requires_approval": {"delete_records": True},
                }
            },
            integration_policy={
                "enable_connector_tools": False,
                "enable_mcp_tools": False,
                "enable_action_tools": True,
                "min_trust_level": "verified",
                "allow_approval_required_actions": False,
            },
        )
        result = executor._handle_invoke_integration(
            {
                "kind": "action",
                "plugin_id": "acme-actions",
                "target_id": "delete_records",
                "operation": "run",
                "payload": {"dataset": "prod-users"},
            }
        )
        assert result["blocked"] is True
        assert "requires approval" in result["error"].lower()

    def test_invoke_integration_allows_action_requiring_approval_with_policy_override(self, project_dir):
        executor = ToolExecutor(
            project_dir,
            integration_catalog={
                "acme-actions": {
                    "enabled": True,
                    "trust_level": "verified",
                    "capabilities": ["action"],
                    "connectors": [],
                    "mcp_servers": [],
                    "actions": ["delete_records"],
                    "action_requires_approval": {"delete_records": True},
                }
            },
            integration_policy={
                "enable_connector_tools": False,
                "enable_mcp_tools": False,
                "enable_action_tools": True,
                "min_trust_level": "verified",
                "allow_approval_required_actions": True,
                "dry_run": True,
            },
        )
        result = executor._handle_invoke_integration(
            {
                "kind": "action",
                "plugin_id": "acme-actions",
                "target_id": "delete_records",
                "operation": "run",
                "payload": {"dataset": "prod-users"},
            }
        )
        assert result["blocked"] is False
        assert result["dry_run"] is True

    def test_invoke_integration_blocks_sensitive_payload_keys_by_default(self, project_dir):
        executor = ToolExecutor(
            project_dir,
            integration_catalog={
                "acme-slack": {
                    "enabled": True,
                    "trust_level": "verified",
                    "capabilities": ["connector"],
                    "connectors": ["slack"],
                    "connector_operations": {"slack": ["post_message"]},
                    "mcp_servers": [],
                    "actions": [],
                }
            },
            integration_policy={
                "enable_connector_tools": True,
                "enable_mcp_tools": False,
                "enable_action_tools": False,
                "min_trust_level": "verified",
                "allow_sensitive_payload_keys": False,
            },
        )
        result = executor._handle_invoke_integration(
            {
                "kind": "connector",
                "plugin_id": "acme-slack",
                "target_id": "slack",
                "operation": "post_message",
                "payload": {"channel": "alerts", "api_key": "secret-value"},
            }
        )
        assert result["blocked"] is True
        assert "sensitive payload" in result["error"].lower()

    def test_invoke_integration_blocks_mcp_operation_not_allowlisted(self, project_dir):
        executor = ToolExecutor(
            project_dir,
            integration_catalog={
                "acme-mcp": {
                    "enabled": True,
                    "trust_level": "verified",
                    "capabilities": ["mcp"],
                    "connectors": [],
                    "mcp_servers": ["knowledge"],
                    "mcp_operations": {"knowledge": ["query"]},
                    "actions": [],
                }
            },
            integration_policy={
                "enable_connector_tools": False,
                "enable_mcp_tools": True,
                "enable_action_tools": False,
                "min_trust_level": "verified",
                "allowed_mcp_operations": ["query"],
            },
        )
        result = executor._handle_invoke_integration(
            {
                "kind": "mcp",
                "plugin_id": "acme-mcp",
                "target_id": "knowledge",
                "operation": "write",
                "payload": {"doc": "x"},
            }
        )
        assert result["blocked"] is True
        assert "mcp" in result["error"].lower()

    def test_tool_executor_worktree_sandbox_writes_inside_worktree(self, project_dir):
        worktree = project_dir / "worktrees" / "w1"
        worktree.mkdir(parents=True)
        executor = ToolExecutor(
            project_dir,
            integration_policy={"allowed_shell_commands": ["echo"]},
            worktree_mode="git_worktree",
            worktree_root=str(worktree),
            filesystem_sandbox_mode="worktree",
        )
        result = executor._handle_write_file({"path": "sandboxed.py", "content": "x = 1\n"})
        assert "error" not in result
        assert (worktree / "sandboxed.py").exists()
        assert not (project_dir / "sandboxed.py").exists()

    def test_tool_executor_worktree_sandbox_blocks_escape(self, project_dir):
        outside = project_dir.parent
        with pytest.raises(PermissionError):
            ToolExecutor(
                project_dir,
                worktree_mode="git_worktree",
                worktree_root=str(outside),
                filesystem_sandbox_mode="worktree",
            )
