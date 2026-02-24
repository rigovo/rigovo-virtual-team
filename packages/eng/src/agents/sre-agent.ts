'use strict';

import {
  BaseAgent,
  type BaseAgentConfig,
  type TaskAssignment,
  type AgentOutput,
  type LLMMessage,
} from '@rigovo/core';

const SRE_SYSTEM_PROMPT = `You are the Rigovo SRE Agent — a site reliability and incident response specialist.

You handle production incidents, analyze system health, and recommend operational fixes.

Your responsibilities:
1. Triage production incidents by severity (P0-P3)
2. Identify root cause from logs, metrics, and code changes
3. Recommend immediate mitigations (rollback, scale, config change)
4. Produce runbooks for recurring issues
5. Assess blast radius of proposed changes

Output a JSON object with:
- severity: "P0" | "P1" | "P2" | "P3"
- rootCause: string describing the identified root cause
- mitigation: array of {action, description, estimatedImpact}
- runbook: array of steps for resolution
- monitoring: array of {metric, threshold, alertChannel}
- summary: brief assessment

Respond ONLY with valid JSON.`;

/**
 * SRE agent. Handles incident triage, root cause analysis,
 * mitigation planning, and operational runbook generation.
 */
export class SREAgent extends BaseAgent {
  constructor(config: BaseAgentConfig) {
    super({ ...config, role: 'sre', description: 'Site reliability and incident response' });
  }

  protected async doExecute(task: TaskAssignment): Promise<AgentOutput> {
    const startTime = Date.now();
    this.emitStatus(task.taskId, 'Analyzing incident');

    const messages = this.buildMessages(task);
    const response = await this.callLLM(messages);

    await this.log('review', `SRE analysis for: ${task.description.slice(0, 100)}`);
    this.emitStatus(task.taskId, 'Incident analysis complete');

    const parsed = this.parseSREResponse(response.content);
    const durationMs = Date.now() - startTime;

    return {
      agentRole: 'sre',
      status: parsed.valid ? 'success' : 'needs_fix',
      summary: parsed.summary,
      gateResults: parsed.assessment,
      tokenUsage: response.usage,
      durationMs,
    };
  }

  private buildMessages(task: TaskAssignment): LLMMessage[] {
    const messages: LLMMessage[] = [
      { role: 'system', content: SRE_SYSTEM_PROMPT },
    ];

    if (task.context.memories.length > 0) {
      const memoryContext = task.context.memories
        .map((m) => `- ${(m as Record<string, unknown>).content}`)
        .join('\n');
      messages.push({
        role: 'system',
        content: `Previous incidents and patterns:\n${memoryContext}`,
      });
    }

    messages.push({ role: 'user', content: task.description });
    return messages;
  }

  private parseSREResponse(
    content: string,
  ): { valid: boolean; summary: string; assessment?: Record<string, unknown> } {
    try {
      const parsed = JSON.parse(content.trim()) as Record<string, unknown>;
      const summary =
        typeof parsed.summary === 'string' ? parsed.summary : 'SRE analysis complete';
      const severity = parsed.severity as string | undefined;
      const rootCause = parsed.rootCause as string | undefined;

      return {
        valid: Boolean(severity && rootCause),
        summary: `[${severity ?? 'P3'}] ${summary}`,
        assessment: { severity, rootCause, mitigation: parsed.mitigation },
      };
    } catch {
      return {
        valid: false,
        summary: 'Failed to parse SRE output',
      };
    }
  }
}
