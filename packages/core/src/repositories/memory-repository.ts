'use strict';

import type {
  Memory,
  MemorySearchResult,
  MemoryType,
} from '../types/index.js';

/**
 * Parameters for searching memories via vector similarity.
 */
export interface MemorySearchParams {
  queryEmbedding: number[];
  workspaceId: string;
  matchCount?: number;
}

/**
 * Input for creating a new memory record.
 */
export interface CreateMemoryInput {
  workspaceId: string;
  sourceProjectId?: string;
  sourceTaskId?: string;
  content: string;
  type: MemoryType;
  embedding: number[];
}

/**
 * Repository contract for memory persistence.
 * Implementations can target Supabase, PostgreSQL, SQLite, or in-memory stores.
 * Core never depends on a specific database — only on this interface.
 */
export interface IMemoryRepository {
  /** Search memories by vector similarity. */
  searchMemories(params: MemorySearchParams): Promise<MemorySearchResult[]>;

  /** Persist a new memory and return the stored record. */
  storeMemory(input: CreateMemoryInput): Promise<Memory>;

  /** Increment usage counters for a memory. */
  incrementUsage(memoryId: string, outsideSource: boolean): Promise<void>;

  /** Retrieve the most-reused memories in a workspace. */
  getMostReused(workspaceId: string, limit?: number): Promise<Memory[]>;

  /** Delete a memory by ID. */
  deleteMemory(memoryId: string): Promise<void>;
}
