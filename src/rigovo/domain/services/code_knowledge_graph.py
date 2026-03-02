"""Code Knowledge Graph — structural understanding of the codebase.

This replaces "search and pray" with "know the architecture."

A real engineer doesn't grep for code. They have a MENTAL MODEL:
- "UserService depends on AuthProvider and DatabasePool"
- "Changing BaseModel affects 47 files"
- "The auth domain spans 5 files across 3 directories"

This module builds that mental model as a lightweight graph:
- Nodes = source files
- Edges = import/dependency relationships
- Clusters = domain groups (files that share common imports)

Built at scan time (<100ms for typical projects), stored in state,
and exposed to agents via `get_component_map`, `get_impact_radius`,
and `probe_environment` tools.

Design invariants:
- Zero LLM calls — pure static analysis
- Language-aware import parsing (Python, TypeScript, JavaScript, Go)
- Incremental refresh — after coder writes files, graph updates in-place
- Budget-bounded — max 1000 nodes, max 5000 edges
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --- Graph limits ---
MAX_GRAPH_NODES = 1000
MAX_GRAPH_EDGES = 5000
MAX_FILE_SIZE_FOR_PARSE = 200_000  # 200KB — skip generated files

# Directories to skip
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "coverage", "htmlcov", ".eggs", ".terraform", ".serverless",
}

# Source file extensions we can parse for imports
PARSEABLE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs",
}

# --- Import parsing patterns per language ---

# Python: from X import Y, import X
_PY_IMPORT = re.compile(
    r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
    re.MULTILINE,
)

# TypeScript/JavaScript: import ... from 'X', require('X')
_TS_IMPORT = re.compile(
    r"""(?:import\s+.*?from\s+['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))""",
    re.MULTILINE,
)

# Go: import "path" or import ( "path" )
_GO_IMPORT = re.compile(
    r"""import\s+(?:\(\s*((?:"[^"]+"\s*)+)\)|"([^"]+)")""",
    re.MULTILINE | re.DOTALL,
)

# --- Symbol extraction patterns ---

# Python: class X, def X
_PY_SYMBOL = re.compile(
    r"^(?:class|def)\s+(\w+)",
    re.MULTILINE,
)

# TypeScript/JavaScript: export class X, export function X, export const X,
# export default class X, export interface X, export type X
_TS_SYMBOL = re.compile(
    r"^export\s+(?:default\s+)?(?:class|function|const|let|var|interface|type|enum)\s+(\w+)",
    re.MULTILINE,
)

# Go: func X, type X struct
_GO_SYMBOL = re.compile(
    r"^(?:func\s+(?:\([^)]+\)\s+)?(\w+)|type\s+(\w+)\s+(?:struct|interface))",
    re.MULTILINE,
)


@dataclass
class GraphNode:
    """A source file in the knowledge graph."""

    path: str  # Relative path from project root
    language: str  # py, ts, js, go, rs
    symbols: list[str] = field(default_factory=list)  # Exported/top-level symbols
    imports: list[str] = field(default_factory=list)  # Raw import strings
    line_count: int = 0
    size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "symbols": self.symbols,
            "imports": self.imports,
            "line_count": self.line_count,
            "size_bytes": self.size_bytes,
        }


@dataclass
class GraphEdge:
    """A dependency edge: source imports target."""

    source: str  # File path that imports
    target: str  # File path being imported
    import_string: str  # The raw import statement


@dataclass
class DomainCluster:
    """A group of files that form a logical domain/module.

    Clustered by shared directory prefix and import proximity.
    """

    name: str  # Domain name (e.g., "auth", "api", "models")
    files: list[str] = field(default_factory=list)
    key_symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "files": self.files,
            "key_symbols": self.key_symbols,
        }


