import { describe, it, expect } from 'vitest';
import { tools } from '../src/tools/index.js';
import { selectActiveTools } from '../src/server.js';

// Mirrors the read-only filter in src/server.ts.
const readOnlyTools = tools.filter(
  (t) => t.annotations?.readOnlyHint === true || t.name === 'zotero_index',
);
const names = readOnlyTools.map((t) => t.name);

describe('read-only mode tool set', () => {
  it('keeps the read/discovery tools', () => {
    for (const t of [
      'zotero_whoami',
      'zotero_search_items',
      'zotero_get_item',
      'zotero_schema',
      'zotero_bibliography',
      'zotero_scholar',
      'zotero_semantic_search',
      'search_tools',
      'zotero_list_tags',
      'zotero_list_collections',
      'zotero_get_fulltext',
      'zotero_fulltext_context',
      'zotero_tag_audit',
      'zotero_ai_summary_context',
    ]) {
      expect(names).toContain(t);
    }
  });

  it('excludes every library-mutating tool', () => {
    for (const t of [
      'zotero_create_items',
      'zotero_update_item',
      'zotero_trash_items',
      'zotero_delete_items',
      'zotero_manage_collections',
      'zotero_manage_tags',
      'zotero_saved_searches',
      'zotero_attachment',
      'zotero_import',
      'zotero_apply_import_plan',
      'zotero_apply_ai_summaries',
    ]) {
      expect(names).not.toContain(t);
    }
  });
});

describe('workbench tool profile', () => {
  const config = { toolProfile: 'workbench', readOnly: false } as any;

  it('exposes only the seventeen workflow-facing tools', () => {
    expect(selectActiveTools(config).map((tool) => tool.name)).toEqual([
      'zotero_whoami',
      'zotero_search_items',
      'zotero_get_item',
      'zotero_get_fulltext',
      'zotero_fulltext_context',
      'zotero_find_duplicates',
      'zotero_apply_import_plan',
      'zotero_apply_metrics_plan',
      'zotero_apply_fulltext_handoff',
      'zotero_apply_citation_plan',
      'zotero_semantic_tag_context',
      'zotero_apply_semantic_tags',
      'zotero_cleanup_auto_tags',
      'zotero_semantic_tag_vocabulary',
      'zotero_sync_literature_project',
      'zotero_ai_summary_context',
      'zotero_apply_ai_summaries',
    ]);
  });

  it('removes the write tool when combined with read-only mode', () => {
    const names = selectActiveTools({ ...config, readOnly: true }).map((tool) => tool.name);
    expect(names).not.toContain('zotero_apply_import_plan');
    expect(names).not.toContain('zotero_apply_metrics_plan');
    expect(names).not.toContain('zotero_apply_citation_plan');
    expect(names).not.toContain('zotero_apply_semantic_tags');
    expect(names).not.toContain('zotero_cleanup_auto_tags');
    expect(names).not.toContain('zotero_semantic_tag_vocabulary');
    expect(names).not.toContain('zotero_sync_literature_project');
    expect(names).not.toContain('zotero_apply_ai_summaries');
    expect(names).toContain('zotero_semantic_tag_context');
    expect(names).toContain('zotero_ai_summary_context');
    expect(names).toContain('zotero_fulltext_context');
    expect(names).toHaveLength(8);
  });
});
