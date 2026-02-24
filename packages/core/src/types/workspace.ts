import { z } from 'zod';

/**
 * Workspace plan tier
 */
export const WorkspacePlanSchema = z.enum(['free', 'pro', 'enterprise'] as const);

export type WorkspacePlan = z.infer<typeof WorkspacePlanSchema>;

/**
 * A workspace is the top-level container for projects and teams
 */
export const WorkspaceSchema = z.object({
  /** Unique workspace identifier */
  id: z.string().uuid(),
  /** Human-readable workspace name */
  name: z.string(),
  /** URL-friendly slug */
  slug: z.string(),
  /** Owner user identifier */
  ownerId: z.string().uuid(),
  /** Subscription plan */
  plan: WorkspacePlanSchema,
  /** Timestamp when workspace was created */
  createdAt: z.string().datetime(),
  /** Timestamp when workspace was last updated */
  updatedAt: z.string().datetime(),
});

export type Workspace = z.infer<typeof WorkspaceSchema>;

/**
 * Technology stack information for a project
 */
export const TechStackSchema = z.object({
  /** Primary programming language */
  language: z.string(),
  /** Framework if applicable */
  framework: z.string().optional(),
  /** ORM if applicable */
  orm: z.string().optional(),
  /** Test runner tool */
  testRunner: z.string().optional(),
  /** Package manager */
  packageManager: z.string().optional(),
}).catchall(z.string());

export type TechStack = z.infer<typeof TechStackSchema>;

/**
 * Configuration for LLM models in a project
 */
export const ModelsConfigSchema = z.object({
  /** Default model to use */
  default: z.string(),
  /** Model for coding tasks */
  coder: z.string().optional(),
  /** Model for review tasks (null to disable) */
  reviewer: z.union([z.string(), z.null()]).optional(),
  /** API keys indexed by provider */
  keys: z.record(z.string()),
});

export type ModelsConfig = z.infer<typeof ModelsConfigSchema>;

/**
 * Quality gate configuration
 */
export const QualityConfigSchema = z.object({
  /** Quality engine to use */
  engine: z.literal('rigour'),
  /** Path to rigour configuration file */
  config: z.string(),
  /** Enable strict quality checking */
  strictMode: z.boolean(),
});

export type QualityConfig = z.infer<typeof QualityConfigSchema>;

/**
 * Memory and knowledge storage configuration
 */
export const MemoryConfigSchema = z.object({
  /** Embedding provider */
  embeddingProvider: z.enum(['openai', 'local']),
  /** Embedding model to use */
  embeddingModel: z.string(),
});

export type MemoryConfig = z.infer<typeof MemoryConfigSchema>;

/**
 * Approval gate configuration
 */
export const ApprovalConfigSchema = z.object({
  /** Require approval after planning phase */
  afterPlanning: z.boolean(),
  /** Require approval after coding phase */
  afterCoding: z.boolean(),
  /** Require approval after review phase */
  afterReview: z.boolean(),
  /** Require approval before committing */
  beforeCommit: z.boolean(),
  /** Auto-create pull requests */
  autoPr: z.boolean().optional(),
});

export type ApprovalConfig = z.infer<typeof ApprovalConfigSchema>;

/**
 * Trust model configuration
 */
export const TrustModeSchema = z.enum(['local', 'balanced', 'cloud'] as const);

export type TrustMode = z.infer<typeof TrustModeSchema>;

export const TrustConfigSchema = z.object({
  /** Trust execution mode */
  mode: TrustModeSchema,
});

export type TrustConfig = z.infer<typeof TrustConfigSchema>;

/**
 * Team configuration
 */
export const TeamConfigSchema = z.object({
  /** Default team template identifier */
  defaultTemplate: z.string().optional(),
  /** Maximum retry attempts */
  maxRetries: z.number().int().positive().default(3),
  /** Task timeout in minutes */
  timeoutMinutes: z.number().int().positive().default(60),
});

export type TeamConfig = z.infer<typeof TeamConfigSchema>;

/**
 * Rigovo platform configuration
 */
