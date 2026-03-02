"""Scan project node — gives agents PERCEPTION of the codebase.

This node runs ONCE at the start of every task, before any agent
executes. It scans the project directory and builds an immutable
snapshot that every agent in the pipeline receives.

Without this node, agents are blind. They have to guess what the
codebase looks like, hallucinate file paths, and assume patterns.

With this node, agents SEE:
- Project structure (file tree)
- Tech stack (Python? TypeScript? Docker?)
- Key config files (pyproject.toml, package.json, rigovo.yml)
- Entry points and test directories

This is the difference between "write code for a login page" (chatbot)
and "write code for a login page in THIS project with THESE patterns" (agent).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rigovo.application.context.project_scanner import ProjectScanner
from rigovo.application.graph.state import TaskState
from rigovo.domain.services.code_knowledge_graph import KnowledgeGraphBuilder

logger = logging.getLogger(__name__)


async def scan_project_node(
    state: TaskState,
    scanner: ProjectScanner | None = None,
) -> dict[str, Any]:
    """Scan the project and store snapshot + knowledge graph in state.

    This runs before classify so that classification also benefits
    from knowing the project structure (e.g., detecting language
    for tech stack-specific task routing).

    Two perception layers:
    1. ProjectSnapshot — file tree, tech stack, key config files
    2. CodeKnowledgeGraph — imports, exports, dependencies, domain clusters
    """
    await asyncio.sleep(0)  # Yield to event loop
    scanner = scanner or ProjectScanner()
    project_root = state.get("project_root", ".")

    logger.info("Scanning project at %s", project_root)
    snapshot = scanner.scan(project_root)

    logger.info(
        "Project scan complete: %d source files, %d total, stack: %s",
        snapshot.source_file_count,
        snapshot.total_file_count,
        ", ".join(snapshot.tech_stack) or "unknown",
    )

    # Build code knowledge graph — structural understanding of dependencies
    kg_builder = KnowledgeGraphBuilder()
    knowledge_graph = kg_builder.build(project_root)

    logger.info(
        "Knowledge graph built: %d nodes, %d edges, %d clusters",
        knowledge_graph.node_count,
        knowledge_graph.edge_count,
        len(knowledge_graph.clusters),
    )

    return {
        "project_snapshot": snapshot,
        "code_knowledge_graph": knowledge_graph,
        "status": "project_scanned",
        "events": state.get("events", [])
        + [
            {
                "type": "project_scanned",
                "source_files": snapshot.source_file_count,
                "total_files": snapshot.total_file_count,
                "tech_stack": snapshot.tech_stack,
                "entry_points": snapshot.entry_points,
                "test_dirs": snapshot.test_directories,
                "knowledge_graph_nodes": knowledge_graph.node_count,
                "knowledge_graph_edges": knowledge_graph.edge_count,
                "knowledge_graph_clusters": len(knowledge_graph.clusters),
            }
        ],
    }
