'use strict';

import type { QualityReport } from '@rigovo/core';
import { exec } from 'child_process';

/**
 * Result from running Rigour quality gates on a project.
 */
export interface RigourGateResult {
  score: number;
  aiHealth: number;
  structural: number;
  passed: boolean;
  violations: GateViolation[];
  report: QualityReport | null;
}

export interface GateViolation {
  severity: 'low' | 'medium' | 'high';
  code: string;
  message: string;
  file?: string;
  hint?: string;
}

/**
 * Wraps the @rigour-labs/cli to run quality gates on a project.
 * Parses the rigour-report.json output into typed results.
 */
export class RigourGate {
  private readonly projectRoot: string;

  constructor(projectRoot: string) {
    if (!projectRoot) {
      throw new Error('RigourGate: projectRoot is required');
    }
    this.projectRoot = projectRoot;
  }

  /** Run quality gates and return typed results. */
  async check(): Promise<RigourGateResult> {
    const output = await this.runCommand('npx @rigour-labs/cli check --json');
    return this.parseCheckOutput(output);
  }

  /** Get the fix packet for current violations. */
  async getFixPacket(): Promise<Record<string, unknown> | null> {
    try {
      const output = await this.runCommand('npx @rigour-labs/cli explain --json');
      return JSON.parse(output) as Record<string, unknown>;
    } catch {
      return null;
    }
  }

  private async runCommand(command: string): Promise<string> {
    return new Promise((resolve, reject) => {
      exec(
        command,
        { cwd: this.projectRoot, timeout: 60000 },
        (error, stdout, stderr) => {
          if (error && !stdout) {
            reject(new Error(`Rigour command failed: ${stderr || error.message}`));
            return;
          }
          resolve(stdout);
        },
      );
    });
  }

  private parseCheckOutput(output: string): RigourGateResult {
    try {
      const report = JSON.parse(output) as Record<string, unknown>;
      return this.mapReportToResult(report);
    } catch {
      return this.parseTextOutput(output);
    }
  }

  private mapReportToResult(report: Record<string, unknown>): RigourGateResult {
    const score = typeof report.score === 'number' ? report.score : 0;
    const passed = score === 100;

    const violations: GateViolation[] = [];
    if (Array.isArray(report.violations)) {
      for (const v of report.violations as Array<Record<string, unknown>>) {
        violations.push({
          severity: (v.severity as GateViolation['severity']) ?? 'medium',
          code: (v.code as string) ?? 'UNKNOWN',
          message: (v.message as string) ?? '',
          file: v.file as string | undefined,
          hint: v.hint as string | undefined,
        });
      }
    }

    return {
      score,
      aiHealth: typeof report.aiHealth === 'number' ? report.aiHealth : score,
      structural: typeof report.structural === 'number' ? report.structural : score,
      passed,
      violations,
      report: report as unknown as QualityReport,
    };
  }

  private parseTextOutput(output: string): RigourGateResult {
    const scoreMatch = output.match(/Score:\s*(\d+)\/100/);
    const score = scoreMatch ? parseInt(scoreMatch[1]!, 10) : 0;

    return {
      score,
      aiHealth: score,
      structural: score,
      passed: output.includes('PASS'),
      violations: [],
      report: null,
    };
  }
}
