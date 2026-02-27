"""Context engineering — the brain that makes agents intelligent.

Unlike prompt-based chatbots that just see a system prompt + task,
intelligent agents SEE the codebase, REMEMBER past tasks, and
LEARN from quality gate feedback.

This package provides:
- ProjectScanner: Reads project structure and key files
- ContextBuilder: Assembles rich per-agent context
- MemoryRetriever: Fetches relevant past learnings
"""

from rigovo.application.context.context_builder import AgentContext, ContextBuilder
from rigovo.application.context.memory_retriever import MemoryRetriever
from rigovo.application.context.project_scanner import ProjectScanner, ProjectSnapshot

__all__ = [
    "AgentContext",
    "ContextBuilder",
    "MemoryRetriever",
    "ProjectScanner",
    "ProjectSnapshot",
]
