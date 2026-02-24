'use strict';

import {
  BaseAgent,
  type BaseAgentConfig,
  type TaskAssignment,
  type AgentOutput,
  type LLMMessage,
} from '@rigovo/core';

const QA_SYSTEM_PROMPT = `You are the Rigovo QA Agent — a test generation and validation specialist.

Given a task and its implementation plan or code output, you produce:
1. Unit tests covering critical paths and edge cases
2. Integration test outlines where applicable
3. Validation of expected behavior against the task description

Rules:
- Write tests using vitest (import { describe, it, expect } from 'vitest')
- Cover happy paths, error cases, and boundary conditions
- Mock external dependencies (LLM calls, database, file I/O)
- Each test file should target a single module
- Keep test files under 400 lines

Output a JSON object with:
- testFiles: array of {path, content, targetModule}
- coverage: {statements, branches, functions} as estimated percentages
- summary: brief description of test strategy

Respond ONLY with valid JSON.`;

/**
 * QA agent. Generates comprehensive test suites for code produced
 * by the Coder agent, validating correctness and edge cases.
 */
export class QAAgent extends BaseAgent {
  constructor(config: BaseAgentConfig) {
    super({ ...config, role: 'qa', description: 'Test generation and validation' });
  }

  protected async doExecute(task: TaskAssignment): Promise<AgentOutput> {
    const startTime = Date.now();
    this.emitStatus(task.taskId, 'Generating test suite');

    const messages = this.buildMessages(task);
    const response = await this.callLLM(messages);

    await this.log('review', `Generated tests for: ${task.description.slice(0, 100)}`);
    this.emitStatus(task.taskId, 'Test generation complete');

    const parsed = this.parseQAResponse(response.content);
    const durationMs = Date.now() - startTime;

    return {
      agentRole: 'qa',
      status: parsed.valid ? 'success' : 'needs_fix',
      filesChanged: parsed.testFiles,
      summary: parsed.summary,
      testResults: parsed.coverage,
      tokenUsage: response.usage,
      durationMs,
    };
  }

  private buildMessages(task: TaskAssignment): LLMMessage[] {
    const messages: LLMMessage[] = [
      { role: 'system', content: QA_SYSTEM_PROMPT },
    ];

    if (task.context.previousAttempt) {
      messages.push({
        role: 'system',
        content: `Code to test:\n${JSON.stringify(task.context.previousAttempt)}`,
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

  private parseQAResponse(
    content: string,
  ): { valid: boolean; testFiles: string[]; summary: string; coverage?: Record<string, unknown> } {
    try {
      const parsed = JSON.parse(content.trim()) as Record<string, unknown>;
      const files = Array.isArray(parsed.testFiles)
        ? (parsed.testFiles as Array<Record<string, unknown>>).map(
            (f) => f.path as string
          )
        : [];

      const summary =
        typeof parsed.summary === 'string' ? parsed.summary : 'Tests generated';
      const coverage = parsed.coverage as Record<string, unknown> | undefined;

      return { valid: files.length > 0, testFiles: files, summary, coverage };
    } catch {
      return {
        valid: false,
        testFiles: [],
        summary: 'Failed to parse QA output',
      };
    }
  }
}
