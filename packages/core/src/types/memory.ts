import { z } from 'zod';

/**
 * Classification of memory for search and retrieval
 */
export const MemoryTypeSchema = z.enum([
  'lesson',
  'pattern',
  'preference',
  'codebase_context',
] as const);

export type MemoryType = z.infer<typeof MemoryTypeSchema>;

/**
 * Stored memory or knowledge artifact for retrieval
 */
export const MemorySchema = z.object({
  /** Unique memory identifier */
  id: z.string().uuid(),
  /** Workspace containing this memory */
  workspaceId: z.string().uuid(),
  /** Source project if this memory came from a specific project */
  sourceProjectId: z.string().uuid().optional(),
  /** Source task if this memory came from a specific task */
  sourceTaskId: z.string().uuid().optional(),
  /** The actual content of the memory */
  content: z.string(),
  /** Classification type */
  type: MemoryTypeSchema,
  /** Vector embedding for semantic search */
  embedding: z.array(z.number()).optional(),
  /** Number of times this memory was retrieved */
  timesUsed: z.number().int().nonnegative(),
  /** Number of times used outside its source */
  timesUsedOutsideSource: z.number().int().nonnegative(),
  /** Timestamp when memory was created */
  createdAt: z.string().datetime(),
  /** Timestamp when memory was last used */
  lastUsedAt: z.string().datetime().optional(),
  /** Tags for categorization */
  tags: z.array(z.string()).optional(),
});

export type Memory = z.infer<typeof MemorySchema>;

/**
 * Memory with similarity score for search results
 */
export const MemorySearchResultSchema = MemorySchema.extend({
  /** Similarity score from semantic search (0-1) */
  similarity: z.number().min(0).max(1),
});

export type MemorySearchResult = z.infer<typeof MemorySearchResultSchema>;

/**
 * Parameters for memory search and retrieval
 */
export const MemorySearchParamsSchema = z.object({
  /** Search query string */
  query: z.string(),
  /** Workspace to search within */
  workspaceId: z.string().uuid(),
  /** Filter by memory type */
  type: MemoryTypeSchema.optional(),
  /** Limit number of results */
  limit: z.number().int().positive().default(10),
  /** Minimum similarity threshold (0-1) */
  minSimilarity: z.number().min(0).max(1).optional(),
  /** Filter by source project */
  sourceProjectId: z.string().uuid().optional(),
});

export type MemorySearchParams = z.infer<typeof MemorySearchParamsSchema>;

/**
 * Lesson learned from task execution
 */
export const LessonMemorySchema = MemorySchema.extend({
  type: z.literal('lesson'),
  /** Lesson category */
  category: z.enum(['error', 'best_practice', 'pitfall', 'optimization']).optional(),
});

export type LessonMemory = z.infer<typeof LessonMemorySchema>;

/**
 * Reusable code pattern or solution
 */
export const PatternMemorySchema = MemorySchema.extend({
  type: z.literal('pattern'),
  /** Language or framework the pattern applies to */
  language: z.string().optional(),
  /** Sample code demonstrating pattern */
  codeExample: z.string().optional(),
});

export type PatternMemory = z.infer<typeof PatternMemorySchema>;

/**
 * Preference or configuration memory
 */
export const PreferenceMemorySchema = MemorySchema.extend({
  type: z.literal('preference'),
  /** Configuration key */
  key: z.string().optional(),
  /** Configuration value */
  value: z.string().optional(),
});

export type PreferenceMemory = z.infer<typeof PreferenceMemorySchema>;

/**
 * Codebase-specific context and information
 */
export const CodebaseContextMemorySchema = MemorySchema.extend({
  type: z.literal('codebase_context'),
  /** File path or module this context applies to */
  filePath: z.string().optional(),
  /** Relevant code snippet */
  codeSnippet: z.string().optional(),
});

export type CodebaseContextMemory = z.infer<typeof CodebaseContextMemorySchema>;

/**
 * Memory creation request
 */
export const CreateMemorySchema = z.object({
  /** Workspace for this memory */
  workspaceId: z.string().uuid(),
  /** Memory content */
  content: z.string(),
  /** Memory type */
  type: MemoryTypeSchema,
  /** Source project if applicable */
  sourceProjectId: z.string().uuid().optional(),
  /** Source task if applicable */
  sourceTaskId: z.string().uuid().optional(),
  /** Tags for categorization */
  tags: z.array(z.string()).optional(),
});

export type CreateMemory = z.infer<typeof CreateMemorySchema>;
