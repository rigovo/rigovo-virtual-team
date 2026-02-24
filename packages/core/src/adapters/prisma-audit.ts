'use strict';

import type { PrismaClient } from '@prisma/client';
import type { AuditEntry, AuditActionType } from '../types/index.js';
import type {
  IAuditRepository,
  CreateAuditEntry,
  WorkspaceAuditParams,
} from '../repositories/index.js';
import { createPrismaClient } from '../prisma-factory.js';

/**
 * Prisma-backed implementation of IAuditRepository.
 * Writes audit entries to the audit_logs table.
 */
export class PrismaAuditRepository implements IAuditRepository {
  private readonly prisma: PrismaClient;

  constructor(prisma?: PrismaClient) {
    this.prisma = prisma ?? createPrismaClient();
  }

  async log(entry: CreateAuditEntry): Promise<AuditEntry> {
    if (!entry.taskId || !entry.workspaceId) {
      throw new Error('Task ID and workspace ID are required');
    }

    const row = await this.prisma.auditLog.create({
      data: {
        taskId: entry.taskId,
        workspaceId: entry.workspaceId,
        agentRole: entry.agentRole,
        actionType: entry.actionType as 'classify' | 'assign' | 'generate' | 'review' | 'fix' | 'test' | 'approve' | 'reject' | 'retry' | 'complete' | 'fail' | 'memory_store' | 'memory_retrieve',
        inputSummary: entry.inputSummary,
        outputSummary: entry.outputSummary,
        gateResults: entry.gateResults as object | undefined,
        fixPacketId: entry.fixPacketId,
        durationMs: entry.durationMs,
        tokenCount: entry.tokenCount,
      },
    });

    return this.rowToAuditEntry(row);
  }

  async getTaskAudit(taskId: string): Promise<AuditEntry[]> {
    if (!taskId) {
      throw new Error('Task ID is required');
    }

    const rows = await this.prisma.auditLog.findMany({
      where: { taskId },
      orderBy: { createdAt: 'desc' },
    });

    return rows.map((row) => this.rowToAuditEntry(row));
  }

  async getWorkspaceAudit(
    params: WorkspaceAuditParams,
  ): Promise<AuditEntry[]> {
    const { workspaceId, limit = 100, offset = 0 } = params;

    if (!workspaceId) {
      throw new Error('Workspace ID is required');
    }

    const rows = await this.prisma.auditLog.findMany({
      where: { workspaceId },
      orderBy: { createdAt: 'desc' },
      take: limit,
      skip: offset,
    });

    return rows.map((row) => this.rowToAuditEntry(row));
  }

  private rowToAuditEntry(row: Record<string, unknown>): AuditEntry {
    return {
      id: row.id as string,
      taskId: row.taskId as string,
      workspaceId: row.workspaceId as string,
      agentRole: row.agentRole as string,
      actionType: row.actionType as AuditActionType,
      inputSummary: row.inputSummary as string | undefined,
      outputSummary: row.outputSummary as string | undefined,
      gateResults: row.gateResults as Record<string, unknown> | undefined,
      fixPacketId: row.fixPacketId as string | undefined,
      durationMs: row.durationMs as number | undefined,
      tokenCount: row.tokenCount as number | undefined,
      createdAt: (row.createdAt as Date).toISOString(),
    };
  }
}
