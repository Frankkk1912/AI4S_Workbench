/*
 * Read-only presentation helpers for Agent-managed Zotero tags:
 * AI4S:Semantic:<canonical English label>
 */

var LiteratureSemanticTags = (function () {
  "use strict";

  const PREFIX = "AI4S:Semantic:";

  function labelsFromTags(tags) {
    if (!Array.isArray(tags)) return [];
    const labels = new Map();
    for (const entry of tags) {
      const tag = typeof entry === "string" ? entry : entry && entry.tag;
      if (typeof tag !== "string" || !tag.startsWith(PREFIX)) continue;
      const label = tag.slice(PREFIX.length).replace(/\s+/g, " ").trim();
      if (!label) continue;
      const key = label.normalize("NFKC").toLocaleLowerCase("en-US");
      if (!labels.has(key)) labels.set(key, label);
    }
    return [...labels.values()].sort((left, right) => left.localeCompare(right, "en"));
  }

  function columnValue(tags) {
    const labels = labelsFromTags(tags);
    return labels.length ? JSON.stringify(labels) : "";
  }

  function labelsFromColumnValue(value) {
    if (typeof value !== "string" || !value) return [];
    try {
      const labels = JSON.parse(value);
      return Array.isArray(labels) && labels.every((label) => typeof label === "string") ? labels : [];
    }
    catch (_error) { return []; }
  }

  return Object.freeze({ PREFIX, labelsFromTags, columnValue, labelsFromColumnValue });
})();
