"""Classify node — Deterministic Brain + Master Agent (Distinguished Engineer).

Two-phase classification:
1. **Deterministic Brain** (<50ms): Two-pass semantic classifier
   (regex + vector similarity) produces an INSTANT classification floor.
   This fires a ``deterministic_classified`` event so the UI can show
   the task type immediately.

2. **Master Agent LLM** (10-30s): Full SME analysis that produces a
   staffing plan.  The LLM receives the deterministic result as a hint
   and can upgrade (e.g., feature → security) but NEVER downgrade the
   classification or produce fewer agents than the minimum team table.

Output is stored in ``state["staffing_plan"]`` (new) and
``state["classification"]`` (backward-compatible).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from rigovo.application.cache_utils import stable_hash, usage_to_dict
from rigovo.application.graph.state import TaskState
from rigovo.application.master.classifier import (
    StaffingPlan,
    TaskClassifier,
)
from rigovo.application.master.deterministic_brain import (
    classify_semantic,
    enforce_minimum_team,
)
from rigovo.domain.interfaces.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


def _enum_or_str_value(value: Any) -> str:
    """Normalize StrEnum/string values from classifier outputs."""
    return str(getattr(value, "value", value))


def _master_decision_event(
    plan_dict: dict[str, Any], classification: dict[str, Any]
) -> dict[str, Any]:
    """Build a durable supervisory event from the final Master staffing plan."""
    return {
        "type": "master_decision",
        "task_type": classification.get("task_type"),
        "complexity": classification.get("complexity"),
        "workspace_type": classification.get("workspace_type"),
        "execution_mode": plan_dict.get("execution_mode", "linear"),
        "summary": plan_dict.get("reasoning", ""),
        "topology": {
            "parallel_groups": plan_dict.get("parallel_groups", []),
            "execution_dag": plan_dict.get("execution_dag", {}),
        },
        "mandatory_consultations": plan_dict.get("consultation_requirements", []),
        "spawn_candidates": plan_dict.get("spawn_candidates", []),
        "required_approvals": plan_dict.get("required_approvals", []),
        "risk_actions": plan_dict.get("risk_actions", []),
        "supervision_checkpoints": plan_dict.get("supervision_checkpoints", []),
    }


def _classifier_timeout_seconds() -> int:
    """Runtime-configurable timeout for Master Agent classification."""
    raw = os.environ.get("RIGOVO_CLASSIFIER_TIMEOUT_SECONDS", "25").strip()
    try:
        value = int(raw)
    except ValueError:
        return 25
    return max(5, min(value, 120))


# Lightweight fallback prompt (used when no classifier is injected)
CLASSIFICATION_PROMPT = """\
You are a task classifier for a software engineering team.

Given a task description, determine:
1. task_type: one of [feature, bug, refactor, test, docs, infra, security, performance, \
investigation, new_project]
   - Use "new_project" when the task is to CREATE a new project from scratch (e.g.
     "build a Flask app", "create a React app", "write a CLI tool", "init a project")
   - Use "feature" for adding functionality to an EXISTING project
2. complexity: one of [low, medium, high, critical]
3. workspace_type: one of [new_project, existing_project, new_subfolder_project]
   - "new_project" = blank workspace, build the full project structure from scratch
   - "existing_project" = workspace has established code, match existing patterns
   - "new_subfolder_project" = workspace already has code, but the user wants a
     new product in a new child folder
4. reasoning: a brief explanation

