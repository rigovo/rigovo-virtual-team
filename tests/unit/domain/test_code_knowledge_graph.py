"""Tests for Code Knowledge Graph — structural codebase understanding.

Covers:
- Import parsing (Python, TypeScript, JavaScript, Go)
- Symbol extraction (classes, functions, exports)
- Edge resolution (import → file path mapping)
- Dependency indexes (forward + reverse)
- Domain clustering
- Impact radius analysis
- Environment probing (semantic search)
- Incremental graph refresh
- Context section generation
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from rigovo.domain.services.code_knowledge_graph import (
    CodeKnowledgeGraph,
    DomainCluster,
    GraphEdge,
    GraphNode,
    KnowledgeGraphBuilder,
)


class TestImportParsing(unittest.TestCase):
    """Test import extraction for supported languages."""

    def setUp(self):
        self.builder = KnowledgeGraphBuilder()

    def test_python_from_import(self):
        """from X import Y should extract module X."""
        content = "from rigovo.domain.services import tools\nfrom os import path"
        imports = self.builder._extract_imports(content, "py")
        assert "rigovo.domain.services" in imports
        assert "os" in imports

    def test_python_plain_import(self):
        """import X should extract module X."""
        content = "import json\nimport logging"
        imports = self.builder._extract_imports(content, "py")
        assert "json" in imports
        assert "logging" in imports

    def test_typescript_import_from(self):
        """import ... from 'X' should extract path X."""
        content = """import { useState } from 'react'
import { Button } from './components/Button'
import type { User } from '../types'"""
        imports = self.builder._extract_imports(content, "ts")
        assert "react" in imports
        assert "./components/Button" in imports
        assert "../types" in imports

    def test_javascript_require(self):
        """require('X') should extract path X."""
        content = """const express = require('express')
const utils = require('./utils')"""
        imports = self.builder._extract_imports(content, "js")
        assert "express" in imports
        assert "./utils" in imports

    def test_go_single_import(self):
        """import "path" should extract path."""
        content = 'import "fmt"\n'
        imports = self.builder._extract_imports(content, "go")
        assert "fmt" in imports

    def test_go_block_import(self):
        """import ( "path1" "path2" ) should extract all paths."""
        content = """import (
    "fmt"
    "net/http"
    "github.com/pkg/errors"
)"""
        imports = self.builder._extract_imports(content, "go")
        assert "fmt" in imports
        assert "net/http" in imports
        assert "github.com/pkg/errors" in imports


class TestSymbolExtraction(unittest.TestCase):
    """Test top-level symbol extraction."""

    def setUp(self):
        self.builder = KnowledgeGraphBuilder()

    def test_python_class_and_function(self):
        """Extract Python classes and public functions."""
        content = """class UserService:
    pass

def authenticate(user):
    pass

def _private_helper():
    pass"""
        symbols = self.builder._extract_symbols(content, "py")
        assert "UserService" in symbols
        assert "authenticate" in symbols
        assert "_private_helper" not in symbols  # Private, skipped

    def test_typescript_exports(self):
        """Extract TypeScript exported symbols."""
        content = """export class AuthProvider {
}
export function login() {}
export const API_URL = "..."
export interface UserProfile {}
export type UserId = string
"""
        symbols = self.builder._extract_symbols(content, "ts")
        assert "AuthProvider" in symbols
        assert "login" in symbols
        assert "API_URL" in symbols
        assert "UserProfile" in symbols
        assert "UserId" in symbols

    def test_go_exported_symbols(self):
        """Extract Go exported types and functions (capitalized)."""
        content = """func HandleRequest(w http.ResponseWriter, r *http.Request) {}
