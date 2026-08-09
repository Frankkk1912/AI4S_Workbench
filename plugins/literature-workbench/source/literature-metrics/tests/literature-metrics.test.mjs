import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const payloadSource = readFileSync(new URL("../src/metrics-payload.js", import.meta.url), "utf8");
const articleTypesSource = readFileSync(new URL("../src/article-types.js", import.meta.url), "utf8");
const semanticTagsSource = readFileSync(new URL("../src/semantic-tags.js", import.meta.url), "utf8");
const aiSummariesSource = readFileSync(new URL("../src/ai-summaries.js", import.meta.url), "utf8");
const prioritiesSource = readFileSync(new URL("../src/priorities.js", import.meta.url), "utf8");
const addOnSource = readFileSync(new URL("../src/literature-metrics.js", import.meta.url), "utf8");

function extra(year, publicationMetrics = []) {
  return `AI4S-Metrics: ${JSON.stringify({
    schema_version: 2,
    by_year: {
      [year]: {
        impact_factor: 10,
        publication_metrics: publicationMetrics.length ? publicationMetrics : undefined,
      },
    },
  })}`;
}

function createElement() {
  return {
    style: {},
    dataset: {},
    attributes: {},
    listeners: {},
    children: [],
    appendChild(child) { this.children.push(child); },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    addEventListener(type, listener) { this.listeners[type] = listener; },
    async dispatch(type, values = {}) {
      const event = {
        key: values.key,
        defaultPrevented: false,
        propagationStopped: false,
        preventDefault() { this.defaultPrevented = true; },
        stopPropagation() { this.propagationStopped = true; },
      };
      this.lastEvent = event;
      await this.listeners[type]?.(event);
      return event;
    },
  };
}

