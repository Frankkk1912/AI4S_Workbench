import { createHash } from 'node:crypto';

export const AI_SUMMARY_PREFIX = 'AI4S-Summary:';
export const AI_SUMMARY_SCHEMA_VERSION = 1;
export const AI_SUMMARY_MAX_LENGTH = 240;

export type SummaryMode = 'missing' | 'refresh';

export interface AiSummaryPayload {
  schema_version: 1;
  text: string;
  language: string;
  basis: 'title-abstract';
  title_sha256: string;
  abstract_sha256: string;
  generated_at: string;
}

export type ParsedAiSummary =
  | { status: 'missing'; retained: string[] }
  | { status: 'valid'; retained: string[]; payload: AiSummaryPayload }
  | { status: 'invalid'; retained: string[]; error: string };

const SHA256 = /^[a-f0-9]{64}$/;
const LANGUAGE = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;

export function normalizeEvidenceText(value: unknown): string {
  return String(value ?? '').normalize('NFKC').replace(/\s+/gu, ' ').trim();
}

export function evidenceHash(value: unknown): string {
  return createHash('sha256').update(normalizeEvidenceText(value), 'utf8').digest('hex');
}

export function normalizeLanguage(value: unknown): string {
  const language = String(value ?? 'zh-CN').trim() || 'zh-CN';
  if (!LANGUAGE.test(language)) throw new Error(`Invalid language tag: ${language}`);
  const [primary, ...rest] = language.split('-');
  return [primary!.toLowerCase(), ...rest.map((part, index) => index === 0 && part.length === 2
    ? part.toUpperCase() : part)].join('-');
}

export function validateSummaryText(value: unknown, language = 'zh-CN'): string {
  const text = String(value ?? '').trim();
  if (!text) throw new Error('AI Summary text may not be empty');
  if (text.length > AI_SUMMARY_MAX_LENGTH) {
    throw new Error(`AI Summary exceeds ${AI_SUMMARY_MAX_LENGTH} Unicode characters`);
  }
  if ([...text].some((character) => {
    const code = character.charCodeAt(0);
    return code <= 31 || code === 127;
  })) throw new Error('AI Summary must be a single line without control characters');
  if (/^\s*(?:[-*+]\s|#{1,6}\s|>\s)/u.test(text)
      || text.includes('**') || text.includes('__') || text.includes('`')
      || /\[[^\]]+\]\([^)]+\)/u.test(text)) {
    throw new Error('AI Summary may not contain Markdown formatting');
  }
  const segmenter = new Intl.Segmenter(normalizeLanguage(language), { granularity: 'sentence' });
  const sentences = [...segmenter.segment(text)].map((entry) => entry.segment.trim()).filter(Boolean);
  if (sentences.length !== 1) throw new Error('AI Summary must contain exactly one sentence');
  return text;
}

function validPayload(value: unknown): value is AiSummaryPayload {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  if (payload.schema_version !== AI_SUMMARY_SCHEMA_VERSION || payload.basis !== 'title-abstract') return false;
  if (typeof payload.text !== 'string' || typeof payload.language !== 'string') return false;
  if (typeof payload.generated_at !== 'string' || Number.isNaN(Date.parse(payload.generated_at))) return false;
  if (typeof payload.title_sha256 !== 'string' || !SHA256.test(payload.title_sha256)) return false;
  if (typeof payload.abstract_sha256 !== 'string' || !SHA256.test(payload.abstract_sha256)) return false;
  try {
    normalizeLanguage(payload.language);
    validateSummaryText(payload.text, String(payload.language));
    return true;
  } catch {
    return false;
  }
}

export function parseAiSummaryExtra(extra: unknown): ParsedAiSummary {
  const lines = String(extra ?? '').split(/\r?\n/u);
  const managed = lines.filter((line) => line.startsWith(AI_SUMMARY_PREFIX));
  const retained = lines.filter((line) => !line.startsWith(AI_SUMMARY_PREFIX));
  if (!managed.length) return { status: 'missing', retained };
  if (managed.length > 1) return { status: 'invalid', retained, error: 'multiple-ai4s-summary-blocks' };
  try {
    const payload = JSON.parse(managed[0]!.slice(AI_SUMMARY_PREFIX.length).trim());
    if (!validPayload(payload)) return { status: 'invalid', retained, error: 'invalid-ai4s-summary-schema' };
    return { status: 'valid', retained, payload };
  } catch {
    return { status: 'invalid', retained, error: 'invalid-ai4s-summary-json' };
  }
}

export function encodeAiSummaryExtra(retained: string[], payload: AiSummaryPayload): string {
  const preserved = retained.length === 1 && retained[0] === '' ? [] : retained;
  return [...preserved, `${AI_SUMMARY_PREFIX} ${JSON.stringify(payload)}`].join('\n');
}

export function mergeAiSummaryExtra(extra: unknown, payload: AiSummaryPayload): string | null {
  const parsed = parseAiSummaryExtra(extra);
  if (parsed.status === 'invalid') return null;
  return encodeAiSummaryExtra(parsed.retained, payload);
}

function deepSort(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(deepSort);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => [key, deepSort(item)]));
  }
  return value;
}

export function aiSummaryPlanHash(plan: Record<string, unknown>): string {
  const canonical = structuredClone(plan);
  canonical.plan_hash = '';
  return `sha256:${createHash('sha256').update(JSON.stringify(deepSort(canonical))).digest('hex')}`;
}
