/**
 * @rigovo/core type definitions
 * Core types for the Rigovo Teams platform - a composable AI engineering team
 */

export type {
  AgentRole,
  LLMProvider,
  LLMConfig,
  LLMMessageRole,
  LLMMessage,
  LLMTool,
  LLMToolCall,
  TokenUsage,
  LLMResponse,
  AgentExecutionStatus,
  AgentOutput,
  BaseAgentConfig,
  BaseAgent,
} from './agent.js';

export {
  AgentRoleSchema,
  LLMProviderSchema,
  LLMConfigSchema,
  LLMMessageRoleSchema,
  LLMMessageSchema,
  LLMToolSchema,
  LLMToolCallSchema,
  TokenUsageSchema,
  LLMResponseSchema,
  AgentExecutionStatusSchema,
  AgentOutputSchema,
  BaseAgentConfigSchema,
  BaseAgentSchema,
} from './agent.js';

export type {
  TaskType,
  TaskStatus,
  TaskOutcome,
  TaskContext,
  TaskAssignment,
  Task,
} from './task.js';

export {
  TaskTypeSchema,
  TaskStatusSchema,
  TaskOutcomeSchema,
  TaskContextSchema,
  TaskAssignmentSchema,
  TaskSchema,
} from './task.js';

export type {
  MessageType,
  TaskAssignmentMessage,
  CodeOutputMessage,
  ReviewStatus,
  ReviewResultMessage,
  FixPacketMessage,
  TestResultMessage,
  ApprovalOption,
  ApprovalRequestMessage,
  ApprovalResponseMessage,
  CompletionStatus,
  CompletionMessage,
  StatusUpdateMessage,
  AgentMessage,
} from './message.js';

export {
  MessageTypeSchema,
  TaskAssignmentMessageSchema,
  CodeOutputMessageSchema,
  ReviewStatusSchema,
  ReviewResultMessageSchema,
  FixPacketMessageSchema,
  TestResultMessageSchema,
  ApprovalOptionSchema,
  ApprovalRequestMessageSchema,
  ApprovalResponseMessageSchema,
  CompletionStatusSchema,
  CompletionMessageSchema,
  StatusUpdateMessageSchema,
  AgentMessageSchema,
} from './message.js';

export type {
  GateStatus,
  Severity,
  GateResult,
  FixViolation,
  FixConstraints,
  FixPacketV2,
  TestStatus,
  TestResult,
  TestSuiteResult,
  QualityReport,
} from './quality.js';

export {
  GateStatusSchema,
  SeveritySchema,
  GateResultSchema,
  FixViolationSchema,
  FixConstraintsSchema,
  FixPacketV2Schema,
  TestStatusSchema,
  TestResultSchema,
  TestSuiteResultSchema,
  QualityReportSchema,
} from './quality.js';

export type {
  MemoryType,
  Memory,
  MemorySearchResult,
  MemorySearchParams,
  LessonMemory,
  PatternMemory,
  PreferenceMemory,
  CodebaseContextMemory,
  CreateMemory,
} from './memory.js';

export {
  MemoryTypeSchema,
  MemorySchema,
  MemorySearchResultSchema,
  MemorySearchParamsSchema,
  LessonMemorySchema,
  PatternMemorySchema,
  PreferenceMemorySchema,
  CodebaseContextMemorySchema,
  CreateMemorySchema,
} from './memory.js';

export type {
  WorkspacePlan,
  Workspace,
  TechStack,
  ModelsConfig,
  QualityConfig,
  MemoryConfig,
  ApprovalConfig,
  TrustMode,
  TrustConfig,
  TeamConfig,
  RigovoConfig,
  ProjectConfig,
  Project,
  TeamTemplate,
  AuditActionType,
  AuditEntry,
} from './workspace.js';

export {
  WorkspacePlanSchema,
  WorkspaceSchema,
  TechStackSchema,
  ModelsConfigSchema,
  QualityConfigSchema,
  MemoryConfigSchema,
  ApprovalConfigSchema,
  TrustModeSchema,
  TrustConfigSchema,
  TeamConfigSchema,
  RigovoConfigSchema,
  ProjectConfigSchema,
  ProjectSchema,
  TeamTemplateSchema,
  AuditActionTypeSchema,
  AuditEntrySchema,
} from './workspace.js';
