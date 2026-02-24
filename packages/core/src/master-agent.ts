'use strict';

import type {
  AgentOutput,
  TaskAssignment,
  Task,
  TaskContext,
  AgentRole,
} from './types/index.js';
import type { IMemoryRepository } from './repositories/memory-repository.js';
import type { IAuditRepository } from './repositories/audit-repository.js';
import type { MessageBus } from './message-bus.js';
import { LLMClient } from './llm-client.js';
import { TaskClassifier } from './task-classifier.js';
import type { ClassificationResult } from './task-classifier.js';
import { TeamAssembler } from './team-assembler.js';
import type { AssembledTeam, AgentSlot } from './team-assembler.js';

export type AgentFactory = (
  slot: AgentSlot,
  deps: AgentDependencies,
) => { execute: (task: TaskAssignment) => Promise<AgentOutput> };

export interface AgentDependencies {
  bus: MessageBus;
  memoryRepo: IMemoryRepository;
  auditRepo: IAuditRepository;
  workspaceId: string;
  projectId?: string;
}

/** Callback for real-time orchestration events (SSE, logging, etc). */
export type OrchestrationEventHandler = (
  event: string,
  data: Record<string, unknown>,
) => void;

/**
 * Approval gate configuration — maps to rigovo.yml section 9.1.
 * Each boolean controls whether the pipeline pauses for human approval.
 */
export interface ApprovalConfig {
  afterPlanning: boolean;   // Approve spec before coding starts
  afterCoding: boolean;     // Approve after code generation
  afterReview: boolean;     // Approve after review (even if gates pass)
  beforeCommit: boolean;    // Approve before git commit
}

/**
 * Approval request sent to user. Contains enough context
 * for the user to make an informed decision.
 */
export interface ApprovalRequest {
  taskId: string;
  checkpoint: 'plan_ready' | 'team_ready' | 'code_ready' | 'deploy_ready';
  summary: string;
  details: Record<string, unknown>;
}

/**
 * Approval response from user.
 */
export interface ApprovalResponse {
  approved: boolean;
  feedback?: string;
  modifications?: Record<string, unknown>;
}

/**
 * Handler for approval gates. The web layer injects an implementation
 * that creates a promise, emits SSE, and waits for the user's response.
 */
export type ApprovalHandler = (
  request: ApprovalRequest,
) => Promise<ApprovalResponse>;

export interface MasterAgentConfig {
  llmClient: LLMClient;
  bus: MessageBus;
  memoryRepo: IMemoryRepository;
  auditRepo: IAuditRepository;
  agentFactory: AgentFactory;
  teamAssembler: TeamAssembler;
  maxRetries: number;
  workspaceId: string;
  projectId?: string;
  onEvent?: OrchestrationEventHandler;
  /** Approval gate config — controls where pipeline pauses for human input. */
  approval?: ApprovalConfig;
  /** Handler called when pipeline hits an approval gate. */
  approvalHandler?: ApprovalHandler;
}

interface StepResult {
  role: AgentRole;
  output: AgentOutput;
  durationMs: number;
}

export interface OrchestrationResult {
  task: Task;
  steps: StepResult[];
  totalTokens: number;
  totalDurationMs: number;
  success: boolean;
  retries: number;
  /** If user rejected at an approval gate, this is set. */
  rejectedAt?: string;
  userFeedback?: string;
}

const DEFAULT_APPROVAL: ApprovalConfig = {
  afterPlanning: true,
  afterCoding: false,
  afterReview: false,
  beforeCommit: true,
};

export class MasterAgent {
  private readonly classifier: TaskClassifier;
  private readonly assembler: TeamAssembler;
  private readonly bus: MessageBus;
  private readonly memoryRepo: IMemoryRepository;
  private readonly auditRepo: IAuditRepository;
  private readonly agentFactory: AgentFactory;
  private readonly maxRetries: number;
  private readonly workspaceId: string;
  private readonly projectId?: string;
  private readonly onEvent: OrchestrationEventHandler;
  private readonly approval: ApprovalConfig;
  private readonly approvalHandler: ApprovalHandler | null;

  constructor(config: MasterAgentConfig) {
    this.classifier = new TaskClassifier(config.llmClient);
    this.assembler = config.teamAssembler;
    this.bus = config.bus;
    this.memoryRepo = config.memoryRepo;
    this.auditRepo = config.auditRepo;
    this.agentFactory = config.agentFactory;
    this.maxRetries = config.maxRetries;
    this.workspaceId = config.workspaceId;
    this.projectId = config.projectId;
    this.onEvent = config.onEvent ?? (() => {});
    this.approval = config.approval ?? DEFAULT_APPROVAL;
    this.approvalHandler = config.approvalHandler ?? null;
  }

