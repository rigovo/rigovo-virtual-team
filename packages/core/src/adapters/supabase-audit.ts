'use strict';

import { createClient } from '@supabase/supabase-js';
import type { AuditEntry, AuditActionType } from '../types/index.js';
import type {
  IAuditRepository,
  CreateAuditEntry,
  WorkspaceAuditParams,
} from '../repositories/index.js';

type SupabaseClient = ReturnType<typeof createClient>;

/**
 * Supabase-backed implementation of IAuditRepository.
 * Writes audit entries to the audit_logs table.
 */
export class SupabaseAuditRepository implements IAuditRepository {
  private client: SupabaseClient;

  constructor(supabaseUrl: string, supabaseKey: string) {
    if (!supabaseUrl || !supabaseKey) {
      throw new Error('Supabase URL and key are required');
    }
    this.client = createClient(supabaseUrl, supabaseKey);
  }

  async log(entry: CreateAuditEntry): Promise<AuditEntry> {
    if (!entry.taskId || !entry.workspaceId) {
      throw new Error('Task ID and workspace ID are required');
    }

    const createdAt = new Date().toISOString();

    const { data, error } = await (this.client
      .from('audit_logs')
      // @ts-expect-error Legacy Supabase adapter
      .insert({
        task_id: entry.taskId,
        workspace_id: entry.workspaceId,
        agent_role: entry.agentRole,
        action_type: entry.actionType,
        input_summary: entry.inputSummary,
        output_summary: entry.outputSummary,
        gate_results: entry.gateResults,
        fix_packet_id: entry.fixPacketId,
        duration_ms: entry.durationMs,
        token_count: entry.tokenCount,
        created_at: createdAt,
      })
      .select()
      .single());

    if (error) {
      throw new Error(`Failed to log audit entry: ${error.message}`);
    }

    return formatAuditRow(data);
  }

  async getTaskAudit(taskId: string): Promise<AuditEntry[]> {
    if (!taskId) {
      throw new Error('Task ID is required');
    }

    const { data, error } = await this.client
      .from('audit_logs')
      .select('*')
      .eq('task_id', taskId)
      .order('created_at', { ascending: false });

    if (error) {
      throw new Error(`Failed to fetch task audit: ${error.message}`);
    }

    return (data ?? []).map((row) => formatAuditRow(row));
  }

  async getWorkspaceAudit(
    params: WorkspaceAuditParams
  ): Promise<AuditEntry[]> {
    const { workspaceId, limit = 100, offset = 0 } = params;

    if (!workspaceId) {
      throw new Error('Workspace ID is required');
    }

    const { data, error } = await this.client
      .from('audit_logs')
      .select('*')
      .eq('workspace_id', workspaceId)
      .order('created_at', { ascending: false })
      .range(offset, offset + limit - 1);

    if (error) {
      throw new Error(`Failed to fetch workspace audit: ${error.message}`);
    }

    return (data ?? []).map((row) => formatAuditRow(row));
  }
}

/** Map a Supabase row to the AuditEntry domain type. */
function formatAuditRow(row: Record<string, unknown>): AuditEntry {
  return {
    id: row.id as string,
    taskId: row.task_id as string,
    workspaceId: row.workspace_id as string,
    agentRole: row.agent_role as string,
    actionType: row.action_type as AuditActionType,
    inputSummary: row.input_summary as string | undefined,
    outputSummary: row.output_summary as string | undefined,
    gateResults: row.gate_results as Record<string, unknown> | undefined,
    fixPacketId: row.fix_packet_id as string | undefined,
    durationMs: row.duration_ms as number | undefined,
    tokenCount: row.token_count as number | undefined,
    createdAt: row.created_at as string,
  };
}
