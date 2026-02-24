'use strict';

import type { PrismaClient } from '@prisma/client';
import type { Memory, MemorySearchResult } from '../types/index.js';
import type {
  IMemoryRepository,
  MemorySearchParams,
  CreateMemoryInput,
} from '../repositories/index.js';
import { createPrismaClient } from '../prisma-factory.js';

/**
 * Prisma-backed implementation of IMemoryRepository.
 * Uses raw SQL for pgvector cosine-similarity search.
 */
export class PrismaMemoryRepository implements IMemoryRepository {
  private readonly prisma: PrismaClient;

  constructor(prisma?: PrismaClient) {
    this.prisma = prisma ?? createPrismaClient();
  }

  async searchMemories(
    params: MemorySearchParams,
  ): Promise<MemorySearchResult[]> {
    const { queryEmbedding, workspaceId, matchCount = 10 } = params;

    if (!Array.isArray(queryEmbedding) || queryEmbedding.length === 0) {
      return [];
    }

    const embeddingStr = `[${queryEmbedding.join(',')}]`;

    const rows = await this.prisma.$queryRawUnsafe<Array<Record<string, unknown>>>(
      `SELECT *, 1 - (embedding <=> $1::vector) as similarity
       FROM memories
       WHERE workspace_id = $2::uuid AND embedding IS NOT NULL
       ORDER BY embedding <=> $1::vector
       LIMIT $3`,
      embeddingStr, workspaceId, matchCount,
    );

    return rows.map((row) => this.toMemory(row) as MemorySearchResult);
  }

  async storeMemory(input: CreateMemoryInput): Promise<Memory> {
    if (!input.content || input.content.trim().length === 0) {
      throw new Error('Memory content cannot be empty');
    }

    const row = await this.prisma.memory.create({
      data: {
        workspaceId: input.workspaceId,
        sourceProjectId: input.sourceProjectId,
        sourceTaskId: input.sourceTaskId,
        content: input.content,
        type: input.type as 'lesson' | 'pattern' | 'preference' | 'codebase_context',
        timesUsed: 0,
        timesUsedOutsideSource: 0,
        tags: [],
      },
    });

    return this.rowToMemory(row);
  }

  async incrementUsage(
    memoryId: string,
    outsideSource: boolean,
  ): Promise<void> {
    await this.prisma.memory.update({
      where: { id: memoryId },
      data: {
        timesUsed: { increment: 1 },
        timesUsedOutsideSource: outsideSource ? { increment: 1 } : undefined,
        lastUsedAt: new Date(),
      },
    });
  }

  async getMostReused(
    workspaceId: string,
    limit: number = 10,
  ): Promise<Memory[]> {
    const rows = await this.prisma.memory.findMany({
      where: { workspaceId },
      orderBy: { timesUsed: 'desc' },
      take: limit,
    });

    return rows.map((row) => this.rowToMemory(row));
  }

  async deleteMemory(memoryId: string): Promise<void> {
    await this.prisma.memory.delete({ where: { id: memoryId } });
  }

  private rowToMemory(row: Record<string, unknown>): Memory {
    return {
      id: row.id as string,
      workspaceId: row.workspaceId as string,
      sourceProjectId: row.sourceProjectId as string | undefined,
      sourceTaskId: row.sourceTaskId as string | undefined,
      content: row.content as string,
      type: row.type as Memory['type'],
      timesUsed: row.timesUsed as number,
      timesUsedOutsideSource: row.timesUsedOutsideSource as number,
      createdAt: (row.createdAt as Date).toISOString(),
      lastUsedAt: row.lastUsedAt ? (row.lastUsedAt as Date).toISOString() : undefined,
      tags: row.tags as string[] | undefined,
    };
  }

  private toMemory(row: Record<string, unknown>): Memory {
    return {
      id: row.id as string,
      workspaceId: row.workspace_id as string,
      sourceProjectId: row.source_project_id as string | undefined,
      sourceTaskId: row.source_task_id as string | undefined,
      content: row.content as string,
      type: row.type as Memory['type'],
      timesUsed: row.times_used as number,
      timesUsedOutsideSource: row.times_used_outside_source as number,
      createdAt: String(row.created_at),
      lastUsedAt: row.last_used_at ? String(row.last_used_at) : undefined,
      tags: row.tags as string[] | undefined,
    };
  }
}
