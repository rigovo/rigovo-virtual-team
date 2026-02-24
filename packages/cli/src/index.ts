#!/usr/bin/env node
'use strict';

import { Command } from 'commander';
import { runCommand } from './commands/run.js';
import { initCommand } from './commands/init.js';
import { statusCommand } from './commands/status.js';

const program = new Command();

program
  .name('rigovo')
  .description('Rigovo Teams — Composable AI engineering team CLI')
  .version('0.1.0');

program
  .command('run')
  .description('Execute a task with the AI engineering team')
  .argument('<description>', 'Task description in plain English')
  .option('--project <path>', 'Project root path', '.')
  .option('--model <model>', 'Override default LLM model')
  .option('--dry-run', 'Classify and plan without executing')
  .action(runCommand);

program
  .command('init')
  .description('Initialize Rigovo configuration in a project')
  .option('--project <path>', 'Project root path', '.')
  .action(initCommand);

program
  .command('status')
  .description('Show current task and agent status')
  .option('--project <path>', 'Project root path', '.')
  .action(statusCommand);

program.parse();