test("removes obsolete year columns and renders Journal Metrics on one line", async () => {
  const definitions = new Map();
  const unregistered = [];
  let observer;
  let saves = 0;
  const itemExtra = new Map([[1, extra("2025")], [2, extra("2026")]]);
  const itemTitles = new Map([[1, "Macrophage states"], [2, "Second paper"]]);
  const itemAbstracts = new Map([[1, "Single-cell analysis of macrophage states."], [2, "Second abstract."]]);
  const itemTags = new Map([
    [1, [{ tag: "AI4S:ArticleType:Systematic Review" }, { tag: "AI4S:ArticleType:Meta-Analysis" }, { tag: "AI4S:Semantic:Macrophage" }, { tag: "AI4S:Semantic:Single-cell transcriptomics" }, { tag: "project:test" }, { tag: "AI4S:Priority:3" }]],
    [2, []],
  ]);
  const item = (id) => ({
    id,
    isRegularItem: () => true,
    isEditable: () => true,
    getField: (field) => field === "extra" ? itemExtra.get(id)
      : field === "title" ? itemTitles.get(id) : field === "abstractNote" ? itemAbstracts.get(id) : "",
    getTags: () => itemTags.get(id),
    setTags: (tags) => itemTags.set(id, tags),
    saveTx: async () => { saves += 1; },
  });
  const Zotero = {
    ItemTreeManager: {
      registerColumn(definition) {
        definitions.set(definition.dataKey, definition);
        return definition.dataKey;
      },
      unregisterColumn(dataKey) {
        unregistered.push(dataKey);
        definitions.delete(dataKey);
      },
      refreshColumns() {},
    },
    Libraries: { getAll: () => [{ libraryID: 1 }] },
    Search: function Search() {
      this.addCondition = () => {};
      this.search = async () => [...itemExtra.keys()];
    },
    Items: { getAsync: async (ids) => ids.map(item) },
    Notifier: {
      registerObserver(value) { observer = value; return 1; },
      unregisterObserver() {},
    },
    debug() {},
    logError(error) { throw error; },
  };
  const context = { Zotero };
  vm.createContext(context);
  vm.runInContext(payloadSource, context, { filename: "metrics-payload.js" });
  vm.runInContext(articleTypesSource, context, { filename: "article-types.js" });
  vm.runInContext(semanticTagsSource, context, { filename: "semantic-tags.js" });
  vm.runInContext(aiSummariesSource, context, { filename: "ai-summaries.js" });
  vm.runInContext(prioritiesSource, context, { filename: "priorities.js" });
  vm.runInContext(addOnSource, context, { filename: "literature-metrics.js" });

  await context.LiteratureMetrics.start();
  assert.ok(definitions.has("metrics-if-2025"));
  assert.ok(definitions.has("metrics-if-2026"));
  assert.equal(definitions.get("publication-metrics").label, "Journal Metrics");
  assert.equal(definitions.get("article-type").label, "Article Type");
  assert.equal(definitions.get("agent-tags").label, "Agent Tags");
  assert.equal(definitions.get("ai-summary").label, "AI Summary");
  assert.equal(definitions.get("priority").label, "Priority");

  const priorityColumn = definitions.get("priority");
  const priorityValue = priorityColumn.dataProvider(item(1));
  const priorityCell = priorityColumn.renderCell(0, priorityValue, { className: "priority" }, false, { createElement });
  assert.deepEqual(priorityCell.children.map((child) => child.textContent), ["★", "★", "★"]);
  assert.equal(priorityCell.children[0].style.color, "#F4A300");
  assert.match(priorityCell.title, /not evidence quality/);

  await priorityCell.children[0].dispatch("mouseenter");
  assert.deepEqual(priorityCell.children.map((child) => child.textContent), ["★", "☆", "☆"]);
  assert.equal(priorityCell.children[0].style.color, "#FFB300");
  await priorityCell.dispatch("mouseleave");
  assert.deepEqual(priorityCell.children.map((child) => child.textContent), ["★", "★", "★"]);
  assert.equal(priorityCell.children[0].style.color, "#F4A300");

  const mouseDown = await priorityCell.children[1].dispatch("mousedown");
  assert.equal(mouseDown.defaultPrevented, true);
  assert.equal(mouseDown.propagationStopped, true);

  await priorityCell.children[1].dispatch("click");
  assert.equal(saves, 1);
  assert.deepEqual(Array.from(itemTags.get(1), ({ tag }) => tag), [
    "AI4S:ArticleType:Systematic Review",
    "AI4S:ArticleType:Meta-Analysis",
    "AI4S:Semantic:Macrophage",
    "AI4S:Semantic:Single-cell transcriptomics",
    "project:test",
    "AI4S:Priority:2",
  ]);
  assert.deepEqual(priorityCell.children.map((child) => child.textContent), ["★", "★", "☆"]);

  await priorityCell.children[1].dispatch("click");
  assert.equal(saves, 2);
  assert.deepEqual(Array.from(itemTags.get(1), ({ tag }) => tag), [
    "AI4S:ArticleType:Systematic Review",
    "AI4S:ArticleType:Meta-Analysis",
    "AI4S:Semantic:Macrophage",
    "AI4S:Semantic:Single-cell transcriptomics",
    "project:test",
  ]);
  assert.deepEqual(priorityCell.children.map((child) => child.textContent), ["☆", "☆", "☆"]);

  const emptyPriorityValue = priorityColumn.dataProvider(item(2));
  const emptyPriorityCell = priorityColumn.renderCell(1, emptyPriorityValue, { className: "priority" }, false, { createElement });
  await emptyPriorityCell.dispatch("keydown", { key: "ArrowRight" });
  await emptyPriorityCell.dispatch("keydown", { key: "ArrowRight" });
  assert.deepEqual(emptyPriorityCell.children.map((child) => child.textContent), ["★", "★", "☆"]);
  await emptyPriorityCell.dispatch("keydown", { key: "Enter" });
  assert.deepEqual(Array.from(itemTags.get(2), ({ tag }) => tag), ["AI4S:Priority:2"]);
  await observer.notify("modify", "item", [2]);

  itemTags.set(2, [{ tag: "project:conflict" }, { tag: "AI4S:Priority:1" }, { tag: "AI4S:Priority:3" }]);
  const conflictValue = priorityColumn.dataProvider(item(2));
  const conflictCell = priorityColumn.renderCell(1, conflictValue, { className: "priority" }, false, { createElement });
  assert.equal(conflictCell.children[0].textContent, "⚠");
  await conflictCell.children[2].dispatch("click");
  assert.deepEqual(Array.from(itemTags.get(2), ({ tag }) => tag), ["project:conflict", "AI4S:Priority:2"]);
  await observer.notify("modify", "item", [2]);

  const articleColumn = definitions.get("article-type");
  const articleValue = articleColumn.dataProvider(item(1));
  const articleCell = articleColumn.renderCell(0, articleValue, { className: "article-type" }, false, {
    createElement() {
      return { style: {}, appendChild(child) { (this.children ||= []).push(child); } };
    },
  });
  assert.equal(articleCell.title, "Systematic Review · Meta-Analysis");
  assert.deepEqual(articleCell.children.map((child) => child.textContent), ["Systematic Review", "Meta-Analysis"]);

  const agentTagsColumn = definitions.get("agent-tags");
  const agentTagsValue = agentTagsColumn.dataProvider(item(1));
  const agentTagsCell = agentTagsColumn.renderCell(0, agentTagsValue, { className: "agent-tags" }, false, { createElement });
  assert.equal(agentTagsCell.title, "Macrophage · Single-cell transcriptomics");
  assert.deepEqual(agentTagsCell.children.map((child) => child.textContent), ["Macrophage", "Single-cell transcriptomics"]);

  const titleHash = context.LiteratureAiSummaries.sha256(itemTitles.get(1));
  const abstractHash = context.LiteratureAiSummaries.sha256(itemAbstracts.get(1));
  itemExtra.set(1, `${extra("2025")}\nAI4S-Summary: ${JSON.stringify({
    schema_version: 1, text: "该研究利用单细胞分析刻画巨噬细胞状态。", language: "zh-CN", basis: "title-abstract",
    title_sha256: titleHash, abstract_sha256: abstractHash, generated_at: "2026-07-21T00:00:00Z",
  })}`);
  const aiSummaryColumn = definitions.get("ai-summary");
  const aiSummaryValue = aiSummaryColumn.dataProvider(item(1));
  const aiSummaryCell = aiSummaryColumn.renderCell(0, aiSummaryValue, { className: "ai-summary" }, false, { createElement });
  assert.equal(aiSummaryCell.children[0].textContent, "该研究利用单细胞分析刻画巨噬细胞状态。");
  assert.equal(aiSummaryCell.title, "该研究利用单细胞分析刻画巨噬细胞状态。");
  itemTitles.set(1, "Changed macrophage title");
  const staleValue = aiSummaryColumn.dataProvider(item(1));
  const staleCell = aiSummaryColumn.renderCell(0, staleValue, { className: "ai-summary" }, false, { createElement });
  assert.match(staleCell.children[0].textContent, /^⚠ /);
  assert.match(staleCell.title, /已过期/);

  itemExtra.set(2, extra("2025"));
  await observer.notify("modify", "item", [2]);
  assert.ok(unregistered.includes("metrics-if-2026"));
  assert.ok(unregistered.includes("metrics-if5-2026"));
  assert.ok(unregistered.includes("metrics-jcr-2026"));
  assert.ok(unregistered.includes("metrics-cas-2026"));
  assert.ok(definitions.has("metrics-if-2025"));

  const column = definitions.get("publication-metrics");
  const doc = { createElement };
  const value = context.LiteratureMetricsPayload.publicationMetricsColumnValue({
    year: "2025",
    metrics: [{ code: "cas_major", value: "生物学1区" }, { code: "cas_top", value: true }],
  });
  const cell = column.renderCell(0, value, { className: "journal-metrics" }, false, doc);
  assert.equal(cell.style.flexWrap, "nowrap");
  assert.equal(cell.title, "生物学1区 · TOP");
  assert.deepEqual(cell.children.map((child) => child.textContent), ["生物学1区", "TOP"]);

  const ifColumn = definitions.get("metrics-if-2025");
  const ifColors = [4.99, 5, 10, 20, 40].map((number) => {
    const ifCell = ifColumn.renderCell(
      0,
      context.LiteratureMetricsPayload.ifColumnValue({ impact_factor: number }),
      { className: "if" },
      false,
      doc,
    );
    return ifCell.children[0].style.backgroundColor;
  });
  assert.equal(new Set(ifColors).size, 5);

  const jcrColumn = definitions.get("metrics-jcr-2025");
  const q1 = jcrColumn.renderCell(0, context.LiteratureMetricsPayload.zoneColumnValue("Q1"), { className: "jcr" }, false, doc);
  const q4 = jcrColumn.renderCell(0, context.LiteratureMetricsPayload.zoneColumnValue("Q4"), { className: "jcr" }, false, doc);
  assert.equal(q1.children[0].textContent, "Q1");
  assert.notEqual(q1.children[0].style.backgroundColor, q4.children[0].style.backgroundColor);
});
