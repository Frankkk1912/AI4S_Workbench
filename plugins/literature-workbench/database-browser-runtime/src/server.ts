import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { DatabaseBroker } from './broker.js';
import { DATABASE_ID, EXPORT_FORMAT } from './domain.js';
import { BrokerError } from './errors.js';

const requestId = z.string().regex(/^[a-f0-9]{64}$/i, 'request_id must be a SHA-256 hex digest.');
const filters = z.object({
  from_year: z.number().int().min(1900).max(2100).optional(),
  until_year: z.number().int().min(1900).max(2100).optional(),
  document_types: z.array(z.string().trim().min(1).max(80)).min(1).max(20).optional(),
}).refine((value) => value.from_year === undefined || value.until_year === undefined || value.from_year <= value.until_year, {
  message: 'from_year must not be later than until_year.',
});

function result(structured: Record<string, unknown>, summary: string) {
  return {
    content: [
      { type: 'text' as const, text: summary },
      { type: 'text' as const, text: JSON.stringify(structured, null, 2) },
    ],
    structuredContent: structured,
  };
}

function errorResult(error: unknown) {
  const brokerError = error instanceof BrokerError
    ? error
    : new BrokerError('PAGE_CONTRACT_CHANGED', error instanceof Error ? error.message : String(error));
  return {
    content: [{ type: 'text' as const, text: JSON.stringify({ error_code: brokerError.code, message: brokerError.message }) }],
    structuredContent: { error_code: brokerError.code, message: brokerError.message },
    isError: true,
  };
}

function snakeFilters(value: z.infer<typeof filters> | undefined) {
  if (!value) return undefined;
  return {
    ...(value.from_year === undefined ? {} : { fromYear: value.from_year }),
    ...(value.until_year === undefined ? {} : { untilYear: value.until_year }),
    ...(value.document_types === undefined ? {} : { documentTypes: value.document_types }),
  };
}

export function createServer(broker: DatabaseBroker): McpServer {
  const server = new McpServer(
    { name: 'ai4s-literature-database-browser', version: '0.1.0' },
    {
      capabilities: { tools: { listChanged: false } },
      instructions:
        'This MCP executes exact literature-database browser actions only. Call database_browser_capabilities before planning and database_session_open before a new session. Use database_search_submit then poll database_search_status; inspect the verified result count before database_export_submit. Do not treat a queued job, a click, an unverified page, or an unvalidated download as a successful search/export. This V1 server supports only Web of Science Core Collection and never bypasses login, CAPTCHA, access control, or export restrictions.',
    },
  );

  server.registerTool(
    'database_browser_capabilities',
    {
      title: 'Get literature database browser capabilities',
      description: 'Read-only capability registry. V1 declares only Web of Science Core Collection.',
      inputSchema: {},
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
    },
    async () => result(broker.capabilities(), 'Reported supported literature database browser capabilities.'),
  );

  server.registerTool(
    'database_session_open',
    {
      title: 'Open the visible literature database browser session',
      description: 'Open or reuse the dedicated, visible Web of Science Core Collection browser profile. It never imports credentials, starts a VPN, or bypasses a challenge.',
      inputSchema: { database: z.literal(DATABASE_ID) },
      annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: true },
    },
    async () => {
      try {
        const state = await broker.openSession();
        return result({
          database: state.database,
          session_state: state.sessionState,
          user_action_required: state.userActionRequired,
          message: state.message,
          ...(state.errorCode ? { error_code: state.errorCode } : {}),
        }, state.message);
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  server.registerTool(
    'database_session_status',
    {
      title: 'Check literature database browser session status',
      description: 'Read-only status check. It never starts a browser implicitly.',
      inputSchema: {},
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
    },
    async () => {
      try {
        const state = await broker.sessionStatus();
        return result({
          database: state.database,
          session_state: state.sessionState,
          user_action_required: state.userActionRequired,
          message: state.message,
          ...(state.errorCode ? { error_code: state.errorCode } : {}),
        }, state.message);
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  server.registerTool(
    'database_search_submit',
    {
      title: 'Submit an asynchronous literature database search',
      description: 'Queue one exact Web of Science Core Collection Advanced Search attempt. This tool does not export records; poll database_search_status for verified result count and filters.',
      inputSchema: {
        database: z.literal(DATABASE_ID),
        attempt_id: z.string().trim().min(1).max(128),
        query: z.object({ mode: z.literal('advanced-search'), value: z.string().trim().min(1).max(10_000) }),
        filters: filters.optional(),
        sort: z.enum(['relevance', 'date-desc', 'citations-desc']).optional(),
        request_id: requestId,
      },
      annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: true },
    },
    async (args) => {
      try {
        const accepted = await broker.submitSearch({
          database: args.database,
          attemptId: args.attempt_id,
          query: args.query,
          ...(args.filters ? { filters: snakeFilters(args.filters) } : {}),
          ...(args.sort ? { sort: args.sort } : {}),
          requestId: args.request_id,
        });
        return result({ job_id: accepted.jobId, state: 'queued', reused: accepted.reused }, accepted.reused ? 'Reused the existing search job for this request_id.' : 'Queued the search job. Poll database_search_status for verified results.');
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  server.registerTool(
    'database_search_status',
    {
      title: 'Get literature database search or export job status',
      description: 'Read-only status for an asynchronous search/export job. A result count is returned only after the page state, filters, and sort are verified.',
      inputSchema: { job_id: z.string().trim().min(1).max(128) },
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: true },
    },
    async (args) => {
      try {
        const status = await broker.status(args.job_id);
        return result(status, `Job ${args.job_id} is ${String(status.state)}.`);
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  server.registerTool(
    'database_export_submit',
    {
      title: 'Submit an official literature database export',
      description: 'Queue official tab-delimited full-record export for a verified results_ready job. V1 allows at most 1000 records and validates each downloaded batch before reporting success.',
      inputSchema: {
        job_id: z.string().trim().min(1).max(128),
        limit: z.number().int().min(1).max(1000),
        format: z.literal(EXPORT_FORMAT),
        request_id: requestId,
      },
      annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: true },
    },
    async (args) => {
      try {
        const accepted = await broker.submitExport({ jobId: args.job_id, limit: args.limit, format: args.format, requestId: args.request_id });
        return result({ job_id: accepted.jobId, state: 'queued', reused: accepted.reused }, accepted.reused ? 'Reused the existing export job for this request_id.' : 'Queued the official export. Poll database_search_status for verification.');
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  server.registerTool(
    'database_job_cancel',
    {
      title: 'Cancel a literature database job',
      description: 'Cancel a queued or running search/export job. A browser download already started may finish on disk, but canceled output is never reported as success.',
      inputSchema: { job_id: z.string().trim().min(1).max(128) },
      annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: true },
    },
    async (args) => {
      try {
        const canceled = await broker.cancel(args.job_id);
        return result(canceled, `Canceled job ${args.job_id}.`);
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  return server;
}
