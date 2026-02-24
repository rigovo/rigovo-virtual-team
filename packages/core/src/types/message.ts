import { z } from 'zod';

/**
 * Message types for inter-agent communication
 */
export const MessageTypeSchema = z.enum([
  'task_assignment',
  'code_output',
  'review_result',
  'fix_packet',
  'test_result',
  'approval_request',
  'approval_response',
  'completion',
  'status_update',
] as const);

export type MessageType = z.infer<typeof MessageTypeSchema>;

/**
 * Base message type with common fields
 */
const BaseMessageSchema = z.object({
  /** Unique message identifier */
  id: z.string().uuid().optional(),
  /** ISO 8601 timestamp */
  timestamp: z.string().datetime(),
});

/**
 * Task assignment from master to an agent
 */
export const TaskAssignmentMessageSchema = BaseMessageSchema.extend({
  type: z.literal('task_assignment'),
  /** Always sent from master agent */
  from: z.literal('master'),
  /** Target agent role */
  to: z.string(),
  /** Task assignment details */
  task: z.record(z.unknown()),
});

export type TaskAssignmentMessage = z.infer<typeof TaskAssignmentMessageSchema>;

/**
 * Code output from coder agent
 */
export const CodeOutputMessageSchema = BaseMessageSchema.extend({
  type: z.literal('code_output'),
  from: z.literal('coder'),
  /** Related task identifier */
  taskId: z.string().uuid(),
  /** Files that were created or modified */
  filesChanged: z.array(z.string()),
  /** Summary of changes */
  summary: z.string(),
  /** Whether self-checks passed */
  selfCheckPassed: z.boolean(),
});

export type CodeOutputMessage = z.infer<typeof CodeOutputMessageSchema>;

/**
 * Review status for code or changes
 */
export const ReviewStatusSchema = z.enum(['approved', 'needs_fix'] as const);

export type ReviewStatus = z.infer<typeof ReviewStatusSchema>;

/**
 * Code review result from reviewer agent
 */
export const ReviewResultMessageSchema = BaseMessageSchema.extend({
  type: z.literal('review_result'),
  from: z.literal('reviewer'),
  /** Related task identifier */
  taskId: z.string().uuid(),
  /** Review outcome */
  status: ReviewStatusSchema,
  /** Quality gate results */
  gateResults: z.record(z.unknown()),
});

export type ReviewResultMessage = z.infer<typeof ReviewResultMessageSchema>;

/**
 * Fix packet sent from reviewer to coder for remediation
 */
export const FixPacketMessageSchema = BaseMessageSchema.extend({
  type: z.literal('fix_packet'),
  from: z.literal('reviewer'),
  to: z.literal('coder'),
  /** Related task identifier */
  taskId: z.string().uuid(),
  /** Fix packet with violation details */
  packet: z.record(z.unknown()),
  /** Current retry attempt number */
  retryCount: z.number().int().nonnegative(),
});

export type FixPacketMessage = z.infer<typeof FixPacketMessageSchema>;

/**
 * Test execution result from QA agent
 */
export const TestResultMessageSchema = BaseMessageSchema.extend({
  type: z.literal('test_result'),
  from: z.literal('qa'),
  /** Related task identifier */
  taskId: z.string().uuid(),
  /** Whether all tests passed */
  passed: z.boolean(),
  /** Code coverage percentage if available */
  coverage: z.number().min(0).max(100).optional(),
  /** Detailed test results */
  details: z.record(z.unknown()),
});

export type TestResultMessage = z.infer<typeof TestResultMessageSchema>;

/**
 * Approval options presented to user
 */
export const ApprovalOptionSchema = z.object({
  /** Option identifier */
  id: z.string(),
  /** Human-readable label */
  label: z.string(),
  /** Brief description */
  description: z.string().optional(),
});

export type ApprovalOption = z.infer<typeof ApprovalOptionSchema>;

/**
 * Request for human approval from an agent
 */
export const ApprovalRequestMessageSchema = BaseMessageSchema.extend({
  type: z.literal('approval_request'),
  /** Agent requesting approval */
  from: z.string(),
  to: z.literal('user'),
  /** Related task identifier */
  taskId: z.string().uuid(),
  /** Approval description and rationale */
  description: z.string(),
  /** Available approval options */
  options: z.array(ApprovalOptionSchema),
});

export type ApprovalRequestMessage = z.infer<typeof ApprovalRequestMessageSchema>;

/**
 * User response to an approval request
 */
export const ApprovalResponseMessageSchema = BaseMessageSchema.extend({
  type: z.literal('approval_response'),
  from: z.literal('user'),
  /** Related task identifier */
  taskId: z.string().uuid(),
  /** Whether action was approved */
  approved: z.boolean(),
  /** Optional feedback from user */
  feedback: z.string().optional(),
});

export type ApprovalResponseMessage = z.infer<typeof ApprovalResponseMessageSchema>;

/**
 * Final completion status for a task
 */
export const CompletionStatusSchema = z.enum(['success', 'failed'] as const);

export type CompletionStatus = z.infer<typeof CompletionStatusSchema>;

/**
 * Task completion message from master
 */
export const CompletionMessageSchema = BaseMessageSchema.extend({
  type: z.literal('completion'),
  from: z.literal('master'),
  /** Related task identifier */
  taskId: z.string().uuid(),
  /** Final status */
  status: CompletionStatusSchema,
  /** Summary of execution */
  summary: z.string(),
  /** Task outcome details */
  outcome: z.record(z.unknown()),
});

export type CompletionMessage = z.infer<typeof CompletionMessageSchema>;

/**
 * Status update from any agent
 */
export const StatusUpdateMessageSchema = BaseMessageSchema.extend({
  type: z.literal('status_update'),
  /** Agent providing update */
  from: z.string(),
  /** Related task identifier */
  taskId: z.string().uuid(),
  /** Status message */
  message: z.string(),
});

export type StatusUpdateMessage = z.infer<typeof StatusUpdateMessageSchema>;

/**
 * Union type of all possible agent messages
 */
export const AgentMessageSchema = z.discriminatedUnion('type', [
  TaskAssignmentMessageSchema,
  CodeOutputMessageSchema,
  ReviewResultMessageSchema,
  FixPacketMessageSchema,
  TestResultMessageSchema,
  ApprovalRequestMessageSchema,
  ApprovalResponseMessageSchema,
  CompletionMessageSchema,
  StatusUpdateMessageSchema,
]);

export type AgentMessage =
  | TaskAssignmentMessage
  | CodeOutputMessage
  | ReviewResultMessage
  | FixPacketMessage
  | TestResultMessage
  | ApprovalRequestMessage
  | ApprovalResponseMessage
  | CompletionMessage
  | StatusUpdateMessage;
