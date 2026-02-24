import { z } from 'zod';

/**
 * Type of task to be performed
 */
export const TaskTypeSchema = z.enum([
  'feature',
  'bug',
  'refactor',
  'incident',
  'test',
  'infra',
  'review',
] as const);

export type TaskType = z.infer<typeof TaskTypeSchema>;

/**
 * Current status of a task in the workflow
 */
export const TaskStatusSchema = z.enum([
  'pending',
  'classifying',
  'assembling',
  'running',
  'awaiting_approval',
  'completed',
  'failed',
] as const);

export type TaskStatus = z.infer<typeof TaskStatusSchema>;

/**
 * Outcome results from completed task execution
 */
export const TaskOutcomeSchema = z.object({
  /** Number of quality gates that passed */
  gatesPassed: z.number().int().nonnegative(),
  /** Number of quality gates that failed */
  gatesFailed: z.number().int().nonnegative(),
  /** Number of retry iterations performed */
  retries: z.number().int().nonnegative(),
  /** Total tokens consumed across all executions */
  totalTokens: z.number().int().nonnegative(),
  /** List of files that were changed */
  filesChanged: z.array(z.string()).optional(),
});

export type TaskOutcome = z.infer<typeof TaskOutcomeSchema>;

/**
 * Technical context provided to agents executing a task
 */
export const TaskContextSchema = z.object({
  /** Stored memories relevant to this task */
  memories: z.array(z.record(z.unknown())),
  /** Project configuration if applicable */
  projectConfig: z.record(z.unknown()).optional(),
  /** Technology stack information */
  techStack: z.record(z.string()).optional(),
  /** Results from a previous failed attempt, if any */
  previousAttempt: z.record(z.unknown()).optional(),
  /** Fix packet with constraints and violation details */
  fixPacket: z.record(z.unknown()).optional(),
});

export type TaskContext = z.infer<typeof TaskContextSchema>;

/**
 * Assignment of a task to a team of agents
 */
export const TaskAssignmentSchema = z.object({
  /** Task identifier */
  taskId: z.string().uuid(),
  /** Workspace containing this task */
  workspaceId: z.string().uuid(),
  /** Project containing this task, if applicable */
  projectId: z.string().uuid().optional(),
  /** Task description and requirements */
  description: z.string(),
  /** Type of task */
  type: TaskTypeSchema,
  /** Technical context for execution */
  context: TaskContextSchema,
});

export type TaskAssignment = z.infer<typeof TaskAssignmentSchema>;

/**
 * Core task entity representing work to be performed
 */
export const TaskSchema = z.object({
  /** Unique task identifier */
  id: z.string().uuid(),
  /** Workspace containing this task */
  workspaceId: z.string().uuid(),
  /** Project containing this task, if applicable */
  projectId: z.string().uuid().optional(),
  /** Description of work to be performed */
  description: z.string(),
  /** Task type classification */
  type: TaskTypeSchema.optional(),
  /** Current status in workflow */
  status: TaskStatusSchema,
  /** Whether agents have been assembled for this task */
  teamAssembled: z.boolean().optional(),
  /** Outcome if task has completed */
  outcome: TaskOutcomeSchema.optional(),
  /** Lessons learned from task execution */
  lessonsLearned: z.array(z.string()).optional(),
  /** Estimated token cost for completion */
  tokenCostEstimate: z.number().int().nonnegative().optional(),
  /** Actual duration in milliseconds */
  durationMs: z.number().int().nonnegative().optional(),
  /** Timestamp when execution started */
  startedAt: z.string().datetime().optional(),
  /** Timestamp when execution completed */
  completedAt: z.string().datetime().optional(),
  /** Timestamp when task was created */
  createdAt: z.string().datetime(),
});

export type Task = z.infer<typeof TaskSchema>;
