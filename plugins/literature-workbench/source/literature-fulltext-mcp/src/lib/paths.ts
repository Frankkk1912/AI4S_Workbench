import { homedir } from 'node:os';
import { posix, win32 } from 'node:path';

function appDataBase(env: NodeJS.ProcessEnv, platform: NodeJS.Platform, home: string): string {
  const platformPath = platform === 'win32' ? win32 : posix;
  if (platform === 'win32') {
    const localAppData = env.LOCALAPPDATA?.trim() || platformPath.join(home, 'AppData', 'Local');
    return platformPath.join(localAppData, 'literature-workbench');
  }
  if (platform === 'darwin') {
    return platformPath.join(home, 'Library', 'Application Support', 'literature-workbench');
  }
  return platformPath.join(
    env.XDG_DATA_HOME ?? platformPath.join(home, '.local', 'share'),
    'literature-workbench',
  );
}

export function defaultDataDir(
  env: NodeJS.ProcessEnv = process.env,
  platform = process.platform,
  home = homedir(),
): string {
  const platformPath = platform === 'win32' ? win32 : posix;
  return env.LITERATURE_FULLTEXT_DATA_DIR ?? platformPath.join(appDataBase(env, platform, home), 'fulltext');
}

export function defaultExchangeRoot(
  env: NodeJS.ProcessEnv = process.env,
  platform = process.platform,
  home = homedir(),
): string {
  const platformPath = platform === 'win32' ? win32 : posix;
  return env.LITERATURE_FULLTEXT_EXCHANGE_ROOT
    ?? platformPath.join(appDataBase(env, platform, home), 'fulltext-exchange');
}