Respond with ONLY valid JSON:
{
    "task_type": "...",
    "complexity": "...",
    "workspace_type": "...",
    "reasoning": "..."
}
"""


async def classify_node(
    state: TaskState,
    llm: LLMProvider,
    classifier: TaskClassifier | None = None,
    embedding_provider: Any | None = None,
    cache_repo: Any | None = None,
) -> dict[str, Any]:
    """Run classification: Deterministic Brain first, then Master Agent LLM.

    Phase 1 (instant): Deterministic two-pass classification (regex + vector).
    Phase 2 (LLM): Full SME analysis with staffing plan, guided by Phase 1 hint.

    The deterministic result is a FLOOR — the LLM can add agents and
    upgrade complexity but can NEVER produce a team below the minimum
    team table or downgrade the task type.
    """
    description = state["description"]
    project_snapshot = state.get("project_snapshot")
    events = list(state.get("events", []))

    # ══════════════════════════════════════════════════════════════════
    # PHASE 1: Deterministic Brain — instant (<50ms, zero LLM calls)
    # ══════════════════════════════════════════════════════════════════
    det_result = await classify_semantic(description, embedding_provider)

    deterministic_classification = {
        "task_type": det_result.task_type,
        "complexity": det_result.complexity,
        "confidence": det_result.confidence,
        "matched_pattern": det_result.matched_pattern,
        "is_deterministic": det_result.is_deterministic,
    }

    # Emit deterministic event IMMEDIATELY (UI shows instant classification)
    events.append(
        {
            "type": "deterministic_classified",
            "task_type": det_result.task_type,
            "complexity": det_result.complexity,
            "confidence": det_result.confidence,
            "source": "regex" if det_result.is_deterministic else "semantic",
            "matched_pattern": det_result.matched_pattern,
        }
    )

    logger.info(
        "Deterministic Brain: type=%s complexity=%s confidence=%.2f pattern=%r",
        det_result.task_type,
        det_result.complexity,
        det_result.confidence,
        det_result.matched_pattern,
    )

    # ══════════════════════════════════════════════════════════════════
    # PHASE 2: Master Agent LLM — full SME analysis
    # Deterministic classification is a floor and fallback, not the final
    # brain. When a Master classifier exists, it must review the task.
    # ══════════════════════════════════════════════════════════════════

    if classifier is not None:
        try:
            plan: StaffingPlan = await asyncio.wait_for(
                classifier.analyze(
                    description,
                    project_snapshot=project_snapshot,
                    deterministic_hint=deterministic_classification,
                ),
                timeout=_classifier_timeout_seconds(),
            )
        except TimeoutError:
            logger.warning(
                "Master classification timed out after %ss; using deterministic fallback",
                _classifier_timeout_seconds(),
            )
            fast_agents = enforce_minimum_team(
                [],
                task_type=det_result.task_type,
                description=description,
            )
            classification = {
                "task_type": det_result.task_type,
                "complexity": det_result.complexity,
                "reasoning": "Master classification timed out; used deterministic fallback.",
            }
            classification = _normalize_greenfield_classification(state, classification)
            plan_dict = {
                "task_type": det_result.task_type,
                "complexity": det_result.complexity,
                "workspace_type": classification["workspace_type"],
                "execution_mode": "linear",
                "domain_analysis": "Deterministic fallback after classifier timeout.",
                "architecture_notes": "",
                "agents": fast_agents,
                "consultation_requirements": [],
                "spawn_candidates": [],
                "completion_contract": [],
                "risk_actions": [],
                "required_approvals": [],
                "supervision_checkpoints": [],
                "risks": ["Master classifier timeout; plan may be less specialized."],
                "acceptance_criteria": [],
                "reasoning": classification["reasoning"],
            }
            events.append(
                {
                    "type": "task_classified",
                    "task_type": classification["task_type"],
                    "complexity": classification["complexity"],
                    "workspace_type": classification["workspace_type"],
                    "reasoning": classification["reasoning"],
                    "agent_count": len(fast_agents),
                    "agent_instances": [
                        {
                            "instance_id": a.get("instance_id", ""),
                            "role": a.get("role", ""),
                            "specialisation": a.get("specialisation", ""),
                            "assignment": (a.get("assignment", "") or "")[:200],
                        }
                        for a in fast_agents
                    ],
                    "deterministic_hint_used": True,
                    "minimum_team_enforced": True,
                    "fallback_reason": "classifier_timeout",
                }
            )
            events.append(_master_decision_event(plan_dict, classification))
            target_root, target_mode = _derive_target_root(state, classification)
            return {
                "classification": classification,
                "target_root": target_root,
                "target_mode": target_mode,
                "deterministic_classification": deterministic_classification,
                "staffing_plan": plan_dict,
                "supervisory_decisions": [_master_decision_event(plan_dict, classification)],
                "status": "classified",
                "cost_accumulator": {
                    **state.get("cost_accumulator", {}),
                    "master_agent": {"tokens": 0, "cost": 0.0},
                },
                "events": events,
            }
        except Exception as e:
            logger.warning(
                "Master classification failed: %s: %s; using deterministic fallback",
                type(e).__name__,
                e or "(no message — check API key configuration)",
            )
            fast_agents = enforce_minimum_team(
                [],
                task_type=det_result.task_type,
                description=description,
            )
            classification = {
                "task_type": det_result.task_type,
                "complexity": det_result.complexity,
                "reasoning": (
                    f"Master classification failed ({type(e).__name__}); "
                    "used deterministic fallback."
                ),
            }
            classification = _normalize_greenfield_classification(state, classification)
            plan_dict = {
                "task_type": det_result.task_type,
                "complexity": det_result.complexity,
                "workspace_type": classification["workspace_type"],
                "execution_mode": "linear",
                "domain_analysis": "Deterministic fallback after classifier failure.",
                "architecture_notes": "",
                "agents": fast_agents,
                "consultation_requirements": [],
                "spawn_candidates": [],
                "completion_contract": [],
                "risk_actions": [],
                "required_approvals": [],
                "supervision_checkpoints": [],
                "risks": ["Master classifier failed; plan may be less specialized."],
                "acceptance_criteria": [],
                "reasoning": classification["reasoning"],
            }
            events.append(
                {
                    "type": "task_classified",
                    "task_type": classification["task_type"],
                    "complexity": classification["complexity"],
                    "workspace_type": classification["workspace_type"],
                    "reasoning": classification["reasoning"],
                    "agent_count": len(fast_agents),
                    "agent_instances": [
                        {
                            "instance_id": a.get("instance_id", ""),
                            "role": a.get("role", ""),
                            "specialisation": a.get("specialisation", ""),
                            "assignment": (a.get("assignment", "") or "")[:200],
                        }
                        for a in fast_agents
                    ],
                    "deterministic_hint_used": True,
                    "minimum_team_enforced": True,
                    "fallback_reason": "classifier_exception",
                }
            )
            events.append(_master_decision_event(plan_dict, classification))
            target_root, target_mode = _derive_target_root(state, classification)
            return {
                "classification": classification,
                "target_root": target_root,
                "target_mode": target_mode,
                "deterministic_classification": deterministic_classification,
                "staffing_plan": plan_dict,
                "supervisory_decisions": [_master_decision_event(plan_dict, classification)],
                "status": "classified",
                "cost_accumulator": {
                    **state.get("cost_accumulator", {}),
                    "master_agent": {"tokens": 0, "cost": 0.0},
                },
                "events": events,
            }

        # ── ENFORCE MINIMUM TEAM — LLM can ADD but NEVER REMOVE ─────
        enforced_agents = enforce_minimum_team(
            [
                {
                    "instance_id": a.instance_id,
                    "role": a.role,
                    "specialisation": a.specialisation,
                    "assignment": a.assignment,
                    "depends_on": a.depends_on,
                    "tools_required": a.tools_required,
                    "verification": a.verification,
                }
                for a in plan.agents
            ],
            task_type=det_result.task_type,
            description=description,
        )

        # ── ENFORCE COMPLEXITY FLOOR — LLM cannot downgrade ─────────
        complexity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        llm_complexity = _enum_or_str_value(plan.complexity)
        det_complexity = det_result.complexity
        if complexity_order.get(llm_complexity, 1) < complexity_order.get(det_complexity, 1):
            logger.info(
                "Enforcing complexity floor: LLM=%s < deterministic=%s → using %s",
                llm_complexity,
                det_complexity,
                det_complexity,
            )
            llm_complexity = det_complexity

        # Build legacy classification dict for backward compatibility
        classification: dict[str, Any] = {
            "task_type": _enum_or_str_value(plan.task_type),
            "complexity": llm_complexity,
            "workspace_type": plan.workspace_type,
            "reasoning": plan.reasoning,
        }

        # Override task_type with deterministic if LLM returned something weaker
        # (e.g., LLM said "feature" when keywords clearly said "new_project")
        if (
            det_result.is_deterministic
            and det_result.confidence >= 0.85
            and det_result.task_type == "new_project"
            and classification["task_type"] != "new_project"
        ):
            logger.info(
                "Enforcing task_type floor: LLM=%s but deterministic=%s → using new_project",
                classification["task_type"],
                det_result.task_type,
            )
            classification["task_type"] = "new_project"
        classification = _normalize_greenfield_classification(state, classification)

        # Rebuild plan with enforced agents
        plan_dict = _serialize_staffing_plan(plan)
        plan_dict["agents"] = enforced_agents
        plan_dict["complexity"] = llm_complexity

        events.append(
            {
                "type": "task_classified",
                "task_type": classification["task_type"],
                "complexity": classification["complexity"],
                "workspace_type": classification["workspace_type"],
                "reasoning": classification["reasoning"],
                "domain_analysis": plan.domain_analysis,
                "agent_count": len(enforced_agents),
                "agent_instances": [
                    {
                        "instance_id": a.get("instance_id", ""),
                        "role": a.get("role", ""),
                        "specialisation": a.get("specialisation", ""),
                        "assignment": (a.get("assignment", "") or "")[:200],
                    }
                    for a in enforced_agents
                ],
                "risks": plan.risks[:5],
                "acceptance_criteria": plan.acceptance_criteria[:5],
                "deterministic_hint_used": True,
                "minimum_team_enforced": len(enforced_agents) > len(plan.agents),
            }
        )
        master_decision = _master_decision_event(plan_dict, classification)
        events.append(master_decision)

        target_root, target_mode = _derive_target_root(state, classification)
        return {
            "classification": classification,
            "target_root": target_root,
            "target_mode": target_mode,
            "deterministic_classification": deterministic_classification,
            "staffing_plan": plan_dict,
            "supervisory_decisions": [master_decision],
            "status": "classified",
            "cost_accumulator": {
                **state.get("cost_accumulator", {}),
                "master_agent": {
                    "tokens": 0,
                    "cost": 0.0,
                },
            },
            "events": events,
        }

    # ══════════════════════════════════════════════════════════════════
    # FALLBACK: lightweight LLM classification (no classifier injected)
    # ══════════════════════════════════════════════════════════════════
    workspace_id = str(state.get("workspace_id", "") or "")
    cache_prompt_hash = stable_hash(
        {
            "v": "classify_fallback_v1",
            "description": description,
            "prompt": CLASSIFICATION_PROMPT,
        }
    )
    cache_context_fingerprint = stable_hash(
        {
            "deterministic": deterministic_classification,
            "workspace_type_hint": _derive_workspace_type(
                state, {"task_type": det_result.task_type}
            ),
            "project_root": str(state.get("project_root", "") or ""),
        }
    )
    if cache_repo is not None and workspace_id:
        cached = await cache_repo.get_exact(
            workspace_id=workspace_id,
            role="master_classify_fallback",
            model=llm.model_name,
            prompt_hash=cache_prompt_hash,
            context_fingerprint=cache_context_fingerprint,
        )
        if cached and isinstance(cached.get("response"), dict):
            cached_cls = cached["response"].get("classification")
            if isinstance(cached_cls, dict):
                events.append(
                    {
                        "type": "task_classified",
                        "task_type": cached_cls.get("task_type"),
                        "complexity": cached_cls.get("complexity"),
                        "workspace_type": cached_cls.get("workspace_type"),
                        "reasoning": cached_cls.get("reasoning", "Loaded from exact cache."),
                    }
                )
                events.append(
                    {
                        "type": "cache_hit",
                        "cache_source": "rigovo_exact",
                        "role": "master_classify_fallback",
                        "saved_tokens": int(
                            (cached.get("usage") or {}).get("total_tokens", 0) or 0
                        ),
                    }
                )
                return {
                    "classification": cached_cls,
                    "deterministic_classification": deterministic_classification,
                    "status": "classified",
                    "cost_accumulator": {
                        **state.get("cost_accumulator", {}),
                        "classifier": {
                            "tokens": 0,
                            "cost": 0.0,
                        },
                    },
                    "events": events,
                }
        events.append(
            {
                "type": "cache_miss",
                "cache_source": "none",
                "role": "master_classify_fallback",
            }
        )

    response = await llm.invoke(
        messages=[
            {"role": "system", "content": CLASSIFICATION_PROMPT},
            {"role": "user", "content": description},
        ],
        temperature=0.0,
        max_tokens=256,
    )

    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        classification = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        classification = {
            "task_type": "feature",
            "complexity": "medium",
            "workspace_type": "existing_project",
            "reasoning": "Failed to parse classification, defaulting to feature/medium.",
        }

    classification = _normalize_greenfield_classification(state, classification)
    target_root, target_mode = _derive_target_root(state, classification)

    # Apply deterministic floor to fallback classification too
    if det_result.is_deterministic and det_result.confidence >= 0.85:
        complexity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        if complexity_order.get(
            classification.get("complexity", "medium"), 1
        ) < complexity_order.get(det_result.complexity, 1):
            classification["complexity"] = det_result.complexity
        if det_result.task_type == "new_project":
            classification["task_type"] = "new_project"
    classification = _normalize_greenfield_classification(state, classification)

    events.append(
        {
            "type": "task_classified",
            "task_type": classification.get("task_type"),
            "complexity": classification.get("complexity"),
            "workspace_type": classification.get("workspace_type"),
            "reasoning": classification.get("reasoning"),
        }
    )
    if cache_repo is not None and workspace_id:
        await cache_repo.put_exact(
            workspace_id=workspace_id,
            role="master_classify_fallback",
            model=llm.model_name,
            prompt_hash=cache_prompt_hash,
            context_fingerprint=cache_context_fingerprint,
            response={"classification": classification},
            usage=usage_to_dict(response.usage),
            metadata={"task_type": classification.get("task_type", "feature")},
            ttl_minutes=180,
        )

    return {
        "classification": classification,
        "target_root": target_root,
        "target_mode": target_mode,
        "deterministic_classification": deterministic_classification,
        "supervisory_decisions": [],
        "status": "classified",
        "cost_accumulator": {
            **state.get("cost_accumulator", {}),
            "classifier": {
                "tokens": response.usage.total_tokens,
                "cost": 0.0,
            },
        },
        "events": events,
    }


def _derive_workspace_type(state: TaskState, classification: dict[str, Any]) -> str:
    """Derive workspace_type when the LLM didn't produce it."""
    explicit = str(classification.get("workspace_type") or "").strip()
    if explicit in {"new_project", "existing_project", "new_subfolder_project"}:
        if explicit == "existing_project" and _looks_greenfield_intent(
            str(state.get("description", ""))
        ):
            snapshot = state.get("project_snapshot")
            if (
                snapshot is not None
                and getattr(snapshot, "workspace_type", "existing_project") != "new_project"
            ):
                return "new_subfolder_project"
        return explicit

    task_type = classification.get("task_type")
    snapshot = state.get("project_snapshot")
    snapshot_type = (
        getattr(snapshot, "workspace_type", "existing_project")
        if snapshot is not None
        else "existing_project"
    )

    if task_type == "new_project" or _looks_greenfield_intent(str(state.get("description", ""))):
        if snapshot is not None and snapshot_type != "new_project":
            return "new_subfolder_project"
        return "new_project"

    if snapshot_type == "new_project":
        return "new_project"
    return "existing_project"


