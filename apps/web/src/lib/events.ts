'use strict';

/**
 * Server-Sent Events (SSE) manager for real-time agent status streaming.
 * Tracks connected clients per task and broadcasts agent messages.
 */

type SSEClient = {
  id: string;
  controller: ReadableStreamDefaultController;
};

const taskClients = new Map<string, SSEClient[]>();

/** Register a new SSE client for a task. */
export function addClient(
  taskId: string,
  clientId: string,
  controller: ReadableStreamDefaultController,
): void {
  const clients = taskClients.get(taskId) ?? [];
  clients.push({ id: clientId, controller });
  taskClients.set(taskId, clients);
}

/** Remove a client when they disconnect. */
export function removeClient(taskId: string, clientId: string): void {
  const clients = taskClients.get(taskId);
  if (!clients) return;

  const filtered = clients.filter((c) => c.id !== clientId);
  if (filtered.length === 0) {
    taskClients.delete(taskId);
  } else {
    taskClients.set(taskId, filtered);
  }
}

/** Broadcast an event to all clients watching a task. */
export function broadcast(taskId: string, event: string, data: unknown): void {
  const clients = taskClients.get(taskId);
  if (!clients) return;

  const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  const encoder = new TextEncoder();
  const encoded = encoder.encode(payload);

  for (const client of clients) {
    try {
      client.controller.enqueue(encoded);
    } catch {
      removeClient(taskId, client.id);
    }
  }
}

/** Get count of connected clients for a task. */
export function getClientCount(taskId: string): number {
  return taskClients.get(taskId)?.length ?? 0;
}