@dataclass
class CodeKnowledgeGraph:
    """The complete structural model of a codebase.

    Built once at scan time, refreshable when files change.
    Exposed to agents through tools for intelligent code navigation.
    """

    project_root: str
    nodes: dict[str, GraphNode] = field(default_factory=dict)  # path -> node
    edges: list[GraphEdge] = field(default_factory=list)
    clusters: list[DomainCluster] = field(default_factory=list)
    # Reverse index: path -> list of files that import it
    reverse_deps: dict[str, list[str]] = field(default_factory=dict)
    # Forward index: path -> list of files it imports
    forward_deps: dict[str, list[str]] = field(default_factory=dict)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def get_component_map(self, domain_filter: str = "") -> list[dict[str, Any]]:
        """Return components grouped by domain cluster.

        If domain_filter is provided, only return clusters whose name
        contains the filter string (case-insensitive).
        """
        result = []
        for cluster in self.clusters:
            if domain_filter and domain_filter.lower() not in cluster.name.lower():
                continue
            result.append(cluster.to_dict())
        return result

    def get_impact_radius(self, file_path: str, max_depth: int = 3) -> dict[str, Any]:
        """Given a file, return all files that would be affected by changes.

        Uses the reverse dependency graph to find transitive dependents.
        Returns files grouped by distance (direct, 2nd-order, 3rd-order).
        """
        if file_path not in self.nodes:
            return {"error": f"File not in graph: {file_path}", "levels": {}}

        visited: set[str] = {file_path}
        levels: dict[int, list[str]] = {}
        current_level = [file_path]

        for depth in range(1, max_depth + 1):
            next_level: list[str] = []
            for f in current_level:
                for dep in self.reverse_deps.get(f, []):
                    if dep not in visited:
                        visited.add(dep)
                        next_level.append(dep)
            if next_level:
                levels[depth] = sorted(next_level)
            current_level = next_level

        # Also include what this file depends on (forward deps)
        direct_deps = self.forward_deps.get(file_path, [])

        node = self.nodes.get(file_path)
        return {
            "file": file_path,
            "symbols": node.symbols if node else [],
            "direct_dependents": levels.get(1, []),
            "transitive_dependents": {
                f"depth_{k}": v for k, v in levels.items() if k > 1
            },
            "depends_on": sorted(direct_deps),
            "total_affected": len(visited) - 1,  # Exclude self
        }

    def probe_environment(self, query: str) -> dict[str, Any]:
        """Semantic probe: find everything related to a concept.

        Combines:
        1. File path matching (e.g., "auth" matches files in auth/ directory)
        2. Symbol matching (e.g., "auth" matches AuthProvider, authenticate)
        3. Import chain following (files connected to matching files)

        This is what makes an agent intelligent — it doesn't just grep,
        it understands RELATIONSHIPS.
        """
        query_lower = query.lower()
        query_parts = query_lower.split()

        # Phase 1: Direct matches (file paths and symbols)
        direct_matches: list[str] = []
        symbol_matches: dict[str, list[str]] = {}  # path -> matching symbols

        for path, node in self.nodes.items():
            path_lower = path.lower()
            # Check if any query part appears in path
            if any(part in path_lower for part in query_parts):
                direct_matches.append(path)

            # Check symbols
            matching_syms = [
                s for s in node.symbols
                if any(part in s.lower() for part in query_parts)
            ]
            if matching_syms:
                symbol_matches[path] = matching_syms
                if path not in direct_matches:
                    direct_matches.append(path)

        # Phase 2: Connected files (1 hop from direct matches)
        connected: set[str] = set()
        for match_path in direct_matches:
            # Files that import the matching file
            for dep in self.reverse_deps.get(match_path, []):
                connected.add(dep)
            # Files the matching file imports
            for dep in self.forward_deps.get(match_path, []):
                connected.add(dep)

        connected -= set(direct_matches)

        # Phase 3: Cluster the results
        relevant_clusters = []
        for cluster in self.clusters:
            if any(f in direct_matches for f in cluster.files):
                relevant_clusters.append(cluster.name)

        return {
            "query": query,
            "direct_matches": sorted(direct_matches),
            "matching_symbols": symbol_matches,
            "connected_files": sorted(connected),
            "relevant_domains": relevant_clusters,
            "total_related": len(direct_matches) + len(connected),
        }

    def to_context_section(self, max_chars: int = 3000) -> str:
        """Render graph summary for agent context injection."""
        parts = ["--- CODE ARCHITECTURE (knowledge graph) ---"]
        parts.append(
            f"Files analyzed: {self.node_count} | "
            f"Dependencies: {self.edge_count} | "
            f"Domains: {len(self.clusters)}"
        )

        if self.clusters:
            parts.append("\nDomain clusters:")
            for cluster in self.clusters[:15]:  # Cap at 15 clusters
                files_str = ", ".join(cluster.files[:5])
                if len(cluster.files) > 5:
                    files_str += f" (+{len(cluster.files) - 5} more)"
                symbols_str = ", ".join(cluster.key_symbols[:8])
                parts.append(f"  [{cluster.name}] {files_str}")
                if symbols_str:
                    parts.append(f"    Key symbols: {symbols_str}")

        result = "\n".join(parts)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (architecture summary truncated)"
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage in graph state."""
        return {
            "project_root": self.project_root,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "nodes": {p: n.to_dict() for p, n in self.nodes.items()},
            "clusters": [c.to_dict() for c in self.clusters],
            "reverse_deps": dict(self.reverse_deps),
            "forward_deps": dict(self.forward_deps),
        }


class KnowledgeGraphBuilder:
    """Builds a CodeKnowledgeGraph from a project directory.

    Runs at scan time alongside ProjectScanner. Pure static analysis,
    no LLM calls, completes in <100ms for typical projects.
    """

    def build(self, project_root: str) -> CodeKnowledgeGraph:
        """Build the complete knowledge graph."""
        root = Path(project_root)
        if not root.is_dir():
            return CodeKnowledgeGraph(project_root=project_root)

        graph = CodeKnowledgeGraph(project_root=project_root)

        # Phase 1: Collect all source files and parse imports/symbols
        self._collect_nodes(root, root, graph)

        if graph.node_count > MAX_GRAPH_NODES:
            logger.warning(
                "Knowledge graph capped at %d nodes (found %d files)",
                MAX_GRAPH_NODES, graph.node_count,
            )

        # Phase 2: Resolve imports to file paths (create edges)
        self._resolve_edges(root, graph)

        # Phase 3: Build reverse/forward dependency indexes
        self._build_indexes(graph)

        # Phase 4: Cluster files into domains
        self._cluster_domains(graph)

        logger.info(
            "Knowledge graph built: %d nodes, %d edges, %d clusters",
            graph.node_count, graph.edge_count, len(graph.clusters),
        )

        return graph

    def refresh_file(
        self,
        graph: CodeKnowledgeGraph,
        file_path: str,
        content: str | None = None,
    ) -> None:
        """Incrementally update the graph after a file is created/modified.

        This is called after the coder writes a file, so subsequent agents
        (reviewer, QA) see the updated architecture.
        """
        root = Path(graph.project_root)
        full_path = root / file_path

        if content is None and full_path.is_file():
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return

        if content is None:
            # File deleted — remove node and edges
            self._remove_node(graph, file_path)
            return

        # Parse the file
        ext = Path(file_path).suffix
        language = self._ext_to_language(ext)
        if not language:
            return

        lines = content.splitlines()
        symbols = self._extract_symbols(content, language)
        imports = self._extract_imports(content, language)

        # Update or create node
        graph.nodes[file_path] = GraphNode(
            path=file_path,
            language=language,
            symbols=symbols,
            imports=imports,
            line_count=len(lines),
            size_bytes=len(content.encode("utf-8")),
        )

        # Remove old edges from this file
        graph.edges = [e for e in graph.edges if e.source != file_path]

        # Re-resolve edges for this file
        self._resolve_file_edges(root, graph, file_path, imports, language)

        # Rebuild indexes
        self._build_indexes(graph)

        # Re-cluster (lightweight — just reassign the changed file)
        self._cluster_domains(graph)

    def _collect_nodes(
        self,
        directory: Path,
        root: Path,
        graph: CodeKnowledgeGraph,
        depth: int = 0,
    ) -> None:
        """Recursively collect source files and parse them."""
        if depth > 8:  # Deeper than typical projects
            return
        if graph.node_count >= MAX_GRAPH_NODES:
            return

        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return

        for entry in entries:
            if entry.name in SKIP_DIRS or entry.name.startswith("."):
                continue

            if entry.is_dir():
                self._collect_nodes(entry, root, graph, depth + 1)
            elif entry.is_file() and entry.suffix in PARSEABLE_EXTENSIONS:
                if graph.node_count >= MAX_GRAPH_NODES:
                    return

                try:
                    size = entry.stat().st_size
                    if size > MAX_FILE_SIZE_FOR_PARSE:
                        continue

                    content = entry.read_text(encoding="utf-8", errors="replace")
                    rel_path = str(entry.relative_to(root))
                    language = self._ext_to_language(entry.suffix)

                    if language:
                        symbols = self._extract_symbols(content, language)
                        imports = self._extract_imports(content, language)

                        graph.nodes[rel_path] = GraphNode(
                            path=rel_path,
                            language=language,
                            symbols=symbols,
                            imports=imports,
                            line_count=len(content.splitlines()),
                            size_bytes=size,
                        )
                except (OSError, UnicodeDecodeError):
                    continue

    def _extract_symbols(self, content: str, language: str) -> list[str]:
        """Extract top-level symbols (classes, functions, types) from source."""
        symbols: list[str] = []

        if language == "py":
            for match in _PY_SYMBOL.finditer(content):
                name = match.group(1)
                if not name.startswith("_"):
                    symbols.append(name)
        elif language in ("ts", "js"):
            for match in _TS_SYMBOL.finditer(content):
                symbols.append(match.group(1))
        elif language == "go":
            for match in _GO_SYMBOL.finditer(content):
                name = match.group(1) or match.group(2)
                if name and name[0].isupper():  # Go exports are capitalized
                    symbols.append(name)

        return symbols[:50]  # Cap to prevent huge symbol lists

    def _extract_imports(self, content: str, language: str) -> list[str]:
        """Extract import statements from source code."""
        imports: list[str] = []

        if language == "py":
            for match in _PY_IMPORT.finditer(content):
                module = match.group(1) or match.group(2)
                if module:
                    imports.append(module)
        elif language in ("ts", "js"):
            for match in _TS_IMPORT.finditer(content):
                path = match.group(1) or match.group(2)
                if path:
                    imports.append(path)
        elif language == "go":
            for match in _GO_IMPORT.finditer(content):
                block = match.group(1)
                single = match.group(2)
                if block:
                    for imp in re.findall(r'"([^"]+)"', block):
                        imports.append(imp)
                elif single:
                    imports.append(single)

        return imports[:100]  # Cap

    def _resolve_edges(self, root: Path, graph: CodeKnowledgeGraph) -> None:
        """Convert raw import strings to file-level edges."""
        for path, node in graph.nodes.items():
            if graph.edge_count >= MAX_GRAPH_EDGES:
                break
            self._resolve_file_edges(root, graph, path, node.imports, node.language)

    def _resolve_file_edges(
        self,
        root: Path,
        graph: CodeKnowledgeGraph,
        source_path: str,
        imports: list[str],
        language: str,
    ) -> None:
        """Resolve imports for a single file into edges."""
        for imp in imports:
            if graph.edge_count >= MAX_GRAPH_EDGES:
                return

            target = self._resolve_import_to_path(root, source_path, imp, language, graph)
            if target and target != source_path and target in graph.nodes:
                graph.edges.append(GraphEdge(
                    source=source_path,
                    target=target,
                    import_string=imp,
                ))

    def _resolve_import_to_path(
        self,
        root: Path,
        source_path: str,
        import_str: str,
        language: str,
        graph: CodeKnowledgeGraph,
    ) -> str | None:
        """Resolve an import string to a file path in the graph.

        This is language-aware:
        - Python: 'rigovo.domain.services.tools' -> 'src/rigovo/domain/services/tools.py'
        - TS/JS: './utils' -> 'src/utils.ts' or 'src/utils/index.ts'
        - Go: Uses module path (less reliable for relative resolution)
        """
        if language == "py":
            return self._resolve_python_import(import_str, graph)
        elif language in ("ts", "js"):
            return self._resolve_ts_import(root, source_path, import_str, graph)
        return None

    def _resolve_python_import(
        self,
        import_str: str,
        graph: CodeKnowledgeGraph,
    ) -> str | None:
        """Resolve Python dotted import to a file path."""
        # Convert dots to path separators
        # 'rigovo.domain.services.tools' -> 'rigovo/domain/services/tools'
        path_parts = import_str.replace(".", "/")

        # Try direct module file
        candidates = [
            f"{path_parts}.py",
            f"src/{path_parts}.py",
            f"{path_parts}/__init__.py",
            f"src/{path_parts}/__init__.py",
        ]

        for candidate in candidates:
            if candidate in graph.nodes:
                return candidate

        return None

    def _resolve_ts_import(
        self,
        root: Path,
        source_path: str,
        import_str: str,
        graph: CodeKnowledgeGraph,
    ) -> str | None:
        """Resolve TypeScript/JavaScript import to a file path."""
        # Skip external packages
        if not import_str.startswith(".") and not import_str.startswith("@/"):
            return None

        # Resolve relative to source file
        source_dir = str(Path(source_path).parent)

        if import_str.startswith("@/"):
            # Common alias for src/
            resolved = import_str.replace("@/", "src/", 1)
        elif import_str.startswith("."):
            resolved = str(Path(source_dir) / import_str)
            # Normalize path
            resolved = str(Path(resolved))
        else:
            return None

        # Try extensions
        extensions = [".ts", ".tsx", ".js", ".jsx"]
        candidates = [resolved + ext for ext in extensions]
        candidates.append(resolved + "/index.ts")
        candidates.append(resolved + "/index.tsx")
        candidates.append(resolved + "/index.js")

        for candidate in candidates:
            # Normalize the candidate path
            normalized = str(Path(candidate))
            if normalized in graph.nodes:
                return normalized

        return None

    def _build_indexes(self, graph: CodeKnowledgeGraph) -> None:
        """Build reverse and forward dependency indexes from edges."""
        graph.reverse_deps = {}
        graph.forward_deps = {}

        for edge in graph.edges:
            # Forward: source -> targets it imports
            if edge.source not in graph.forward_deps:
                graph.forward_deps[edge.source] = []
            graph.forward_deps[edge.source].append(edge.target)

            # Reverse: target -> files that import it
            if edge.target not in graph.reverse_deps:
                graph.reverse_deps[edge.target] = []
            graph.reverse_deps[edge.target].append(edge.source)

    def _cluster_domains(self, graph: CodeKnowledgeGraph) -> None:
        """Group files into domain clusters by directory structure.

        Uses directory prefixes to create natural clusters:
        - src/auth/*.py -> "auth" cluster
        - src/api/*.py -> "api" cluster
        - tests/ -> "tests" cluster
        """
        clusters: dict[str, DomainCluster] = {}

        for path, node in graph.nodes.items():
            # Extract domain from path
            parts = Path(path).parts
            if len(parts) <= 1:
                domain = "root"
            elif parts[0] in ("src", "lib", "app", "apps"):
                # Skip the src/ prefix, use the next meaningful directory
                domain = parts[1] if len(parts) > 1 else "root"
                # For deeper nesting like src/rigovo/domain/services, use 2nd level
                if len(parts) > 2 and parts[1] in graph.nodes.get(path, GraphNode(path="", language="")).path:
                    domain = parts[1]
            elif parts[0] in ("tests", "test", "spec", "__tests__"):
                domain = "tests"
            else:
                domain = parts[0]

            if domain not in clusters:
                clusters[domain] = DomainCluster(name=domain)

            clusters[domain].files.append(path)

            # Collect key symbols (public/exported names)
            for sym in node.symbols[:3]:  # Top 3 symbols per file
                if sym not in clusters[domain].key_symbols:
                    clusters[domain].key_symbols.append(sym)

        # Sort clusters by file count (largest first)
        graph.clusters = sorted(
            clusters.values(),
            key=lambda c: len(c.files),
            reverse=True,
        )

        # Cap key_symbols per cluster
        for cluster in graph.clusters:
            cluster.key_symbols = cluster.key_symbols[:20]

    def _remove_node(self, graph: CodeKnowledgeGraph, file_path: str) -> None:
        """Remove a node and its edges from the graph."""
        graph.nodes.pop(file_path, None)
        graph.edges = [
            e for e in graph.edges
            if e.source != file_path and e.target != file_path
        ]
        self._build_indexes(graph)

    def _ext_to_language(self, ext: str) -> str | None:
        """Map file extension to language identifier."""
        mapping = {
            ".py": "py",
            ".ts": "ts",
            ".tsx": "ts",
            ".js": "js",
            ".jsx": "js",
            ".go": "go",
            ".rs": "rs",
        }
        return mapping.get(ext)
