/**
 * @rigovo/eng — Engineering agents and tools.
 *
 * Exports concrete agent implementations (Coder, Reviewer, Planner),
 * the agent factory for MasterAgent integration, engineering tools
 * (Rigour gates, file operations), and team templates.
 */

export { CoderAgent } from './agents/index.js';
export { ReviewerAgent } from './agents/index.js';
export { PlannerAgent } from './agents/index.js';
export { QAAgent } from './agents/index.js';
export { SREAgent } from './agents/index.js';
export { DevOpsAgent } from './agents/index.js';

export { createAgent } from './agent-factory.js';

export { RigourGate } from './tools/index.js';
export type { RigourGateResult, GateViolation } from './tools/index.js';

export { FileOperations } from './tools/index.js';
export type { FileWrite, FileRead } from './tools/index.js';

export { PipelineRunner } from './pipeline-runner.js';
export type { PipelineIteration, PipelineResult } from './pipeline-runner.js';

export { SYSTEM_TEMPLATES, getSystemTemplate } from './templates/team-templates.js';
export type { TeamTemplateDef } from './templates/team-templates.js';
