import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const payloadSource = readFileSync(new URL("../src/metrics-payload.js", import.meta.url), "utf8");
const articleTypesSource = readFileSync(new URL("../src/article-types.js", import.meta.url), "utf8");
const prioritiesSource = readFileSync(new URL("../src/priorities.js", import.meta.url), "utf8");
const addOnSource = readFileSync(new URL("../src/literature-metrics.js", import.meta.url), "utf8");

function node(localName = "div") {
  return {
    localName,
    attributes: {},
    children: [],
    listeners: {},
    appendChild(child) { child.parentNode = this; this.children.push(child); },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); },
    removeEventListener(type, listener) {
      this.listeners[type] = (this.listeners[type] || []).filter((candidate) => candidate !== listener);
    },
    async dispatch(type, event = {}) {
      for (const listener of this.listeners[type] || []) await listener(event);
    },
    remove() {
      this.removed = true;
      if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    },
  };
}

function keyEvent(key, target, overrides = {}) {
  return {
    key,
    target,
    repeat: false,
    isComposing: false,
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    defaultPrevented: false,
    propagationStopped: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.propagationStopped = true; },
    ...overrides,
  };
}

test("bulk Priority shortcuts and context menu update only selected regular editable items", async () => {
  const definitions = new Map();
  const documentListeners = {};
  const itemMenu = node("menupopup");
  const treeTarget = node("div");
  treeTarget.closest = () => null;
  const itemTree = node("div");
  itemTree.contains = (target) => target === treeTarget;
  const document = {
    getElementById(id) {
      if (id === "zotero-items-tree") return itemTree;
      if (id === "zotero-itemmenu") return itemMenu;
      return null;
    },
    createElementNS(_namespace, name) { return node(name); },
    addEventListener(type, listener) { documentListeners[type] = listener; },
    removeEventListener(type, listener) {
      if (documentListeners[type] === listener) delete documentListeners[type];
    },
  };

  let saves = 0;
  const tags = new Map([
    [1, [{ tag: "project:a" }, { tag: "AI4S:Priority:1" }]],
    [2, [{ tag: "project:b" }, { tag: "AI4S:Priority:2" }]],
    [3, [{ tag: "attachment-tag" }]],
    [4, [{ tag: "AI4S:Priority:1" }]],
  ]);
  const items = new Map();
  const makeItem = (id, { regular = true, editable = true } = {}) => ({
    id,
    isRegularItem: () => regular,
    isEditable: () => editable,
    getField: () => "",
    getTags: () => tags.get(id),
    setTags: (next) => tags.set(id, next),
    saveTx: async () => { saves += 1; },
  });
  items.set(1, makeItem(1));
  items.set(2, makeItem(2));
  items.set(3, makeItem(3, { regular: false }));
  items.set(4, makeItem(4, { editable: false }));
  let selected = [...items.values()];
  const progress = [];
  const mainWindow = {
    document,
    ZoteroPane: { getSelectedItems: () => selected },
  };
  const Zotero = {
    ItemTreeManager: {
      registerColumn(definition) { definitions.set(definition.dataKey, definition); return definition.dataKey; },
      unregisterColumn() {},
      refreshColumns() {},
    },
    Libraries: { getAll: () => [] },
    Search: function Search() { this.addCondition = () => {}; this.search = async () => []; },
    Items: { getAsync: async (ids) => ids.map((id) => items.get(id)) },
    Notifier: { registerObserver: () => 1, unregisterObserver() {} },
    getMainWindow: () => mainWindow,
    ProgressWindow: function ProgressWindow() {
      const record = {};
      progress.push(record);
      this.changeHeadline = (value) => { record.headline = value; };
      this.addDescription = (value) => { record.description = value; };
      this.show = () => { record.shown = true; };
      this.startCloseTimer = () => { record.closeTimer = true; };
    },
    debug() {},
    logError() {},
  };
  const context = { Zotero };
  vm.createContext(context);
  vm.runInContext(payloadSource, context, { filename: "metrics-payload.js" });
  vm.runInContext(articleTypesSource, context, { filename: "article-types.js" });
  vm.runInContext(prioritiesSource, context, { filename: "priorities.js" });
  vm.runInContext(addOnSource, context, { filename: "literature-metrics.js" });

  await context.LiteratureMetrics.start();
  assert.equal(typeof documentListeners.keydown, "function");
  assert.equal(itemMenu.children[0].attributes.label, "Set Priority");

  const setThree = keyEvent("3", treeTarget);
  await documentListeners.keydown(setThree);
  assert.equal(setThree.defaultPrevented, true);
  assert.equal(setThree.propagationStopped, true);
  assert.deepEqual(Array.from(tags.get(1), ({ tag }) => tag), ["project:a", "AI4S:Priority:3"]);
  assert.deepEqual(Array.from(tags.get(2), ({ tag }) => tag), ["project:b", "AI4S:Priority:3"]);
  assert.deepEqual(Array.from(tags.get(4), ({ tag }) => tag), ["AI4S:Priority:1"]);
  assert.equal(saves, 2);
  assert.match(progress.at(-1).description, /2 updated/);
  assert.match(progress.at(-1).description, /1 read-only skipped/);

  await documentListeners.keydown(keyEvent("3", treeTarget));
  assert.equal(saves, 2);
  assert.match(progress.at(-1).description, /2 unchanged/);

  const input = node("input");
  await documentListeners.keydown(keyEvent("1", input));
  await documentListeners.keydown(keyEvent("1", treeTarget, { repeat: true }));
  await documentListeners.keydown(keyEvent("1", treeTarget, { metaKey: true }));
  assert.equal(saves, 2);

  await documentListeners.keydown(keyEvent("0", treeTarget));
  assert.deepEqual(Array.from(tags.get(1), ({ tag }) => tag), ["project:a"]);
  assert.deepEqual(Array.from(tags.get(2), ({ tag }) => tag), ["project:b"]);
  assert.equal(saves, 4);

  selected = [items.get(1), items.get(2)];
  const menuPopup = itemMenu.children[0].children[0];
  await menuPopup.children[1].dispatch("command");
  assert.deepEqual(Array.from(tags.get(1), ({ tag }) => tag), ["project:a", "AI4S:Priority:2"]);
  assert.deepEqual(Array.from(tags.get(2), ({ tag }) => tag), ["project:b", "AI4S:Priority:2"]);
  assert.equal(saves, 6);

  await context.LiteratureMetrics.stop();
  assert.equal(documentListeners.keydown, undefined);
  assert.equal(itemMenu.children.length, 0);
  assert.deepEqual(itemMenu.listeners.popupshowing, []);
});
