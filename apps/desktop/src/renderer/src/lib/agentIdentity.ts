import type { TaskStep } from "../types";

const CANONICAL_LABELS: Record<string, string> = {
  master: "Chief Architect",
  planner: "Project Manager",
  lead: "Tech Lead",
  coder: "Software Engineer",
  reviewer: "Code Reviewer",
  qa: "QA Engineer",
  security: "Security Engineer",
  devops: "DevOps Engineer",
  sre: "SRE Engineer",
  docs: "Technical Writer",
  rigour: "Rigour Gates",
  memory: "Knowledge Base",
  trinity: "Rigour Gates",
  system: "System",
};

const BASE_ROLE_KEYWORDS: Record<string, string> = {
  master: "master",
  planner: "planner",
  pm: "planner",
  manager: "planner",
  architect: "planner",
  lead: "lead",
  coder: "coder",
  backend: "coder",
  frontend: "coder",
  engineer: "coder",
  software: "coder",
  developer: "coder",
  dev: "coder",
  programmer: "coder",
  implementer: "coder",
  reviewer: "reviewer",
  review: "reviewer",
  qa: "qa",
  tester: "qa",
  test: "qa",
  security: "security",
  sec: "security",
  auditor: "security",
  devops: "devops",
  infra: "devops",
  deploy: "devops",
  sre: "sre",
  reliability: "sre",
  ops: "sre",
  docs: "docs",
  documentation: "docs",
  writer: "docs",
  rigour: "rigour",
  gate: "rigour",
  quality: "rigour",
  memory: "memory",
  knowledge: "memory",
  kb: "memory",
  trinity: "trinity",
};

function tokenize(raw: string): string[] {
  return raw.toLowerCase().split(/[^a-z0-9]+/).filter((p) => p && !/^\d+$/.test(p));
}

function titleCase(raw: string): string {
  return raw
    .split(/[^a-z0-9]+/i)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function resolveCanonicalRole(rawRole: string): string {
  const raw = String(rawRole || "").trim().toLowerCase();
  if (!raw) return "agent";
  if (CANONICAL_LABELS[raw]) return raw;

  const parts = tokenize(raw);
  for (const part of parts) {
    const mapped = BASE_ROLE_KEYWORDS[part];
    if (mapped) return mapped;
  }
  return raw;
}

export function canonicalAgentLabel(rawRole: string): string {
  const canonical = resolveCanonicalRole(rawRole);
  return CANONICAL_LABELS[canonical] ?? titleCase(String(rawRole || "agent"));
}

export function canonicalStepLabel(step: Pick<TaskStep, "agent" | "agent_role" | "agent_instance">): string {
  const base = canonicalAgentLabel(step.agent_role || step.agent || "agent");
  const source = String(step.agent_instance || step.agent || "");
  const m = source.match(/(\d+)$/);
  if (!m) return base;
  if (new RegExp(`\\s${m[1]}$`).test(base)) return base;
  return `${base} ${m[1]}`;
}

export function stepRoleKey(step: Pick<TaskStep, "agent" | "agent_role">): string {
  return resolveCanonicalRole(step.agent_role || step.agent || "");
}

export function isWorkRole(rawRole: string): boolean {
  const role = resolveCanonicalRole(rawRole);
  return !["master", "memory", "rigour", "trinity", "system"].includes(role);
}
