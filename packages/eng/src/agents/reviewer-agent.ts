'use strict';

import {
  BaseAgent,
  type BaseAgentConfig,
  type TaskAssignment,
  type AgentOutput,
  type AgentExecutionStatus,
} from '@rigovo/core';
import { RigourGate, type RigourGateResult } from '../tools/rigour-gate.js';

/**
 * Reviewer Agent — Independent code quality verifier.
 *
 * Per spec section 6.4:
 * - NEVER inherits context from the Coder (isolated context).
 * - Runs Rigour gate runner (24+ deterministic gates):
 *     Structural: file size, content hygiene
 *     AST: complexity, nesting, method count
 *     Security: secrets, SQLi, XSS, CSRF
 *     AI-specific: hallucinated imports, phantom APIs, deprecated APIs
 *     Test quality: tautological assertions, empty tests
 * - If any gate fails → generate Fix Packet v2 → send back to Coder
 * - If all gates pass → run deep analysis (AST → LLM → verify) if configured
 * - Log all gate results to audit trail
 *
 * The Reviewer uses DETERMINISTIC verification (Rigour), not LLM opinions.
 * This is the structural guarantee that separates Rigovo from competitors.
 */
export class ReviewerAgent extends BaseAgent {
  private rigour: RigourGate | null = null;

  constructor(config: BaseAgentConfig) {
    super({
      ...config,
      role: 'reviewer',
      description: 'Deterministic code quality verifier via Rigour gates',
    });
  }

  protected async doExecute(task: TaskAssignment): Promise<AgentOutput> {
    const startTime = Date.now();
    this.emitStatus(task.taskId, 'Starting deterministic code review via Rigour');

    // Resolve project root from context or fallback
    const projectRoot = this.resolveProjectRoot(task);
    this.rigour = new RigourGate(projectRoot);

    // ── Step 1: Run Rigour quality gates (deterministic, not LLM) ──
    this.emitStatus(task.taskId, 'Running 24+ deterministic quality gates...');
    let gateResult: RigourGateResult;
    try {
      gateResult = await this.rigour.check();
    } catch (err) {
      // If Rigour isn't installed or fails, fall back to LLM-based review
      // but flag it clearly — this is a degraded mode
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      this.emitStatus(task.taskId, `Rigour gates unavailable: ${errorMsg}. Falling back to LLM review.`);
      return this.fallbackLLMReview(task, startTime);
    }

    // ── Step 2: Log gate results to audit trail ──
    await this.log(
      'review',
      `Rigour gates: ${gateResult.score}/100 | Passed: ${gateResult.passed} | ` +
      `Violations: ${gateResult.violations.length} | ` +
      `AI Health: ${gateResult.aiHealth} | Structural: ${gateResult.structural}`,
    );

    // ── Step 3: If gates fail → generate Fix Packet ──
    if (!gateResult.passed) {
      this.emitStatus(
        task.taskId,
        `${gateResult.violations.length} gate violations found (score: ${gateResult.score}/100). Generating fix packet...`,
      );

      const fixPacket = await this.buildFixPacket(gateResult);
      const durationMs = Date.now() - startTime;

      const violationSummary = gateResult.violations
        .slice(0, 5)
        .map((v) => `[${v.severity.toUpperCase()}] ${v.code}: ${v.message}`)
        .join('\n');

      return {
        agentRole: 'reviewer',
        status: 'needs_fix',
        summary: `Review FAILED — ${gateResult.violations.length} violations (${gateResult.score}/100)\n${violationSummary}`,
        gateResults: this.formatGateResults(gateResult),
        fixPacket: fixPacket ?? undefined,
        tokenUsage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
        durationMs,
      };
    }

    // ── Step 4: All gates pass ──
    this.emitStatus(task.taskId, `All gates pass (${gateResult.score}/100). Code approved.`);
    const durationMs = Date.now() - startTime;

    return {
      agentRole: 'reviewer',
      status: 'success',
      summary: `Review APPROVED — ${gateResult.score}/100, all ${gateResult.violations.length === 0 ? '24+' : 'checked'} gates pass`,
      gateResults: this.formatGateResults(gateResult),
      tokenUsage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
      durationMs,
    };
  }

  /** Build a structured Fix Packet v2 from Rigour gate results. */
  private async buildFixPacket(
    gateResult: RigourGateResult,
  ): Promise<Record<string, unknown> | null> {
    // First try to get Rigour's own fix packet (machine-readable)
    if (this.rigour) {
      const rigourPacket = await this.rigour.getFixPacket();
      if (rigourPacket) return rigourPacket;
    }

    // Fallback: construct from violation list
    if (gateResult.violations.length === 0) return null;

    return {
      violations: gateResult.violations.map((v) => ({
        id: v.code,
        severity: v.severity,
        file: v.file ?? 'unknown',
        instructions: [v.message, v.hint ?? 'Fix the violation'].filter(Boolean),
      })),
      constraints: {
        noNewDeps: false,
        doNotTouch: [],
        maxRetries: 3,
      },
      generatedAt: new Date().toISOString(),
    };
  }

  /** Format gate results for the AgentOutput.gateResults field. */
  private formatGateResults(result: RigourGateResult): Record<string, unknown> {
    return {
      score: result.score,
      aiHealth: result.aiHealth,
      structural: result.structural,
      passed: result.passed,
      violationCount: result.violations.length,
      violations: result.violations.map((v) => ({
        severity: v.severity,
        code: v.code,
        message: v.message,
        file: v.file,
      })),
    };
  }

  /** Resolve project root for Rigour execution. */
  private resolveProjectRoot(task: TaskAssignment): string {
    // Look for project root in context or fall back to cwd
    const techStack = task.context.techStack as Record<string, unknown> | undefined;
    if (techStack && typeof techStack.projectRoot === 'string') {
      return techStack.projectRoot;
    }
    return process.cwd();
  }

  /**
   * Fallback LLM-based review when Rigour is unavailable.
   * This is a DEGRADED mode — clearly flagged as non-deterministic.
   */
  private async fallbackLLMReview(
    task: TaskAssignment,
    startTime: number,
  ): Promise<AgentOutput> {
    const messages = [
      {
        role: 'system' as const,
        content: `You are a code reviewer. This is a FALLBACK review — deterministic Rigour gates are unavailable.
Review the code output for: correctness, security issues, best practices.
Output JSON: { "status": "approved" | "needs_fix", "issues": [...], "summary": "..." }
Be strict. Respond ONLY with valid JSON.`,
      },
      {
        role: 'user' as const,
        content: `Task: ${task.description}\nPrevious output: ${JSON.stringify(task.context.previousAttempt ?? 'none')}`,
      },
    ];

    const response = await this.callLLM(messages);
    const durationMs = Date.now() - startTime;

    try {
      const parsed = JSON.parse(response.content.trim()) as Record<string, unknown>;
      const status: AgentExecutionStatus =
        parsed.status === 'approved' ? 'success' : 'needs_fix';

      return {
        agentRole: 'reviewer',
        status,
        summary: `[FALLBACK LLM REVIEW] ${parsed.summary ?? 'Review complete'}`,
        gateResults: { fallback: true, issues: parsed.issues },
        fixPacket: parsed.fixPacket as Record<string, unknown> | undefined,
        tokenUsage: response.usage,
        durationMs,
      };
    } catch {
      return {
        agentRole: 'reviewer',
        status: 'needs_fix',
        summary: '[FALLBACK] Failed to parse review response',
        tokenUsage: response.usage,
        durationMs,
      };
    }
  }
}
