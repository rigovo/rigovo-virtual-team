'use strict';

import { PrismaClient } from '@prisma/client';
import { PrismaPg } from '@prisma/adapter-pg';

let _instance: PrismaClient | null = null;

/**
 * Creates a PrismaClient using the pg driver adapter (required in Prisma 7).
 * Reuses a singleton in non-production environments to avoid connection leaks.
 */
export function createPrismaClient(): PrismaClient {
  if (_instance) return _instance;

  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    throw new Error('DATABASE_URL environment variable is not set');
  }

  const adapter = new PrismaPg({ connectionString });
  const client = new PrismaClient({ adapter });

  if (process.env.NODE_ENV !== 'production') {
    _instance = client;
  }

  return client;
}
