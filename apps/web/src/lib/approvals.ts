'use strict';

/**
 * Approval Gate Store — Promise-based mechanism for human-in-the-loop.
 *
 * When MasterAgent hits an approval checkpoint, it:
 * 1. Creates a pending approval via createApproval()
 * 2. Awaits the returned promise (pipeline pauses)
 * 3. The approval API endpoint calls resolveApproval() when user responds
 * 4. The promise resolves and pipeline continues
 *
 * This is an in-memory store — works for single-process deployments.
 * For multi-process, swap with Redis pub/sub or database polling.
 */

export interface ApprovalRequest {
  taskId: string;
  checkpoint: 'plan_ready' | 'team_ready' | 'code_ready' | 'deploy_ready';
  summary: string;
  details: Record<string, unknown>;
  createdAt: string;
}

export interface ApprovalResponse {
  approved: boolean;
  feedback?: string;
  modifications?: Record<string, unknown>;
}

interface PendingApproval {
  request: ApprovalRequest;
  resolve: (response: ApprovalResponse) => void;
}

const pendingApprovals = new Map<string, PendingApproval>();

/** Build a key from taskId + checkpoint for uniqueness. */
function key(taskId: string, checkpoint: string): string {
  return `${taskId}:${checkpoint}`;
}

/**
 * Create a pending approval and return a promise that resolves
 * when the user responds. The MasterAgent awaits this.
 */
export function createApproval(
  request: ApprovalRequest,
): Promise<ApprovalResponse> {
  return new Promise<ApprovalResponse>((resolve) => {
    const k = key(request.taskId, request.checkpoint);
    pendingApprovals.set(k, { request, resolve });
  });
}

/**
 * Resolve a pending approval. Called from the approval API endpoint
 * when the user approves or rejects.
 * Returns true if the approval was found and resolved.
 */
export function resolveApproval(
  taskId: string,
  checkpoint: string,
  response: ApprovalResponse,
): boolean {
  const k = key(taskId, checkpoint);
  const pending = pendingApprovals.get(k);
  if (!pending) return false;

  pending.resolve(response);
  pendingApprovals.delete(k);
  return true;
}

/**
 * Get the current pending approval for a task (if any).
 * Useful for the UI to check what's pending.
 */
export function getPendingApproval(
  taskId: string,
): ApprovalRequest | null {
  for (const [k, v] of pendingApprovals) {
    if (k.startsWith(`${taskId}:`)) {
      return v.request;
    }
  }
  return null;
}

/**
 * Clean up any pending approvals for a task (e.g., on error or cancel).
 */
export function clearApprovals(taskId: string): void {
  for (const k of pendingApprovals.keys()) {
    if (k.startsWith(`${taskId}:`)) {
      pendingApprovals.delete(k);
    }
  }
}
