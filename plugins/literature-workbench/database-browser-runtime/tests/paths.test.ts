import { describe, expect, it } from 'vitest';
import { defaultDataDir } from '../src/lib/paths.js';

describe('platform data path', () => {
  it('uses native Windows local application data with a home fallback', () => {
    const home = 'C:\\Users\\Alice';
    expect(defaultDataDir({ LOCALAPPDATA: `${home}\\AppData\\Local` }, 'win32', home)).toBe(
      `${home}\\AppData\\Local\\literature-database-browser`,
    );
    expect(defaultDataDir({}, 'win32', home)).toBe(
      `${home}\\AppData\\Local\\literature-database-browser`,
    );
  });

  it('preserves explicit overrides', () => {
    expect(defaultDataDir({ LITERATURE_DATABASE_BROWSER_DATA_DIR: '/private/browser' }, 'linux', '/home/a')).toBe(
      '/private/browser',
    );
  });
});
