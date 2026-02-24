import { promises as fs } from 'fs';
import { join } from 'path';
import { parse as parseYaml } from 'yaml';
import { z } from 'zod';
import { RigovoConfig, RigovoConfigSchema } from './types/index.js';

const ENV_VAR_REGEX = /\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g;

export function resolveEnvVars(value: string): string {
  return value.replace(ENV_VAR_REGEX, (_match: string, varName: string) => {
    const envValue = process.env[varName];
    if (envValue === undefined) {
      throw new Error(`Environment variable ${varName} is not set`);
    }
    return envValue;
  });
}

function resolveEnvVarsInObject(
  obj: Record<string, unknown>
): Record<string, unknown> {
  const resolved: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(obj)) {
    if (typeof value === 'string') {
      resolved[key] = resolveEnvVars(value);
    } else if (value !== null && typeof value === 'object') {
      resolved[key] = resolveEnvVarsInObject(
        value as Record<string, unknown>
      );
    } else {
      resolved[key] = value;
    }
  }

  return resolved;
}

async function readConfigFile(projectRoot: string): Promise<string> {
  const ymlPath = join(projectRoot, 'rigovo.yml');
  const yamlPath = join(projectRoot, 'rigovo.yaml');

  try {
    return await fs.readFile(ymlPath, 'utf-8');
  } catch {
    try {
      return await fs.readFile(yamlPath, 'utf-8');
    } catch {
      throw new Error(
        `Configuration file not found. Looked for rigovo.yml and rigovo.yaml in ${projectRoot}`
      );
    }
  }
}

function parseConfigYaml(content: string): unknown {
  try {
    return parseYaml(content);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : 'Unknown YAML parsing error';
    throw new Error(`Failed to parse YAML configuration: ${message}`);
  }
}

export function validateConfig(config: unknown): RigovoConfig {
  try {
    return RigovoConfigSchema.parse(config);
  } catch (error) {
    if (error instanceof z.ZodError) {
      const messages = error.errors
        .map((err) => `${err.path.join('.')}: ${err.message}`)
        .join('; ');
      throw new Error(`Configuration validation failed: ${messages}`);
    }
    throw error;
  }
}

export async function loadConfig(projectRoot: string): Promise<RigovoConfig> {
  const content = await readConfigFile(projectRoot);
  const parsed = parseConfigYaml(content);

  if (!parsed || typeof parsed !== 'object') {
    throw new Error('Configuration file is empty or invalid');
  }

  const resolved = resolveEnvVarsInObject(
    parsed as Record<string, unknown>
  );
  return validateConfig(resolved);
}

export function getDefaultConfig(): RigovoConfig {
  const config: RigovoConfig = {
    version: '1.0.0',
    project: 'rigovo-project',
    models: {
      default: 'claude-sonnet-4-5-20250929',
      keys: {},
    },
    quality: {
      engine: 'rigour',
      config: './rigour.yml',
      strictMode: false,
    },
    memory: {
      embeddingProvider: 'local',
      embeddingModel: 'all-minilm-l6-v2',
    },
    approval: {
      afterPlanning: false,
      afterCoding: false,
      afterReview: true,
      beforeCommit: false,
      autoPr: false,
    },
    trust: {
      mode: 'balanced',
    },
    team: {
      maxRetries: 3,
      timeoutMinutes: 30,
    },
  };

  return config;
}
