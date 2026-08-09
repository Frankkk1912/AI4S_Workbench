import { describe, expect, it } from 'vitest';
import { defaultDataDir, defaultExchangeRoot } from '../src/lib/paths.js';

describe('platform data paths', () => {
  it('uses native Windows local application data with a home fallback', () => {
    const home = 'C:\\Users\\Alice';
    expect(defaultDataDir({ LOCALAPPDATA: `${home}\\AppData\\Local` }, 'win32', home)).toBe(
      `${home}\\AppData\\Local\\literature-workbench\\fulltext`,
    );
    expect(defaultExchangeRoot({}, 'win32', home)).toBe(
      `${home}\\AppData\\Local\\literature-workbench\\fulltext-exchange`,
    );
  });

  it('preserves explicit overrides', () => {
    expect(defaultDataDir({ LITERATURE_FULLTEXT_DATA_DIR: '/private/fulltext' }, 'linux', '/home/a')).toBe(
      '/private/fulltext',
    );
  });
});