def _normalize_greenfield_classification(
    state: TaskState, classification: dict[str, Any]
) -> dict[str, Any]:
    """Align task type with greenfield workspace intent when needed."""
    normalized = dict(classification)
    workspace_type = _derive_workspace_type(state, normalized)
    normalized["workspace_type"] = workspace_type
    if workspace_type in {"new_project", "new_subfolder_project"} and _looks_greenfield_intent(
        str(state.get("description", ""))
    ):
        normalized["task_type"] = "new_project"
    return normalized


def _serialize_staffing_plan(plan: StaffingPlan) -> dict[str, Any]:
    """Serialize a StaffingPlan to a dict suitable for graph state."""
    return {
        "task_type": _enum_or_str_value(plan.task_type),
        "complexity": _enum_or_str_value(plan.complexity),
        "workspace_type": plan.workspace_type,
        "execution_mode": plan.execution_mode,
        "domain_analysis": plan.domain_analysis,
        "architecture_notes": plan.architecture_notes,
        "agents": [
            {
                "instance_id": a.instance_id,
                "role": a.role,
                "specialisation": a.specialisation,
                "assignment": a.assignment,
                "depends_on": a.depends_on,
                "tools_required": a.tools_required,
                "verification": a.verification,
            }
            for a in plan.agents
        ],
        "risks": plan.risks,
        "acceptance_criteria": plan.acceptance_criteria,
        "reasoning": plan.reasoning,
        "consultation_requirements": plan.consultation_requirements,
        "spawn_candidates": plan.spawn_candidates,
        "completion_contract": plan.completion_contract,
        "risk_actions": plan.risk_actions,
        "required_approvals": plan.required_approvals,
        "supervision_checkpoints": plan.supervision_checkpoints,
        "execution_dag": plan.execution_dag,
        "parallel_groups": plan.parallel_groups,
    }


