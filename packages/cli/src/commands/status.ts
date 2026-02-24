'use strict';

import { resolve } from 'path';
import { loadConfig } from '@rigovo/core';

interface StatusOptions {
  project: string;
}

/**
 * Show current project configuration and status.
 */
export async function statusCommand(options: StatusOptions): Promise<void> {
  const projectRoot = resolve(options.project);

  console.log('\nRigovo Teams — Status');
  console.log(`Project: ${projectRoot}\n`);

  const config = await loadConfigSafe(projectRoot);

  if (!config) {
    console.log('No rigovo.yml found. Run "rigovo init" first.');
    return;
  }

  printConfig(config);
  printEnvironment();
}

async function loadConfigSafe(
  projectRoot: string,
): Promise<Record<string, unknown> | null> {
  try {
    const config = await loadConfig(projectRoot);
    return config as unknown as Record<string, unknown>;
  } catch {
    return null;
  }
}

function printConfig(config: Record<string, unknown>): void {
  const models = (config.models ?? {}) as Record<string, unknown>;
  const quality = (config.quality ?? {}) as Record<string, unknown>;
  const trust = (config.trust ?? {}) as Record<string, unknown>;
  const team = (config.team ?? {}) as Record<string, unknown>;

  console.log('Configuration:');
  console.log(`  Version: ${config.version}`);
  console.log(`  Project: ${config.project}`);
  console.log(`  Default Model: ${models.default ?? 'not set'}`);
  console.log(`  Quality Engine: ${quality.engine ?? 'not set'}`);
  console.log(`  Strict Mode: ${quality.strictMode ?? false}`);
  console.log(`  Trust Mode: ${trust.mode ?? 'balanced'}`);
  console.log(`  Max Retries: ${team.maxRetries ?? 3}`);
}

function printEnvironment(): void {
  console.log('\nEnvironment:');

  const vars = [
    'SUPABASE_URL',
    'SUPABASE_ANON_KEY',
    'OPENAI_API_KEY',
    'ANTHROPIC_API_KEY',
  ];

  for (const v of vars) {
    const isSet = !!process.env[v];
    const indicator = isSet ? 'set' : 'not set';
    console.log(`  ${v}: ${indicator}`);
  }
}
