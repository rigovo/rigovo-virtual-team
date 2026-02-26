/* ------------------------------------------------------------------ */
/*  Default / fallback data for the Rigovo Control Plane UI           */
/* ------------------------------------------------------------------ */

import type {
  WorkspaceSetup, GovernancePolicy, PersonaMember,
  ConnectorStatus, InboxTask, ApprovalItem, WorkforceCell,
  EventItem, IdentityConfig, Tier, TaskDetail
} from "./types";

export const defaultWorkspace: WorkspaceSetup = {
  workspaceName: "",
  workspaceSlug: "",
  adminEmail: "",
  deploymentMode: "self_hosted",
  region: "us-east-1"
};

export const defaultPolicy: GovernancePolicy = {
  authMode: "email_only",
  defaultTier: "notify",
  deepRigour: true,
  requireApprovalHighRisk: true,
  requireApprovalProdSecrets: true,
  notifyChannels: ["slack", "email"]
};

export const defaultMembers: PersonaMember[] = [];

export const fallbackConnectors: ConnectorStatus[] = [
  { name: "WorkOS AuthKit", type: "Identity", state: "connected", notes: "Redirect-based auth via browser", channel: "AuthKit" },
  { name: "Slack Adapter", type: "Messaging", state: "offline", notes: "Not configured", channel: "" },
  { name: "n8n Bridge", type: "Workflow", state: "offline", notes: "Not configured", channel: "" },
  { name: "Company KB", type: "Knowledge", state: "offline", notes: "Not configured", channel: "" },
];

export const defaultIdentityConfig: IdentityConfig = {
  provider: "local",
  authMode: "email_only",
  workosClientId: "",
  workosOrganizationId: "",
  workosApiKey: ""
};

/* ---- Demo data — visible when backend is unreachable ---- */

const now = new Date();
const ago = (min: number) => new Date(now.getTime() - min * 60_000).toISOString();

export const fallbackInbox: InboxTask[] = [
  { id: "demo-1", title: "Add JWT authentication to API", source: "manual", tier: "approve", status: "in_progress", team: "platform", updatedAt: "2 min ago" },
  { id: "demo-2", title: "Fix N+1 query in /users endpoint", source: "manual", tier: "auto", status: "completed", team: "backend", updatedAt: "15 min ago" },
  { id: "demo-3", title: "Write unit tests for payment module", source: "manual", tier: "notify", status: "awaiting_approval", team: "backend", updatedAt: "8 min ago" },
];

export const fallbackApprovals: ApprovalItem[] = [
  { id: "appr-1", taskId: "demo-3", summary: "QA found 2 edge cases, requesting review", tier: "notify", requestedBy: "qa-agent", age: "8m" },
];

/* ---- Demo task details ---- */

