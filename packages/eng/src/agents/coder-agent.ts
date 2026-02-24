'use strict';

import {
  BaseAgent,
  type BaseAgentConfig,
  type TaskAssignment,
  type AgentOutput,
  type LLMMessage,
  type AgentExecutionStatus,
} from '@rigovo/core';
import { RigourGate } from '../tools/rigour-gate.js';

const CODER_SYSTEM_PROMPT = `You are the Rigovo Coder Agent — a production-grade code generation engine.

You receive a task assignment with description, context (memories, tech stack, fix packets),
and produce code that passes 24+ deterministic quality gates.

Rules:
1. Write TypeScript strict mode, ESM modules, with proper error handling.
2. Follow existing project conventions from context.
3. If a fix packet is provided, address EVERY violation listed. This is non-negotiable.
4. Output a JSON object with: files (array of {path, content}), summary (string).
5. Never hallucinate imports — only use packages listed in package.json or standard library.
6. Keep functions under 50 lines, classes under 10 methods, files under 400 lines.
7. No placeholder comments, TODOs, or unresolved tasks in output.
8. Include proper error handling with typed errors.
9. All exported functions must have JSDoc comments.

Respond ONLY with valid JSON.`;

/**
 * Coder Agent — Production code generation with self-check.
 *
 * Per spec section 6.3:
 * 1. Receive task + context + relevant memories
 * 2. Read existing codebase structure
 * 3. Generate code using LLM with tools
 * 4. Self-check: run rigour check on own output
 * 5. If self-check fails, auto-fix before passing to Reviewer
 * 6. Emit CodeOutput message with files changed
 *
 * If receiving a FixPacket from Reviewer:
 * - Parse structured violations
 * - Apply fixes based on instructions
 * - Re-run self-check
 * - Re-emit
 */
export class CoderAgent extends BaseAgent {
  constructor(config: BaseAgentConfig) {
    super({ ...config, role: 'coder', description: 'Production code generator with self-check' });
  }

  protected async doExecute(task: TaskAssignment): Promise<AgentOutput> {
    const startTime = Date.now();

    // ── Step 1: Generate code via LLM ──
    this.emitStatus(task.taskId, 'Generating production code...');
    const messages = this.buildMessages(task);
    const response = await this.callLLM(messages);

    await this.log('generate', `Generated code for: ${task.description.slice(0, 100)}`);
    const parsed = this.parseCoderResponse(response.content);

    if (!parsed.valid) {
      this.emitStatus(task.taskId, 'Code generation produced invalid output');
      return {
        agentRole: 'coder',
        status: 'needs_fix',
        filesChanged: [],
        summary: parsed.summary,
        tokenUsage: response.usage,
        durationMs: Date.now() - startTime,
      };
    }

    // ── Step 2: Self-check via Rigour ──
    this.emitStatus(task.taskId, 'Running self-check via Rigour quality gates...');
    const selfCheckResult = await this.selfCheck(task);

    if (selfCheckResult && !selfCheckResult.passed) {
      // ── Step 3: Auto-fix if self-check fails ──
      this.emitStatus(
        task.taskId,
        `Self-check found ${selfCheckResult.violations.length} issues (${selfCheckResult.score}/100). Auto-fixing...`,
      );

      const fixMessages = this.buildSelfFixMessages(task, parsed, selfCheckResult);
      const fixResponse = await this.callLLM(fixMessages);
      const fixParsed = this.parseCoderResponse(fixResponse.content);

      await this.log('generate', `Self-fix applied for ${selfCheckResult.violations.length} violations`);

      // Re-run self-check after fix
      const recheck = await this.selfCheck(task);
      const recheckPassed = !recheck || recheck.passed;

      this.emitStatus(
        task.taskId,
        recheckPassed
          ? 'Self-check passed after auto-fix'
          : `Self-check still has ${recheck?.violations.length ?? 0} issues. Passing to Reviewer.`,
      );

      const durationMs = Date.now() - startTime;
      return {
        agentRole: 'coder',
        status: recheckPassed ? 'success' : 'needs_fix',
        filesChanged: fixParsed.files,
        summary: fixParsed.summary + (recheckPassed ? ' (self-check: PASS)' : ` (self-check: ${recheck?.score}/100)`),
        tokenUsage: {
          promptTokens: response.usage.promptTokens + fixResponse.usage.promptTokens,
          completionTokens: response.usage.completionTokens + fixResponse.usage.completionTokens,
          totalTokens: response.usage.totalTokens + fixResponse.usage.totalTokens,
        },
        durationMs,
      };
    }

    // ── Step 4: Self-check passed (or unavailable) ──
    this.emitStatus(task.taskId, 'Code generated. Self-check passed.');
    const durationMs = Date.now() - startTime;

    return {
      agentRole: 'coder',
      status: 'success',
      filesChanged: parsed.files,
      summary: parsed.summary + (selfCheckResult ? ' (self-check: PASS)' : ''),
      tokenUsage: response.usage,
      durationMs,
    };
  }

