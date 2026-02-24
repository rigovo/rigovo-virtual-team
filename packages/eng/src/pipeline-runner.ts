'use strict';

import type {
  TaskAssignment,
  AgentOutput,
} from '@rigovo/core';
import type { RigourGate, RigourGateResult } from './tools/rigour-gate.js';

/**
 * Tracks the state of a single pipeline iteration.
 */
export interface PipelineIteration {
  attempt: number;
  coderOutput: AgentOutput | null;
  reviewerOutput: AgentOutput | null;
  gateResult: RigourGateResult | null;
  fixPacketApplied: boolean;
}

/**
 * Final pipeline result after all iterations.
 */
export interface PipelineResult {
  success: boolean;
  iterations: PipelineIteration[];
  totalAttempts: number;
  finalGateScore: number;
  filesChanged: string[];
}

type AgentExecutor = (task: TaskAssignment) => Promise<AgentOutput>;

/**
 * Runs the Coder → Rigour → Reviewer → FixPacket retry loop.
 * This is the core engineering pipeline where code is generated,
 * quality-checked against 24+ gates, reviewed, and retried until
 * gates pass or max retries are exhausted.
 */
export class PipelineRunner {
  private readonly maxRetries: number;
  private readonly rigourGate: RigourGate;

  constructor(rigourGate: RigourGate, maxRetries: number = 3) {
    this.rigourGate = rigourGate;
    this.maxRetries = maxRetries;
  }

  /**
   * Execute the full code → check → review → fix loop.
   */
  async run(
    task: TaskAssignment,
    coderExecute: AgentExecutor,
    reviewerExecute: AgentExecutor,
  ): Promise<PipelineResult> {
    const iterations: PipelineIteration[] = [];
    let currentTask = task;
    let finalScore = 0;
    let allFilesChanged: string[] = [];

    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      const iteration = await this.runIteration(
        attempt, currentTask, coderExecute, reviewerExecute,
      );
      iterations.push(iteration);

      finalScore = iteration.gateResult?.score ?? 0;
      allFilesChanged = this.mergeFiles(
        allFilesChanged, iteration.coderOutput?.filesChanged,
      );

      if (this.isSuccess(iteration)) {
        return this.buildResult(true, iterations, finalScore, allFilesChanged);
      }

      currentTask = this.applyFixContext(currentTask, iteration);
    }

    return this.buildResult(false, iterations, finalScore, allFilesChanged);
  }

  private async runIteration(
    attempt: number,
    task: TaskAssignment,
    coderExecute: AgentExecutor,
    reviewerExecute: AgentExecutor,
  ): Promise<PipelineIteration> {
    const coderOutput = await coderExecute(task);

    if (coderOutput.status === 'failed') {
      return { attempt, coderOutput, reviewerOutput: null, gateResult: null, fixPacketApplied: false };
    }

    const gateResult = await this.rigourGate.check();

    if (gateResult.passed) {
      const reviewerOutput = await reviewerExecute(task);
      return { attempt, coderOutput, reviewerOutput, gateResult, fixPacketApplied: false };
    }

    return { attempt, coderOutput, reviewerOutput: null, gateResult, fixPacketApplied: true };
  }

  private isSuccess(iteration: PipelineIteration): boolean {
    const gatesPassed = iteration.gateResult?.passed ?? false;
    const reviewApproved = iteration.reviewerOutput?.status === 'success';
    return gatesPassed && reviewApproved;
  }

  private applyFixContext(
    task: TaskAssignment,
    iteration: PipelineIteration,
  ): TaskAssignment {
    return {
      ...task,
      context: {
        ...task.context,
        fixPacket: iteration.gateResult as unknown as Record<string, unknown>,
        previousAttempt: {
          summary: iteration.coderOutput?.summary ?? '',
          filesChanged: iteration.coderOutput?.filesChanged ?? [],
          gateScore: iteration.gateResult?.score ?? 0,
        },
      },
    };
  }

  private mergeFiles(existing: string[], incoming?: string[]): string[] {
    if (!incoming) return existing;
    const merged = new Set([...existing, ...incoming]);
    return Array.from(merged);
  }

  private buildResult(
    success: boolean,
    iterations: PipelineIteration[],
    finalScore: number,
    filesChanged: string[],
  ): PipelineResult {
    return {
      success,
      iterations,
      totalAttempts: iterations.length,
      finalGateScore: finalScore,
      filesChanged,
    };
  }
}
