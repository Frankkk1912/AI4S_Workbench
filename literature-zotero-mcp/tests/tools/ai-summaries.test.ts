import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import {
  evidenceHash, mergeAiSummaryExtra, parseAiSummaryExtra, validateSummaryText, type AiSummaryPayload,
} from '../../src/features/ai-summaries/contract.js';
import { executeAiSummaries } from '../../src/features/ai-summaries/apply.js';
import aiSummaryContext from '../../src/tools/ai-summary-context.js';

const library = { type: 'user' as const, id: 1 };
const title = 'Single-cell analysis of macrophage states';
const abstract = 'We profiled human macrophages by single-cell RNA sequencing and identified inflammation-associated cell states.';

function payload(text = '该研究通过单细胞RNA测序分析人巨噬细胞，并识别出炎症相关的细胞状态。'): AiSummaryPayload {
  return {
    schema_version: 1, text, language: 'zh-CN', basis: 'title-abstract',
    title_sha256: evidenceHash(title), abstract_sha256: evidenceHash(abstract),
    generated_at: '2026-07-21T00:00:00Z',
  };
}

function recommendation(text = payload().text) {
  return {
    item_key: 'ITEM0001', expected_version: 4, title_sha256: evidenceHash(title),
    abstract_sha256: evidenceHash(abstract), text, language: 'zh-CN',
  };
}

describe('AI Summary metadata contract', () => {
  it('round-trips one managed block while preserving unrelated Extra', () => {
    const extra = mergeAiSummaryExtra('Human note\nAI4S-Metrics: {"schema_version":2,"by_year":{}}', payload());
    expect(extra).toContain('Human note');
    expect(extra).toContain('AI4S-Metrics:');
    const parsed = parseAiSummaryExtra(extra);
    expect(parsed.status).toBe('valid');
    if (parsed.status === 'valid') expect(parsed.payload).toMatchObject({ language: 'zh-CN', basis: 'title-abstract' });
  });

  it('rejects duplicate/corrupt blocks and multi-sentence or Markdown text', () => {
    expect(parseAiSummaryExtra('AI4S-Summary: {}\nAI4S-Summary: {}')).toMatchObject({ status: 'invalid', error: 'multiple-ai4s-summary-blocks' });
    expect(parseAiSummaryExtra('AI4S-Summary: not-json')).toMatchObject({ status: 'invalid', error: 'invalid-ai4s-summary-json' });
    expect(() => validateSummaryText('第一句。第二句。', 'zh-CN')).toThrow(/exactly one sentence/);
    expect(() => validateSummaryText('**加粗摘要**', 'zh-CN')).toThrow(/Markdown/);
  });
});

describe('AI Summary context', () => {
  it('defaults to Chinese and returns only missing title-and-abstract candidates', async () => {
    const items = {
      ITEM0001: { key: 'ITEM0001', version: 4, data: { itemType: 'journalArticle', title, abstractNote: abstract, extra: '' } },
      ITEM0002: { key: 'ITEM0002', version: 5, data: { itemType: 'journalArticle', title: 'No abstract', abstractNote: '' } },
    } as Record<string, any>;
    const ctx = {
      router: {
        defaultLibrary: () => library,
        getItem: vi.fn(async (key) => structuredClone(items[key])),
      },
    } as any;
    const result = await aiSummaryContext.handler({ item_keys: ['ITEM0001', 'ITEM0002'] }, ctx);
    expect(result.structuredContent).toMatchObject({ language: 'zh-CN', mode: 'missing' });
    expect(result.structuredContent?.summary).toMatchObject({ candidate: 1, skipped: 1 });
    const candidate = (result.structuredContent?.items as any[])[0];
    expect(candidate).toMatchObject({ item_key: 'ITEM0001', language: 'zh-CN', existing_summary_state: 'missing' });
    expect(candidate.abstract).toBe(abstract);
  });

  it('keeps current summaries unchanged in missing mode and exposes them in refresh mode', async () => {
    const item = { key: 'ITEM0001', version: 4, data: {
      itemType: 'journalArticle', title, abstractNote: abstract,
      extra: mergeAiSummaryExtra('', payload()),
    } };
    const ctx = { router: { defaultLibrary: () => library, getItem: vi.fn(async () => structuredClone(item)) } } as any;
    const missing = await aiSummaryContext.handler({ item_keys: ['ITEM0001'] }, ctx);
    expect(missing.structuredContent?.summary).toMatchObject({ candidate: 0, unchanged: 1 });
    const refresh = await aiSummaryContext.handler({ item_keys: ['ITEM0001'], mode: 'refresh' }, ctx);
    expect(refresh.structuredContent?.summary).toMatchObject({ candidate: 1 });
    expect((refresh.structuredContent?.items as any[])[0].existing_summary_state).toBe('current');
  });
});