  async orchestrate(
    taskId: string,
    description: string,
  ): Promise<OrchestrationResult> {
    const startTime = Date.now();

    // ── Phase 1: Classify ────────────────────────────────────────
    this.emit('status_update', {
      from: 'master',
      phase: 'classifying',
      message: 'Analyzing task requirements...',
    });

    await this.safeAudit(taskId, 'classify', 'Starting classification');
    const classification = await this.classifier.classify(description);

    this.emit('classification', {
      taskType: classification.taskType,
      complexity: classification.complexity,
      suggestedAgents: classification.suggestedAgents,
    });

    await this.safeAudit(
      taskId, 'classify',
      `Classified as ${classification.taskType}`,
    );

    // ── Phase 2: Assemble Team ───────────────────────────────────
    this.emit('status_update', {
      from: 'master',
      phase: 'assembling',
      message: `Assembling team for ${classification.taskType} task...`,
    });

    const team = this.assembler.assemble(classification);

    this.emit('team_assembled', {
      agents: team.slots.map((s) => ({
        role: s.role,
        priority: s.order,
      })),
      pipelineOrder: team.pipelineOrder,
    });

    await this.safeAudit(
      taskId, 'assign',
      `Team: ${team.pipelineOrder.join(', ')}`,
    );

    // ── Approval Gate: after_planning ────────────────────────────
    // This is the "plan and team are ready" checkpoint the user asked for.
    // Pipeline pauses here until user approves.
    if (this.approval.afterPlanning) {
      const approvalResult = await this.requestApproval({
        taskId,
        checkpoint: 'plan_ready',
        summary: `Task classified as "${classification.taskType}" (${classification.complexity} complexity). ` +
          `Team assembled: ${team.pipelineOrder.join(' → ')}. Ready to start execution.`,
        details: {
          classification: {
            taskType: classification.taskType,
            complexity: classification.complexity,
            suggestedAgents: classification.suggestedAgents,
          },
          team: {
            pipeline: team.pipelineOrder,
            agents: team.slots.map((s) => ({
              role: s.role,
              description: s.description,
              order: s.order,
            })),
            estimatedTokens: team.estimatedTokens,
          },
        },
      });

      if (!approvalResult.approved) {
        await this.safeAudit(taskId, 'fail', `User rejected at plan_ready: ${approvalResult.feedback ?? 'no feedback'}`);
        this.emit('status_update', {
          from: 'master',
          phase: 'rejected',
          message: `User rejected the plan. ${approvalResult.feedback ?? ''}`,
        });
        return this.buildRejectedResult(
          taskId, description, classification, startTime,
          'plan_ready', approvalResult.feedback,
        );
      }

      // User may have provided modifications (e.g., "add QA agent" or "remove SRE")
      if (approvalResult.feedback) {
        await this.safeAudit(taskId, 'assign', `User feedback: ${approvalResult.feedback}`);
      }
    }

    // ── Phase 3: Build Context ───────────────────────────────────
    const context = await this.buildContext();
    const assignment = this.buildAssignment(
      taskId, description, classification, context,
    );

    // ── Phase 4: Execute Pipeline ────────────────────────────────
    this.emit('status_update', {
      from: 'master',
      phase: 'running',
      message: 'Starting agent pipeline...',
    });

    const { steps, retries } = await this.executePipeline(
      team, assignment, taskId,
    );

    // ── Approval Gate: after_coding ──────────────────────────────
    // Check if user wants to review code before it goes to Reviewer
    const coderStep = steps.find((s) => s.role === 'coder');
    if (this.approval.afterCoding && coderStep?.output.status === 'success') {
      const codeApproval = await this.requestApproval({
        taskId,
        checkpoint: 'code_ready',
        summary: `Coder finished. ${coderStep.output.filesChanged?.length ?? 0} files changed. Ready for review.`,
        details: {
          filesChanged: coderStep.output.filesChanged,
          summary: coderStep.output.summary,
          durationMs: coderStep.durationMs,
          tokens: coderStep.output.tokenUsage.totalTokens,
        },
      });

      if (!codeApproval.approved) {
        await this.safeAudit(taskId, 'fail', `User rejected at code_ready`);
        return this.buildRejectedResult(
          taskId, description, classification, startTime,
          'code_ready', codeApproval.feedback,
        );
      }
    }

    // ── Finalize ─────────────────────────────────────────────────
    const totalTokens = steps.reduce(
      (sum, s) => sum + s.output.tokenUsage.totalTokens, 0,
    );
    const success = steps.every((s) => s.output.status === 'success');

    // ── Post-completion: Store Memory ────────────────────────────
    if (success) {
      await this.storeTaskMemory(taskId, description, classification, steps);
    }

    await this.safeAudit(
      taskId,
      success ? 'complete' : 'fail',
      `Pipeline ${success ? 'succeeded' : 'failed'} (${retries} retries)`,
    );

    return {
      task: this.buildTaskRecord(
        taskId, description, classification, success,
      ),
      steps,
      totalTokens,
      totalDurationMs: Date.now() - startTime,
      success,
      retries,
    };
  }

