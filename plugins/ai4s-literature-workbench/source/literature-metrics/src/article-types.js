/*
 * Parser/presentation helpers for namespaced Zotero tags such as:
 * AI4S:ArticleType:Systematic Review
 *
 * Tags are the canonical Zotero-side value so users can filter and edit them
 * with Zotero's native tag UI. This module only creates sortable column values.
 */

var LiteratureArticleTypes = (function () {
  "use strict";

  const PREFIX = "AI4S:ArticleType:";
  const ORDER = [
    "Systematic Review", "Meta-Analysis", "Review",
    "Randomized Controlled Trial", "Controlled Clinical Trial",
    "Pragmatic Clinical Trial", "Adaptive Clinical Trial",
    "Clinical Trial, Phase IV", "Clinical Trial, Phase III",
    "Clinical Trial, Phase II", "Clinical Trial, Phase I",
    "Clinical Trial", "Clinical Study", "Observational Study",
    "Multicenter Study", "Comparative Study", "Evaluation Study",
    "Validation Study", "Case Report", "Guideline", "Practice Guideline",
    "Consensus Statement", "Editorial", "Letter", "Comment",
    "Meeting Abstract", "Conference Paper", "Correction",
    "Retraction Notice", "Retracted Publication", "Expression of Concern",
    "Preprint", "Article", "News",
  ];
  const RANK = new Map(ORDER.map((label, index) => [label, index]));

  function labelsFromTags(tags) {
    if (!Array.isArray(tags)) return [];
    const labels = [];
    for (const entry of tags) {
      const tag = typeof entry === "string" ? entry : entry && entry.tag;
      if (typeof tag !== "string" || !tag.startsWith(PREFIX)) continue;
      const label = tag.slice(PREFIX.length).trim();
      if (label && !labels.includes(label)) labels.push(label);
    }
    if (labels.includes("Systematic Review") && labels.includes("Review")) {
      labels.splice(labels.indexOf("Review"), 1);
    }
    if (labels.length > 1 && labels.includes("Article")) {
      labels.splice(labels.indexOf("Article"), 1);
    }
    return labels.sort((left, right) => {
      const leftRank = RANK.has(left) ? RANK.get(left) : 999;
      const rightRank = RANK.has(right) ? RANK.get(right) : 999;
      return leftRank - rightRank || left.localeCompare(right);
    });
  }

  function columnValue(tags) {
    const labels = labelsFromTags(tags);
    if (!labels.length) return "";
    const rank = RANK.has(labels[0]) ? RANK.get(labels[0]) : 999;
    // Zotero compares custom column data lexically. A larger hidden key means
    // a more specific/high-priority type when sorting descending.
    return String(999 - rank).padStart(3, "0") + "|" + JSON.stringify(labels);
  }

  function labelsFromColumnValue(value) {
    if (typeof value !== "string") return [];
    const separator = value.indexOf("|");
    if (separator === -1) return [];
    try {
      const labels = JSON.parse(value.slice(separator + 1));
      return Array.isArray(labels) && labels.every((label) => typeof label === "string") ? labels : [];
    }
    catch (_error) { return []; }
  }

  function tone(label) {
    if (/review|meta-analysis/i.test(label)) return "review";
    if (/clinical trial/i.test(label)) return "clinical";
    if (/study|case report/i.test(label)) return "study";
    if (/retract|correction|expression of concern/i.test(label)) return "alert";
    if (/editorial|letter|comment|guideline|consensus/i.test(label)) return "editorial";
    if (/preprint|meeting abstract|conference/i.test(label)) return "preprint";
    return "article";
  }

  return Object.freeze({ PREFIX, labelsFromTags, columnValue, labelsFromColumnValue, tone });
})();
