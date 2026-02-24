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