export const demoTaskDetails: Record<string, TaskDetail> = {
  "demo-1": {
    id: "demo-1",
    description: "Add JWT authentication to API",
    status: "in_progress",
    task_type: "feature",
    tier: "approve",
    team: "platform",
    created_at: ago(12),
    started_at: ago(10),
    completed_at: null,
    steps: [
      {
        agent: "planner",
        status: "complete",
        started_at: ago(10),
        completed_at: ago(8),
        output: "Analyzed the codebase structure. The API currently has no auth middleware.\n\nPlan:\n1. Create src/auth/jwt.ts — token generation & verification\n2. Create src/middleware/auth.ts — Express middleware\n3. Update src/routes/index.ts — protect routes\n4. Add tests for token flow\n\nEstimated complexity: Medium. No breaking changes to existing endpoints.",
        files_changed: [],
        gate_results: [
          { gate: "complexity", passed: true, message: "Moderate scope", severity: "info" },
          { gate: "security", passed: true, message: "Auth patterns look correct", severity: "info" },
        ]
      },
      {
        agent: "coder",
        status: "running",
        started_at: ago(7),
        completed_at: null,
        output: "Implementing JWT authentication module...\n\nCreated token utilities with RS256 signing.\nAdded auth middleware with Bearer token extraction.\nProtecting /api/v1/* routes, leaving /health and /auth/login open.",
        files_changed: ["src/auth/jwt.ts", "src/middleware/auth.ts", "src/routes/index.ts"],
        gate_results: []
      },
      {
        agent: "reviewer",
        status: "pending",
        started_at: null,
        completed_at: null,
        output: "",
        files_changed: [],
        gate_results: []
      },
      {
        agent: "qa",
        status: "pending",
        started_at: null,
        completed_at: null,
        output: "",
        files_changed: [],
        gate_results: []
      },
      {
        agent: "security",
        status: "pending",
        started_at: null,
        completed_at: null,
        output: "",
        files_changed: [],
        gate_results: []
      }
    ],
    cost: { total_tokens: 18420, total_cost_usd: 0.0341 },
    approval_data: {}
  },
  "demo-2": {
    id: "demo-2",
    description: "Fix N+1 query in /users endpoint",
    status: "completed",
    task_type: "bugfix",
    tier: "auto",
    team: "backend",
    created_at: ago(30),
    started_at: ago(28),
    completed_at: ago(15),
    steps: [
      {
        agent: "planner",
        status: "complete",
        started_at: ago(28),
        completed_at: ago(26),
        output: "Identified N+1 in UserRepository.findAll() — each user triggers a separate SELECT for their profile.\n\nFix: Use eager loading with JOIN FETCH or add a batch loader.\nRisk: Low. Read-only query path.",
        files_changed: [],
        gate_results: [
          { gate: "complexity", passed: true, message: "Simple fix", severity: "info" },
        ]
      },
      {
        agent: "coder",
        status: "complete",
        started_at: ago(25),
        completed_at: ago(20),
        output: "Replaced lazy loading with JOIN FETCH in the repository query.\nAdded index on users.profile_id for faster joins.\nQuery count dropped from N+1 to 1 single query.\n\nBefore: 47 queries for 46 users\nAfter:  1 query with JOIN",
        files_changed: ["src/repositories/UserRepository.ts", "migrations/20260226_add_profile_index.sql"],
        gate_results: [
          { gate: "lint", passed: true, message: "Clean", severity: "info" },
          { gate: "types", passed: true, message: "No type errors", severity: "info" },
          { gate: "security", passed: true, message: "No injection risk", severity: "info" },
        ]
      },
      {
        agent: "reviewer",
        status: "complete",
        started_at: ago(19),
        completed_at: ago(17),
        output: "Code review passed. JOIN FETCH approach is correct.\nThe index migration looks good — profile_id should have been indexed from the start.\nOne suggestion: add a comment explaining why eager loading is used here.",
        files_changed: [],
        gate_results: []
      },
      {
        agent: "qa",
        status: "complete",
        started_at: ago(19),
        completed_at: ago(16),
        output: "Ran integration tests — all 23 user-related tests pass.\nPerformance test: endpoint response time dropped from 340ms to 12ms with 100 users.\nNo regressions detected.",
        files_changed: [],
        gate_results: [
          { gate: "tests", passed: true, message: "23/23 passed", severity: "info" },
          { gate: "performance", passed: true, message: "96% improvement", severity: "info" },
        ]
      }
    ],
    cost: { total_tokens: 24100, total_cost_usd: 0.0456 },
    approval_data: {}
  },
  "demo-3": {
    id: "demo-3",
    description: "Write unit tests for payment module",
    status: "awaiting_approval",
    task_type: "testing",
    tier: "notify",
    team: "backend",
    created_at: ago(20),
    started_at: ago(18),
    completed_at: null,
    steps: [
      {
        agent: "planner",
        status: "complete",
        started_at: ago(18),
        completed_at: ago(16),
        output: "Analyzed payment module — 4 key areas need test coverage:\n1. Stripe webhook signature verification\n2. Refund flow with idempotency\n3. Subscription upgrade/downgrade logic\n4. Failed payment retry with exponential backoff\n\nCurrent coverage: 34%. Target: 85%+.",
        files_changed: [],
        gate_results: []
      },
      {
        agent: "coder",
        status: "complete",
        started_at: ago(15),
        completed_at: ago(10),
        output: "Written 18 test cases across 4 test files.\nUsed vitest with MSW for API mocking.\nCoverage increased from 34% to 91%.\n\nKey tests:\n- Webhook signature verification (valid, invalid, expired)\n- Refund idempotency (duplicate requests return same result)\n- Subscription tier changes (upgrade prorates, downgrade waits)\n- Retry backoff (1s, 2s, 4s, 8s, give up)",
        files_changed: ["tests/payment/webhook.test.ts", "tests/payment/refund.test.ts", "tests/payment/subscription.test.ts", "tests/payment/retry.test.ts"],
        gate_results: [
          { gate: "tests", passed: true, message: "18/18 passed", severity: "info" },
          { gate: "coverage", passed: true, message: "91% (target: 85%)", severity: "info" },
        ]
      },
      {
        agent: "qa",
        status: "complete",
        started_at: ago(9),
        completed_at: ago(8),
        output: "Reviewed test quality. Found 2 edge cases not covered:\n1. Webhook with empty body (should return 400, not 500)\n2. Refund on already-refunded transaction\n\nRecommend adding these before merging. Requesting approval.",
        files_changed: [],
        gate_results: [
          { gate: "quality", passed: false, message: "2 edge cases missing", severity: "warning" },
        ]
      }
    ],
    cost: { total_tokens: 31200, total_cost_usd: 0.0587 },
    approval_data: {}
  }
};

export const fallbackWorkforce: WorkforceCell[] = [];

export const fallbackEvents: EventItem[] = [];

/* ---- CSS class helpers ------------------------------------------- */

export function tierClass(t: Tier): string {
  if (t === "approve") return "tier-chip tier-approve";
  if (t === "notify") return "tier-chip tier-notify";
  return "tier-chip tier-auto";
}

export function statusClass(status: string): string {
  if (status.includes("approval") || status.includes("awaiting")) return "status-pill status-awaiting";
  if (status.includes("running") || status.includes("progress") || status.includes("assembl") || status.includes("classif") || status.includes("rout") || status.includes("in_progress")) return "status-pill status-running";
  if (status.includes("fail") || status.includes("reject")) return "status-pill status-failed";
  if (status.includes("complete")) return "status-pill status-complete";
  return "status-pill status-idle";
}

export function connectorClass(state: ConnectorStatus["state"]): string {
  if (state === "connected") return "tier-chip tier-auto";
  if (state === "degraded") return "tier-chip tier-notify";
  return "tier-chip tier-approve";
}
