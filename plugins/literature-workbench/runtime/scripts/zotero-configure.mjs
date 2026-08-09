#!/usr/bin/env node
/**
 * Local-only Zotero credential onboarding. This deliberately accepts secrets
 * only through an interactive terminal, never through argv or MCP tool input.
 */
import {
  existsSync,
  readFileSync,
  rmSync,
} from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import {
  defaultAcademicResearchConfigFile,
  legacyPrivateEnvFile,
  preferredPrivateEnvFile,
} from '../dist/lib/env-files.js';
import {
  maskedPrompt,
  readJsonObject,
  updateEnvKey,
  writeJsonPrivate,
  writePrivateFile,
} from './credential-utils.mjs';

const command = process.argv[2] ?? 'setup';
const ACADEMIC_RESEARCH_CONFIG_FILE = defaultAcademicResearchConfigFile();
const LEGACY_ACADEMIC_RESEARCH_CONFIG_FILE = join(
  homedir(),
  '.config',
  'frank-ai4s',
  'academic-research.json',
);

function usage() {
  process.stdout.write(
    'Usage: node scripts/zotero-configure.mjs <setup|status|remove>\n',
  );
}

function removeEnvKey(text, name) {
  return text
    .split(/\r?\n/)
    .filter((line) => !new RegExp(`^\\s*(?:export\\s+)?${name}\\s*=`).test(line))
    .join('\n')
    .replace(/^\n+|\n+$/g, '');
}

function readAcademicResearchConfig() {
  const source = existsSync(ACADEMIC_RESEARCH_CONFIG_FILE)
    ? ACADEMIC_RESEARCH_CONFIG_FILE
    : ACADEMIC_RESEARCH_CONFIG_FILE !== LEGACY_ACADEMIC_RESEARCH_CONFIG_FILE
        && existsSync(LEGACY_ACADEMIC_RESEARCH_CONFIG_FILE)
      ? LEGACY_ACADEMIC_RESEARCH_CONFIG_FILE
      : undefined;
  return source ? readJsonObject(source) : {};
}

function writeAcademicResearchConfig(value) {
  writeJsonPrivate(ACADEMIC_RESEARCH_CONFIG_FILE, value);
}

async function verifyKey(key) {
  const response = await fetch('https://api.zotero.org/keys/current', {
    headers: { 'Zotero-API-Key': key },
  });
  if (!response.ok) throw new Error(`Zotero rejected the key (HTTP ${response.status}).`);
  const info = await response.json();
  if (!Number.isInteger(info.userID) || !info.username) {
    throw new Error('Zotero returned an unexpected key-validation response.');
  }
  return info;
}

async function setup(path, legacyPath) {
  const key = String(await maskedPrompt('Paste Zotero API key (input hidden): ')).trim();
  if (!key || /[\r\n]/.test(key)) throw new Error('The key must be a single non-empty line.');

  const info = await verifyKey(key);
  const migratingLegacySettings = path !== legacyPath && !existsSync(path) && existsSync(legacyPath);
  const existing = existsSync(path)
    ? readFileSync(path, 'utf8')
    : migratingLegacySettings
      ? readFileSync(legacyPath, 'utf8')
      : '';
  writePrivateFile(path, updateEnvKey(existing, 'ZOTERO_API_KEY', key));
  const migration = migratingLegacySettings
    ? ' Existing private settings were migrated from the legacy location.'
    : '';
  process.stdout.write(`Zotero key verified for ${info.username} and stored in your private configuration.${migration} Restart Codex to reload MCP.\n`);
}

function status(path, legacyPath) {
  const processKey = Boolean(process.env.ZOTERO_API_KEY?.trim());
  const fileKey = existsSync(path) && /^\s*(?:export\s+)?ZOTERO_API_KEY\s*=.+$/m.test(readFileSync(path, 'utf8'));
  const legacyKey = path !== legacyPath && existsSync(legacyPath) && /^\s*(?:export\s+)?ZOTERO_API_KEY\s*=.+$/m.test(readFileSync(legacyPath, 'utf8'));
  const source = processKey
    ? 'process environment'
    : fileKey
      ? 'private configuration file'
      : legacyKey
        ? 'legacy private configuration file (will be migrated by setup)'
        : 'not configured';
  process.stdout.write(`Credential source: ${source}\n`);
  process.stdout.write(`Private configuration path: ${path}\n`);

}

function removeKeyFromFile(path) {
  if (!existsSync(path)) return false;
  const remaining = removeEnvKey(readFileSync(path, 'utf8'), 'ZOTERO_API_KEY');
  if (remaining) writePrivateFile(path, `${remaining}\n`);
  else rmSync(path, { force: true });
  return true;
}

function remove(path, legacyPath) {
  const removed = removeKeyFromFile(path) || (legacyPath !== path && removeKeyFromFile(legacyPath));
  if (!removed) {
    process.stdout.write('No private Zotero configuration file exists.\n');
    return;
  }
  if (legacyPath !== path) removeKeyFromFile(legacyPath);
  process.stdout.write('Stored Zotero API key removed. Restart Codex to reload MCP.\n');
}

async function setupSemanticScholar() {
  const key = String(await maskedPrompt('Paste Semantic Scholar API key (input hidden): ')).trim();
  if (!key || /[\r\n]/.test(key)) throw new Error('The key must be a single non-empty line.');
  const config = readAcademicResearchConfig();
  config.s2_api_key = key;
  writeAcademicResearchConfig(config);
  process.stdout.write('Semantic Scholar key stored in your private academic-research configuration. It will be used by future citation refreshes.\n');
}

function removeSemanticScholar() {
  const nativeExists = existsSync(ACADEMIC_RESEARCH_CONFIG_FILE);
  const legacyExists = ACADEMIC_RESEARCH_CONFIG_FILE !== LEGACY_ACADEMIC_RESEARCH_CONFIG_FILE
    && existsSync(LEGACY_ACADEMIC_RESEARCH_CONFIG_FILE);
  if (!nativeExists && !legacyExists) {
    process.stdout.write('No private Semantic Scholar configuration file exists.\n');
    return;
  }
  const config = readAcademicResearchConfig();
  if (!Object.prototype.hasOwnProperty.call(config, 's2_api_key')) {
    process.stdout.write('No stored Semantic Scholar API key exists.\n');
    return;
  }
  delete config.s2_api_key;
  if (Object.keys(config).length) writeAcademicResearchConfig(config);
  else rmSync(ACADEMIC_RESEARCH_CONFIG_FILE, { force: true });
  if (legacyExists) rmSync(LEGACY_ACADEMIC_RESEARCH_CONFIG_FILE, { force: true });
  process.stdout.write('Stored Semantic Scholar API key removed.\n');
}

const path = preferredPrivateEnvFile();
const legacyPath = legacyPrivateEnvFile();
try {
  if (command === 'setup') await setup(path, legacyPath);
  else if (command === 'setup-semantic-scholar') await setupSemanticScholar();
  else if (command === 'status') status(path, legacyPath);
  else if (command === 'remove') remove(path, legacyPath);
  else if (command === 'remove-semantic-scholar') removeSemanticScholar();
  else {
    usage();
    process.exitCode = 2;
  }
} catch (error) {
  process.stderr.write(`Zotero configuration failed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
