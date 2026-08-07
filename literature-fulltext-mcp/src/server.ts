import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { FulltextBroker } from './broker.js';
import { asFulltextError, FulltextError } from './errors.js';
import type { FetchRequest } from './domain.js';

const requestId = z.string().regex(/^[a-f0-9]{64}$/i, 'request_id must be a SHA-256 hex digest.');
const itemKey = z.string().regex(/^[A-Z0-9]{8}$/);
const url = z.string().url().max(2_048).refine((value) => ['http:', 'https:'].includes(new URL(value).protocol), 'candidate URL must use http or https');

function result(structured: Record<string, unknown>, message: string) {
  return { content: [{ type: 'text' as const, text: message }, { type: 'text' as const, text: JSON.stringify(structured, null, 2) }], structuredContent: structured };
}

function errorResult(error: unknown) {
  const value = asFulltextError(error);
  return { content: [{ type: 'text' as const, text: JSON.stringify({ error_code: value.code, message: value.message }) }], structuredContent: { error_code: value.code, message: value.message }, isError: true };
}

export function createServer(broker: FulltextBroker): McpServer {
  const server = new McpServer(
    { name: 'ai4s-literature-fulltext', version: '0.1.0' },
    { capabilities: { tools: { listChanged: false } }, instructions: 'This MCP retrieves only public OA PDFs through legal HTTP routes, validates PDF bytes plus DOI-and-title identity, and emits compact hashed handoffs. It does not upload to Zotero, handle institutional credentials, start VPNs, bypass access controls, or return PDF bytes/full text in conversation. Submit an asynchronous job then poll its status.' },
  );
  server.registerTool('fulltext_capabilities', {
    title: 'Get Fulltext MCP capabilities', description: 'Read-only capability registry; it does not make network requests.', inputSchema: {}, annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
  }, async () => result(broker.capabilities(), 'Reported verified Fulltext MCP capabilities.'));
  server.registerTool('fulltext_access_status', {
    title: 'Get Fulltext MCP access status', description: 'Read-only local status. It never starts a browser or checks external identity.', inputSchema: {}, annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
  }, async () => result(broker.accessStatus(), 'Reported Fulltext MCP access status.'));
  server.registerTool('fulltext_session_open', {
    title: 'Open institutional fulltext session', description: 'Reserved for a future visible institutional-browser phase. OA-only V1 returns a clear unavailable result and never accepts credentials.',
    inputSchema: { institution: z.string().trim().min(1).max(300) }, annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: true },
  }, async () => errorResult(new FulltextError('INSTITUTION_ACCESS_UNAVAILABLE', 'Institutional visible-browser access is not installed in this OA-only runtime.')));
  server.registerTool('fulltext_fetch_submit', {
    title: 'Submit an asynchronous OA fulltext job', description: 'Queues up to 50 selected, exact Zotero-parent targets. Only legal OA routes are attempted; poll fulltext_job_status for a compact result and handoff id.',
    inputSchema: {
      request_id: requestId,
      route_policy: z.enum(['oa_only', 'oa_then_current_entitlement', 'oa_then_institutional']),
      records: z.array(z.object({
        evidence_id: z.string().trim().min(1).max(300), zotero_item_key: itemKey,
        doi: z.string().trim().min(1).max(300).optional(), arxiv_id: z.string().trim().min(3).max(100).optional(), repository_id: z.string().trim().min(3).max(300).optional(),
        title: z.string().trim().min(1).max(2_000), year: z.number().int().min(1000).max(3000).optional(), item_type: z.string().trim().min(1).max(100), candidate_urls: z.array(url).max(20).optional(),
      }).refine((record) => Boolean(record.doi || record.arxiv_id || record.repository_id), 'Each record requires DOI, arXiv ID, or repository ID.')).min(1).max(50),
    }, annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: true },
  }, async (args) => {
    try {
      const request: FetchRequest = {
        requestId: args.request_id, routePolicy: args.route_policy,
        records: args.records.map((record) => ({ evidenceId: record.evidence_id, zoteroItemKey: record.zotero_item_key, doi: record.doi, arxivId: record.arxiv_id, repositoryId: record.repository_id, title: record.title, year: record.year, itemType: record.item_type, candidateUrls: record.candidate_urls ?? [] })),
      };
      const accepted = await broker.submit(request);
      return result({ job_id: accepted.jobId, state: 'queued', reused: accepted.reused }, accepted.reused ? 'Reused existing fulltext job for this request_id.' : 'Queued OA fulltext job. Poll fulltext_job_status.');
    } catch (error) { return errorResult(error); }
  });
  server.registerTool('fulltext_job_status', {
    title: 'Get Fulltext job status', description: 'Read-only compact job status. It never returns PDF bytes, browser traces, paths, signed URLs, or full text.', inputSchema: { job_id: z.string().regex(/^ft-[A-Za-z0-9-]{8,128}$/) }, annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
  }, async (args) => {
    try { return result(await broker.status(args.job_id), `Reported fulltext job ${args.job_id}.`); } catch (error) { return errorResult(error); }
  });
  server.registerTool('fulltext_job_cancel', {
    title: 'Cancel a Fulltext job', description: 'Cancels queued or running work. Already-staged bytes may remain private for diagnostics, but canceled jobs never create a handoff.', inputSchema: { job_id: z.string().regex(/^ft-[A-Za-z0-9-]{8,128}$/) }, annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: true },
  }, async (args) => {
    try { return result(await broker.cancel(args.job_id), `Canceled fulltext job ${args.job_id}.`); } catch (error) { return errorResult(error); }
  });
  return server;
}
