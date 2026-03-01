/* ------------------------------------------------------------------ */
/*  Shared types for the Rigovo Control Plane desktop UI              */
/* ------------------------------------------------------------------ */

export type Tier = "auto" | "notify" | "approve";
export type Route = "auth" | "project" | "control";

export interface AuthSession {
  signed_in: boolean;
  email: string;
  full_name: string;
  first_name: string;
  last_name: string;
  role: string;
  organization_id: string;
  organization_name: string;
  workspace: {
    name: string;
    slug: string;
    admin_email: string;
    region: string;
  };
}
export type SettingsTab = "teams" | "connectors" | "identity" | "governance";

export interface InboxTask {
  id: string;
  title: string;
  source: string;
  tier: Tier;
  status: string;
  team: string;
  updatedAt: string;
  /** Absolute path to the workspace folder this task runs against (optional). */
  workspacePath?: string;
  /** Human-readable label derived from workspacePath basename (optional). */
  workspaceLabel?: string;
}

export interface ApprovalItem {
  id: string;
  taskId: string;
  summary: string;
  tier: Tier;
  requestedBy: string;
  age: string;
}

export interface WorkforceCell {
  team: string;
  planner: string;
  coder: string;
  reviewer: string;
  qa: string;
  devops: string;
  sre: string;
  lead: string;
}

export interface EventItem {
  id: string;
  time: string;
  event: string;
  details: string;
}

export interface ConnectorStatus {
  name: string;
  type: string;
  state: "connected" | "degraded" | "offline";
  notes: string;
  channel?: string;
}

export interface WorkspaceSetup {
  workspaceName: string;
  workspaceSlug: string;
  adminEmail: string;
  deploymentMode: "cloud" | "self_hosted";
  region: string;
}

export interface PersonaMember {
  id: string;
  name: string;
  role: "admin" | "tech_lead" | "devops" | "qa" | "sre" | "reviewer";
  team: string;
}

export interface GovernancePolicy {
  authMode: "email_only" | "hybrid" | "sso_required";
  defaultTier: Tier;
  deepRigour: boolean;
  requireApprovalHighRisk: boolean;
  requireApprovalProdSecrets: boolean;
  notifyChannels: string[];
}

export interface ControlStatePayload {
  auth: { signed_in: boolean; email: string; full_name: string };
  workspace: WorkspaceSetup;
  policy: GovernancePolicy;
  personas: PersonaMember[];
  connectors: ConnectorStatus[];
}

export interface EngineStatus {
  running: boolean;
  pid: number | null;
  apiUrl: string;
}

export interface EngineRuntimeConfig {
  electronSandbox: boolean;
  worktreeMode: "project" | "git_worktree";
  worktreeRoot: string;
}

export interface IdentityStatus {
  provider: string;
  authMode: GovernancePolicy["authMode"];
  workosClientId: string;
  workosOrganizationId: string;
  workosEnabled: boolean;
  workosOrganizationIdConfigured: boolean;
  workosClientIdConfigured: boolean;
  workosApiKeyConfigured: boolean;
}

export interface IdentityConfig {
  provider: "local" | "workos";
  authMode: GovernancePolicy["authMode"];
  workosClientId: string;
  workosOrganizationId: string;
  workosApiKey: string;
}

/* ---------- Project ---------- */

export interface Project {
  id: string;
  name: string;
  path: string;
  language: string;
  framework: string;
  created_at: string;
}

/* ---------- Task Detail (drill-down) ---------- */

export interface TaskStep {
  agent: string;
  /** Human-readable agent name (e.g. "Backend Engineer 1") */
  agent_name?: string;
  status: "pending" | "running" | "complete" | "failed" | "skipped";
  started_at: string | null;
  completed_at: string | null;
  output: string;
  files_changed: string[];
  tokens?: number;
  cost_usd?: number;
  duration_ms?: number;
  gate_results: GateResult[];
}

export interface GateResult {
  gate: string;
  passed: boolean;
  message: string;
  severity: "error" | "warning" | "info";
  /** Number of violations found (Phase 7/8) */
  violation_count?: number;
  /** Number of gates that ran */
  gates_run?: number;
  /** Whether Rigour deep analysis was used */
  deep?: boolean;
  /** Whether pro tier deep was used */
  pro?: boolean;
}

export interface TaskDetail {
  id: string;
  description: string;
  status: string;
  task_type: string;
  /** Task complexity from Master Agent classification (Phase 1) */
  complexity?: "low" | "medium" | "high" | "critical" | null;
  tier: Tier;
  team: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  steps: TaskStep[];
  cost: { total_tokens: number; total_cost_usd: number } | null;
  approval_data: Record<string, string>;
}

/* ---------- Electron IPC bridge (exposed via preload) ---------- */
export interface ElectronAPI {
  engineStatus: () => Promise<EngineStatus>;
  engineRuntimeConfig: () => Promise<EngineRuntimeConfig>;
  startEngine: (args: {
    host?: string;
    port?: number;
    projectDir?: string;
  }) => Promise<EngineStatus>;
  stopEngine: () => Promise<EngineStatus>;
  engineLastError: () => Promise<string>;
  openExternal: (url: string) => Promise<void>;
  openFolder: () => Promise<string | null>;
  listProjectFiles: (projectPath: string) => Promise<string[]>;
  /** Shallow-clone a git repo to destDir. Resolves with destDir on success. */
  gitClone: (url: string, destDir: string) => Promise<string>;
  /** Open folder picker for selecting clone destination parent directory. */
  pickCloneDest: () => Promise<string | null>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}
