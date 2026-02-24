'use strict';

import { promises as fs } from 'fs';
import { join } from 'path';
import { resolve } from 'path';

interface InitOptions {
  project: string;
}

const RIGOVO_YML_TEMPLATE = `# Rigovo Teams configuration
# See https://rigovo.dev/docs/config for full reference

version: "1.0.0"
project: "{PROJECT_NAME}"

models:
  default: claude-sonnet-4-5-20250929
  keys: {}

quality:
  engine: rigour
  config: ./rigour.yml
  strictMode: false

memory:
  embeddingProvider: local
  embeddingModel: all-minilm-l6-v2

approval:
  afterPlanning: false
  afterCoding: false
  afterReview: true
  beforeCommit: false
  autoPr: false

trust:
  mode: balanced

team:
  maxRetries: 3
  timeoutMinutes: 30
`;

/**
 * Initialize Rigovo configuration in a project directory.
 * Creates rigovo.yml with sensible defaults if it doesn't exist.
 */
export async function initCommand(options: InitOptions): Promise<void> {
  const projectRoot = resolve(options.project);
  const configPath = join(projectRoot, 'rigovo.yml');

  const exists = await fileExists(configPath);
  if (exists) {
    console.log('rigovo.yml already exists. Skipping initialization.');
    return;
  }

  const projectName = extractProjectName(projectRoot);
  const content = RIGOVO_YML_TEMPLATE.replace('{PROJECT_NAME}', projectName);

  await fs.writeFile(configPath, content, 'utf-8');
  console.log(`Created rigovo.yml in ${projectRoot}`);
  console.log('\nNext steps:');
  console.log('  1. Add your API keys to rigovo.yml or set environment variables');
  console.log('  2. Run: rigovo run "your task description"');
}

async function fileExists(path: string): Promise<boolean> {
  try {
    await fs.access(path);
    return true;
  } catch {
    return false;
  }
}

function extractProjectName(projectRoot: string): string {
  const parts = projectRoot.split('/');
  return parts[parts.length - 1] ?? 'my-project';
}
