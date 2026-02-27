"""Master Agent — Context Enricher.

Analyzes completed agent executions and extracts reusable context
(pitfalls, patterns, conventions) that gets injected into future
agent prompts via EnrichmentContext.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from rigovo.domain.entities.agent import Agent, EnrichmentContext
from rigovo.domain.entities.quality import GateResult
from rigovo.domain.interfaces.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

ENRICHER_SYSTEM_PROMPT = """\
You are a learning engine for a virtual engineering team.

After each agent execution, you analyze what happened and extract
reusable knowledge. This knowledge will be injected into future
agent prompts to improve performance over time.

Given an agent execution summary, quality gate results, and any
previous enrichment context, produce updated enrichment data.

Categories:
- known_pitfalls: Mistakes this agent made that should be avoided
- domain_knowledge: Patterns, conventions, or facts learned
- pre_check_rules: Quick checks the agent should do before submitting
- workspace_conventions: Project-specific conventions discovered

Respond ONLY with valid JSON:
{
  "known_pitfalls": ["pitfall 1", "pitfall 2"],
  "domain_knowledge": ["knowledge 1"],
  "pre_check_rules": ["rule 1"],
  "workspace_conventions": ["convention 1"],
  "reasoning": "brief explanation of what was learned"
}

Rules:
- Only add genuinely useful, specific items
- Don't repeat existing items
- Keep each item to 1-2 sentences
- Focus on actionable, concrete knowledge
- Max 5 items per category per enrichment cycle
"""


@dataclass
class EnrichmentUpdate:
    """Result of an enrichment analysis."""

    known_pitfalls: list[str] = field(default_factory=list)
    domain_knowledge: list[str] = field(default_factory=list)
    pre_check_rules: list[str] = field(default_factory=list)
    workspace_conventions: list[str] = field(default_factory=list)
    reasoning: str = ""


class ContextEnricher:
    """
    Learns from agent executions and updates enrichment context.

    This is the Master Agent's learning loop. After each task
    completes (or fails), we analyze what happened and extract
    knowledge that makes future executions better.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def analyze_execution(
        self,
        agent: Agent,
        execution_summary: str,
        gate_result: GateResult | None = None,
        files_changed: list[str] | None = None,
    ) -> EnrichmentUpdate:
        """Analyze a completed agent execution and extract learnings."""
        context_parts = [
            f"Agent: {agent.name} (role: {agent.role})",
            f"\nExecution Summary:\n{execution_summary}",
        ]

        if gate_result:
            context_parts.append(f"\nQuality Gate: {gate_result.status.value}")
            if gate_result.violations:
                violations_text = "\n".join(
                    f"  - [{v.severity.value}] {v.rule}: {v.message}"
                    for v in gate_result.violations[:10]
                )
                context_parts.append(f"Violations:\n{violations_text}")

        if files_changed:
            context_parts.append(f"\nFiles Changed: {', '.join(files_changed[:20])}")

        if agent.enrichment:
            context_parts.append(f"\nCurrent Enrichment:\n{agent.enrichment.to_prompt_section()}")

        response = await self._llm.invoke(
            messages=[
                {"role": "system", "content": ENRICHER_SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(context_parts)},
            ],
            temperature=0.1,
            max_tokens=1024,
        )

        return self._parse_response(response.content)

    def merge_enrichment(
        self,
        existing: EnrichmentContext | None,
        update: EnrichmentUpdate,
        max_items_per_category: int = 15,
    ) -> EnrichmentContext:
        """Merge new learnings into existing enrichment context."""
        if existing is None:
            existing = EnrichmentContext()

        def _merge_list(existing_items: list[str], new_items: list[str]) -> list[str]:
            """Add new items, deduplicate, and cap at max."""
            combined = list(existing_items)  # preserve order
            existing_lower = {item.lower() for item in combined}
            for item in new_items:
                if item.lower() not in existing_lower:
                    combined.append(item)
                    existing_lower.add(item.lower())
            # Keep most recent if over limit
            return combined[-max_items_per_category:]

        return EnrichmentContext(
            common_mistakes=_merge_list(existing.common_mistakes, update.known_pitfalls),
            domain_knowledge=_merge_list(existing.domain_knowledge, update.domain_knowledge),
            pre_check_rules=_merge_list(existing.pre_check_rules, update.pre_check_rules),
            workspace_conventions=_merge_list(
                existing.workspace_conventions, update.workspace_conventions
            ),
        )

    def _parse_response(self, content: str) -> EnrichmentUpdate:
        """Parse LLM response into EnrichmentUpdate."""
        try:
            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            data = json.loads(text)

            return EnrichmentUpdate(
                known_pitfalls=data.get("known_pitfalls", [])[:5],
                domain_knowledge=data.get("domain_knowledge", [])[:5],
                pre_check_rules=data.get("pre_check_rules", [])[:5],
                workspace_conventions=data.get("workspace_conventions", [])[:5],
                reasoning=data.get("reasoning", ""),
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to parse enrichment: %s", e)
            return EnrichmentUpdate(reasoning=f"Parse failed: {e}")
