import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { DatabaseBroker } from '../src/broker.js';
import type { BrowserAdapter, ExportExecutionResult, ExportInput, SearchExecutionResult, SearchInput, SessionSnapshot } from '../src/domain.js';
import { DATABASE_ID } from '../src/domain.js';
import { JobStore } from '../src/store.js';

const temporaryDirectories: string[] = [];

async function temporaryDirectory(): Promise<string> {
  const path = await mkdtemp(join(tmpdir(), 'literature-database-browser-test-'));
  temporaryDirectories.push(path);
  return path;
}

afterEach(async () => {
  // The OS test temp directory is intentionally left to its normal TTL cleanup;
  // no repository or user profile data is ever used by these tests.
  temporaryDirectories.length = 0;
});

class FakeAdapter implements BrowserAdapter {
  readonly calls: string[] = [];
  searchResult: SearchExecutionResult = {
    reportedResultCount: 2,
    appliedFilters: { fromYear: 2020, untilYear: 2026, documentTypes: ['Article', 'Review'] },
    appliedSort: 'relevance',
  };
  invalidExport = false;

  async openSession(): Promise<SessionSnapshot> {
    this.calls.push('open');
    return { database: DATABASE_ID, sessionState: 'ready', userActionRequired: false, message: 'ready', updatedAt: new Date().toISOString() };
  }

  async sessionStatus(): Promise<SessionSnapshot> {
    return { database: DATABASE_ID, sessionState: 'closed', userActionRequired: false, message: 'closed', updatedAt: new Date().toISOString() };
  }

  async executeSearch(_input: SearchInput): Promise<SearchExecutionResult> {
    this.calls.push('search');
    return this.searchResult;
  }

  async executeExport(_input: ExportInput, exportDirectory: string): Promise<ExportExecutionResult> {
    this.calls.push('export');
    const path = join(exportDirectory, 'batch-0001.txt');
    await writeFile(path, this.invalidExport
      ? 'Not a WoS export\n'
      : 'Article Title\tUT (Unique WOS ID)\tDOI\nPaper one\tWOS:0001\t10.1000/one\nPaper two\tWOS:0002\t10.1000/two\n');
    return { artifacts: [{ path, rangeStart: 1, rangeEnd: 2 }] };
  }
}

async function waitFor(
  broker: DatabaseBroker,
  jobId: string,
  state: string,
  timeoutMs = 5_000,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + timeoutMs;
  let lastStatus: Record<string, unknown> | undefined;
  while (Date.now() < deadline) {
    lastStatus = await broker.status(jobId);
    if (lastStatus.state === state) return lastStatus;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(
    `Timed out waiting for ${jobId} to reach ${state}; last state was ${String(lastStatus?.state ?? 'unknown')}.`,
  );
}

function searchInput(requestId = 'a'.repeat(64)): SearchInput {
  return {
    database: DATABASE_ID,
    attemptId: 'wos-01',
    query: { mode: 'advanced-search', value: 'TS=(cardiac fibrosis)' },
    filters: { fromYear: 2020, untilYear: 2026, documentTypes: ['Article', 'Review'] },
    sort: 'relevance',
    requestId,
  };
}

describe('DatabaseBroker', () => {
  it('runs search and export as separate idempotent jobs and writes a redacted receipt', async () => {
    const dataDir = await temporaryDirectory();
    const adapter = new FakeAdapter();
    const broker = new DatabaseBroker(new JobStore(dataDir), adapter);
    const first = await broker.submitSearch(searchInput());
    const retry = await broker.submitSearch(searchInput());

    expect(retry).toEqual({ jobId: first.jobId, reused: true });
    const results = await waitFor(broker, first.jobId, 'results_ready');
    expect(results.reported_result_count).toBe(2);
    expect(results.can_export).toBe(true);

    const exported = await broker.submitExport({
      jobId: first.jobId,
      limit: 1000,
      format: 'tab-delimited-full-record',
      requestId: 'b'.repeat(64),
    });
    expect(exported.reused).toBe(false);
    const complete = await waitFor(broker, first.jobId, 'complete');
    expect(complete.requested_export_limit).toBe(1000);
    expect(complete.exported_record_count).toBe(2);
    expect(adapter.calls).toEqual(['open', 'search', 'export']);

    const receipt = await readFile(new JobStore(dataDir).receiptPath(first.jobId), 'utf8');
    expect(receipt).toContain('query_hash');
    expect(receipt).not.toContain('TS=(cardiac fibrosis)');
  });

  it('rejects a request_id reused for different canonical input', async () => {
    const broker = new DatabaseBroker(new JobStore(await temporaryDirectory()), new FakeAdapter());
    await broker.submitSearch(searchInput());
    await expect(broker.submitSearch({ ...searchInput(), query: { mode: 'advanced-search', value: 'TS=(different)' } }))
      .rejects.toEqual(expect.objectContaining({ code: 'REQUEST_ID_CONFLICT' }));
  });

  it('never reports an invalid download as a successful export', async () => {
    const adapter = new FakeAdapter();
    adapter.invalidExport = true;
    const broker = new DatabaseBroker(new JobStore(await temporaryDirectory()), adapter);
    const submitted = await broker.submitSearch(searchInput());
    await waitFor(broker, submitted.jobId, 'results_ready');
    await broker.submitExport({
      jobId: submitted.jobId,
      limit: 2,
      format: 'tab-delimited-full-record',
      requestId: 'b'.repeat(64),
    });
    const failed = await waitFor(broker, submitted.jobId, 'failed');
    expect(failed.error_code).toBe('DOWNLOAD_INVALID');
    expect(failed.export_files).toBeUndefined();
  });

  it('requires an exact verified filter echo before exposing results', async () => {
    const adapter = new FakeAdapter();
    adapter.searchResult = { ...adapter.searchResult, appliedFilters: { fromYear: 2021, untilYear: 2026, documentTypes: ['Article', 'Review'] } };
    const broker = new DatabaseBroker(new JobStore(await temporaryDirectory()), adapter);
    const submitted = await broker.submitSearch(searchInput());
    const failed = await waitFor(broker, submitted.jobId, 'failed');
    expect(failed.error_code).toBe('FILTER_NOT_APPLIED');
  });

  it('does not accept export from an unverified job', async () => {
    const broker = new DatabaseBroker(new JobStore(await temporaryDirectory()), new FakeAdapter());
    await expect(broker.submitExport({
      jobId: 'job-missing',
      limit: 1,
      format: 'tab-delimited-full-record',
      requestId: 'c'.repeat(64),
    })).rejects.toEqual(expect.objectContaining({ code: 'JOB_NOT_FOUND' }));
  });
});