  // ────────────────────────────────────────────────────────────────
  // Pipeline Execution
  // ────────────────────────────────────────────────────────────────

  private async executePipeline(
    team: AssembledTeam,
    assignment: TaskAssignment,
    taskId: string,
  ): Promise<{ steps: StepResult[]; retries: number }> {
    const steps: StepResult[] = [];
    let retries = 0;
    let currentAssignment = assignment;

    for (const slot of team.slots) {
      this.emit('agent_start', {
        role: slot.role,
        order: slot.order,
        message: `${slot.role} agent starting work...`,
      });

      const result = await this.executeSlotWithRetry(
        slot, currentAssignment, retries,
      );
      steps.push(result.step);
      retries += result.retriesUsed;

      this.emit('agent_complete', {
        role: slot.role,
        status: result.step.output.status,
        summary: result.step.output.summary,
        durationMs: result.step.durationMs,
        tokens: result.step.output.tokenUsage.totalTokens,
      });

      // Emit gate results if the agent produced them
      if (result.step.output.gateResults) {
        this.emit('gate_results', {
          agent: slot.role,
          ...result.step.output.gateResults as Record<string, unknown>,
        });
      }

      if (result.step.output.status === 'needs_fix') {
        this.emit('status_update', {
          from: slot.role,
          phase: 'fixing',
          message: `${slot.role} needs fixes, applying fix packet...`,
        });
        currentAssignment = this.applyFixPacket(
          currentAssignment, result.step.output,
        );
      }

      if (result.step.output.status === 'failed') {
        break;
      }
    }

    return { steps, retries };
  }

  private async executeSlotWithRetry(
    slot: AgentSlot,
    assignment: TaskAssignment,
    priorRetries: number,
  ): Promise<{ step: StepResult; retriesUsed: number }> {
    const deps: AgentDependencies = {
      bus: this.bus,
      memoryRepo: this.memoryRepo,
      auditRepo: this.auditRepo,
      workspaceId: this.workspaceId,
      projectId: this.projectId,
    };

    const agent = this.agentFactory(slot, deps);
    let retriesUsed = 0;
    let lastOutput: AgentOutput | null = null;
    const maxSlotRetries = Math.max(0, this.maxRetries - priorRetries);

    for (let attempt = 0; attempt <= maxSlotRetries; attempt++) {
      const start = Date.now();
      lastOutput = await agent.execute(assignment);
      const durationMs = Date.now() - start;

      if (
        lastOutput.status === 'success' ||
        lastOutput.status === 'failed'
      ) {
        return {
          step: { role: slot.role, output: lastOutput, durationMs },
          retriesUsed,
        };
      }

      retriesUsed++;
      this.emit('agent_retry', {
        role: slot.role,
        attempt: retriesUsed,
        maxRetries: maxSlotRetries,
      });

      await this.safeAudit(
        assignment.taskId, 'retry',
        `Retry ${retriesUsed} for ${slot.role}`,
      );
    }

    return {
      step: { role: slot.role, output: lastOutput!, durationMs: 0 },
      retriesUsed,
    };
  }

  // ────────────────────────────────────────────────────────────────
  // Approval Gates
  // ────────────────────────────────────────────────────────────────

  /**
   * Request human approval. Emits an SSE event and waits for user response.
   * If no approvalHandler is configured, auto-approves (backwards compatible).
   */
  private async requestApproval(
    request: ApprovalRequest,
  ): Promise<ApprovalResponse> {
    // If no handler, auto-approve (e.g., CLI mode, tests, or disabled gates)
    if (!this.approvalHandler) {
      return { approved: true };
    }

    this.emit('status_update', {
      from: 'master',
      phase: 'awaiting_approval',
      message: `Waiting for your approval: ${request.summary}`,
    });

    this.emit('approval_request', {
      checkpoint: request.checkpoint,
      summary: request.summary,
      details: request.details,
    });

    await this.safeAudit(
      request.taskId, 'classify',
      `Awaiting approval at ${request.checkpoint}`,
    );

    // Pipeline pauses here — the promise only resolves when user responds
    const response = await this.approvalHandler(request);

    this.emit('approval_response', {
      checkpoint: request.checkpoint,
      approved: response.approved,
      feedback: response.feedback ?? null,
    });

    await this.safeAudit(
      request.taskId,
      response.approved ? 'assign' : 'fail',
      `Approval ${response.approved ? 'granted' : 'denied'} at ${request.checkpoint}`,
    );

    return response;
  }

