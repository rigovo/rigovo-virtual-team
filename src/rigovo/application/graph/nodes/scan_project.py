"""Scan project node — gives agents PERCEPTION of the codebase.

This node runs ONCE per task before agent execution. It scans the
project directory and builds an immutable
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
import hashlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from rigovo.application.cache_utils import CACHE_VERSION, stable_hash
from rigovo.application.context.project_scanner import ProjectScanner, ProjectSnapshot
from rigovo.application.graph.state import TaskState
from rigovo.domain.services.code_knowledge_graph import CodeKnowledgeGraph, KnowledgeGraphBuilder

logger = logging.getLogger(__name__)
SCANNER_ARTIFACT_VERSION = f"{CACHE_VERSION}:project_scanner:v1"
KNOWLEDGE_GRAPH_VERSION = f"{CACHE_VERSION}:knowledge_graph:v1"


def _git_cmd(project_root: str, *args: str) -> str:
    output = subprocess.check_output(
        ["git", "-C", project_root, *args],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return output.strip()


def _non_git_fingerprint(root: Path) -> str:
    """Lightweight fallback when workspace is not a git repo."""
    parts: list[tuple[str, int, int]] = []
    max_entries = 400
    for idx, path in enumerate(root.rglob("*")):
        if idx >= max_entries:
            break
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rel = str(path.relative_to(root))
        # Skip obviously irrelevant directories for cache invalidation.
        if rel.startswith((".git/", "node_modules/", "__pycache__/")):
            continue
        parts.append((rel, int(stat.st_size), int(stat.st_mtime_ns)))
    digest = hashlib.sha256(
        json.dumps(sorted(parts), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return digest


def _workspace_fingerprint(project_root: str) -> str:
    root = Path(project_root).expanduser().resolve()
    git_head = ""
    dirty_hash = ""
    try:
        git_head = _git_cmd(str(root), "rev-parse", "HEAD")
        dirty = _git_cmd(str(root), "status", "--porcelain")
        dirty_hash = hashlib.sha256(dirty.encode("utf-8")).hexdigest() if dirty else "clean"
    except Exception:
        git_head = "nogit"
        dirty_hash = _non_git_fingerprint(root)
    return stable_hash(
        {
            "root": str(root),
            "git_head": git_head,
            "dirty_hash": dirty_hash,
            "scanner_version": SCANNER_ARTIFACT_VERSION,
            "graph_version": KNOWLEDGE_GRAPH_VERSION,
        }
    )


async def scan_project_node(
    state: TaskState,
    scanner: ProjectScanner | None = None,
    cache_repo: Any | None = None,
) -> dict[str, Any]:
    """Scan the project and store snapshot + knowledge graph in state.

    This runs after early intent classification/routing so the UI can
    react quickly, but before execute_agent so agents still get full
    structural context.

    Two perception layers:
    1. ProjectSnapshot — file tree, tech stack, key config files
    2. CodeKnowledgeGraph — imports, exports, dependencies, domain clusters
    """
    await asyncio.sleep(0)  # Yield to event loop
    scanner = scanner or ProjectScanner()
    project_root = state.get("project_root", ".")
    workspace_id = str(state.get("workspace_id", "") or "")
    events = list(state.get("events", []))

    workspace_fingerprint = _workspace_fingerprint(project_root)
    snapshot: ProjectSnapshot | None = None
    knowledge_graph: CodeKnowledgeGraph | None = None
    rigour_conventions: str = ""

    if cache_repo is not None and workspace_id:
        cached_snapshot = await cache_repo.get_artifact(
            workspace_id=workspace_id,
            artifact_type="project_snapshot",
            workspace_fingerprint=workspace_fingerprint,
            version=SCANNER_ARTIFACT_VERSION,
        )
        cached_graph = await cache_repo.get_artifact(
            workspace_id=workspace_id,
            artifact_type="code_knowledge_graph",
            workspace_fingerprint=workspace_fingerprint,
            version=KNOWLEDGE_GRAPH_VERSION,
        )
        if cached_snapshot and cached_graph:
            try:
                snapshot = ProjectSnapshot(**(cached_snapshot.get("artifact") or {}))
                knowledge_graph = CodeKnowledgeGraph.from_dict(cached_graph.get("artifact") or {})
                events.append(
                    {
                        "type": "artifact_cache_hit",
                        "cache_source": "rigovo_exact",
                        "artifact_types": ["project_snapshot", "code_knowledge_graph"],
                    }
                )
                logger.info("Artifact cache hit for project scan at %s", project_root)
            except Exception:
                snapshot = None
                knowledge_graph = None
        else:
            missing = []
            if not cached_snapshot:
                missing.append("project_snapshot")
            if not cached_graph:
                missing.append("code_knowledge_graph")
            events.append(
                {
                    "type": "artifact_cache_miss",
                    "cache_source": "none",
                    "artifact_types": missing,
                }
            )

    if snapshot is None:
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

        # Enrich with Rigour semantic indexing (optional — graceful degradation)
        try:
            from rigovo.infrastructure.quality.rigour_gate import RigourQualityGate

            rigour_binary = RigourQualityGate._find_binary(project_root)
            if rigour_binary:
                cmd = RigourQualityGate._build_cmd(
                    rigour_binary, "index", "--semantic", "--json",
                )
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=project_root,
                )
                if result.returncode == 0 and result.stdout.strip():
                    semantic_data = json.loads(result.stdout)
                    knowledge_graph.merge_semantic_patterns(semantic_data)
                    logger.info(
                        "Rigour semantic index merged: %d clusters total",
                        len(knowledge_graph.clusters),
                    )
        except Exception:
            pass  # Rigour CLI not available or index failed — continue without it

        # Load project conventions from Rigour memory
        try:
            if rigour_binary:
                recall_cmd = RigourQualityGate._build_cmd(
                    rigour_binary, "recall",
                )
                recall_result = subprocess.run(
                    recall_cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=project_root,
                )
                if recall_result.returncode == 0 and recall_result.stdout.strip():
                    rigour_conventions = recall_result.stdout.strip()
                    logger.info(
                        "Rigour conventions loaded: %d chars",
                        len(rigour_conventions),
                    )
        except Exception:
            pass  # Graceful degradation

        if cache_repo is not None and workspace_id:
            await cache_repo.put_artifact(
                workspace_id=workspace_id,
                artifact_type="project_snapshot",
                workspace_fingerprint=workspace_fingerprint,
                version=SCANNER_ARTIFACT_VERSION,
                artifact={
                    "root": snapshot.root,
                    "tree": snapshot.tree,
                    "tech_stack": snapshot.tech_stack,
                    "key_file_contents": snapshot.key_file_contents,
                    "source_file_count": snapshot.source_file_count,
                    "total_file_count": snapshot.total_file_count,
                    "entry_points": snapshot.entry_points,
                    "test_directories": snapshot.test_directories,
                    "workspace_type": snapshot.workspace_type,
                    "is_rigovo_self": snapshot.is_rigovo_self,
                },
                metadata={"project_root": project_root},
                ttl_minutes=180,
            )
            await cache_repo.put_artifact(
                workspace_id=workspace_id,
                artifact_type="code_knowledge_graph",
                workspace_fingerprint=workspace_fingerprint,
                version=KNOWLEDGE_GRAPH_VERSION,
                artifact=knowledge_graph.to_dict(),
                metadata={"project_root": project_root},
                ttl_minutes=180,
            )

    return {
        "project_snapshot": snapshot,
        "code_knowledge_graph": knowledge_graph,
        "rigour_conventions": rigour_conventions,
        "status": "project_scanned",
        "events": [
            *events,
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
            },
        ],
    }
