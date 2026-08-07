import { z } from 'zod';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';

function userMessage(text: string) {
  return { messages: [{ role: 'user' as const, content: { type: 'text' as const, text } }] };
}

/** Registers user-triggered scholarly workflow prompts. */
export function registerPrompts(server: McpServer): void {
  server.registerPrompt(
    'zotero-literature-review',
    {
      title: 'Literature review',
      description: 'Survey the library on a topic and synthesize a cited mini-review.',
      argsSchema: { topic: z.string().describe('The research topic.'), collection: z.string().optional().describe('Optional collection name/key to scope to.') },
    },
    ({ topic, collection }) =>
      userMessage(
        `Conduct a literature review on "${topic}"${collection ? ` within the "${collection}" collection` : ''} using my Zotero library.\n\n` +
          `1. Use zotero_semantic_search (and zotero_search_items for precise filters) to find the most relevant items.\n` +
          `2. For key papers, use zotero_get_item to read abstracts/notes.\n` +
          `3. Synthesize themes, agreements, and gaps.\n` +
          `4. Produce a short review with inline citations and a bibliography via zotero_bibliography or zotero_format_bibliography.`,
      ),
  );

  server.registerPrompt(
    'zotero-cite',
    {
      title: 'Cite items',
      description: 'Format a bibliography for specific items in a chosen style.',
      argsSchema: { item_keys: z.string().describe('Comma-separated item keys.'), style: z.string().optional().describe('Citation style (e.g. "APA 7th", default APA).') },
    },
    ({ item_keys, style }) =>
      userMessage(
        `Format a bibliography for the Zotero items [${item_keys}] in ${style ?? 'APA'} style. ` +
          `Resolve the style with zotero_styles if unsure, then call zotero_bibliography (library items) or zotero_format_bibliography.`,
      ),
  );

  server.registerPrompt(
    'zotero-add-from-url',
    {
      title: 'Add from URL or identifier',
      description: 'Ingest a paper from a URL, DOI, ISBN, PMID, or arXiv id.',
      argsSchema: { source: z.string().describe('A URL or identifier (DOI/ISBN/PMID/arXiv).'), collection: z.string().optional() },
    },
    ({ source, collection }) =>
      userMessage(
        `Add "${source}" to my Zotero library. Use zotero_import (by_identifier if it looks like a DOI/ISBN/PMID/arXiv id, else by_url) with save_to_library:true` +
          `${collection ? ` and add it to the "${collection}" collection (resolve the collection key with zotero_manage_collections)` : ''}. Confirm what was saved.`,
      ),
  );

  server.registerPrompt(
    'zotero-organize',
    {
      title: 'Organize loose items',
      description: 'Suggest tags and collection moves for unfiled items.',
      argsSchema: { collection: z.string().optional().describe('Scope to a collection (default: whole library).') },
    },
    ({ collection }) =>
      userMessage(
        `Help me organize ${collection ? `the "${collection}" collection` : 'my library'}. ` +
          `Use zotero_search_items to find loosely-organized items, propose consistent tags and collection assignments, and (after I confirm) apply them with zotero_manage_tags and zotero_manage_collections.`,
      ),
  );

  server.registerPrompt(
    'zotero-find-related',
    {
      title: 'Find related work',
      description: 'Find work related to an item — in your library and beyond.',
      argsSchema: { item_key: z.string().describe('The item to find related work for.') },
    },
    ({ item_key }) =>
      userMessage(
        `Find work related to Zotero item ${item_key}. Use zotero_get_item to get its DOI, then zotero_scholar (action:"related" and "citations") to find related and citing works, flagging which are already in my library. Also try zotero_semantic_search on its topic.`,
      ),
  );

  server.registerPrompt(
    'zotero-citation-audit',
    {
      title: 'Citation audit',
      description: 'Check a draft\'s citations against the library and the literature.',
      argsSchema: { text: z.string().describe('The draft text or reference list to audit.') },
    },
    ({ text }) =>
      userMessage(
        `Audit the citations in this draft against my Zotero library and the literature:\n\n${text}\n\n` +
          `For each cited work, check it exists (zotero_search_items / zotero_scholar lookup), flag anything not in my library, and surface important missing references via zotero_scholar (references/citations).`,
      ),
  );

  server.registerPrompt(
    'zotero-summarize-collection',
    {
      title: 'Summarize a collection',
      description: 'Summarize the contents and themes of a collection.',
      argsSchema: { collection: z.string().describe('Collection name or key.') },
    },
    ({ collection }) =>
      userMessage(
        `Summarize the "${collection}" collection: list its items with zotero_search_items (collectionKey), read key abstracts with zotero_get_item, and produce a thematic summary of what the collection covers and any gaps.`,
      ),
  );

  server.registerPrompt(
    'zotero-semantic-tag',
    {
      title: 'Generate Agent Tags',
      description: 'Generate and automatically apply a compact reusable English semantic vocabulary.',
      argsSchema: {
        collection: z.string().optional().describe('Collection key to tag; omit when item_keys is supplied.'),
        item_keys: z.string().optional().describe('Comma-separated Zotero item keys; omit when collection is supplied.'),
      },
    },
    ({ collection, item_keys }) =>
      userMessage(
        `Generate Agent Tags for ${collection ? `collection ${collection}` : `items ${item_keys ?? '(ask me for the target)'}`}. ` +
          `Call zotero_semantic_tag_context, reuse its English canonical vocabulary wherever accurate, and assign zero to four tags per paper. ` +
          `Only tag principal topics/entities/methods/mechanisms; do not fill missing dimensions. Metadata-only records get at most two tags and no mechanism. ` +
          `Then call zotero_apply_semantic_tags with the returned item versions and vocabulary revision. Automatic tagging and cleanup of Zotero automatic tags are enabled; preserve all user and non-semantic AI4S tags.`,
      ),
  );

  server.registerPrompt(
    'zotero-ai-summary',
    {
      title: 'Generate AI Summary metadata',
      description: 'Explicitly generate or refresh one Chinese sentence per paper from title and abstract.',
      argsSchema: {
        collection: z.string().optional().describe('Collection key; omit when item_keys is supplied.'),
        item_keys: z.string().optional().describe('Comma-separated Zotero item keys; omit when collection is supplied.'),
        refresh: z.string().optional().describe('Set to true only when the user explicitly asks to refresh existing summaries.'),
        language: z.string().optional().describe('Output language; defaults to zh-CN.'),
      },
    },
    ({ collection, item_keys, refresh, language }) =>
      userMessage(
        `Generate AI Summary metadata for ${collection ? `collection ${collection}` : `items ${item_keys ?? '(ask me for the target)'}`}. ` +
          `This prompt is an explicit user request. Call zotero_ai_summary_context with mode ${refresh === 'true' ? 'refresh' : 'missing'} and language ${language ?? 'zh-CN'}. ` +
          `For every returned candidate, write exactly one sentence using only its title and abstract; preserve uncertainty, study population, and causal limits, and add no external knowledge. ` +
          `Then call zotero_apply_ai_summaries with trigger "explicit-user-request", the same mode, hashes, versions, and summaries. Do not alter Abstract, tags, collections, metrics, Agent Tags, Priority, or report Notes.`,
      ),
  );
}