def _looks_greenfield_intent(description: str) -> bool:
    text = description.lower()
    strong_markers = (
        "from scratch",
        "new project",
        "new app",
        "new api",
        "new service",
        "new saas",
        "scaffold",
        "bootstrap",
        "create identity",
        "create auth",
        "build auth",
    )
    if any(marker in text for marker in strong_markers):
        return True
    verbs = ("create", "build", "make", "scaffold", "bootstrap", "develop")
    nouns = ("saas", "api", "app", "service", "platform", "system", "backend", "product")
    return any(v in text for v in verbs) and any(n in text for n in nouns)


def _derive_target_root(state: TaskState, classification: dict[str, Any]) -> tuple[str, str]:
    workspace_root = (
        Path(str(state.get("workspace_root") or state.get("project_root") or "."))
        .expanduser()
        .resolve()
    )
    existing_target = str(state.get("target_root") or "").strip()
    workspace_type = classification.get("workspace_type", "existing_project")
    if workspace_type == "managed_workspace_project":
        return str(workspace_root), workspace_type

    if existing_target:
        target_path = Path(existing_target).expanduser().resolve()
        try:
            target_path.relative_to(workspace_root)
        except ValueError:
            target_path = workspace_root
        else:
            if workspace_type == str(state.get("target_mode") or "").strip():
                return str(target_path), workspace_type

    if workspace_type == "new_subfolder_project":
        target_root = workspace_root / _suggest_project_folder_name(
            state.get("description", "task")
        )
        target_root.mkdir(parents=True, exist_ok=True)
        return str(target_root), workspace_type
    return str(workspace_root), workspace_type


def _suggest_project_folder_name(description: str) -> str:
    import re

    text = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")
    if not text:
        return "rigovo-project"
    stop = {"create", "build", "make", "new", "a", "an", "the", "in", "for", "from", "scratch"}
    parts = [part for part in text.split("-") if part and part not in stop]
    slug = "-".join(parts[:5]).strip("-")
    return slug or "rigovo-project"