  // ────────────────────────────────────────────────────────────────
  // Memory — Post-task learning
  // ────────────────────────────────────────────────────────────────

  /**
   * After successful task completion, extract and store reusable learnings.
   * This is the spec's "flat memory, no scoping" system.
   */
  private async storeTaskMemory(
    taskId: string,
    description: string,
    classification: ClassificationResult,
    steps: StepResult[],
  ): Promise<void> {
    try {
      // Build a summary of what was learned from this task
      const reviewerStep = steps.find((s) => s.role === 'reviewer');
      const coderStep = steps.find((s) => s.role === 'coder');

      const lessons: string[] = [];

      // If reviewer caught issues → store the fix pattern
      if (reviewerStep?.output.status === 'needs_fix' && reviewerStep.output.summary) {
        lessons.push(
          `Task "${description}" (${classification.taskType}): ` +
          `Reviewer flagged issues — ${reviewerStep.output.summary}`,
        );
      }

      // If coder self-check failed → store the pattern
      if (coderStep?.output.summary?.includes('self-check')) {
        lessons.push(
          `Self-check pattern for ${classification.taskType}: ${coderStep.output.summary}`,
        );
      }

      // General completion pattern
      lessons.push(
        `Completed "${description}" as ${classification.taskType} task. ` +
        `Pipeline: ${steps.map((s) => s.role).join(' → ')}. ` +
        `Total retries: ${steps.length}.`,
      );

      for (const lesson of lessons) {
        await this.memoryRepo.storeMemory({
          workspaceId: this.workspaceId,
          content: lesson,
          type: 'task_outcome',
          embedding: [], // TODO: generate embeddings via embedding provider
        });
      }
    } catch (err) {
      console.error('[MasterAgent] Memory storage failed:', err);
    }
  }

  // ────────────────────────────────────────────────────────────────
  // Helpers
  // ────────────────────────────────────────────────────────────────

  private async buildContext(): Promise<TaskContext> {
    try {
      const memories = await this.memoryRepo.searchMemories({
        queryEmbedding: [],
        workspaceId: this.workspaceId,
        matchCount: 5,
      });

      return {
        memories: memories.map((m) => ({
          content: m.content,
          type: m.type,
        })),
        techStack: undefined,
        previousAttempt: undefined,
        fixPacket: undefined,
      };
    } catch {
      return {
        memories: [],
        techStack: undefined,
        previousAttempt: undefined,
        fixPacket: undefined,
      };
    }
  }

  private buildAssignment(
    taskId: string,
    description: string,
    classification: ClassificationResult,
    context: TaskContext,
  ): TaskAssignment {
    return {
      taskId,
      workspaceId: this.workspaceId,
      projectId: this.projectId,
      description,
      type: classification.taskType,
      context,
    };
  }

  private applyFixPacket(
    assignment: TaskAssignment,
    output: AgentOutput,
  ): TaskAssignment {
    return {
      ...assignment,
      context: {
        ...assignment.context,
        fixPacket: output.fixPacket as Record<string, unknown> | undefined,
        previousAttempt: {
          summary: output.summary,
          filesChanged: output.filesChanged,
        },
      },
    };
  }

  private buildTaskRecord(
    taskId: string,
    description: string,
    classification: ClassificationResult,
    success: boolean,
  ): Task {
    return {
      id: taskId,
      workspaceId: this.workspaceId,
      projectId: this.projectId,
      description,
      type: classification.taskType,
      status: success ? 'completed' : 'failed',
      createdAt: new Date().toISOString(),
    };
  }

  private buildRejectedResult(
    taskId: string,
    description: string,
    classification: ClassificationResult,
    startTime: number,
    rejectedAt: string,
    feedback?: string,
  ): OrchestrationResult {
    return {
      task: this.buildTaskRecord(taskId, description, classification, false),
      steps: [],
      totalTokens: 0,
      totalDurationMs: Date.now() - startTime,
      success: false,
      retries: 0,
      rejectedAt,
      userFeedback: feedback,
    };
  }

  /** Emit an orchestration event to the onEvent callback. */
  private emit(
    eventType: string,
    data: Record<string, unknown>,
  ): void {
    try {
      this.onEvent(eventType, {
        ...data,
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      console.error('[MasterAgent] Event emit failed:', err);
    }
  }

  /** Audit log that never throws — failures are logged to console. */
  private async safeAudit(
    taskId: string,
    actionType: string,
    summary: string,
  ): Promise<void> {
    try {
      await this.auditRepo.log({
        taskId,
        workspaceId: this.workspaceId,
        agentRole: 'master',
        actionType: actionType as
          | 'classify' | 'assign' | 'complete'
          | 'fail' | 'retry',
        outputSummary: summary,
      });
    } catch (err) {
      console.error('[MasterAgent] Audit log failed:', err);
    }
  }
}
