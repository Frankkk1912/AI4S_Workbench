import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/priorities.js", import.meta.url), "utf8");
const context = {};
vm.createContext(context);
vm.runInContext(source, context, { filename: "priorities.js" });
const priorities = context.LiteraturePriorities;

test("reads one valid namespaced priority and ignores unrelated or malformed tags", () => {
  assert.deepEqual(Array.from(priorities.levelsFromTags([
    { tag: "AI4S:Priority:3" }, { tag: "project:test" }, { tag: "AI4S:Priority:4" },
  ])), [3]);
  const parsed = priorities.fromColumnValue(priorities.columnValue([{ tag: "AI4S:Priority:3" }]));
  assert.equal(parsed.conflict, false);
  assert.deepEqual(Array.from(parsed.levels), [3]);
  assert.match(priorities.tooltip(3), /not evidence quality/);
});

test("surfaces conflicting user priority tags instead of silently choosing one", () => {
  const parsed = priorities.fromColumnValue(priorities.columnValue([
    "AI4S:Priority:1", "AI4S:Priority:3",
  ]));
  assert.equal(parsed.conflict, true);
  assert.deepEqual(Array.from(parsed.levels), [3, 1]);
});

test("carries a stable item ID even when an item has no priority yet", () => {
  const parsed = priorities.fromColumnValue(priorities.columnValue([], 42));
  assert.equal(parsed.itemID, 42);
  assert.equal(parsed.conflict, false);
  assert.deepEqual(Array.from(parsed.levels), []);
  assert.equal(priorities.columnValue([]), "");
});
