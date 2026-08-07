/*
 * Parser/presentation helpers for user-owned Zotero priority tags:
 * AI4S:Priority:1, AI4S:Priority:2, AI4S:Priority:3.
 *
 * Priority means personal reading/use priority, not evidence quality.
 */

var LiteraturePriorities = (function () {
  "use strict";

  const PREFIX = "AI4S:Priority:";
  const LABELS = {
    1: "Background / supporting",
    2: "Important",
    3: "Core / must-read",
  };

  function levelsFromTags(tags) {
    if (!Array.isArray(tags)) return [];
    const levels = [];
    for (const entry of tags) {
      const tag = typeof entry === "string" ? entry : entry && entry.tag;
      const match = typeof tag === "string" ? tag.match(/^AI4S:Priority:([1-3])$/) : null;
      const level = match ? Number(match[1]) : null;
      if (level && !levels.includes(level)) levels.push(level);
    }
    return levels.sort((left, right) => right - left);
  }

  function columnValue(tags, itemID) {
    const levels = levelsFromTags(tags);
    const validItemID = Number.isInteger(itemID) && itemID > 0 ? itemID : null;
    if (!levels.length && !validItemID) return "";
    const conflict = levels.length > 1;
    const sortLevel = conflict ? 9 : (levels[0] || 0);
    return String(sortLevel) + "|" + JSON.stringify({
      conflict,
      levels,
      ...(validItemID ? { itemID: validItemID } : {}),
    });
  }

  function fromColumnValue(value) {
    if (typeof value !== "string") return null;
    const separator = value.indexOf("|");
    if (separator === -1) return null;
    try {
      const parsed = JSON.parse(value.slice(separator + 1));
      if (!parsed || !Array.isArray(parsed.levels) || !parsed.levels.every((level) => [1, 2, 3].includes(level))) return null;
      if (parsed.itemID !== undefined && (!Number.isInteger(parsed.itemID) || parsed.itemID <= 0)) return null;
      return {
        conflict: parsed.conflict === true,
        levels: parsed.levels,
        ...(parsed.itemID ? { itemID: parsed.itemID } : {}),
      };
    }
    catch (_error) { return null; }
  }

  function tooltip(level) {
    return "Priority: " + LABELS[level] + ". Personal reading and use priority; not evidence quality.";
  }

  return Object.freeze({ PREFIX, LABELS, levelsFromTags, columnValue, fromColumnValue, tooltip });
})();
