'use strict';

import type {
  TaskType,
  LLMMessage,
  LLMResponse,
} from './types/index.js';
import type { LLMClient } from './llm-client.js';

/**
 * Classification result from the Master Agent's analysis.
 */
export interface ClassificationResult {
  taskType: TaskType;
  complexity: 'low' | 'medium' | 'high';
  estimatedTokens: number;
  reasoning: string;
  suggestedAgents: string[];
}

const CLASSIFICATION_PROMPT = `You are the Rigovo Master Agent — a super-intelligence that classifies engineering tasks.

Given a task description, return a JSON object with:
- taskType: one of "feature", "bug", "refactor", "incident", "test", "infra", "review"
- complexity: "low", "medium", or "high"
- estimatedTokens: estimated total LLM tokens needed (number)
- reasoning: 1-2 sentence explanation
- suggestedAgents: array of agent roles needed from ["coder", "reviewer", "qa", "planner", "sre", "devops"]

Rules:
- "feature" = new functionality. Needs planner + coder + reviewer.
- "bug" = fix existing broken behavior. Coder + reviewer.
- "refactor" = improve code without changing behavior. Coder + reviewer.
- "incident" = production issue. SRE + coder.
- "test" = add/fix tests. QA + coder.
- "infra" = infrastructure/deployment. DevOps + SRE.
- "review" = code review only. Reviewer.

Complexity guide:
- low: single file, < 50 lines changed, < 5000 tokens
- medium: 2-5 files, < 200 lines, < 20000 tokens
- high: 5+ files, architecture changes, > 20000 tokens

Respond ONLY with valid JSON. No markdown, no explanation outside JSON.`;

/**
 * Classifies user tasks using LLM-powered analysis.
 * Determines task type, complexity, and required agents.
 */
export class TaskClassifier {
  private readonly llm: LLMClient;

  constructor(llm: LLMClient) {
    this.llm = llm;
  }

  /** Classify a task description into type, complexity, and agent roster. */
  async classify(description: string): Promise<ClassificationResult> {
    if (!description || description.trim().length === 0) {
      throw new Error('Task description cannot be empty');
    }

    const messages: LLMMessage[] = [
      { role: 'system', content: CLASSIFICATION_PROMPT },
      { role: 'user', content: description },
    ];

    const response = await this.llm.chat(messages);
    return this.parseClassification(response);
  }

  private parseClassification(response: LLMResponse): ClassificationResult {
    const content = response.content.trim();

    try {
      const parsed = JSON.parse(content) as Record<string, unknown>;
      return this.validateParsedResult(parsed);
    } catch {
      return this.getFallbackClassification();
    }
  }

  private validateParsedResult(
    parsed: Record<string, unknown>
  ): ClassificationResult {
    const validTypes = [
      'feature', 'bug', 'refactor', 'incident', 'test', 'infra', 'review',
    ];
    const validComplexity = ['low', 'medium', 'high'];

    const taskType = validTypes.includes(parsed.taskType as string)
      ? (parsed.taskType as TaskType)
      : 'feature';

    const complexity = validComplexity.includes(parsed.complexity as string)
      ? (parsed.complexity as 'low' | 'medium' | 'high')
      : 'medium';

    const estimatedTokens =
      typeof parsed.estimatedTokens === 'number'
        ? parsed.estimatedTokens
        : 10000;

    const reasoning =
      typeof parsed.reasoning === 'string'
        ? parsed.reasoning
        : 'Classification completed';

    const suggestedAgents = Array.isArray(parsed.suggestedAgents)
      ? (parsed.suggestedAgents as string[])
      : ['coder', 'reviewer'];

    return { taskType, complexity, estimatedTokens, reasoning, suggestedAgents };
  }

  private getFallbackClassification(): ClassificationResult {
    return {
      taskType: 'feature',
      complexity: 'medium',
      estimatedTokens: 15000,
      reasoning: 'Fallback classification — LLM response was not valid JSON',
      suggestedAgents: ['planner', 'coder', 'reviewer'],
    };
  }
}
