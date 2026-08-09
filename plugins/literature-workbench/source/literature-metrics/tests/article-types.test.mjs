import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/article-types.js", import.meta.url), "utf8");
const context = {};
vm.createContext(context);
vm.runInContext(source, context, { filename: "article-types.js" });
const articleTypes = context.LiteratureArticleTypes;

test("reads only namespaced Zotero tags and suppresses broader redundant types", () => {
  const labels = articleTypes.labelsFromTags([
    { tag: "project:test" },
    { tag: "AI4S:ArticleType:Article" },
    { tag: "AI4S:ArticleType:Review" },
    { tag: "AI4S:ArticleType:Systematic Review" },
    { tag: "AI4S:ArticleType:Meta-Analysis" },
  ]);
  assert.deepEqual(Array.from(labels), ["Systematic Review", "Meta-Analysis"]);
});

test("creates a stable sortable value and preserves unknown user-added types", () => {
  const value = articleTypes.columnValue([
    "AI4S:ArticleType:Novel Source Vocabulary",
    "AI4S:ArticleType:Clinical Trial, Phase III",
  ]);
  assert.deepEqual(
    Array.from(articleTypes.labelsFromColumnValue(value)),
    ["Clinical Trial, Phase III", "Novel Source Vocabulary"],
  );
  assert.equal(articleTypes.tone("Clinical Trial, Phase III"), "clinical");
  assert.deepEqual(Array.from(articleTypes.labelsFromColumnValue("bad")), []);
});
