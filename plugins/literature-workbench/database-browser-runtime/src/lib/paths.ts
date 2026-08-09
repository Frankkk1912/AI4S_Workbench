import { homedir } from 'node:os';
import { posix, win32 } from 'node:path';

export function defaultDataDir(
  env: NodeJS.ProcessEnv = process.env,
  platform = process.platform,
  home = homedir(),
): string {
  if (env.LITERATURE_DATABASE_BROWSER_DATA_DIR) return env.LITERATURE_DATABASE_BROWSER_DATA_DIR;
  const platformPath = platform === 'win32' ? win32 : posix;
  if (platform === 'win32') {
    const localAppData = env.LOCALAPPDATA?.trim() || platformPath.join(home, 'AppData', 'Local');
    return platformPath.join(localAppData, 'literature-database-browser');
  }
  if (platform === 'darwin') {
    return platformPath.join(home, 'Library', 'Application Support', 'literature-database-browser');
  }
  return platformPath.join(
    env.XDG_DATA_HOME ?? platformPath.join(home, '.local', 'share'),
    'literature-database-browser',
  );
}
