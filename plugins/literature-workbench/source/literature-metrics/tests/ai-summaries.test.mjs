import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/ai-summaries.js", import.meta.url), "utf8");
const context = {};
vm.createContext(context);
vm.runInContext(source, context, { filename: "ai-summaries.js" });
const summaries = context.LiteratureAiSummaries;

function hash(value) {
  const normalized = String(value).normalize("NFKC").replace(/\s+/gu, " ").trim();
  return createHash("sha256").update(normalized, "utf8").digest("hex");
}

function extra(title, abstractNote, text = "该研究概括了标题和摘要明确支持的核心内容。") {
  return `Human note\nAI4S-Summary: ${JSON.stringify({
    schema_version: 1, text, language: "zh-CN", basis: "title-abstract",
    title_sha256: hash(title), abstract_sha256: hash(abstractNote), generated_at: "2026-07-21T00:00:00Z",
  })}`;
}

test("implements the same normalized SHA-256 contract as the MCP", () => {
  for (const value of ["abc", "  多行\n中文  文本 ", "single-cell α"])
    assert.equal(summaries.sha256(value), hash(value));
});

test("reads one valid managed block and detects stale title or abstract", () => {
  const title = "Paper title";
  const abstractNote = "Paper abstract.";
  assert.deepEqual(
    { ...summaries.summary(extra(title, abstractNote), title, abstractNote) },
    {
      text: "该研究概括了标题和摘要明确支持的核心内容。",
      language: "zh-CN", stale: false, generatedAt: "2026-07-21T00:00:00Z",
    },
  );
  assert.equal(summaries.summary(extra(title, abstractNote), `${title} changed`, abstractNote).stale, true);
});

test("column values sort by visible text and retain a stale flag", () => {
  const value = summaries.columnValue(extra("T", "A", "一句话总结。"), "T", "A");
  assert.equal(value.startsWith("一句话总结。"), true);
  assert.deepEqual({ ...summaries.fromColumnValue(value) }, { text: "一句话总结。", stale: false });
  const stale = summaries.columnValue(extra("T", "A", "一句话总结。"), "T changed", "A");
  assert.deepEqual({ ...summaries.fromColumnValue(stale) }, { text: "一句话总结。", stale: true });
});

test("corrupt or duplicate managed blocks render empty", () => {
  assert.equal(summaries.columnValue("AI4S-Summary: bad-json", "T", "A"), "");
  assert.equal(summaries.columnValue("AI4S-Summary: {}\nAI4S-Summary: {}", "T", "A"), "");
});
