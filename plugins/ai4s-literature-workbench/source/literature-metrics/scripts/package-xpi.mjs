import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { resolve, relative } from "node:path";
import { unzipSync, zipSync } from "fflate";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");
const manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));
const output = resolve(dist, `literature-metrics-${manifest.version}.xpi`);
const excluded = new Set(["dist", "node_modules", ".git", ".gitignore"]);
const stableMtime = new Date("1980-01-01T00:00:00.000Z");

function collectFiles(directory, files = {}) {
  for (const entry of readdirSync(directory).sort()) {
    if (directory === root && excluded.has(entry)) continue;
    const absolute = resolve(directory, entry);
    const info = lstatSync(absolute);
    if (info.isSymbolicLink()) {
      throw new Error(`Refusing to package symbolic link: ${absolute}`);
    }
    if (info.isDirectory()) {
      collectFiles(absolute, files);
      continue;
    }
    if (!info.isFile()) continue;
    const archivePath = relative(root, absolute).replaceAll("\\", "/");
    files[archivePath] = [new Uint8Array(readFileSync(absolute)), { mtime: stableMtime }];
  }
  return files;
}

const check = await import("./check.mjs");
void check;
mkdirSync(dist, { recursive: true });
rmSync(output, { force: true });

const archive = zipSync(collectFiles(root), { level: 9 });
writeFileSync(output, archive);

const packaged = unzipSync(new Uint8Array(readFileSync(output)));
for (const required of ["manifest.json", "bootstrap.js", "src/literature-metrics.js"]) {
  if (!Object.prototype.hasOwnProperty.call(packaged, required)) {
    throw new Error(`Generated XPI is missing required entry: ${required}`);
  }
}
if (!existsSync(output) || readFileSync(output).byteLength === 0) {
  throw new Error("Generated XPI is empty.");
}

console.log(`Success! Literature Metrics XPI written to: ${output}`);
