import { NextRequest } from 'next/server';
import { randomUUID } from 'crypto';
import { addClient, removeClient } from '../../../../../lib/events';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: taskId } = await params;
  const clientId = randomUUID();

  const stream = new ReadableStream({
    start(controller) {
      addClient(taskId, clientId, controller);

      const encoder = new TextEncoder();
      controller.enqueue(
        encoder.encode(`event: connected\ndata: ${JSON.stringify({ clientId })}\n\n`)
      );
    },
    cancel() {
      removeClient(taskId, clientId);
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
    },
  });
}
