'use strict';

import type {
  AgentSlot,
  AgentDependencies,
  TaskAssignment,
  AgentOutput,
  BaseAgentConfig,
} from '@rigovo/core';
import { CoderAgent } from './agents/coder-agent.js';
import { ReviewerAgent } from './agents/reviewer-agent.js';
import { PlannerAgent } from './agents/planner-agent.js';
import { QAAgent } from './agents/qa-agent.js';
import { SREAgent } from './agents/sre-agent.js';
import { DevOpsAgent } from './agents/devops-agent.js';

type ExecutableAgent = { execute: (task: TaskAssignment) => Promise<AgentOutput> };

/**
 * Agent constructor registry. Maps roles to their concrete classes.
 */
const AGENT_REGISTRY: Record<string, new (c: BaseAgentConfig) => ExecutableAgent> = {
  coder: CoderAgent,
  reviewer: ReviewerAgent,
  planner: PlannerAgent,
  qa: QAAgent,
  sre: SREAgent,
  devops: DevOpsAgent,
};

/**
 * Creates concrete agent instances from slot definitions.
 * This is the bridge between core's abstract orchestration
 * and eng's concrete agent implementations.
 */
export function createAgent(
  slot: AgentSlot,
  deps: AgentDependencies,
): ExecutableAgent {
  const config: BaseAgentConfig = {
    role: slot.role,
    description: slot.description,
    llmConfig: slot.llmConfig,
    bus: deps.bus,
    auditRepo: deps.auditRepo,
    memoryRepo: deps.memoryRepo,
    workspaceId: deps.workspaceId,
    projectId: deps.projectId,
  };

  const AgentClass = AGENT_REGISTRY[slot.role];
  if (!AgentClass) {
    throw new Error(`No agent implementation for role: ${slot.role}`);
  }

  return new AgentClass(config);
}
