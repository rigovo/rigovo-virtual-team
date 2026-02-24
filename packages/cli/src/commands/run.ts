'use strict';

import { randomUUID } from 'crypto';
import { resolve } from 'path';
import {
  loadConfig,
  getDefaultConfig,
  MessageBus,
  LLMClient,
  MasterAgent,
  TeamAssembler,
  PrismaMemoryRepository,
  PrismaAuditRepository,
  type OrchestrationResult,
} from '@rigovo/core';
import { createAgent } from '@rigovo/eng';

interface RunOptions {
  project: string;
  model?: string;
  dryRun?: boolean;
}

/**
 * Execute a task with the full AI engineering team pipeline.
 */
export async function runCommand(
  description: string,
  options: RunOptions,
): Promise<void> {
  const projectRoot = resolve(options.project);
  const taskId = randomUUID();

  console.log(`\nRigovo Teams — Task ${taskId.slice(0, 8)}`);
  console.log(`Project: ${projectRoot}`);
  console.log(`Task: ${description}\n`);

  const config = await loadConfigSafe(projectRoot);
  const llmConfig = buildLLMConfig(config, options.model);

  const llmClient = new LLMClient(llmConfig);
  const bus = new MessageBus();
  const { memoryRepo, auditRepo } = createRepositories(config);

  const assembler = new TeamAssembler(llmConfig, getModelOverrides(config));

  const master = new MasterAgent({
    llmClient,
    bus,
    memoryRepo,
    auditRepo,
    agentFactory: createAgent,
    teamAssembler: assembler,
    maxRetries: (config.team as Record<string, unknown> | undefined)?.maxRetries as number | undefined ?? 3,
    workspaceId: randomUUID(),
  });

  setupBusLogging(bus);

  if (options.dryRun) {
    console.log('[Dry run] Would execute with above configuration.');
    return;
  }

  const result = await master.orchestrate(taskId, description);
  printResult(result);

  bus.destroy();
}

async function loadConfigSafe(
  projectRoot: string,
): Promise<Record<string, unknown>> {
  try {
    const config = await loadConfig(projectRoot);
    return config as unknown as Record<string, unknown>;
  } catch {
    console.log('No rigovo.yml found, using defaults.');
    return getDefaultConfig() as unknown as Record<string, unknown>;
  }
}

function buildLLMConfig(
  config: Record<string, unknown>,
  modelOverride?: string,
): { provider: 'openai' | 'anthropic' | 'groq' | 'ollama'; model: string; apiKey: string } {
  const models = (config.models ?? {}) as Record<string, unknown>;
  const keys = (models.keys ?? {}) as Record<string, string>;

  const model = modelOverride ?? (models.default as string) ?? 'claude-sonnet-4-5-20250929';
  const provider = detectProvider(model);
  const apiKey = keys[provider] ?? process.env[`${provider.toUpperCase()}_API_KEY`] ?? '';

  return { provider, model, apiKey };
}

function detectProvider(
  model: string,
): 'openai' | 'anthropic' | 'groq' | 'ollama' {
  if (model.startsWith('claude')) return 'anthropic';
  if (model.startsWith('gpt') || model.startsWith('o1')) return 'openai';
  if (model.startsWith('llama') || model.startsWith('mixtral')) return 'groq';
  return 'ollama';
}

function createRepositories(_config: Record<string, unknown>): {
  memoryRepo: InstanceType<typeof PrismaMemoryRepository>;
  auditRepo: InstanceType<typeof PrismaAuditRepository>;
} {
  return {
    memoryRepo: new PrismaMemoryRepository(),
    auditRepo: new PrismaAuditRepository(),
  };
}

function getModelOverrides(
  config: Record<string, unknown>,
): Record<string, string> {
  const models = (config.models ?? {}) as Record<string, unknown>;
  const overrides: Record<string, string> = {};

  if (typeof models.coder === 'string') overrides.coder = models.coder;
  if (typeof models.reviewer === 'string') overrides.reviewer = models.reviewer;

  return overrides;
}

function setupBusLogging(bus: MessageBus): void {
  bus.on({ channel: 'type', messageType: 'status_update' }, (msg) => {
    const agentMsg = msg as Record<string, unknown>;
    console.log(`  [${agentMsg.from}] ${agentMsg.message}`);
  });
}

function printResult(result: OrchestrationResult): void {
  console.log('\n--- Results ---');
  console.log(`Success: ${result.success}`);
  console.log(`Steps: ${result.steps.length}`);
  console.log(`Retries: ${result.retries}`);
  console.log(`Tokens: ${result.totalTokens}`);
  console.log(`Duration: ${result.totalDurationMs}ms`);

  for (const step of result.steps) {
    console.log(`  ${step.role}: ${step.output.status} (${step.durationMs}ms)`);
  }
}
