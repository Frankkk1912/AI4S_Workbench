import { existsSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const required = ["manifest.json", "bootstrap.js", "src/metrics-payload.js", "src/article-types.js", "src/semantic-tags.js", "src/ai-summaries.js", "src/priorities.js", "src/literature-metrics.js", "README.md", "LICENSE"];
for (const relative of required) {
  if (!existsSync(resolve(root, relative))) throw new Error(`Missing required add-on file: ${relative}`);
}

const manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));
if (manifest.applications?.zotero?.id !== "literature-metrics@frank-ai4s.local") {
  throw new Error("manifest applications.zotero.id is missing or unexpected");
}
if (manifest.applications?.zotero?.strict_min_version !== "7.0") {
  throw new Error("manifest must declare Zotero 7 as the minimum supported version");
}
if (typeof manifest.applications?.zotero?.update_url !== "string" || !manifest.applications.zotero.update_url.startsWith("https://")) {
  throw new Error("manifest must provide an HTTPS applications.zotero.update_url");
}

for (const relative of ["bootstrap.js", "src/metrics-payload.js", "src/article-types.js", "src/semantic-tags.js", "src/ai-summaries.js", "src/priorities.js", "src/literature-metrics.js"]) {
  const result = spawnSync(process.execPath, ["--check", resolve(root, relative)], { encoding: "utf8" });
  if (result.status !== 0) throw new Error(`${relative} failed syntax validation:\n${result.stderr || result.stdout}`);
}

console.log("Success! Literature Metrics add-on structure and JavaScript syntax are valid.");
