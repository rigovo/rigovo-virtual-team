'use strict';

import type {
  AuditEntry,
  AuditActionType,
  AgentRole,
  GateResult,
} from '../types/index.js';

/**
 * Input for creating an audit log entry.
 */
export interface CreateAuditEntry {
  taskId: string;
  workspaceId: string;
  agentRole: AgentRole;
  actionType: AuditActionType;
  inputSummary?: string;
  outputSummary?: string;
  gateResults?: GateResult[];
  fixPacketId?: string;
  durationMs?: number;
  tokenCount?: number;
}

/**
 * Parameters for querying workspace audit history.
 */
export interface WorkspaceAuditParams {
  workspaceId: string;
  limit?: number;
  offset?: number;
}

/**
 * Repository contract for audit trail persistence.
 * Implementations can target Supabase, PostgreSQL, or any log store.
 * Core never depends on a specific database — only on this interface.
 */
export interface IAuditRepository {
  /** Persist an audit entry and return the stored record. */
  log(entry: CreateAuditEntry): Promise<AuditEntry>;

  /** Retrieve all audit entries for a specific task. */
  getTaskAudit(taskId: string): Promise<AuditEntry[]>;

  /** Retrieve paginated audit entries for a workspace. */
  getWorkspaceAudit(params: WorkspaceAuditParams): Promise<AuditEntry[]>;
}
