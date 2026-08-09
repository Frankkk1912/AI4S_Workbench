import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { applyImportPlan, dryRunImportPlan } from '../../src/features/import-plan/apply.js';
import {
  canonicalPlanHash,
  type ImportPlan,
  validateImportPlan,
} from '../../src/features/import-plan/contract.js';
import applyImportPlanTool from '../../src/tools/apply-import-plan.js';

function plan(): ImportPlan {
  const value: ImportPlan = {
    schema_version: '1.0',
    plan_type: 'zotero-import',
    created_at: '2026-07-12T00:00:00Z',
    plan_hash: 'sha256:'.padEnd(71, '0'),
    project: { slug: 'test-project', search_date: '2026-07-12' },
    target: {
      library_type: 'user',
      library_id: 1,
      collection_name: 'Test project',
      tags: ['import-run:test-project-20260712', 'project:test-project'],
    },
    matching: {
      mode: 'snapshot',
      source_library_version: 3,
      candidate_limit: 50,
      unchecked_create: false,
    },
    priority: {
      source_sha256: 'a'.repeat(64),
      scope: 'test-project',
      review_depth: 'abstract',
      default_for_selected: 1,
    },
    actions: [
      {
        evidence_id: 'doi:10.1/create',
        display_rank: 2,
        decision: 'create',
        reason_codes: ['no-library-match'],
        source: { database: 'pubmed', record_id: '2' },
        item: {
          itemType: 'journalArticle',
          title: 'Create paper',
          DOI: '10.1/create',
          date: '2025',
          creators: [],
          tags: [
            { tag: 'AI4S:ArticleType:Review' },
            { tag: 'AI4S:Priority:1' },
            { tag: 'import-run:test-project-20260712' },
            { tag: 'project:test-project' },
          ],
        },
        match: null,
        priority_recommendation: {
          level: 1,
          reason_codes: ['selected-default'],
          tag_decision: 'add',
        },
      },
      {
        evidence_id: 'doi:10.1/reuse',
        display_rank: 1,
        decision: 'reuse',
        reason_codes: ['unique-doi-match'],
        source: { database: 'pubmed', record_id: '1' },
        item: {
          itemType: 'journalArticle',
          title: 'Reuse paper',
          DOI: '10.1/reuse',
          date: '2024',
          creators: [],
          tags: [
            { tag: 'AI4S:ArticleType:Review' },
            { tag: 'AI4S:Priority:3' },
            { tag: 'import-run:test-project-20260712' },
            { tag: 'project:test-project' },
          ],
        },
        match: {
          zotero_key: 'EXIST001',
          zotero_version: 3,
          match_kind: 'doi',
          matched_identity: '10.1/reuse',
        },
        priority_recommendation: {
          level: 3,
          reason_codes: ['core-conclusion'],
          tag_decision: 'add',
        },
      },
    ],
    summary: { selected: 2, create: 1, reuse: 1, check: 0, skip: 0 },
  };
  value.plan_hash = canonicalPlanHash(value);
  return value;
}

function context(overrides: Record<string, any> = {}) {
  const web = {
    hasKey: true,
    listCollections: vi.fn(async () => ({
      data: [{ key: 'COLL001', version: 1, data: { name: 'Test project' } }],
      totalResults: 1,
      lastModifiedVersion: 3,
    })),
    listItems: vi.fn(async () => ({ data: [], totalResults: 0, lastModifiedVersion: 3 })),
    getItem: vi.fn(async () => ({
      key: 'EXIST001',
      version: 3,
      data: {
        itemType: 'journalArticle',
        title: 'Reuse paper',
        DOI: '10.1/reuse',
        date: '2024',
        collections: ['OLD'],
        tags: [{ tag: 'existing' }],
      },
    })),
    writeCollections: vi.fn(async () => ({
      successful: [{ index: 0, key: 'COLL001', version: 1 }],
      failed: [],
      unchanged: [],
      newLibraryVersion: 4,
    })),
    writeItems: vi.fn(async () => ({
      successful: [{ index: 0, key: 'NEW001', version: 4 }],
      failed: [],
      unchanged: [],
      newLibraryVersion: 4,
    })),
    patchItem: vi.fn(async () => 5),
    ...overrides,
  };
  return {
    web,
    schema: { validateItem: vi.fn(async () => ({ valid: true, errors: [] })) },
    capabilities: { cloud: { userID: 1 } },
  } as any;
}

