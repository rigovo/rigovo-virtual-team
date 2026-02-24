/**
 * Concrete adapter implementations for repository interfaces.
 * Ships Prisma (primary) and Supabase (legacy) adapters.
 */

export { PrismaMemoryRepository } from './prisma-memory.js';
export { PrismaAuditRepository } from './prisma-audit.js';

export { SupabaseMemoryRepository } from './supabase-memory.js';
export { SupabaseAuditRepository } from './supabase-audit.js';
