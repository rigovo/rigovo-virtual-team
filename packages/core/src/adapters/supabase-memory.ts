'use strict';

import { createClient } from '@supabase/supabase-js';
import type { Memory, MemorySearchResult } from '../types/index.js';
import type {
  IMemoryRepository,
  MemorySearchParams,
  CreateMemoryInput,
} from '../repositories/index.js';

type SupabaseClient = ReturnType<typeof createClient>;

/**
 * Supabase-backed implementation of IMemoryRepository.
 * Uses pgvector RPC for cosine-similarity search.
 */
export class SupabaseMemoryRepository implements IMemoryRepository {
  private client: SupabaseClient;

  constructor(supabaseUrl: string, supabaseKey: string) {
    if (!supabaseUrl || !supabaseKey) {
      throw new Error('Supabase URL and key are required');
    }
    this.client = createClient(supabaseUrl, supabaseKey);
  }

  async searchMemories(
    params: MemorySearchParams
  ): Promise<MemorySearchResult[]> {
    const { queryEmbedding, workspaceId, matchCount = 10 } = params;

    if (!Array.isArray(queryEmbedding) || queryEmbedding.length === 0) {
      throw new Error('Query embedding must be a non-empty array');
    }

    const { data, error } = await this.client.rpc('search_memories', {
      query_embedding: queryEmbedding,
      workspace_id: workspaceId,
      match_count: matchCount,
    } as any);

    if (error) {
      throw new Error(`Memory search failed: ${error.message}`);
    }

    return (data ?? []) as MemorySearchResult[];
  }

  async storeMemory(input: CreateMemoryInput): Promise<Memory> {
    if (!input.content || input.content.trim().length === 0) {
      throw new Error('Memory content cannot be empty');
    }

    const { data, error } = await (this.client
      .from('memories')
      // @ts-expect-error Legacy Supabase adapter
      .insert({
        workspace_id: input.workspaceId,
        source_project_id: input.sourceProjectId,
        source_task_id: input.sourceTaskId,
        content: input.content,
        type: input.type,
        embedding: input.embedding,
        times_used: 0,
        times_used_outside_source: 0,
      })
      .select()
      .single());

    if (error) {
      throw new Error(`Failed to store memory: ${error.message}`);
    }

    return formatMemoryRow(data);
  }

  async incrementUsage(
    memoryId: string,
    outsideSource: boolean
  ): Promise<void> {
    const { error: fetchError } = await this.client
      .from('memories')
      .select('times_used, times_used_outside_source')
      .eq('id', memoryId)
      .single();

    if (fetchError) {
      throw new Error(`Memory not found: ${fetchError.message}`);
    }

    const updates: Record<string, number> = { times_used: 1 };
    if (outsideSource) {
      updates.times_used_outside_source = 1;
    }

    const { error: updateError } = await (this.client
      .from('memories')
      // @ts-expect-error Legacy Supabase adapter
      .update(updates as any)
      .eq('id', memoryId));

    if (updateError) {
      throw new Error(`Failed to increment usage: ${updateError.message}`);
    }
  }

  async getMostReused(
    workspaceId: string,
    limit: number = 10
  ): Promise<Memory[]> {
    const { data, error } = await this.client
      .from('memories')
      .select('*')
      .eq('workspace_id', workspaceId)
      .order('times_used', { ascending: false })
      .limit(limit);

    if (error) {
      throw new Error(`Failed to fetch memories: ${error.message}`);
    }

    return (data ?? []).map((row) => formatMemoryRow(row));
  }

  async deleteMemory(memoryId: string): Promise<void> {
    const { error } = await this.client
      .from('memories')
      .delete()
      .eq('id', memoryId);

    if (error) {
      throw new Error(`Failed to delete memory: ${error.message}`);
    }
  }
}

/** Map a Supabase row to the Memory domain type. */
function formatMemoryRow(row: Record<string, unknown>): Memory {
  return {
    id: row.id as string,
    workspaceId: row.workspace_id as string,
    sourceProjectId: row.source_project_id as string | undefined,
    sourceTaskId: row.source_task_id as string | undefined,
    content: row.content as string,
    type: row.type as Memory['type'],
    embedding: row.embedding as number[] | undefined,
    timesUsed: row.times_used as number,
    timesUsedOutsideSource: row.times_used_outside_source as number,
    createdAt: row.created_at as string,
    lastUsedAt: row.last_used_at as string | undefined,
    tags: row.tags as string[] | undefined,
  };
}