const lib = { type: 'user', id: 1 } as const;

describe('import plan contract', () => {
  it('has a stable cross-runtime canonical hash and detects changes', () => {
    const original = plan();
    expect(validateImportPlan(structuredClone(original)).plan_hash).toBe(original.plan_hash);
    const changed = structuredClone(original);
    changed.target.collection_name = 'Changed';
    expect(() => validateImportPlan(changed)).toThrow(/hash mismatch/i);
  });

  it('rejects update/delete fields inside a create action', () => {
    const unsafe = plan();
    unsafe.actions[0]!.item!.key = 'EXISTING';
    unsafe.plan_hash = canonicalPlanHash(unsafe);
    expect(() => validateImportPlan(unsafe)).toThrow(/must not contain key/i);
  });

  it('validates the Python planner shared golden fixture', async () => {
    const fixtureName = join('tests', 'fixtures', 'import_plan_expected.json');
    const candidates = [
      join(process.cwd(), '..', '..', '..', '..', 'skills', 'literature-manager', fixtureName),
    ];
    const fixture = candidates.find(existsSync);
    if (!fixture) throw new Error(`Missing shared import-plan fixture: ${candidates.join(', ')}`);
    const value = validateImportPlan(JSON.parse(await readFile(fixture, 'utf8')));
    expect(value.summary).toEqual({ selected: 2, create: 1, reuse: 1, check: 0, skip: 0 });
    const ctx = context({
      listCollections: vi.fn(async () => ({
        data: [{ key: 'GPLD1COLL', data: { name: 'GPLD1 cardiovascular disease' } }],
        totalResults: 1,
        lastModifiedVersion: 8,
      })),
      getItem: vi.fn(async () => ({
        key: 'AAAA1111',
        version: 3,
        data: { title: 'GPLD1 regulates cardiovascular aging through phospholipid remodeling' },
      })),
    });
    const dryRun = await dryRunImportPlan(ctx, value, { type: 'user', id: 19552201 });
    expect(dryRun.status).toBe('ready');
    expect(dryRun.summary).toMatchObject({ create: 1, reuse: 1, check: 0 });
  });
});

