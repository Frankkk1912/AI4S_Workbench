import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/semantic-tags.js", import.meta.url), "utf8");
const context = {};
vm.createContext(context);
vm.runInContext(source, context, { filename: "semantic-tags.js" });
const semanticTags = context.LiteratureSemanticTags;

test("reads only AI4S semantic tags, hides the namespace, and deduplicates labels", () => {
  assert.deepEqual(Array.from(semanticTags.labelsFromTags([
    { tag: "manual:keep" },
    { tag: "AI4S:Semantic:Macrophage" },
    { tag: "AI4S:Semantic:macrophage" },
    { tag: "AI4S:ArticleType:Review" },
    { tag: "AI4S:Semantic:Single-cell transcriptomics" },
  ])), ["Macrophage", "Single-cell transcriptomics"]);
});

test("round-trips a stable sortable column value", () => {
  const value = semanticTags.columnValue([
    "AI4S:Semantic:Inflammation",
    "AI4S:Semantic:Atherosclerosis",
  ]);
  assert.deepEqual(Array.from(semanticTags.labelsFromColumnValue(value)), ["Atherosclerosis", "Inflammation"]);
  assert.deepEqual(Array.from(semanticTags.labelsFromColumnValue("bad")), []);
});
