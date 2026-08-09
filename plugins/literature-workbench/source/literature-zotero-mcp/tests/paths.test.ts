import { describe, expect, it } from 'vitest';
import { defaultDataDir, defaultFulltextExchangeRoot } from '../src/lib/paths.js';

describe('platform data paths', () => {
  it('uses native Windows application-data paths with deterministic fallbacks', () => {
    const home = 'C:\\Users\\Alice';
    expect(defaultDataDir({ APPDATA: `${home}\\AppData\\Roaming` }, 'win32', home)).toBe(
      `${home}\\AppData\\Roaming\\literature-zotero-mcp`,
    );
    expect(defaultDataDir({}, 'win32', home)).toBe(
      `${home}\\AppData\\Roaming\\literature-zotero-mcp`,
    );
    expect(defaultFulltextExchangeRoot({ LOCALAPPDATA: `${home}\\AppData\\Local` }, 'win32', home)).toBe(
      `${home}\\AppData\\Local\\literature-workbench\\fulltext-exchange`,
    );
  });

  it('preserves explicit overrides and POSIX defaults', () => {
    expect(defaultDataDir({ LITERATURE_ZOTERO_MCP_DATA_DIR: '/private/zotero' }, 'linux', '/home/a')).toBe('/private/zotero');
    expect(defaultFulltextExchangeRoot({ XDG_DATA_HOME: '/srv/data' }, 'linux', '/home/a')).toBe(
      '/srv/data/literature-workbench/fulltext-exchange',
    );
  });
});
