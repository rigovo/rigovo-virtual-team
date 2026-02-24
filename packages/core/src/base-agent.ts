'use strict';

import type {
  AgentRole,
  LLMConfig,
  LLMMessage,
  LLMResponse,
  LLMTool,
  TaskAssignment,
  AgentOutput,
  AuditActionType,
  Memory,
  MemoryType,
  AgentMessage,
} from './types/index.js';
import type MessageBus from './message-bus.js';
import type { IMemoryRepository } from './repositories/memory-repository.js';
import type { IAuditRepository } from './repositories/audit-repository.js';
import { LLMClient } from './llm-client.js';

export interface BaseAgentConfig {
  role: AgentRole;
  description: string;
  llmConfig: LLMConfig;
  bus: MessageBus;
  auditRepo: IAuditRepository;
  memoryRepo: IMemoryRepository;
  workspaceId: string;
  projectId?: string;
}

/**
 * Abstract base for all Rigovo agents. Provides LLM access, memory,
 * audit logging, and message bus communication via injected dependencies.
 * Subclasses implement execute() with domain-specific logic.
 */
export abstract class BaseAgent {
  readonly role: AgentRole;
  readonly description: string;

  protected readonly llm: LLMClient;
  protected readonly bus: MessageBus;
  protected readonly auditRepo: IAuditRepository;
  protected readonly memoryRepo: IMemoryRepository;
  protected readonly workspaceId: string;
  protected readonly projectId?: string;

  protected totalTokensUsed: number = 0;

  /** Current task ID — set when execute() is called. Used for audit logging. */
  protected currentTaskId: string = '';

  constructor(config: BaseAgentConfig) {
    this.role = config.role;
    this.description = config.description;
    this.llm = new LLMClient(config.llmConfig);
    this.bus = config.bus;
    this.auditRepo = config.auditRepo;
    this.memoryRepo = config.memoryRepo;
    this.workspaceId = config.workspaceId;
    this.projectId = config.projectId;
  }

  /**
   * Main entry point. Sets up task context (taskId for audit),
   * then delegates to the subclass implementation.
   */
  async execute(task: TaskAssignment): Promise<AgentOutput> {
    this.currentTaskId = task.taskId;
    return this.doExecute(task);
  }

  /** Subclasses implement their actual task execution logic here. */
  protected abstract doExecute(task: TaskAssignment): Promise<AgentOutput>;

  /**
   * Wrapper that sets currentTaskId before delegating to subclass execute().
   * Call this from MasterAgent instead of execute() directly.
   */
  async run(task: TaskAssignment): Promise<AgentOutput> {
    this.currentTaskId = task.taskId;
    return this.execute(task);
  }

  /** Send a chat completion request via the LLM client. */
  protected async callLLM(
    messages: LLMMessage[],
    tools?: LLMTool[],
  ): Promise<LLMResponse> {
    const response = await this.llm.chat(messages, tools);
    this.totalTokensUsed += response.usage.totalTokens;
    return response;
  }

  /** Publish a message to the inter-agent bus. */
  protected emit(message: AgentMessage): void {
    this.bus.publish(message);
  }

  /** Write an audit trail entry for this agent. Never throws — logs to console on failure. */
  protected async log(
    actionType: AuditActionType,
    summary: string,
  ): Promise<void> {
    try {
      await this.auditRepo.log({
        taskId: this.currentTaskId,
        workspaceId: this.workspaceId,
        agentRole: this.role,
        actionType,
        outputSummary: summary,
      });
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'unknown';
      console.error(`[${this.role}] Audit log failed: ${detail}`);
    }
  }

  /** Retrieve semantically relevant memories for context. */
  protected async getRelevantMemories(
    embedding: number[],
  ): Promise<Memory[]> {
    return this.memoryRepo.searchMemories({
      queryEmbedding: embedding,
      workspaceId: this.workspaceId,
      matchCount: 10,
    });
  }

  /** Store a new memory from task execution. */
  protected async storeMemory(
    content: string,
    type: MemoryType,
    embedding: number[],
  ): Promise<void> {
    await this.memoryRepo.storeMemory({
      workspaceId: this.workspaceId,
      content,
      type,
      embedding,
    });
  }

  /** Emit a status update message on the bus. */
  protected emitStatus(taskId: string, message: string): void {
    this.emit({
      type: 'status_update',
      timestamp: new Date().toISOString(),
      from: this.role,
      taskId,
      message,
    });
  }
}

export default BaseAgent;
