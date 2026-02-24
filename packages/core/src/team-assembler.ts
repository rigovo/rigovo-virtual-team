'use strict';

import type { AgentRole, LLMConfig } from './types/index.js';
import type { ClassificationResult } from './task-classifier.js';

/**
 * Blueprint for a single agent slot in the assembled team.
 */
export interface AgentSlot {
  role: AgentRole;
  description: string;
  llmConfig: LLMConfig;
  order: number;
}

/**
 * Assembled team ready for execution.
 */
export interface AssembledTeam {
  slots: AgentSlot[];
  estimatedTokens: number;
  pipelineOrder: AgentRole[];
}

/** Static descriptions for each agent role. */
const ROLE_DESCRIPTIONS: Record<string, string> = {
  planner: 'Analyzes requirements, designs architecture, plans implementation',
  coder: 'Writes production-ready code following project conventions',
  reviewer: 'Runs 24+ deterministic Rigour quality gates on code output',
  qa: 'Writes and executes tests, validates edge cases via Rigour test gates',
  sre: 'Handles production incidents, monitors reliability, runbooks',
  devops: 'Manages infrastructure, CI/CD, deployment pipelines',
};

/**
 * Base pipeline templates by task type.
 * These are STARTING POINTS — the assembler enriches them based on
 * complexity, suggested agents, and task characteristics.
 *
 * Per spec 6.2:
 * - Phase 1: always Coder → Reviewer
 * - Phase 2: uses templates based on task type
 * - Phase 3: custom composition based on context + memory
 */
const PIPELINE_TEMPLATES: Record<string, AgentRole[]> = {
  feature: ['planner', 'coder', 'reviewer'],
  bug: ['coder', 'reviewer'],
  refactor: ['coder', 'reviewer'],
  incident: ['sre', 'coder'],
  test: ['qa', 'coder'],
  infra: ['devops', 'sre'],
  review: ['reviewer'],
};

/**
 * Assembles agent teams based on task classification.
 *
 * The assembler is intelligent about team composition:
 * 1. Starts from a template based on task type
 * 2. Enriches based on complexity (adds planner for high, QA for medium+)
 * 3. Respects the classifier's suggestedAgents
 * 4. Ensures Reviewer is ALWAYS present for code-producing tasks
 * 5. Orders pipeline logically (plan → code → review → test)
 */
export class TeamAssembler {
  private readonly defaultLLMConfig: LLMConfig;
  private readonly modelOverrides: Record<string, string>;

  constructor(
    defaultLLMConfig: LLMConfig,
    modelOverrides: Record<string, string> = {},
  ) {
    this.defaultLLMConfig = defaultLLMConfig;
    this.modelOverrides = modelOverrides;
  }

  /** Assemble a team of agents based on classification. */
  assemble(classification: ClassificationResult): AssembledTeam {
    const pipeline = this.buildIntelligentPipeline(classification);
    const slots = pipeline.map((role, index) =>
      this.createSlot(role, index),
    );

    return {
      slots,
      estimatedTokens: classification.estimatedTokens,
      pipelineOrder: pipeline,
    };
  }

  /**
   * Build an intelligent pipeline based on classification.
   *
   * Logic:
   * 1. Start from task type template
   * 2. Merge in classifier's suggestedAgents
   * 3. Apply complexity-based rules:
   *    - HIGH: Always include planner
   *    - MEDIUM+: Include QA if coder is present
   *    - Any code-producing task: Reviewer must be present
   * 4. Deduplicate and order by logical execution sequence
   */
  private buildIntelligentPipeline(
    classification: ClassificationResult,
  ): AgentRole[] {
    // Start from template
    const template = PIPELINE_TEMPLATES[classification.taskType]
      ?? ['coder', 'reviewer'];
    const agents = new Set<AgentRole>(template);

    // Merge classifier suggestions
    for (const suggested of classification.suggestedAgents) {
      if (this.isValidRole(suggested)) {
        agents.add(suggested as AgentRole);
      }
    }

    // Complexity-based enrichment
    if (classification.complexity === 'high') {
      agents.add('planner');
      if (['feature', 'refactor'].includes(classification.taskType)) {
        agents.add('qa');
      }
    }

    if (classification.complexity === 'medium') {
      if (classification.taskType === 'feature') {
        agents.add('qa');
      }
    }

    // Structural guarantee: if any code-producing agent is present,
    // Reviewer MUST be present (deterministic verification)
    const codeProducers: AgentRole[] = ['coder', 'devops'];
    const hasCodeProducer = codeProducers.some((r) => agents.has(r));
    if (hasCodeProducer) {
      agents.add('reviewer');
    }

    // Order by logical execution sequence
    return this.orderPipeline(Array.from(agents));
  }

  /** Order agents by logical execution sequence. */
  private orderPipeline(agents: AgentRole[]): AgentRole[] {
    const ORDER: AgentRole[] = [
      'planner',
      'sre',
      'devops',
      'coder',
      'reviewer',
      'qa',
    ];
    return ORDER.filter((role) => agents.includes(role));
  }

  private isValidRole(role: string): boolean {
    return role in ROLE_DESCRIPTIONS;
  }

  private createSlot(role: AgentRole, order: number): AgentSlot {
    const model = this.modelOverrides[role] ?? this.defaultLLMConfig.model;
    const description = ROLE_DESCRIPTIONS[role] ?? `Agent with role: ${role}`;

    return {
      role,
      description,
      llmConfig: { ...this.defaultLLMConfig, model },
      order,
    };
  }
}
