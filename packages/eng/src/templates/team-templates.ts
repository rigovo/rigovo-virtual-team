'use strict';

import type { AgentRole } from '@rigovo/core';

/**
 * Pre-configured team template definition.
 */
export interface TeamTemplateDef {
  name: string;
  description: string;
  agents: AgentRole[];
  isSystem: boolean;
}

/**
 * Built-in team templates for common engineering workflows.
 */
export const SYSTEM_TEMPLATES: TeamTemplateDef[] = [
  {
    name: 'full-stack',
    description: 'Complete feature development: plan, code, review',
    agents: ['planner', 'coder', 'reviewer'],
    isSystem: true,
  },
  {
    name: 'quick-fix',
    description: 'Fast bug fix or patch: code and review',
    agents: ['coder', 'reviewer'],
    isSystem: true,
  },
  {
    name: 'code-review',
    description: 'Review-only workflow for existing code',
    agents: ['reviewer'],
    isSystem: true,
  },
  {
    name: 'incident-response',
    description: 'Production incident handling: SRE lead with coder support',
    agents: ['sre', 'coder'],
    isSystem: true,
  },
  {
    name: 'infrastructure',
    description: 'Infrastructure and deployment changes',
    agents: ['devops', 'sre'],
    isSystem: true,
  },
  {
    name: 'test-suite',
    description: 'Test generation and validation',
    agents: ['qa', 'coder'],
    isSystem: true,
  },
];

/** Look up a system template by name. Returns undefined if not found. */
export function getSystemTemplate(name: string): TeamTemplateDef | undefined {
  return SYSTEM_TEMPLATES.find((t) => t.name === name);
}
