import { NextRequest, NextResponse } from 'next/server';
import { randomUUID } from 'crypto';
import { prisma } from '../../../lib/prisma';
import { broadcast } from '../../../lib/events';
import { createApproval, clearApprovals } from '../../../lib/approvals';
import type { ApprovalRequest } from '../../../lib/approvals';
import {
  MessageBus,
  LLMClient,
  MasterAgent,
  TeamAssembler,
  PrismaMemoryRepository,
  PrismaAuditRepository,
} from '@rigovo/core';
import type { ApprovalConfig, ApprovalHandler } from '@rigovo/core';
import { createAgent } from '@rigovo/eng';

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { description } = body as { description: string };

  if (!description || description.trim().length === 0) {
    return NextResponse.json(
      { error: 'Description required' },
      { status: 400 },
    );
  }

  const workspace = await getOrCreateWorkspace();

  const task = await prisma.task.create({
    data: {
      workspaceId: workspace.id,
      description,
      status: 'classifying',
      startedAt: new Date(),
    },
  });

  runOrchestration(task.id, description, workspace.id).catch(
    console.error,
  );

  return NextResponse.json({ taskId: task.id, status: 'classifying' });
}

/** Get or create a default workspace for local dev. */
async function getOrCreateWorkspace() {
  const envId = process.env.DEFAULT_WORKSPACE_ID || '';

  if (envId) {
    const existing = await prisma.workspace.findUnique({
      where: { id: envId },
    });
    if (existing) return existing;
  }

  const existing = await prisma.workspace.findFirst({
    where: { slug: 'default' },
  });
  if (existing) return existing;

  return prisma.workspace.create({
    data: {
      name: 'Default Workspace',
      slug: 'default',
      ownerId: randomUUID(),
      plan: 'free',
    },
  });
}

/**
 * Run real MasterAgent orchestration.
 * The onEvent callback streams events directly to SSE clients.
 * The approvalHandler creates a promise that pauses the pipeline
 * until the user responds via POST /api/tasks/[id]/approve.
 */
async function runOrchestration(
  taskId: string,
  description: string,
  workspaceId: string,
): Promise<void> {
  const bus = new MessageBus();
  const memoryRepo = new PrismaMemoryRepository(prisma);
  const auditRepo = new PrismaAuditRepository(prisma);

  const llmConfig = buildLLMConfig();
  const llmClient = new LLMClient(llmConfig);
  const assembler = new TeamAssembler(llmConfig);

  // Build approval config from env or defaults
  const approval = buildApprovalConfig();

  // The approval handler bridges MasterAgent (backend) with the user (frontend).
  // When MasterAgent hits an approval gate:
  // 1. Creates a promise in the shared approval store
  // 2. The promise resolves when POST /api/tasks/[id]/approve is called
  // 3. MasterAgent was awaiting this promise, so pipeline resumes
  const approvalHandler: ApprovalHandler = async (request) => {
    // Map to the shared approval store format
    const storeRequest: ApprovalRequest = {
      taskId: request.taskId,
      checkpoint: request.checkpoint,
      summary: request.summary,
      details: request.details,
      createdAt: new Date().toISOString(),
    };

    // This promise won't resolve until the user calls the approve endpoint
    return createApproval(storeRequest);
  };

  const master = new MasterAgent({
    llmClient,
    bus,
    memoryRepo,
    auditRepo,
    agentFactory: createAgent,
    teamAssembler: assembler,
    maxRetries: 3,
    workspaceId,
    approval,
    approvalHandler,
    onEvent: (event, data) => {
      broadcast(taskId, event, data);
    },
  });

  try {
    const result = await master.orchestrate(taskId, description);

    await prisma.task.update({
      where: { id: taskId },
      data: {
        status: result.success ? 'completed' : 'failed',
        completedAt: new Date(),
        durationMs: result.totalDurationMs,
      },
    });

    broadcast(taskId, 'task_complete', {
      success: result.success,
      steps: result.steps.length,
      totalTokens: result.totalTokens,
      duration: result.totalDurationMs,
      retries: result.retries,
      rejectedAt: result.rejectedAt ?? null,
      userFeedback: result.userFeedback ?? null,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : 'Unknown error';

    broadcast(taskId, 'task_error', { error: message });

    try {
      await prisma.task.update({
        where: { id: taskId },
        data: { status: 'failed', completedAt: new Date() },
      });
    } catch {
      console.error('[route] Failed to update task status');
    }
  } finally {
    clearApprovals(taskId);
    bus.destroy();
  }
}

/**
 * Build approval config from environment variables.
 * Defaults match the spec: after_planning=true, before_commit=true, rest=false.
 */
function buildApprovalConfig(): ApprovalConfig {
  return {
    afterPlanning: process.env.APPROVAL_AFTER_PLANNING !== 'false',
    afterCoding: process.env.APPROVAL_AFTER_CODING === 'true',
    afterReview: process.env.APPROVAL_AFTER_REVIEW === 'true',
    beforeCommit: process.env.APPROVAL_BEFORE_COMMIT !== 'false',
  };
}

function buildLLMConfig(): {
  provider: 'openai' | 'anthropic' | 'groq' | 'ollama';
  model: string;
  apiKey: string;
} {
  const model = process.env.LLM_MODEL ?? 'claude-sonnet-4-6';
  const provider = detectProvider(model);
  const keyEnv = `${provider.toUpperCase()}_API_KEY`;
  const apiKey = process.env[keyEnv] ?? '';

  return { provider, model, apiKey };
}

function detectProvider(
  model: string,
): 'openai' | 'anthropic' | 'groq' | 'ollama' {
  if (model.startsWith('claude')) return 'anthropic';
  if (model.startsWith('gpt') || model.startsWith('o1')) return 'openai';
  if (model.startsWith('llama') || model.startsWith('mixtral'))
    return 'groq';
  return 'ollama';
}