export const RigovoConfigSchema = z.object({
  /** Configuration version */
  version: z.string(),
  /** Project name */
  project: z.string(),
  /** LLM models configuration */
  models: ModelsConfigSchema,
  /** Quality gates configuration */
  quality: QualityConfigSchema,
  /** Memory and embeddings configuration */
  memory: MemoryConfigSchema,
  /** Approval gates configuration */
  approval: ApprovalConfigSchema,
  /** Trust model configuration */
  trust: TrustConfigSchema,
  /** Team configuration */
  team: TeamConfigSchema,
});

export type RigovoConfig = z.infer<typeof RigovoConfigSchema>;

/**
 * Project-level configuration
 */
export const ProjectConfigSchema = z.object({
  /** Project root directory */
  projectRoot: z.string(),
  /** Technology stack */
  techStack: TechStackSchema.optional(),
  /** Rigour quality configuration */
  rigourConfig: z.record(z.unknown()).optional(),
  /** Rigovo platform configuration */
  rigovoConfig: RigovoConfigSchema,
});

export type ProjectConfig = z.infer<typeof ProjectConfigSchema>;

/**
 * A project within a workspace
 */
export const ProjectSchema = z.object({
  /** Unique project identifier */
  id: z.string().uuid(),
  /** Workspace containing this project */
  workspaceId: z.string().uuid(),
  /** Project name */
  name: z.string(),
  /** URL-friendly slug */
  slug: z.string(),
  /** Technology stack information */
  techStack: TechStackSchema.optional(),
  /** Project configuration */
  config: ProjectConfigSchema.optional(),
  /** Timestamp when project was created */
  createdAt: z.string().datetime(),
  /** Timestamp when project was last updated */
  updatedAt: z.string().datetime(),
});

export type Project = z.infer<typeof ProjectSchema>;

/**
 * Pre-configured team template for agent assembly
 */
export const TeamTemplateSchema = z.object({
  /** Unique template identifier */
  id: z.string().uuid(),
  /** Workspace containing this template */
  workspaceId: z.string().uuid().optional(),
  /** Template name */
  name: z.string(),
  /** Template description */
  description: z.string().optional(),
  /** Agent roles in this template */
  agents: z.array(z.string()),
  /** Template-specific configuration */
  config: z.record(z.unknown()).optional(),
  /** Whether this is a system template */
  isSystem: z.boolean().default(false),
  /** Timestamp when template was created */
  createdAt: z.string().datetime(),
});

export type TeamTemplate = z.infer<typeof TeamTemplateSchema>;

/**
 * Type of audit action
 */
export const AuditActionTypeSchema = z.enum([
  'classify',
  'assign',
  'generate',
  'review',
  'fix',
  'test',
  'approve',
  'reject',
  'retry',
  'complete',
  'fail',
  'memory_store',
  'memory_retrieve',
] as const);

export type AuditActionType = z.infer<typeof AuditActionTypeSchema>;

/**
 * Audit log entry for task execution
 */
export const AuditEntrySchema = z.object({
  /** Unique audit entry identifier */
  id: z.string().uuid(),
  /** Related task identifier */
  taskId: z.string().uuid(),
  /** Workspace containing task */
  workspaceId: z.string().uuid(),
  /** Agent that performed action */
  agentRole: z.string(),
  /** Type of action performed */
  actionType: AuditActionTypeSchema,
  /** Summary of input provided */
  inputSummary: z.string().optional(),
  /** Summary of output generated */
  outputSummary: z.string().optional(),
  /** Quality gate results if applicable */
  gateResults: z.record(z.unknown()).optional(),
  /** Related fix packet identifier if applicable */
  fixPacketId: z.string().uuid().optional(),
  /** Duration of action in milliseconds */
  durationMs: z.number().int().nonnegative().optional(),
  /** Token count used in action */
  tokenCount: z.number().int().nonnegative().optional(),
  /** Timestamp of audit entry */
  createdAt: z.string().datetime(),
});

export type AuditEntry = z.infer<typeof AuditEntrySchema>;
