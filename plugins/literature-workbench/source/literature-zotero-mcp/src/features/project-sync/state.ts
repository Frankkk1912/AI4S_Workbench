import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import type { LibraryRef } from '../../api/web-client.js';

export interface ProjectSyncState {
  schema_version: '1.0';
  project_slug: string;
  library: LibraryRef;
  collection_name: string;
  collection_key: string;
  report_note_key: string;
  report_note_version: number | null;
  report_sha256: string;
  report_note_sha256: string;
  evidence_sha256: string;
  synced_evidence_ids: string[];
  updated_at: string;
}

function safeSlug(value: string): string {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value)) throw new Error('project_slug must be lower-kebab-case');
  return value;
}

export function projectStatePath(dataDir: string, lib: LibraryRef, slug: string): string {
  return join(dataDir, 'project-sync', `${lib.type}-${lib.id}`, `${safeSlug(slug)}.json`);
}

export function projectReceiptPath(dataDir: string, lib: LibraryRef, slug: string, planHash: string): string {
  const hash = planHash.replace(/^sha256:/, '');
  if (!/^[0-9a-f]{64}$/.test(hash)) throw new Error('Invalid internal plan hash');
  return join(dataDir, 'project-sync', `${lib.type}-${lib.id}`, 'receipts', safeSlug(slug), `${hash}.json`);
}

export async function readProjectState(path: string): Promise<ProjectSyncState | null> {
  try {
    const value = JSON.parse(await readFile(path, 'utf8')) as ProjectSyncState;
    if (value.schema_version !== '1.0' || !value.collection_key || !value.report_note_key || !value.report_note_sha256) throw new Error('Invalid project-sync state');
    return value;
  } catch (error: any) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
}

export async function writeProjectState(path: string, state: ProjectSyncState): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  await rename(temporary, path);
}
