import { callMCPTool } from '../runtime.js';

/**
 * Find duplicate candidates in a Zotero import batch — Read-only duplicate candidate detection for a collection or import-run tag. Compares the selected batch against all top-level bibliographic items in the same Zotero library using DOI, PMID, ISBN, normalized title, creators, and year. Saves an auditable JSON report and recommends a master record, but never merges, trashes, deletes, or otherwise modifies Zotero. Review every candidate and perform the final merge in Zotero Desktop so collections, tags, and citation relations are preserved.
 * Params: collection_key, tag, limit, title_threshold, library_type, library_id.
 */
export function findDuplicates(input: Record<string, unknown> = {}): Promise<any> {
  return callMCPTool('zotero_find_duplicates', input);
}