describe('zotero import-plan execution', () => {
  it('dry-runs without writes', async () => {
    const ctx = context();
    const result = await dryRunImportPlan(ctx, plan(), lib);
    expect(result.status).toBe('ready');
    expect(ctx.web.writeItems).not.toHaveBeenCalled();
    expect(ctx.web.patchItem).not.toHaveBeenCalled();
    expect(ctx.web.writeCollections).not.toHaveBeenCalled();
  });

  it('creates and reuses items, persists a complete receipt, and no-ops on repeat', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'zotero-import-'));
    const receiptPath = join(directory, 'receipt.json');
    const ctx = context();
    const first = await applyImportPlan(ctx, plan(), lib, receiptPath);
    expect(first.status).toBe('complete');
    expect(first.summary).toMatchObject({ created: 1, reused: 1, pending: 0 });
    const receipt = JSON.parse(await readFile(receiptPath, 'utf8'));
    expect(receipt.results.map((result: any) => result.outcome).sort()).toEqual([
      'created',
      'reused',
    ]);
    expect(ctx.web.patchItem).toHaveBeenCalledWith(
      lib,
      'EXIST001',
      expect.objectContaining({
        collections: ['OLD', 'COLL001'],
        tags: [
          { tag: 'existing' },
          { tag: 'import-run:test-project-20260712' },
          { tag: 'project:test-project' },
          { tag: 'AI4S:ArticleType:Review' },
          { tag: 'AI4S:Priority:3' },
        ],
      }),
      3,
    );
    const writeCount = ctx.web.writeItems.mock.calls.length;
    const second = await applyImportPlan(ctx, plan(), lib, receiptPath);
    expect(second.noOp).toBe(true);
    expect(ctx.web.writeItems).toHaveBeenCalledTimes(writeCount);
  });

  it('preserves a live user Priority added after plan generation', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'zotero-import-'));
    const ctx = context({
      getItem: vi.fn(async () => ({
        key: 'EXIST001',
        version: 3,
        data: {
          itemType: 'journalArticle',
          title: 'Reuse paper',
          DOI: '10.1/reuse',
          date: '2024',
          collections: ['OLD'],
          tags: [{ tag: 'existing' }, { tag: 'AI4S:Priority:2' }],
        },
      })),
    });
    await applyImportPlan(ctx, plan(), lib, join(directory, 'receipt.json'));
    const patch = ctx.web.patchItem.mock.calls[0][2];
    expect(patch.tags).toContainEqual({ tag: 'AI4S:Priority:2' });
    expect(patch.tags).not.toContainEqual({ tag: 'AI4S:Priority:3' });
    expect(patch.tags).toContainEqual({ tag: 'AI4S:ArticleType:Review' });
  });

  it('records an item-level create failure while continuing reuse', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'zotero-import-'));
    const ctx = context({
      writeItems: vi.fn(async () => ({
        successful: [],
        unchanged: [],
        failed: [{ index: 0, code: 400, message: 'bad item' }],
        newLibraryVersion: 4,
      })),
    });
    const result = await applyImportPlan(ctx, plan(), lib, join(directory, 'receipt.json'));
    expect(result.status).toBe('partial');
    expect(result.summary).toMatchObject({ failed: 1, reused: 1, pending: 0 });
  });

  it('persists retryable batch failure as blocked pending work', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'zotero-import-'));
    const error: any = new Error('rate limited');
    error.status = 429;
    const ctx = context({
      writeItems: vi.fn(async () => {
        throw error;
      }),
    });
    const result = await applyImportPlan(ctx, plan(), lib, join(directory, 'receipt.json'));
    expect(result.status).toBe('blocked');
    expect(result.summary.pending).toBeGreaterThan(0);
    expect(result.blockingIssues).toContain('item-create-request-failed');
  });

  it('blocks stale reuse and ambiguous collection before writes', async () => {
    const stale = context({
      getItem: vi.fn(async () => ({ key: 'EXIST001', version: 4, data: { title: 'Reuse paper' } })),
      listCollections: vi.fn(async () => ({
        data: [
          { key: 'C1', data: { name: 'Test project' } },
          { key: 'C2', data: { name: 'Test project' } },
        ],
        totalResults: 2,
        lastModifiedVersion: 4,
      })),
    });
    const directory = await mkdtemp(join(tmpdir(), 'zotero-import-'));
    const result = await applyImportPlan(stale, plan(), lib, join(directory, 'receipt.json'));
    expect(result.status).toBe('blocked');
    expect(result.blockingIssues).toContain('multiple-exact-collection-matches');
    expect(result.blockingIssues).toContain('stale-reuse-item:doi:10.1/reuse');
    expect(stale.web.writeItems).not.toHaveBeenCalled();
  });

  it('turns a new live match for planned create into check', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'zotero-import-'));
    const ctx = context({
      listItems: vi.fn(async () => ({
        data: [
          {
            key: 'LIVE001',
            version: 1,
            data: { title: 'Create paper', DOI: '10.1/create', date: '2025' },
          },
        ],
        totalResults: 1,
        lastModifiedVersion: 4,
      })),
    });
    const result = await applyImportPlan(ctx, plan(), lib, join(directory, 'receipt.json'));
    expect(result.summary).toMatchObject({ created: 0, reused: 1, check: 1 });
    expect(ctx.web.writeItems).not.toHaveBeenCalled();
  });
});

describe('zotero_apply_import_plan tool boundary', () => {
  it('requires exact confirmation and a Web API key before apply', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'zotero-import-tool-'));
    const planPath = join(directory, 'plan.json');
    const value = plan();
    await writeFile(planPath, JSON.stringify(value), 'utf8');
    const ctx = context();
    ctx.web.hasKey = false;
    const result = await applyImportPlanTool.handler(
      {
        plan_path: planPath,
        mode: 'apply',
        receipt_path: join(directory, 'receipt.json'),
        confirm_plan_hash: value.plan_hash,
      },
      ctx,
    );
    expect(result.isError).toBe(true);
    expect(result.content[0]?.text).toMatch(/Web API key/i);
    expect(ctx.web.writeItems).not.toHaveBeenCalled();
  });
});
