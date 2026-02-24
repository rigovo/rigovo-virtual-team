'use strict';

import {
  BaseAgent,
  type BaseAgentConfig,
  type TaskAssignment,
  type AgentOutput,
  type LLMMessage,
} from '@rigovo/core';

const DEVOPS_SYSTEM_PROMPT = `You are the Rigovo DevOps Agent — an infrastructure and deployment automation specialist.

You handle CI/CD pipelines, infrastructure-as-code, containerization, and deployment configurations.

Your responsibilities:
1. Generate Dockerfiles, docker-compose configs, and CI/CD pipeline definitions
2. Write infrastructure-as-code (Terraform, Pulumi, or CloudFormation)
3. Configure monitoring, logging, and alerting
4. Set up environment configurations (dev, staging, production)
5. Optimize build and deployment performance

Output a JSON object with:
- files: array of {path, content, type} where type is "dockerfile" | "ci" | "iac" | "config"
- environments: array of {name, variables, services}
- pipeline: {stages: array of {name, steps, triggers}}
- summary: brief description of infrastructure changes

Respond ONLY with valid JSON.`;

/**
 * DevOps agent. Generates infrastructure configs, CI/CD pipelines,
 * container definitions, and deployment automation scripts.
 */
export class DevOpsAgent extends BaseAgent {
  constructor(config: BaseAgentConfig) {
    super({ ...config, role: 'devops', description: 'Infrastructure and deployment automation' });
  }

  protected async doExecute(task: TaskAssignment): Promise<AgentOutput> {
    const startTime = Date.now();
    this.emitStatus(task.taskId, 'Generating infrastructure configuration');

    const messages = this.buildMessages(task);
    const response = await this.callLLM(messages);

    await this.log('generate', `DevOps config for: ${task.description.slice(0, 100)}`);
    this.emitStatus(task.taskId, 'Infrastructure configuration complete');

    const parsed = this.parseDevOpsResponse(response.content);
    const durationMs = Date.now() - startTime;

    return {
      agentRole: 'devops',
      status: parsed.valid ? 'success' : 'needs_fix',
      filesChanged: parsed.files,
      summary: parsed.summary,
      tokenUsage: response.usage,
      durationMs,
    };
  }

  private buildMessages(task: TaskAssignment): LLMMessage[] {
    const messages: LLMMessage[] = [
      { role: 'system', content: DEVOPS_SYSTEM_PROMPT },
    ];

    if (task.context.techStack) {
      messages.push({
        role: 'system',
        content: `Tech stack: ${JSON.stringify(task.context.techStack)}`,
      });
    }

    if (task.context.memories.length > 0) {
      const memoryContext = task.context.memories
        .map((m) => `- ${(m as Record<string, unknown>).content}`)
        .join('\n');
      messages.push({
        role: 'system',
        content: `Infrastructure context:\n${memoryContext}`,
      });
    }

    messages.push({ role: 'user', content: task.description });
    return messages;
  }

  private parseDevOpsResponse(
    content: string,
  ): { valid: boolean; files: string[]; summary: string } {
    try {
      const parsed = JSON.parse(content.trim()) as Record<string, unknown>;
      const files = Array.isArray(parsed.files)
        ? (parsed.files as Array<Record<string, unknown>>).map(
            (f) => f.path as string
          )
        : [];

      const summary =
        typeof parsed.summary === 'string'
          ? parsed.summary
          : 'DevOps configuration generated';

      return { valid: files.length > 0, files, summary };
    } catch {
      return {
        valid: false,
        files: [],
        summary: 'Failed to parse DevOps output',
      };
    }
  }
}