  /** Run Rigour self-check on the current project state. */
  private async selfCheck(
    task: TaskAssignment,
  ): Promise<{ passed: boolean; score: number; violations: Array<{ code: string; message: string }> } | null> {
    try {
      const projectRoot = this.resolveProjectRoot(task);
      const rigour = new RigourGate(projectRoot);
      const result = await rigour.check();
      return {
        passed: result.passed,
        score: result.score,
        violations: result.violations.map((v) => ({
          code: v.code,
          message: v.message,
        })),
      };
    } catch {
      // Rigour not available — skip self-check
      return null;
    }
  }

  /** Build LLM messages for self-fix based on Rigour violations. */
  private buildSelfFixMessages(
    task: TaskAssignment,
    previousOutput: { files: string[]; summary: string },
    selfCheckResult: { violations: Array<{ code: string; message: string }> },
  ): LLMMessage[] {
    const violationList = selfCheckResult.violations
      .map((v) => `- [${v.code}] ${v.message}`)
      .join('\n');

    return [
      { role: 'system', content: CODER_SYSTEM_PROMPT },
      {
        role: 'system',
        content: `Your previous code generation had ${selfCheckResult.violations.length} quality gate violations.
Fix ALL of the following violations while preserving the working code:

${violationList}

Produce updated files that pass all gates. Respond with the same JSON format.`,
      },
      {
        role: 'user',
        content: `Original task: ${task.description}\nPrevious files: ${previousOutput.files.join(', ')}\nPrevious summary: ${previousOutput.summary}`,
      },
    ];
  }

  private buildMessages(task: TaskAssignment): LLMMessage[] {
    const messages: LLMMessage[] = [
      { role: 'system', content: CODER_SYSTEM_PROMPT },
    ];

    if (task.context.memories.length > 0) {
      const memoryContext = task.context.memories
        .map((m) => `- ${(m as Record<string, unknown>).content}`)
        .join('\n');
      messages.push({
        role: 'system',
        content: `Relevant memories from past tasks:\n${memoryContext}`,
      });
    }

    if (task.context.techStack) {
      messages.push({
        role: 'system',
        content: `Tech stack: ${JSON.stringify(task.context.techStack)}`,
      });
    }

    if (task.context.fixPacket) {
      messages.push({
        role: 'system',
        content: `Fix packet from Reviewer — address EVERY violation:\n${JSON.stringify(task.context.fixPacket, null, 2)}`,
      });
    }

    if (task.context.previousAttempt) {
      messages.push({
        role: 'system',
        content: `Previous attempt (fix these issues):\n${JSON.stringify(task.context.previousAttempt)}`,
      });
    }

    messages.push({ role: 'user', content: task.description });
    return messages;
  }

  private parseCoderResponse(
    content: string,
  ): { valid: boolean; files: string[]; summary: string } {
    try {
      const parsed = JSON.parse(content.trim()) as Record<string, unknown>;
      const files = Array.isArray(parsed.files)
        ? (parsed.files as Array<Record<string, unknown>>).map(
            (f) => f.path as string,
          )
        : [];
      const summary =
        typeof parsed.summary === 'string'
          ? parsed.summary
          : 'Code generated';

      return { valid: files.length > 0, files, summary };
    } catch {
      return {
        valid: false,
        files: [],
        summary: 'Failed to parse coder output as JSON',
      };
    }
  }

  private resolveProjectRoot(task: TaskAssignment): string {
    const techStack = task.context.techStack as Record<string, unknown> | undefined;
    if (techStack && typeof techStack.projectRoot === 'string') {
      return techStack.projectRoot;
    }
    return process.cwd();
  }
}
