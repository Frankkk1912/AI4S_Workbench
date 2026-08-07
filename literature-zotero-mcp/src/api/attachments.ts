import { createHash } from 'node:crypto';
import { readFile, writeFile, stat } from 'node:fs/promises';
import { basename, extname } from 'node:path';
import type { WebApiClient, LibraryRef } from './web-client.js';

const CONTENT_TYPES: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.txt': 'text/plain',
  '.html': 'text/html',
  '.htm': 'text/html',
  '.json': 'application/json',
  '.csv': 'text/csv',
  '.epub': 'application/epub+zip',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
};

export function guessContentType(filename: string): string {
  return CONTENT_TYPES[extname(filename).toLowerCase()] ?? 'application/octet-stream';
}

function concatBytes(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((n, p) => n + p.byteLength, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const p of parts) {
    out.set(p, offset);
    offset += p.byteLength;
  }
  return out;
}

export interface UploadOptions {
  filePath: string;
  parentItem?: string;
  title?: string;
  contentType?: string;
  linkMode?: string;
}

export interface UploadResult {
  key: string;
  exists: boolean;
  filename: string;
}

/**
 * Resume File Storage bytes/register work for an attachment item that already
 * exists. The caller owns creation and persists the key before calling this,
 * so an interrupted retry cannot create a second child attachment.
 */
export async function resumeUploadFile(
  web: WebApiClient,
  lib: LibraryRef,
  opts: { filePath: string; attachmentKey: string },
  onPhase?: (phase: 'bytes_uploaded' | 'registered') => Promise<void>,
): Promise<{ exists: boolean; filename: string }> {
  const bytes = new Uint8Array(await readFile(opts.filePath));
  const st = await stat(opts.filePath);
  const filename = basename(opts.filePath);
  const md5 = createHash('md5').update(bytes).digest('hex');
  const auth = await web.requestUpload(lib, opts.attachmentKey, {
    md5, filename, filesize: bytes.byteLength, mtime: Math.floor(st.mtimeMs),
  });
  if (auth.exists === 1) {
    await onPhase?.('registered');
    return { exists: true, filename };
  }
  const enc = new TextEncoder();
  const body = concatBytes(enc.encode(auth.prefix ?? ''), bytes, enc.encode(auth.suffix ?? ''));
  await web.uploadBytes(auth.url, auth.contentType, body);
  await onPhase?.('bytes_uploaded');
  await web.registerUpload(lib, opts.attachmentKey, auth.uploadKey);
  await onPhase?.('registered');
  return { exists: false, filename };
}

/** Run the full 5-step Zotero File Storage upload for a local file. */
export async function uploadFile(
  web: WebApiClient,
  lib: LibraryRef,
  opts: UploadOptions,
): Promise<UploadResult> {
  const bytes = new Uint8Array(await readFile(opts.filePath));
  const st = await stat(opts.filePath);
  const filename = basename(opts.filePath);
  const md5 = createHash('md5').update(bytes).digest('hex');
  const mtime = Math.floor(st.mtimeMs);
  const contentType = opts.contentType ?? guessContentType(filename);

  // Step 1: create the attachment item.
  const itemObj: Record<string, unknown> = {
    itemType: 'attachment',
    linkMode: opts.linkMode ?? 'imported_file',
    title: opts.title ?? filename,
    filename,
    contentType,
  };
  if (opts.parentItem) itemObj.parentItem = opts.parentItem;
  const created = await web.writeItems(lib, [itemObj]);
  if (!created.successful.length) {
    throw new Error(`Failed to create attachment item: ${JSON.stringify(created.failed)}`);
  }
  const key = created.successful[0]!.key;

  // Step 2: request upload authorization.
  const auth = await web.requestUpload(lib, key, { md5, filename, filesize: bytes.byteLength, mtime });

  // Step 3: short-circuit if the file already exists in storage.
  if (auth.exists === 1) return { key, exists: true, filename };

  // Step 4: upload prefix + bytes + suffix to the storage URL.
  const enc = new TextEncoder();
  const body = concatBytes(enc.encode(auth.prefix ?? ''), bytes, enc.encode(auth.suffix ?? ''));
  await web.uploadBytes(auth.url, auth.contentType, body);

  // Step 5: register the completed upload.
  await web.registerUpload(lib, key, auth.uploadKey);
  return { key, exists: false, filename };
}

export async function downloadFile(
  web: WebApiClient,
  lib: LibraryRef,
  key: string,
  savePath: string,
): Promise<{ savePath: string; bytes: number; contentType?: string }> {
  const { bytes, contentType } = await web.downloadFileBytes(lib, key);
  await writeFile(savePath, bytes);
  return { savePath, bytes: bytes.byteLength, contentType };
}
