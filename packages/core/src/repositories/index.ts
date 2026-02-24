/**
 * Repository interfaces — the DI contracts for @rigovo/core.
 * Core depends on these abstractions, never on concrete database clients.
 */

export type {
  IMemoryRepository,
  MemorySearchParams,
  CreateMemoryInput,
} from './memory-repository.js';

export type {
  IAuditRepository,
  CreateAuditEntry,
  WorkspaceAuditParams,
} from './audit-repository.js';