describe('AI Summary application', () => {
  it('creates only AI4S-Summary Extra, preserves other metadata, and writes plan/receipt', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'ai-summaries-'));
    const item = { key: 'ITEM0001', version: 4, data: {
      itemType: 'journalArticle', title, abstractNote: abstract,
      extra: 'Human note\nAI4S-Metrics: {"schema_version":2,"by_year":{}}',
      tags: [{ tag: 'manual:keep' }], collections: ['COLL0001'],
    } };
    const patchItem = vi.fn(async () => 5);
    const ctx = { config: { dataDir }, web: { getItem: vi.fn(async () => structuredClone(item)), patchItem } } as any;
    const result = await executeAiSummaries(ctx, library, {
      trigger: 'explicit-user-request', mode: 'missing', items: [recommendation()],
    });
    expect(result.status).toBe('complete');
    expect(result.summary).toMatchObject({ created: 1, failed: 0 });
    expect(patchItem).toHaveBeenCalledTimes(1);
    const patch = patchItem.mock.calls[0]![2];
    expect(Object.keys(patch)).toEqual(['extra']);
    expect(patch.extra).toContain('Human note');
    expect(patch.extra).toContain('AI4S-Metrics:');
    expect(parseAiSummaryExtra(patch.extra).status).toBe('valid');
    const plan = JSON.parse(await readFile(String(result.plan_path), 'utf8'));
    const receipt = JSON.parse(await readFile(String(result.receipt_path), 'utf8'));
    expect(plan).toMatchObject({ plan_type: 'zotero-ai-summaries', trigger: 'explicit-user-request', mode: 'missing' });
    expect(plan.actions[0]).not.toHaveProperty('final_extra');
    expect(receipt.results[0]).toMatchObject({ outcome: 'created', after_summary: payload().text });
  });

  it('does not overwrite an existing summary in missing mode but refreshes it explicitly', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'ai-summary-refresh-'));
    const item = { key: 'ITEM0001', version: 4, data: {
      itemType: 'journalArticle', title, abstractNote: abstract, extra: mergeAiSummaryExtra('Human note', payload('旧的一句话。')),
    } };
    const patchItem = vi.fn(async () => 5);
    const ctx = { config: { dataDir }, web: { getItem: vi.fn(async () => structuredClone(item)), patchItem } } as any;
    const missing = await executeAiSummaries(ctx, library, {
      trigger: 'explicit-user-request', mode: 'missing', items: [recommendation()],
    });
    expect(missing.summary).toMatchObject({ unchanged: 1 });
    expect(patchItem).not.toHaveBeenCalled();
    const refreshed = await executeAiSummaries(ctx, library, {
      trigger: 'explicit-user-request', mode: 'refresh', items: [recommendation()],
    });
    expect(refreshed.summary).toMatchObject({ refreshed: 1 });
    expect(patchItem).toHaveBeenCalledTimes(1);
  });

  it('blocks stale inputs and invalid managed blocks without writing', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'ai-summary-conflict-'));
    const items: Record<string, any> = {
      ITEM0001: { key: 'ITEM0001', version: 4, data: { itemType: 'journalArticle', title: `${title} changed`, abstractNote: abstract, extra: '' } },
      ITEM0002: { key: 'ITEM0002', version: 4, data: { itemType: 'journalArticle', title, abstractNote: abstract, extra: 'AI4S-Summary: bad-json' } },
    };
    const patchItem = vi.fn();
    const ctx = { config: { dataDir }, web: { getItem: vi.fn(async (_library, key) => structuredClone(items[key])), patchItem } } as any;
    const result = await executeAiSummaries(ctx, library, {
      trigger: 'explicit-user-request', mode: 'refresh', items: [
        recommendation(), { ...recommendation(), item_key: 'ITEM0002' },
      ],
    });
    expect(result.status).toBe('partial');
    expect(result.summary).toMatchObject({ conflicted: 2 });
    expect(patchItem).not.toHaveBeenCalled();
  });
});
