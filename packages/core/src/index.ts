/**
 * @rigovo/core — Public API
 *
 * The brain of Rigovo Teams. Exports all types, the BaseAgent abstract class,
 * MessageBus for inter-agent communication, repository interfaces for DI,
 * Supabase adapters, and ConfigLoader for rigovo.yml parsing.
 */

export * from './types/index.js';

export { BaseAgent } from './base-agent.js';
export type { BaseAgentConfig } from './base-agent.js';

export { MessageBus } from './message-bus.js';
export type {
  MessageBusConfig,
  MessageHandler,
  Unsubscribe,
  ExternalCallback,
} from './message-bus.js';

export type {
  IMemoryRepository,
  MemorySearchParams,
  CreateMemoryInput,
} from './repositories/index.js';

export type {
  IAuditRepository,
  CreateAuditEntry,
  WorkspaceAuditParams,
} from './repositories/index.js';

export { PrismaMemoryRepository } from './adapters/index.js';
export { PrismaAuditRepository } from './adapters/index.js';
export { createPrismaClient } from './prisma-factory.js';

export { SupabaseMemoryRepository } from './adapters/index.js';
export { SupabaseAuditRepository } from './adapters/index.js';

export { LLMClient } from './llm-client.js';

export { EmbeddingClient } from './embedding-client.js';

export { TaskClassifier } from './task-classifier.js';
export type { ClassificationResult } from './task-classifier.js';

export { TeamAssembler } from './team-assembler.js';
export type { AgentSlot, AssembledTeam } from './team-assembler.js';

export { MasterAgent } from './master-agent.js';
export type {
  MasterAgentConfig,
  AgentFactory,
  AgentDependencies,
  OrchestrationResult,
  OrchestrationEventHandler,
} from './master-agent.js';

export {
  loadConfig,
  validateConfig,
  getDefaultConfig,
  resolveEnvVars,
} from './config-loader.js';
