import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join } from 'node:path';

export function setPrivatePermissions(path) {
  if (process.platform !== 'win32') chmodSync(path, 0o600);
}

export function writePrivateFile(path, content) {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temp = join(dirname(path), `.${process.pid}.${path.split(/[\\/]/).at(-1)}.tmp`);
  try {
    writeFileSync(temp, content, { encoding: 'utf8', mode: 0o600 });
    setPrivatePermissions(temp);
    renameSync(temp, path);
    setPrivatePermissions(path);
  } finally {
    if (existsSync(temp)) rmSync(temp, { force: true });
  }
}

export function readJsonObject(path) {
  if (!path || !existsSync(path)) return {};
  const value = JSON.parse(readFileSync(path, 'utf8'));
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Expected a JSON object in ${path}.`);
  }
  return value;
}

export function writeJsonPrivate(path, value) {
  writePrivateFile(path, `${JSON.stringify(value, null, 2)}\n`);
}

export function updateEnvKey(text, name, value) {
  const lines = text ? text.split(/\r?\n/) : [];
  let updated = false;
  const next = lines.map((line) => {
    if (new RegExp(`^\\s*(?:export\\s+)?${name}\\s*=`).test(line)) {
      updated = true;
      return `${name}=${value}`;
    }
    return line;
  });
  if (!updated) next.push(`${name}=${value}`);
  return `${next.filter((line, index) => line || index < next.length - 1).join('\n').replace(/\n+$/, '')}\n`;
}

export function envKeyExists(path, name) {
  return Boolean(path)
    && existsSync(path)
    && new RegExp(`^\\s*(?:export\\s+)?${name}\\s*=.+$`, 'm').test(readFileSync(path, 'utf8'));
}

export function maskedPrompt(message) {
  if (!process.stdin.isTTY || !process.stdout.isTTY || typeof process.stdin.setRawMode !== 'function') {
    throw new Error('An interactive terminal is required. Run this command locally and paste the key into its masked prompt.');
  }

  process.stdout.write(message);
  return new Promise((resolve, reject) => {
    let value = '';
    const stdin = process.stdin;
    const wasRaw = stdin.isRaw;

    const finish = (error) => {
      stdin.off('data', onData);
      stdin.setRawMode(wasRaw ?? false);
      stdin.pause();
      process.stdout.write('\n');
      if (error) reject(error);
      else resolve(value);
    };

    const onData = (chunk) => {
      for (const character of String(chunk)) {
        if (character === '\r' || character === '\n') return finish();
        if (character === '\u0003') return finish(new Error('Cancelled.'));
        if (character === '\u0004') return finish(new Error('No key entered.'));
        if (character === '\u007f' || character === '\b') {
          if (value) {
            value = value.slice(0, -1);
            process.stdout.write('\b \b');
          }
          continue;
        }
        if (character >= ' ') {
          value += character;
          process.stdout.write('*');
        }
      }
    };

    stdin.setRawMode(true);
    stdin.resume();
    stdin.on('data', onData);
  });
}

export function linePrompt(message) {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    throw new Error('An interactive terminal is required.');
  }
  process.stdout.write(message);
  return new Promise((resolve) => {
    const onData = (chunk) => {
      process.stdin.off('data', onData);
      process.stdin.pause();
      resolve(String(chunk).trim());
    };
    process.stdin.resume();
    process.stdin.on('data', onData);
  });
}
