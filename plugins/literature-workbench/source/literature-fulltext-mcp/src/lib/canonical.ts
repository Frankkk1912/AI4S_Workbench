import { createHash } from 'node:crypto';

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => [key, stable(child)]));
  }
  return value;
}

export function canonicalJson(value: unknown): string { return JSON.stringify(stable(value)); }
export function sha256(value: string | Uint8Array): string { return createHash('sha256').update(value).digest('hex'); }
export function md5(value: Uint8Array): string { return createHash('md5').update(value).digest('hex'); }
