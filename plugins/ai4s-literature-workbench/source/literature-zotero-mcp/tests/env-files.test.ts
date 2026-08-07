import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  defaultAcademicResearchConfigFile,
  defaultPrivateEnvFile,
  legacyPrivateEnvFile,
  loadStartupEnvFiles,
  preferredPrivateEnvFile,
} from '../src/lib/env-files.js';

describe('startup env files', () => {
  it('loads values from env files that are not already present in the process env', () => {
    const dir = mkdtempSync(join(tmpdir(), 'zoteus-env-'));
    const file = join(dir, 'zotero.env');
    writeFileSync(file, 'ZOTERO_API_KEY=secret\nZOTEUS_LOCAL=on\n');

    const env: NodeJS.ProcessEnv = {};
    const loaded = loadStartupEnvFiles(env, [file]);

    expect(loaded).toEqual([file]);
    expect(env.ZOTERO_API_KEY).toBe('secret');
    expect(env.ZOTEUS_LOCAL).toBe('on');

    rmSync(dir, { recursive: true, force: true });
  });

  it('keeps values that were already present before startup', () => {
    const dir = mkdtempSync(join(tmpdir(), 'zoteus-env-'));
    const file = join(dir, 'zotero.env');
    writeFileSync(file, 'ZOTERO_API_KEY=secret\n');

    const env: NodeJS.ProcessEnv = { ZOTERO_API_KEY: 'existing' };
    loadStartupEnvFiles(env, [file]);

    expect(env.ZOTERO_API_KEY).toBe('existing');

    rmSync(dir, { recursive: true, force: true });
  });

  it('supports export prefixes and quoted values', () => {
    const dir = mkdtempSync(join(tmpdir(), 'zoteus-env-'));
    const file = join(dir, 'zotero.env');
    writeFileSync(file, "export ZOTERO_API_KEY='secret key'\nZOTEUS_LOCAL=\"auto\"\n");

    const env: NodeJS.ProcessEnv = {};
    loadStartupEnvFiles(env, [file]);

    expect(env.ZOTERO_API_KEY).toBe('secret key');
    expect(env.ZOTEUS_LOCAL).toBe('auto');

    rmSync(dir, { recursive: true, force: true });
  });

  it('uses native private configuration locations on each supported platform', () => {
    expect(defaultPrivateEnvFile({}, 'darwin', '/Users/alice')).toBe(
      '/Users/alice/Library/Application Support/ai4s-literature-workbench/zotero.env',
    );
    expect(defaultPrivateEnvFile({ LOCALAPPDATA: 'C:\\Users\\Alice\\AppData\\Local' }, 'win32', 'C:\\Users\\Alice')).toBe(
      'C:\\Users\\Alice\\AppData\\Local\\ai4s-literature-workbench\\zotero.env',
    );
    expect(defaultPrivateEnvFile({ XDG_CONFIG_HOME: '/srv/config' }, 'linux', '/home/alice')).toBe(
      '/srv/config/ai4s-literature-workbench/zotero.env',
    );
  });

  it('uses an explicit private env file for interactive setup when provided', () => {
    expect(preferredPrivateEnvFile({ LITERATURE_ZOTERO_MCP_ENV_FILE: '/secure/zotero.env' }, 'linux', '/home/alice')).toBe(
      '/secure/zotero.env',
    );
  });

  it('retains the historic dot-config location for credential migration', () => {
    expect(legacyPrivateEnvFile('/Users/alice')).toBe('/Users/alice/.config/ai4s-literature-workbench/zotero.env');
    expect(legacyPrivateEnvFile('C:\\Users\\Alice')).toBe(
      'C:\\Users\\Alice\\.config\\ai4s-literature-workbench\\zotero.env',
    );
  });

  it('uses the same platform-private academic-research path as the Python skill', () => {
    expect(defaultAcademicResearchConfigFile(
      { LOCALAPPDATA: 'C:\\Users\\Alice\\AppData\\Local' },
      'win32',
      'C:\\Users\\Alice',
    )).toBe('C:\\Users\\Alice\\AppData\\Local\\frank-ai4s\\academic-research.json');
    expect(defaultAcademicResearchConfigFile({}, 'linux', '/home/alice')).toBe(
      '/home/alice/.config/frank-ai4s/academic-research.json',
    );
  });
});
