import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, posix, win32 } from 'node:path';
import { fileURLToPath } from 'node:url';

const ENV_KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

function packageRoot(): string {
  return join(dirname(fileURLToPath(import.meta.url)), '..', '..');
}

export function defaultPrivateEnvFile(
  env: NodeJS.ProcessEnv = process.env,
  platform = process.platform,
  home = homedir(),
): string {
  const platformPath = platform === 'win32' ? win32 : posix;
  if (platform === 'win32') {
    const localAppData = env.LOCALAPPDATA?.trim() || platformPath.join(home, 'AppData', 'Local');
    return platformPath.join(localAppData, 'ai4s-literature-workbench', 'zotero.env');
  }

  if (platform === 'darwin') {
    return platformPath.join(home, 'Library', 'Application Support', 'ai4s-literature-workbench', 'zotero.env');
  }

  const configHome = env.XDG_CONFIG_HOME?.trim() || platformPath.join(home, '.config');
  return platformPath.join(configHome, 'ai4s-literature-workbench', 'zotero.env');
}

/** Historical location used before native macOS/Windows paths were introduced. */
export function legacyPrivateEnvFile(home = homedir()): string {
  const platformPath = /^[A-Za-z]:[\\/]/.test(home) || home.startsWith('\\\\') ? win32 : posix;
  return platformPath.join(home, '.config', 'ai4s-literature-workbench', 'zotero.env');
}

/** The private target used by the interactive setup command. */
export function preferredPrivateEnvFile(
  env: NodeJS.ProcessEnv = process.env,
  platform = process.platform,
  home = homedir(),
): string {
  return env.LITERATURE_ZOTERO_MCP_ENV_FILE?.trim() || defaultPrivateEnvFile(env, platform, home);
}

export function defaultAcademicResearchConfigFile(
  env: NodeJS.ProcessEnv = process.env,
  platform = process.platform,
  home = homedir(),
): string {
  const platformPath = platform === 'win32' ? win32 : posix;
  if (platform === 'win32') {
    const localAppData = env.LOCALAPPDATA?.trim() || platformPath.join(home, 'AppData', 'Local');
    return platformPath.join(localAppData, 'frank-ai4s', 'academic-research.json');
  }
  return platformPath.join(home, '.config', 'frank-ai4s', 'academic-research.json');
}

export function startupEnvFiles(env: NodeJS.ProcessEnv = process.env): string[] {
  const native = defaultPrivateEnvFile(env);
  const legacy = legacyPrivateEnvFile();
  // Preserve existing installations during migration. Native locations take
  // precedence because later env files override earlier file values.
  const files = [join(packageRoot(), '.env'), ...(legacy === native ? [] : [legacy]), native];
  const explicit = env.LITERATURE_ZOTERO_MCP_ENV_FILE?.trim();
  if (explicit) files.push(explicit);
  return files;
}

function parseEnvFile(text: string, filePath: string): Array<[string, string]> {
  const entries: Array<[string, string]> = [];
  const lines = text.split(/\r?\n/);

  for (let i = 0; i < lines.length; i += 1) {
    const raw = lines[i] ?? '';
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;

    const assignment = line.startsWith('export ') ? line.slice(7).trimStart() : line;
    const eq = assignment.indexOf('=');
    if (eq <= 0) {
      throw new Error(`Invalid env assignment in ${filePath}:${i + 1}`);
    }

    const key = assignment.slice(0, eq).trim();
    if (!ENV_KEY_RE.test(key)) {
      throw new Error(`Invalid env key in ${filePath}:${i + 1}: ${key}`);
    }

    let value = assignment.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    } else {
      const commentIndex = value.search(/\s+#/);
      if (commentIndex !== -1) value = value.slice(0, commentIndex).trimEnd();
    }

    entries.push([key, value]);
  }

  return entries;
}

/**
 * Load startup env files into the provided environment.
 *
 * Process environment values already present before this function runs win over
 * file values. Later files can override earlier file values.
 */
export function loadStartupEnvFiles(
  env: NodeJS.ProcessEnv = process.env,
  files: string[] = startupEnvFiles(env),
): string[] {
  const originalKeys = new Set(Object.keys(env));
  const loaded: string[] = [];

  for (const filePath of files) {
    if (!filePath || !existsSync(filePath)) continue;

    const assignments = parseEnvFile(readFileSync(filePath, 'utf8'), filePath);
    for (const [key, value] of assignments) {
      if (originalKeys.has(key)) continue;
      env[key] = value;
    }
    loaded.push(filePath);
  }

  return loaded;
}
