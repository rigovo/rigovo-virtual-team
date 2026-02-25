"""Master Agent — Task Classifier.

Analyzes a natural-language task description and returns structured
classification (task type + complexity) so the router and assembler
can build the right agent pipeline.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from rigovo.domain.entities.task import TaskComplexity, TaskType
from rigovo.domain.interfaces.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

CLASSIFIER_SYSTEM_PROMPT = """\
You are a task classifier for a virtual engineering team platform.

Given a task description, classify it into EXACTLY:
1. task_type — one of: feature, bug, refactor, test, docs, infra, security, performance, investigation
2. complexity — one of: low, medium, high, critical

Classification rules:
- feature: New functionality, endpoints, UI components, integrations
- bug: Fixing broken behavior, error resolution, regression fixes
- refactor: Code restructuring without behavior change, tech debt
- test: Adding/fixing tests, test infrastructure, coverage improvement
- docs: README, API docs, inline docs, architecture docs
- infra: CI/CD, deployment, Docker, infrastructure-as-code
- security: Vulnerability assessment, dependency audit, pen testing
- performance: Optimization, profiling, caching, scaling
- investigation: Research, exploration, debugging, analysis

Complexity rules:
- low: Single file, < 1 hour, well-defined scope
- medium: 2-5 files, few hours, clear but multi-step
- high: 5-15 files, multi-day, cross-cutting concerns, needs planning
- critical: System-wide, multi-week, architectural, needs approval gates

Respond ONLY with valid JSON:
{"task_type": "...", "complexity": "...", "reasoning": "one sentence why"}
"""


@dataclass
class ClassificationResult:
    """Result of task classification."""

    task_type: TaskType
    complexity: TaskComplexity
    reasoning: str


class TaskClassifier:
    """
    Uses LLM to classify task descriptions.

    Part of the Master Agent's brain. Called during the classify
    node of the task pipeline graph.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def classify(self, description: str) -> ClassificationResult:
        """Classify a task description into type and complexity."""
        response = await self._llm.invoke(
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": f"Classify this task:\n\n{description}"},
            ],
            temperature=0.0,
            max_tokens=256,
        )

        return self._parse_response(response.content)

    def _parse_response(self, content: str) -> ClassificationResult:
        """Parse LLM JSON response into ClassificationResult."""
        try:
            # Strip markdown code fences if present
            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            data = json.loads(text)

            task_type = TaskType(data["task_type"])
            complexity = TaskComplexity(data["complexity"])
            reasoning = data.get("reasoning", "")

            return ClassificationResult(
                task_type=task_type,
                complexity=complexity,
                reasoning=reasoning,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse classification: %s — %s", e, content[:200])
            # Safe defaults
            return ClassificationResult(
                task_type=TaskType.FEATURE,
                complexity=TaskComplexity.MEDIUM,
                reasoning=f"Classification parse failed, using defaults: {e}",
            )
