'use strict';

import {
  BaseAgent,
  type BaseAgentConfig,
  type TaskAssignment,
  type AgentOutput,
  type LLMMessage,
} from '@rigovo/core';

const PLANNER_SYSTEM_PROMPT = `You are the Rigovo Planner Agent — an architecture and implementation strategist.

Given a task, you produce a detailed implementation plan that guides the Coder Agent.

Your plan must include:
1. files: array of {path, purpose, estimatedLines}
2. dependencies: any new packages needed
3. steps: ordered implementation steps
4. risks: potential issues and mitigations
5. testStrategy: how to verify the implementation

Rules:
- Respect max 400 lines per file, 10 methods per class, 50 lines per function
- Plan for Rigour quality gates compliance from the start
- If memories contain relevant patterns, reference and reuse them

Respond ONLY with valid JSON.`;

/**
 * Planning agent. Analyzes requirements and produces detailed
 * implementation plans for complex tasks before coding begins.
 */
export class PlannerAgent extends BaseAgent {
  constructor(config: BaseAgentConfig) {
    super({ ...config, role: 'planner', description: 'Architecture and implementation planner' });
  }

  protected async doExecute(task: TaskAssignment): Promise<AgentOutput> {
    const startTime = Date.now();
    this.emitStatus(task.taskId, 'Planning implementation approach');

    const messages = this.buildMessages(task);
    const response = await this.callLLM(messages);

    await this.log('generate', `Planned: ${task.description.slice(0, 100)}`);
    this.emitStatus(task.taskId, 'Planning complete');

    const parsed = this.parsePlanResponse(response.content);
    const durationMs = Date.now() - startTime;

    return {
      agentRole: 'planner',
      status: parsed.valid ? 'success' : 'needs_fix',
      summary: parsed.summary,
      filesChanged: parsed.plannedFiles,
      tokenUsage: response.usage,
      durationMs,
    };
  }

  private buildMessages(task: TaskAssignment): LLMMessage[] {
    const messages: LLMMessage[] = [
      { role: 'system', content: PLANNER_SYSTEM_PROMPT },
    ];

    if (task.context.memories.length > 0) {
      const memoryContext = task.context.memories
        .map((m) => `- ${(m as Record<string, unknown>).content}`)
        .join('\n');
      messages.push({
        role: 'system',
        content: `Relevant patterns and lessons:\n${memoryContext}`,
      });
    }

    if (task.context.techStack) {
      messages.push({
        role: 'system',
        content: `Tech stack: ${JSON.stringify(task.context.techStack)}`,
      });
    }

    messages.push({ role: 'user', content: task.description });
    return messages;
  }

  private parsePlanResponse(
    content: string,
  ): { valid: boolean; summary: string; plannedFiles: string[] } {
    try {
      const parsed = JSON.parse(content.trim()) as Record<string, unknown>;
      const files = Array.isArray(parsed.files)
        ? (parsed.files as Array<Record<string, unknown>>).map(
            (f) => f.path as string
          )
        : [];

      const steps = Array.isArray(parsed.steps) ? parsed.steps.length : 0;
      const summary = `Plan: ${files.length} files, ${steps} steps`;

      return { valid: files.length > 0, summary, plannedFiles: files };
    } catch {
      return {
        valid: false,
        summary: 'Failed to parse planner output',
        plannedFiles: [],
      };
    }
  }
}