func internalHelper() {}
type UserService struct {}
type config struct {}"""
        symbols = self.builder._extract_symbols(content, "go")
        assert "HandleRequest" in symbols
        assert "UserService" in symbols
        # Unexported symbols (lowercase) should not be included
        assert "internalHelper" not in symbols
        assert "config" not in symbols


class TestGraphBuilding(unittest.TestCase):
    """Test full knowledge graph construction from a project directory."""

    def setUp(self):
        self.builder = KnowledgeGraphBuilder()
        self.tmpdir = tempfile.mkdtemp()
        # Create a small Python project structure
        src = Path(self.tmpdir) / "src" / "app"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "models.py").write_text(
            "class User:\n    pass\n\nclass Order:\n    pass\n"
        )
        (src / "service.py").write_text(
            "from app.models import User\n\nclass UserService:\n    pass\n"
        )
        (src / "routes.py").write_text(
            "from app.service import UserService\nfrom app.models import Order\n\n"
            "def get_users():\n    pass\n\ndef create_order():\n    pass\n"
        )
        # Create a test file
        tests = Path(self.tmpdir) / "tests"
        tests.mkdir()
        (tests / "test_service.py").write_text(
            "from app.service import UserService\n\ndef test_user():\n    pass\n"
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_builds_nodes_for_source_files(self):
        """Should create nodes for all .py files."""
        graph = self.builder.build(self.tmpdir)
        assert graph.node_count >= 4  # models, service, routes, test_service
        # Verify specific files are in the graph
        paths = set(graph.nodes.keys())
        assert any("models.py" in p for p in paths)
        assert any("service.py" in p for p in paths)
        assert any("routes.py" in p for p in paths)

    def test_extracts_symbols(self):
        """Should extract class and function names."""
        graph = self.builder.build(self.tmpdir)
        models_node = None
        for path, node in graph.nodes.items():
            if "models.py" in path and "__init__" not in path:
                models_node = node
                break
        assert models_node is not None
        assert "User" in models_node.symbols
        assert "Order" in models_node.symbols

    def test_creates_domain_clusters(self):
        """Should cluster files by directory."""
        graph = self.builder.build(self.tmpdir)
        assert len(graph.clusters) > 0
        cluster_names = [c.name for c in graph.clusters]
        # Should have at least an 'app' and 'tests' cluster
        assert any("app" in n for n in cluster_names) or any("src" in n for n in cluster_names)

    def test_node_serialization(self):
        """Nodes should serialize to dict correctly."""
        node = GraphNode(
            path="src/app/models.py",
            language="py",
            symbols=["User", "Order"],
            imports=["os"],
            line_count=10,
            size_bytes=200,
        )
        d = node.to_dict()
        assert d["path"] == "src/app/models.py"
        assert d["symbols"] == ["User", "Order"]

    def test_graph_serialization(self):
        """Graph should serialize to dict with all fields."""
        graph = self.builder.build(self.tmpdir)
        d = graph.to_dict()
        assert "project_root" in d
        assert "node_count" in d
        assert "edge_count" in d
        assert "nodes" in d
        assert "clusters" in d


class TestImpactRadius(unittest.TestCase):
    """Test impact analysis from knowledge graph."""

    def test_direct_dependents(self):
        """Files importing the target should appear as direct dependents."""
        graph = CodeKnowledgeGraph(project_root="/tmp")
        graph.nodes = {
            "models.py": GraphNode(path="models.py", language="py", symbols=["User"]),
            "service.py": GraphNode(path="service.py", language="py", symbols=["UserService"]),
            "routes.py": GraphNode(path="routes.py", language="py", symbols=["get_users"]),
        }
        graph.edges = [
            GraphEdge(source="service.py", target="models.py", import_string="models"),
            GraphEdge(source="routes.py", target="service.py", import_string="service"),
        ]
        # Build indexes
        graph.reverse_deps = {
            "models.py": ["service.py"],
            "service.py": ["routes.py"],
        }
        graph.forward_deps = {
            "service.py": ["models.py"],
            "routes.py": ["service.py"],
        }

        result = graph.get_impact_radius("models.py")
        assert result["file"] == "models.py"
        assert "service.py" in result["direct_dependents"]
        # routes.py is a transitive dependent (depth 2)
        assert result["total_affected"] == 2

    def test_unknown_file_returns_error(self):
        """Non-existent file should return error dict."""
        graph = CodeKnowledgeGraph(project_root="/tmp")
        result = graph.get_impact_radius("nonexistent.py")
        assert "error" in result

    def test_no_dependents(self):
        """File with no imports should have empty dependents."""
        graph = CodeKnowledgeGraph(project_root="/tmp")
        graph.nodes = {
            "leaf.py": GraphNode(path="leaf.py", language="py", symbols=["Leaf"]),
        }
        graph.reverse_deps = {}
        graph.forward_deps = {}

        result = graph.get_impact_radius("leaf.py")
        assert result["direct_dependents"] == []
        assert result["total_affected"] == 0


class TestProbeEnvironment(unittest.TestCase):
    """Test semantic environment probing."""

    def _build_test_graph(self) -> CodeKnowledgeGraph:
        graph = CodeKnowledgeGraph(project_root="/tmp")
        graph.nodes = {
            "src/auth/provider.py": GraphNode(
                path="src/auth/provider.py", language="py",
                symbols=["AuthProvider", "authenticate"],
            ),
            "src/auth/middleware.py": GraphNode(
                path="src/auth/middleware.py", language="py",
                symbols=["AuthMiddleware"],
            ),
            "src/routes/login.py": GraphNode(
                path="src/routes/login.py", language="py",
                symbols=["login_handler", "logout_handler"],
            ),
            "src/models/user.py": GraphNode(
                path="src/models/user.py", language="py",
                symbols=["User", "UserRole"],
            ),
            "src/db/pool.py": GraphNode(
                path="src/db/pool.py", language="py",
                symbols=["DatabasePool"],
            ),
        }
        graph.reverse_deps = {
            "src/auth/provider.py": ["src/auth/middleware.py", "src/routes/login.py"],
            "src/models/user.py": ["src/auth/provider.py", "src/routes/login.py"],
        }
        graph.forward_deps = {
            "src/auth/middleware.py": ["src/auth/provider.py"],
            "src/routes/login.py": ["src/auth/provider.py", "src/models/user.py"],
            "src/auth/provider.py": ["src/models/user.py"],
        }
        graph.clusters = [
            DomainCluster(
                name="auth",
                files=["src/auth/provider.py", "src/auth/middleware.py"],
                key_symbols=["AuthProvider", "AuthMiddleware"],
            ),
            DomainCluster(
                name="routes",
                files=["src/routes/login.py"],
                key_symbols=["login_handler"],
            ),
        ]
        return graph

    def test_probe_by_path(self):
        """Query matching file paths should return those files."""
        graph = self._build_test_graph()
        result = graph.probe_environment("auth")
        assert "src/auth/provider.py" in result["direct_matches"]
        assert "src/auth/middleware.py" in result["direct_matches"]

    def test_probe_by_symbol(self):
        """Query matching symbol names should return those files."""
        graph = self._build_test_graph()
        result = graph.probe_environment("authenticate")
        assert "src/auth/provider.py" in result["direct_matches"]
        assert "authenticate" in result["matching_symbols"].get("src/auth/provider.py", [])

    def test_probe_includes_connected_files(self):
        """Connected files (importers/importees) should be included."""
        graph = self._build_test_graph()
        result = graph.probe_environment("auth")
        # Routes imports auth, so should appear as connected
        connected = result["connected_files"]
        assert "src/routes/login.py" in connected or "src/models/user.py" in connected

    def test_probe_includes_relevant_domains(self):
        """Relevant domain clusters should be identified."""
        graph = self._build_test_graph()
        result = graph.probe_environment("auth")
        assert "auth" in result["relevant_domains"]

    def test_probe_no_match(self):
        """Query with no matches should return empty results."""
        graph = self._build_test_graph()
        result = graph.probe_environment("payment_gateway")
        assert len(result["direct_matches"]) == 0


class TestComponentMap(unittest.TestCase):
    """Test domain-grouped component map."""

    def test_all_clusters_returned(self):
        """Without filter, all clusters should be returned."""
        graph = CodeKnowledgeGraph(project_root="/tmp")
        graph.clusters = [
            DomainCluster(name="auth", files=["a.py", "b.py"], key_symbols=["Auth"]),
            DomainCluster(name="api", files=["c.py"], key_symbols=["Router"]),
        ]
        result = graph.get_component_map()
        assert len(result) == 2

    def test_domain_filter(self):
        """Domain filter should narrow results."""
        graph = CodeKnowledgeGraph(project_root="/tmp")
        graph.clusters = [
            DomainCluster(name="auth", files=["a.py"], key_symbols=["Auth"]),
            DomainCluster(name="api", files=["c.py"], key_symbols=["Router"]),
        ]
        result = graph.get_component_map("auth")
        assert len(result) == 1
        assert result[0]["name"] == "auth"


class TestIncrementalRefresh(unittest.TestCase):
    """Test incremental graph updates after file changes."""

    def setUp(self):
        self.builder = KnowledgeGraphBuilder()
        self.tmpdir = tempfile.mkdtemp()
        src = Path(self.tmpdir)
        (src / "models.py").write_text("class User:\n    pass\n")
        (src / "service.py").write_text(
            "from models import User\n\nclass UserService:\n    pass\n"
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_refresh_adds_new_file(self):
        """Refreshing with new file content should add it to the graph."""
        graph = self.builder.build(self.tmpdir)
        initial_count = graph.node_count

        # Add a new file
        new_content = "from models import User\n\ndef get_all_users():\n    pass\n"
        (Path(self.tmpdir) / "routes.py").write_text(new_content)

        self.builder.refresh_file(graph, "routes.py", new_content)
        assert graph.node_count == initial_count + 1
        assert "routes.py" in graph.nodes
        assert "get_all_users" in graph.nodes["routes.py"].symbols

    def test_refresh_updates_existing_file(self):
        """Refreshing an existing file should update its symbols."""
        graph = self.builder.build(self.tmpdir)

        # Modify models.py
        new_content = "class User:\n    pass\n\nclass Admin:\n    pass\n"
        self.builder.refresh_file(graph, "models.py", new_content)

        assert "Admin" in graph.nodes["models.py"].symbols

    def test_refresh_removes_deleted_file(self):
        """Refreshing after file deletion should remove the node."""
        graph = self.builder.build(self.tmpdir)
        assert "models.py" in graph.nodes

        # Delete the actual file, then refresh (simulates real usage)
        (Path(self.tmpdir) / "models.py").unlink()
        self.builder.refresh_file(graph, "models.py")
        assert "models.py" not in graph.nodes


class TestContextSection(unittest.TestCase):
    """Test context section rendering."""

    def test_empty_graph_minimal_output(self):
        """Empty graph should produce minimal context."""
        graph = CodeKnowledgeGraph(project_root="/tmp")
        section = graph.to_context_section()
        assert "0" in section  # Files analyzed: 0

    def test_graph_with_clusters_shows_domains(self):
        """Graph with clusters should list domain names."""
        graph = CodeKnowledgeGraph(project_root="/tmp")
        graph.nodes = {
            "a.py": GraphNode(path="a.py", language="py", symbols=["Foo"]),
        }
        graph.clusters = [
            DomainCluster(name="auth", files=["a.py"], key_symbols=["Foo"]),
        ]
        section = graph.to_context_section()
        assert "auth" in section
        assert "Foo" in section

    def test_context_respects_budget(self):
        """Context section should be truncated to max_chars."""
        graph = CodeKnowledgeGraph(project_root="/tmp")
        graph.clusters = [
            DomainCluster(
                name=f"domain_{i}",
                files=[f"file_{i}_{j}.py" for j in range(20)],
                key_symbols=[f"Sym_{i}_{j}" for j in range(10)],
            )
            for i in range(20)
        ]
        section = graph.to_context_section(max_chars=500)
        assert len(section) <= 600  # Allow small buffer for truncation message


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_empty_directory(self):
        """Building from empty directory should return empty graph."""
        with tempfile.TemporaryDirectory() as tmpdir:
            builder = KnowledgeGraphBuilder()
            graph = builder.build(tmpdir)
            assert graph.node_count == 0
            assert graph.edge_count == 0

    def test_nonexistent_directory(self):
        """Building from nonexistent directory should return empty graph."""
        builder = KnowledgeGraphBuilder()
        graph = builder.build("/nonexistent/path/that/doesnt/exist")
        assert graph.node_count == 0

    def test_binary_files_skipped(self):
        """Non-parseable extensions should be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "image.png").write_bytes(b"\x89PNG")
            (Path(tmpdir) / "data.csv").write_text("a,b,c\n1,2,3")
            (Path(tmpdir) / "code.py").write_text("x = 1\n")
            builder = KnowledgeGraphBuilder()
            graph = builder.build(tmpdir)
            assert graph.node_count == 1  # Only code.py
            assert "code.py" in graph.nodes

    def test_cluster_to_dict(self):
        """DomainCluster should serialize correctly."""
        cluster = DomainCluster(
            name="auth",
            files=["a.py", "b.py"],
            key_symbols=["Auth", "Login"],
        )
        d = cluster.to_dict()
        assert d["name"] == "auth"
        assert len(d["files"]) == 2
        assert "Auth" in d["key_symbols"]


if __name__ == "__main__":
    unittest.main()
