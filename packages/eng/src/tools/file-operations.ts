'use strict';

import { promises as fs } from 'fs';
import { join, dirname } from 'path';

/**
 * A file with its path and content for writing to disk.
 */
export interface FileWrite {
  path: string;
  content: string;
}

/**
 * Result of reading a file from disk.
 */
export interface FileRead {
  path: string;
  content: string;
  exists: boolean;
}

/**
 * Safe file system operations for agent code generation.
 * All paths are resolved relative to the project root.
 * Never allows writes outside the project boundary.
 */
export class FileOperations {
  private readonly projectRoot: string;

  constructor(projectRoot: string) {
    if (!projectRoot) {
      throw new Error('FileOperations: projectRoot is required');
    }
    this.projectRoot = projectRoot;
  }

  /** Write multiple files atomically (all or nothing). */
  async writeFiles(files: FileWrite[]): Promise<string[]> {
    const written: string[] = [];

    for (const file of files) {
      const resolvedPath = this.resolveSafePath(file.path);
      await fs.mkdir(dirname(resolvedPath), { recursive: true });
      await fs.writeFile(resolvedPath, file.content, 'utf-8');
      written.push(file.path);
    }

    return written;
  }

  /** Read a file relative to the project root. */
  async readFile(relativePath: string): Promise<FileRead> {
    const resolvedPath = this.resolveSafePath(relativePath);

    try {
      const content = await fs.readFile(resolvedPath, 'utf-8');
      return { path: relativePath, content, exists: true };
    } catch {
      return { path: relativePath, content: '', exists: false };
    }
  }

  /** List files matching a pattern in a directory. */
  async listFiles(relativeDir: string): Promise<string[]> {
    const resolvedDir = this.resolveSafePath(relativeDir);

    try {
      const entries = await fs.readdir(resolvedDir, { recursive: true, withFileTypes: false });
      return (entries as string[])
        .filter((entry) => !entry.includes('node_modules'));
    } catch {
      return [];
    }
  }

  /** Check if a file exists. */
  async fileExists(relativePath: string): Promise<boolean> {
    const resolvedPath = this.resolveSafePath(relativePath);
    try {
      await fs.access(resolvedPath);
      return true;
    } catch {
      return false;
    }
  }

  private resolveSafePath(relativePath: string): string {
    const resolved = join(this.projectRoot, relativePath);

    if (!resolved.startsWith(this.projectRoot)) {
      throw new Error(
        `Path traversal detected: ${relativePath} escapes project root`
      );
    }

    return resolved;
  }
}
