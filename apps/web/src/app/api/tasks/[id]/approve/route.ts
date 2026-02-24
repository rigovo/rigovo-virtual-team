import { NextRequest, NextResponse } from 'next/server';
import { resolveApproval, getPendingApproval } from '../../../../../lib/approvals';

/**
 * POST /api/tasks/[id]/approve
 * User approves or rejects a pending approval gate.
 *
 * Body: { checkpoint: string, approved: boolean, feedback?: string, modifications?: object }
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: taskId } = await params;

  const body = await request.json() as {
    checkpoint: string;
    approved: boolean;
    feedback?: string;
    modifications?: Record<string, unknown>;
  };

  if (!body.checkpoint || typeof body.approved !== 'boolean') {
    return NextResponse.json(
      { error: 'checkpoint (string) and approved (boolean) are required' },
      { status: 400 },
    );
  }

  const resolved = resolveApproval(taskId, body.checkpoint, {
    approved: body.approved,
    feedback: body.feedback,
    modifications: body.modifications,
  });

  if (!resolved) {
    return NextResponse.json(
      { error: `No pending approval for checkpoint '${body.checkpoint}' on task ${taskId}` },
      { status: 404 },
    );
  }

  return NextResponse.json({ ok: true, checkpoint: body.checkpoint, approved: body.approved });
}

/**
 * GET /api/tasks/[id]/approve
 * Check if there's a pending approval for this task.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: taskId } = await params;
  const pending = getPendingApproval(taskId);

  if (!pending) {
    return NextResponse.json({ pending: false });
  }

  return NextResponse.json({ pending: true, ...pending });
}
