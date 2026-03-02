"""Hierarchical State Machine (HSM) for agent behavioral inheritance.

Agents are not flat "coder" or "reviewer" roles — they operate in a
hierarchy of behavioral states where parent states enforce mandatory
transitions that sub-states inherit.

Example hierarchy:
    Senior_Engineer (parent)
    ├── Frontend_Expert (sub-state)
    ├── Backend_Expert (sub-state)
    └── Fullstack_Engineer (sub-state)

A ``Senior_Engineer`` MUST go through ``Architecture_Review`` before
``Write_Code``. This transition is inherited by ALL sub-states.
A ``Frontend_Expert`` adds additional mandatory phases like
``Component_Design`` before ``Write_Code``.

Design invariants:
- Parent mandatory phases are ALWAYS inherited — sub-states can ADD but
  never REMOVE mandatory phases.
- Each phase produces a structured output that the next phase can consume.
- The HSM resolves the behavioral state at agent execution time based on
  task classification + agent specialisation + project context.
- Phase enforcement is advisory (injected into the prompt as mandatory
  workflow steps) — not a hard routing constraint. The LLM follows the
  prescribed workflow because it's told to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BehaviorPhase:
    """A single mandatory phase within a behavioral state.

    Phases are ordered steps an agent MUST complete before moving to the
    next phase. Each phase produces a named output that subsequent phases
    can reference.

    Example:
        BehaviorPhase(
            name="architecture_review",
            description="Review project architecture before writing code",
            prompt_injection="Before writing ANY code, you must first...",
            output_label="ARCHITECTURE_ASSESSMENT",
            tools_required=["read_file", "list_directory", "search_codebase"],
        )
    """

    name: str
    description: str
    prompt_injection: str  # Injected into agent's system prompt
    output_label: str  # Label for the phase's output section
    tools_required: list[str] = field(default_factory=list)
    estimated_tokens: int = 500  # Budget hint for this phase


@dataclass
class BehaviorState:
    """A node in the behavioral state hierarchy.

    Each state defines mandatory phases and can have child states that
    inherit those phases. Child states add their own phases ON TOP of
    the parent's.

    The resolution order for mandatory phases is:
    1. Root ancestor phases (most general)
    2. Intermediate ancestor phases
    3. Current state phases (most specific)

    This ensures that fundamental disciplines (like architecture review)
    are never skipped by specialized agents.
    """

    state_id: str
    name: str
    description: str
    parent_id: str | None = None  # None = root state
    mandatory_phases: list[BehaviorPhase] = field(default_factory=list)

    # Conditions for entering this state (matched against context)
    activation_conditions: dict[str, Any] = field(default_factory=dict)
    # activation_conditions example:
    # {"task_types": ["feature", "new_project"], "specialisations": ["frontend", "react"]}


# ── Built-in behavioral state hierarchy ─────────────────────────────────

_ARCHITECTURE_REVIEW_PHASE = BehaviorPhase(
    name="architecture_review",
    description="Review existing architecture before making changes",
    prompt_injection=(
        "MANDATORY PHASE 1 — ARCHITECTURE REVIEW:\n"
        "Before writing ANY code, you MUST:\n"
        "1. Read the project structure (list_directory on src/ and key dirs)\n"
        "2. Identify the architectural patterns in use (MVC, hexagonal, event-driven, etc.)\n"
        "3. Map the dependency graph for the files you will touch\n"
        "4. Write a brief ARCHITECTURE_ASSESSMENT section in your output that confirms:\n"
        "   - Pattern identified\n"
        "   - Files you will create/modify and WHY they belong in those locations\n"
        "   - Any architectural risks from your proposed changes\n"
        "You CANNOT proceed to write code until this assessment is complete."
    ),
    output_label="ARCHITECTURE_ASSESSMENT",
    tools_required=["read_file", "list_directory", "search_codebase"],
    estimated_tokens=800,
)

_DEPENDENCY_CHECK_PHASE = BehaviorPhase(
    name="dependency_check",
    description="Verify all imports and dependencies exist before coding",
    prompt_injection=(
        "MANDATORY PHASE 2 — DEPENDENCY CHECK:\n"
        "Before writing new imports, you MUST:\n"
        "1. Read the project's dependency manifest (package.json, pyproject.toml, etc.)\n"
        "2. Confirm every import you plan to use EXISTS in the project\n"
        "3. If a dependency is missing, flag it — do NOT hallucinate an import\n"
        "4. Write a brief DEPENDENCY_CHECK section confirming all imports are valid."
    ),
    output_label="DEPENDENCY_CHECK",
    tools_required=["read_file"],
    estimated_tokens=300,
)

_COMPONENT_DESIGN_PHASE = BehaviorPhase(
    name="component_design",
    description="Design component structure before implementing",
    prompt_injection=(
        "MANDATORY PHASE — COMPONENT DESIGN (Frontend):\n"
        "Before writing component code, you MUST:\n"
        "1. Read existing components in the same directory to understand patterns\n"
        "2. Identify the component hierarchy (parent → child relationships)\n"
        "3. Define props interface and state management approach\n"
        "4. Write a brief COMPONENT_DESIGN section describing:\n"
        "   - Component name, props, and state\n"
        "   - Parent component and data flow\n"
        "   - Styling approach (CSS modules, Tailwind, styled-components, etc.)"
    ),
    output_label="COMPONENT_DESIGN",
    tools_required=["read_file", "list_directory"],
    estimated_tokens=500,
)

_API_CONTRACT_PHASE = BehaviorPhase(
    name="api_contract",
    description="Define API contracts before implementing endpoints",
    prompt_injection=(
        "MANDATORY PHASE — API CONTRACT (Backend):\n"
        "Before implementing endpoints, you MUST:\n"
        "1. Read existing route/handler files to match patterns\n"
        "2. Define request/response schemas with types\n"
        "3. Identify authentication/authorization requirements\n"
        "4. Write a brief API_CONTRACT section with:\n"
        "   - Endpoint paths, methods, and status codes\n"
        "   - Request and response body schemas\n"
        "   - Error response formats"
    ),
    output_label="API_CONTRACT",
    tools_required=["read_file", "search_codebase"],
    estimated_tokens=500,
)

_DATA_MODEL_PHASE = BehaviorPhase(
    name="data_model_review",
    description="Review data model impact before modifying schemas",
    prompt_injection=(
        "MANDATORY PHASE — DATA MODEL REVIEW:\n"
        "Before modifying any data models or database schemas, you MUST:\n"
        "1. Read all existing model/entity files\n"
        "2. Identify foreign key relationships and constraints\n"
        "3. Consider migration impact (backward compatibility)\n"
        "4. Write a brief DATA_MODEL_REVIEW section confirming:\n"
        "   - Fields added/modified and their types\n"
        "   - Index requirements\n"
        "   - Migration strategy (if applicable)"
    ),
    output_label="DATA_MODEL_REVIEW",
    tools_required=["read_file", "search_codebase"],
    estimated_tokens=500,
)

_SECURITY_AUDIT_PHASE = BehaviorPhase(
    name="pre_security_scan",
    description="Self-audit for security issues before submitting",
    prompt_injection=(
        "MANDATORY PHASE — SECURITY SELF-AUDIT:\n"
        "Before finalizing your code, you MUST self-check:\n"
        "1. No hardcoded secrets, tokens, or credentials\n"
        "2. All user input is validated and sanitized\n"
        "3. SQL queries use parameterized statements\n"
        "4. No path traversal vulnerabilities in file operations\n"
        "5. Authentication checks on all protected endpoints\n"
        "Write a brief SECURITY_SELF_AUDIT confirming each check passed."
    ),
    output_label="SECURITY_SELF_AUDIT",
    tools_required=[],
    estimated_tokens=300,
)

_TEST_STRATEGY_PHASE = BehaviorPhase(
    name="test_strategy",
    description="Define test strategy before writing tests",
    prompt_injection=(
        "MANDATORY PHASE — TEST STRATEGY:\n"
        "Before writing ANY tests, you MUST:\n"
        "1. Read the code under test with read_file\n"
        "2. Identify the test framework in use (pytest, jest, etc.)\n"
        "3. Map out: happy path, error cases, edge cases, boundary conditions\n"
        "4. Write a brief TEST_STRATEGY section listing:\n"
        "   - Test categories and count\n"
        "   - Mocking strategy for external dependencies\n"
        "   - Expected coverage areas"
    ),
    output_label="TEST_STRATEGY",
    tools_required=["read_file", "list_directory"],
    estimated_tokens=400,
)

_INFRA_IMPACT_PHASE = BehaviorPhase(
    name="infra_impact",
    description="Assess infrastructure impact before changes",
    prompt_injection=(
        "MANDATORY PHASE — INFRASTRUCTURE IMPACT ASSESSMENT:\n"
        "Before modifying infrastructure configs, you MUST:\n"
        "1. Read existing CI/CD, Docker, and deployment configs\n"
        "2. Identify blast radius — what services/environments are affected\n"
        "3. Check for environment-specific variables that need updates\n"
        "4. Write a brief INFRA_IMPACT section with:\n"
        "   - Services affected\n"
        "   - Environment variables needed\n"
        "   - Rollback strategy"
    ),
    output_label="INFRA_IMPACT",
    tools_required=["read_file", "list_directory"],
    estimated_tokens=400,
)


# ── State hierarchy definition ──────────────────────────────────────────

def _build_default_hierarchy() -> dict[str, BehaviorState]:
    """Build the default behavioral state hierarchy.

    Hierarchy:
        senior_engineer (root for all coding roles)
        ├── frontend_expert
        ├── backend_expert
        ├── fullstack_engineer
        ├── infra_engineer
        └── data_engineer

        senior_reviewer (root for all review roles)
        ├── security_reviewer
        └── architecture_reviewer

        senior_qa (root for all QA roles)
        └── integration_tester
    """
    states: dict[str, BehaviorState] = {}

    # ── Root: Senior Engineer ───────────────────────────────────────
    states["senior_engineer"] = BehaviorState(
        state_id="senior_engineer",
        name="Senior Engineer",
        description="Base behavioral state for all engineering agents",
        parent_id=None,
        mandatory_phases=[
            _ARCHITECTURE_REVIEW_PHASE,
            _DEPENDENCY_CHECK_PHASE,
        ],
        activation_conditions={
            "roles": ["coder", "devops", "sre"],
        },
    )

    # ── Frontend Expert ─────────────────────────────────────────────
    states["frontend_expert"] = BehaviorState(
        state_id="frontend_expert",
        name="Frontend Expert",
        description="Specialized for React/Vue/Angular component work",
        parent_id="senior_engineer",
        mandatory_phases=[
            _COMPONENT_DESIGN_PHASE,
        ],
        activation_conditions={
            "roles": ["coder"],
            "specialisations": ["frontend", "react", "vue", "angular", "ui", "css"],
            "task_types": ["feature", "bug", "refactor"],
        },
    )

    # ── Backend Expert ──────────────────────────────────────────────
    states["backend_expert"] = BehaviorState(
        state_id="backend_expert",
        name="Backend Expert",
        description="Specialized for API, database, and server-side work",
        parent_id="senior_engineer",
        mandatory_phases=[
            _API_CONTRACT_PHASE,
            _DATA_MODEL_PHASE,
        ],
        activation_conditions={
            "roles": ["coder"],
            "specialisations": ["backend", "api", "database", "server"],
            "task_types": ["feature", "bug", "refactor"],
        },
    )

    # ── Fullstack Engineer ──────────────────────────────────────────
    states["fullstack_engineer"] = BehaviorState(
        state_id="fullstack_engineer",
        name="Fullstack Engineer",
        description="Handles both frontend and backend",
        parent_id="senior_engineer",
        mandatory_phases=[
            _API_CONTRACT_PHASE,
        ],
        activation_conditions={
            "roles": ["coder"],
            "specialisations": ["fullstack", "full-stack"],
        },
    )

    # ── Infrastructure Engineer ─────────────────────────────────────
    states["infra_engineer"] = BehaviorState(
        state_id="infra_engineer",
        name="Infrastructure Engineer",
        description="Specialized for CI/CD, Docker, K8s, Terraform",
        parent_id="senior_engineer",
        mandatory_phases=[
            _INFRA_IMPACT_PHASE,
        ],
        activation_conditions={
            "roles": ["devops", "sre"],
            "task_types": ["infra"],
        },
    )

    # ── Root: Senior Reviewer ───────────────────────────────────────
    states["senior_reviewer"] = BehaviorState(
        state_id="senior_reviewer",
        name="Senior Reviewer",
        description="Base behavioral state for all review/audit roles",
        parent_id=None,
        mandatory_phases=[],  # Reviewers have light-touch process
        activation_conditions={
            "roles": ["reviewer", "security", "lead"],
        },
    )

    # ── Security Reviewer ───────────────────────────────────────────
    states["security_reviewer"] = BehaviorState(
        state_id="security_reviewer",
        name="Security Reviewer",
        description="Security-focused code auditor",
        parent_id="senior_reviewer",
        mandatory_phases=[
            _SECURITY_AUDIT_PHASE,
        ],
        activation_conditions={
            "roles": ["security"],
        },
    )

    # ── Root: Senior QA ─────────────────────────────────────────────
    states["senior_qa"] = BehaviorState(
        state_id="senior_qa",
        name="Senior QA Engineer",
        description="Base behavioral state for QA agents",
        parent_id=None,
        mandatory_phases=[
            _TEST_STRATEGY_PHASE,
        ],
        activation_conditions={
            "roles": ["qa"],
        },
    )

    return states


# ── Global hierarchy (lazy-initialized) ─────────────────────────────────

_HIERARCHY: dict[str, BehaviorState] | None = None


def _get_hierarchy() -> dict[str, BehaviorState]:
    """Get or initialize the global state hierarchy."""
    global _HIERARCHY
    if _HIERARCHY is None:
        _HIERARCHY = _build_default_hierarchy()
    return _HIERARCHY


# ── Public API ──────────────────────────────────────────────────────────


def resolve_behavior_state(
    role: str,
    specialisation: str = "",
    task_type: str = "",
) -> BehaviorState | None:
    """Resolve the most specific behavioral state for an agent.

    Matches against the hierarchy using role, specialisation, and task_type.
    Returns the most specific (deepest) matching state, or None if no state
    matches (rare — most agents match at least a root state).

    Resolution strategy:
    1. Find all states whose activation_conditions match
    2. Prefer deepest state (most specific)
    3. Prefer states with more matching conditions (tighter fit)
    """
    hierarchy = _get_hierarchy()
    candidates: list[tuple[int, int, BehaviorState]] = []  # (depth, match_score, state)

    for state in hierarchy.values():
        score = _match_score(state, role, specialisation, task_type)
        if score > 0:
            depth = _state_depth(state, hierarchy)
            candidates.append((depth, score, state))

    if not candidates:
        return None

    # Sort by depth (deepest first), then by match score (highest first)
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    return candidates[0][2]


def get_inherited_phases(state: BehaviorState) -> list[BehaviorPhase]:
    """Get ALL mandatory phases for a state, including inherited ones.

    Returns phases in execution order:
    1. Root ancestor phases (most general)
    2. Intermediate ancestor phases
    3. Current state phases (most specific)

    This guarantees that fundamental disciplines (like architecture review)
    are never skipped by specialized agents.
    """
    hierarchy = _get_hierarchy()
    chain: list[BehaviorState] = []

    # Walk up to root
    current: BehaviorState | None = state
    while current is not None:
        chain.append(current)
        parent_id = current.parent_id
        current = hierarchy.get(parent_id) if parent_id else None

    # Reverse: root first, most specific last
    chain.reverse()

    # Collect phases in inheritance order (no duplicates by name)
    seen_names: set[str] = set()
    phases: list[BehaviorPhase] = []
    for ancestor in chain:
        for phase in ancestor.mandatory_phases:
            if phase.name not in seen_names:
                phases.append(phase)
                seen_names.add(phase.name)

    return phases


def build_hsm_prompt_section(
    role: str,
    specialisation: str = "",
    task_type: str = "",
) -> str:
    """Build the HSM behavioral injection for an agent's system prompt.

    Returns a formatted prompt section containing all mandatory phases
    the agent must complete, ordered by inheritance hierarchy.
    Returns empty string if no behavioral state matches.
    """
    state = resolve_behavior_state(role, specialisation, task_type)
    if state is None:
        return ""

    phases = get_inherited_phases(state)
    if not phases:
        return ""

    sections: list[str] = [
        f"═══ BEHAVIORAL STATE: {state.name} ═══",
        f"You are operating as a {state.name}. This means you MUST complete "
        f"the following mandatory phases IN ORDER before producing your final output.",
        "",
    ]

    for i, phase in enumerate(phases, 1):
        sections.append(f"── Phase {i}/{len(phases)}: {phase.description} ──")
        sections.append(phase.prompt_injection)
        sections.append("")

    sections.append(
        "═══ END BEHAVIORAL STATE ═══\n"
        "You MUST complete ALL phases above in order. Skip none. "
        "Your final output must include the labeled sections from each phase."
    )

    return "\n".join(sections)


# ── Internal helpers ────────────────────────────────────────────────────


def _match_score(
    state: BehaviorState,
    role: str,
    specialisation: str,
    task_type: str,
) -> int:
    """Compute how well a state's activation conditions match the context.

    Returns 0 if the state doesn't match at all, or a positive score
    indicating match quality (higher = better fit).

    CRITICAL RULE: If a state defines specialisation conditions, the input
    MUST provide a matching specialisation. This prevents child states from
    matching when only a bare role is provided (e.g., "coder" without
    specialisation should NOT match "frontend_expert").
    """
    conditions = state.activation_conditions
    if not conditions:
        return 0

    score = 0
    matched_any = False

    # Role match — required if defined
    roles = conditions.get("roles", [])
    if roles:
        if role in roles:
            score += 10
            matched_any = True
        else:
            return 0  # Role mismatch = no match

    # Specialisation match — REQUIRED if state defines it
    specs = conditions.get("specialisations", [])
    if specs:
        if not specialisation:
            return 0  # State requires specialisation but none provided
        spec_lower = specialisation.lower()
        if any(s.lower() in spec_lower or spec_lower in s.lower() for s in specs):
            score += 5
            matched_any = True
        else:
            return 0  # Specialisation mismatch = no match

    # Task type match — for CHILD states (has parent), task_types is REQUIRED
    # For ROOT states, task_types is a bonus (not required)
    task_types = conditions.get("task_types", [])
    if task_types:
        if task_type in task_types:
            score += 3
            matched_any = True
        elif state.parent_id is not None:
            return 0  # Child state requires matching task_type

    return score if matched_any else 0


def _state_depth(state: BehaviorState, hierarchy: dict[str, BehaviorState]) -> int:
    """Compute the depth of a state in the hierarchy (root = 0)."""
    depth = 0
    current = state
    while current.parent_id and current.parent_id in hierarchy:
        depth += 1
        current = hierarchy[current.parent_id]
    return depth
