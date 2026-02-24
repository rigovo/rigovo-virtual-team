import { z } from 'zod';

/**
 * Agent roles in the Rigovo Teams platform
 * - master: Orchestrates task decomposition and team assembly
 * - coder: Generates and modifies source code
 * - reviewer: Reviews code quality and gate compliance
 * - qa: Runs tests and validates functionality
 * - planner: Plans approach and architecture
 * - em: Engineering manager, handles approvals
 * - lead: Technical lead, provides guidance
 * - sre: Site reliability engineer, handles ops
 * - devops: DevOps engineer, manages infrastructure
 */
export const AgentRoleSchema = z.enum([
  'master',
  'coder',
  'reviewer',
  'qa',
  'planner',
  'em',
  'lead',
  'sre',
  'devops',
] as const);

export type AgentRole = z.infer<typeof AgentRoleSchema>;

/**
 * Supported LLM providers for agent execution
 */
export const LLMProviderSchema = z.enum(['openai', 'anthropic', 'groq', 'ollama'] as const);

export type LLMProvider = z.infer<typeof LLMProviderSchema>;

/**
 * Configuration for an LLM provider
 */
export const LLMConfigSchema = z.object({
  /** The LLM provider */
  provider: LLMProviderSchema,
  /** Model identifier (e.g., "gpt-4", "claude-opus-4-6") */
  model: z.string(),
  /** API key for authentication */
  apiKey: z.string(),
  /** Optional base URL override for self-hosted or proxy endpoints */
  baseUrl: z.string().optional(),
  /** Sampling temperature (0-2) */
  temperature: z.number().min(0).max(2).optional(),
  /** Maximum tokens in completion */
  maxTokens: z.number().int().positive().optional(),
});

export type LLMConfig = z.infer<typeof LLMConfigSchema>;

/**
 * Role of a message participant in LLM conversations
 */
export const LLMMessageRoleSchema = z.enum(['system', 'user', 'assistant', 'tool'] as const);

export type LLMMessageRole = z.infer<typeof LLMMessageRoleSchema>;

/**
 * A single message in an LLM conversation
 */
export const LLMMessageSchema = z.object({
  /** The role of the message sender */
  role: LLMMessageRoleSchema,
  /** Message content */
  content: z.string(),
  /** For tool messages, the call ID being responded to */
  toolCallId: z.string().optional(),
  /** For tool messages, the tool name */
  name: z.string().optional(),
});

export type LLMMessage = z.infer<typeof LLMMessageSchema>;

/**
 * JSON schema for an LLM tool parameter
 */
export const ToolParameterSchema = z.record(z.unknown());

/**
 * Definition of a tool available to an LLM agent
 */
export const LLMToolSchema = z.object({
  /** Tool name */
  name: z.string(),
  /** Human-readable description */
  description: z.string(),
  /** JSON schema for tool parameters */
  parameters: ToolParameterSchema,
});

export type LLMTool = z.infer<typeof LLMToolSchema>;

/**
 * A tool call within an LLM response
 */
export const LLMToolCallSchema = z.object({
  /** Unique call identifier */
  id: z.string(),
  /** Name of the tool being called */
  name: z.string(),
  /** Stringified JSON arguments */
  arguments: z.string(),
});

export type LLMToolCall = z.infer<typeof LLMToolCallSchema>;

/**
 * Token usage information from LLM API calls
 */
export const TokenUsageSchema = z.object({
  /** Tokens used in the prompt */
  promptTokens: z.number().int().nonnegative(),
  /** Tokens generated in completion */
  completionTokens: z.number().int().nonnegative(),
  /** Total tokens used */
  totalTokens: z.number().int().nonnegative(),
});

export type TokenUsage = z.infer<typeof TokenUsageSchema>;

/**
 * Response from an LLM API call
 */
export const LLMResponseSchema = z.object({
  /** Generated text content */
  content: z.string(),
  /** Tool calls made by the LLM, if any */
  toolCalls: z.array(LLMToolCallSchema).optional(),
  /** Token usage metrics */
  usage: TokenUsageSchema,
});

export type LLMResponse = z.infer<typeof LLMResponseSchema>;

/**
 * Status of agent execution
 */
export const AgentExecutionStatusSchema = z.enum([
  'success',
  'needs_fix',
  'failed',
  'awaiting_approval',
] as const);

export type AgentExecutionStatus = z.infer<typeof AgentExecutionStatusSchema>;

/**
 * Output from an agent execution
 */
export const AgentOutputSchema = z.object({
  /** Role of the agent that executed */
  agentRole: AgentRoleSchema,
  /** Execution status */
  status: AgentExecutionStatusSchema,
  /** List of files that were created or modified */
  filesChanged: z.array(z.string()).optional(),
  /** Human-readable summary of work performed */
  summary: z.string(),
  /** Quality gate results from execution */
  gateResults: z.record(z.unknown()).optional(),
  /** Fix packet if fixes were generated */
  fixPacket: z.record(z.unknown()).optional(),
  /** Test results from execution */
  testResults: z.record(z.unknown()).optional(),
  /** Token usage metrics */
  tokenUsage: TokenUsageSchema,
  /** Duration of execution in milliseconds */
  durationMs: z.number().int().nonnegative(),
});

export type AgentOutput = z.infer<typeof AgentOutputSchema>;

/**
 * Configuration for an agent instance
 */
export const BaseAgentConfigSchema = z.object({
  /** Role of this agent */
  role: AgentRoleSchema,
  /** LLM configuration */
  llmConfig: LLMConfigSchema,
  /** Maximum retries for failed operations */
  maxRetries: z.number().int().positive().optional(),
  /** Timeout in milliseconds */
  timeoutMs: z.number().int().positive().optional(),
  /** Custom system prompt override */
  systemPrompt: z.string().optional(),
  /** Tools available to this agent */
  tools: z.array(LLMToolSchema).optional(),
});

export type BaseAgentConfig = z.infer<typeof BaseAgentConfigSchema>;

/**
 * Base agent instance with common functionality
 */
export const BaseAgentSchema = z.object({
  /** Unique agent identifier */
  id: z.string().uuid(),
  /** Agent configuration */
  config: BaseAgentConfigSchema,
  /** Whether agent is currently active */
  isActive: z.boolean().default(true),
});

export type BaseAgent = z.infer<typeof BaseAgentSchema>;
