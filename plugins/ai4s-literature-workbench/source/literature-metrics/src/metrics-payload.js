/* global Zotero */
/*
 * Shared parser for the managed, single-line Extra block:
 *
 * AI4S-Metrics: {"schema_version":2,"by_year":{"2026":{...}}}
 *
 * It is intentionally self-contained so Zotero can load it with loadSubScript
 * and Node can evaluate it in unit tests without a build dependency.
 */

var LiteratureMetricsPayload = (function () {
  "use strict";

  const PREFIX = "AI4S-Metrics:";
  const SCHEMA_VERSION = 2;
  const YEAR_RE = /^(?:19|20)\d{2}$/;
  const PUBLICATION_METRIC_CODES = new Set(["cas_major", "cas_top", "esi_category", "indexing"]);

  function isPlainObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function normalizeMetric(value) {
    if (!isPlainObject(value)) return null;
    const metric = {};
    if (value.impact_factor !== undefined && value.impact_factor !== null && value.impact_factor !== "") {
      const impactFactor = Number(value.impact_factor);
      if (!Number.isFinite(impactFactor) || impactFactor < 0) return null;
      metric.impact_factor = impactFactor;
    }
    if (value.impact_factor_5y !== undefined && value.impact_factor_5y !== null && value.impact_factor_5y !== "") {
      const impactFactor5y = Number(value.impact_factor_5y);
      if (!Number.isFinite(impactFactor5y) || impactFactor5y < 0) return null;
      metric.impact_factor_5y = impactFactor5y;
    }
    for (const key of ["jcr_zone", "cas_zone", "source_label", "source_sha256"]) {
      if (typeof value[key] === "string" && value[key].trim()) metric[key] = value[key].trim();
    }
    if (value.retrieved_at !== undefined) {
      if (typeof value.retrieved_at !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.retrieved_at)) return null;
      metric.retrieved_at = value.retrieved_at;
    }
    if (value.publication_metrics !== undefined) {
      if (!Array.isArray(value.publication_metrics) || !value.publication_metrics.length) return null;
      const seen = new Set();
      metric.publication_metrics = [];
      for (const raw of value.publication_metrics) {
        if (!isPlainObject(raw) || !PUBLICATION_METRIC_CODES.has(raw.code)) return null;
        const validValue = raw.code === "cas_top"
          ? raw.value === true
          : typeof raw.value === "string" && raw.value.trim();
        if (!validValue) return null;
        const normalized = { code: raw.code, value: raw.code === "cas_top" ? true : raw.value.trim() };
        const identity = normalized.code + ":" + String(normalized.value);
        if (!seen.has(identity)) {
          seen.add(identity);
          metric.publication_metrics.push(normalized);
        }
      }
    }
    return Object.keys(metric).length ? metric : null;
  }

  function normalizeCitation(value) {
    if (!isPlainObject(value)) return null;
    const count = Number(value.citation_count);
    if (!Number.isInteger(count) || count < 0 || value.provider !== "semantic-scholar") return null;
    if (typeof value.retrieved_at !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.retrieved_at)) return null;
    const citation = { citation_count: count, provider: value.provider, retrieved_at: value.retrieved_at };
    if (typeof value.source_sha256 === "string" && /^[0-9a-f]{64}$/.test(value.source_sha256)) citation.source_sha256 = value.source_sha256;
    return citation;
  }

  function normalizePayload(value) {
    if (!isPlainObject(value) || value.schema_version !== SCHEMA_VERSION || !isPlainObject(value.by_year)) {
      return null;
    }
    const byYear = {};
    for (const [year, rawMetric] of Object.entries(value.by_year)) {
      if (!YEAR_RE.test(year)) return null;
      const metric = normalizeMetric(rawMetric);
      if (!metric) return null;
      byYear[year] = metric;
    }
    const citation = value.citation ? normalizeCitation(value.citation.latest || value.citation) : null;
    if (!Object.keys(byYear).length && !citation) return null;
    const payload = { schema_version: SCHEMA_VERSION, by_year: byYear };
    if (citation) payload.citation = { latest: citation };
    return payload;
  }

  function parseExtra(extra) {
    const text = typeof extra === "string" ? extra : "";
    const lines = text.split(/\r?\n/);
    const indexes = [];
    for (let index = 0; index < lines.length; index++) {
      if (lines[index].startsWith(PREFIX)) indexes.push(index);
    }
    if (!indexes.length) return { payload: null, error: null };
    if (indexes.length > 1) return { payload: null, error: "multiple-ai4s-metrics-blocks" };
    const jsonText = lines[indexes[0]].slice(PREFIX.length).trim();
    try {
      const payload = normalizePayload(JSON.parse(jsonText));
      return payload ? { payload, error: null } : { payload: null, error: "invalid-ai4s-metrics-schema" };
    }
    catch (_error) {
      return { payload: null, error: "invalid-ai4s-metrics-json" };
    }
  }

  function getMetric(extra, year) {
    const parsed = parseExtra(extra);
    if (!parsed.payload || !YEAR_RE.test(String(year))) return null;
    return parsed.payload.by_year[String(year)] || null;
  }

  function years(extra) {
    const parsed = parseExtra(extra);
    return parsed.payload ? Object.keys(parsed.payload.by_year).sort() : [];
  }

  function getCitation(extra) {
    const parsed = parseExtra(extra);
    return parsed.payload?.citation?.latest || null;
  }

  function latestPublicationMetrics(extra) {
    const parsed = parseExtra(extra);
    if (!parsed.payload) return null;
    const orderedYears = Object.keys(parsed.payload.by_year).sort().reverse();
    for (const year of orderedYears) {
      const metrics = parsed.payload.by_year[year].publication_metrics;
      if (Array.isArray(metrics) && metrics.length) return { year, metrics };
    }
    return null;
  }

  // Zotero's custom-column comparator is lexical. The fixed-width numeric
  // prefix makes lexical IF ordering numerically correct; renderCell displays
  // only the human-readable suffix after the separator.
  function ifSortValue(impactFactor) {
    if (!Number.isFinite(impactFactor) || impactFactor < 0) return "";
    return impactFactor.toFixed(6).padStart(20, "0");
  }

  function ifColumnValue(metric) {
    if (!metric || !Number.isFinite(metric.impact_factor)) return "";
    const display = String(metric.impact_factor);
    return ifSortValue(metric.impact_factor) + "|" + display;
  }

  function if5ColumnValue(metric) {
    if (!metric || !Number.isFinite(metric.impact_factor_5y)) return "";
    const display = String(metric.impact_factor_5y);
    return ifSortValue(metric.impact_factor_5y) + "|" + display;
  }

  // JCR/CAS are ordinal rather than nominal categories. Encode the best
  // partition with the largest hidden key so descending sort is Q1/1区 first.
  function zoneColumnValue(zone) {
    const display = typeof zone === "string" ? zone.trim() : "";
    const match = display.match(/^(?:Q)?([1-4])(?:区)?$/i);
    if (!match) return "";
    return String(5 - Number(match[1])) + "|" + display;
  }

  function publicationMetricPresentation(metric) {
    if (!metric || !PUBLICATION_METRIC_CODES.has(metric.code)) return null;
    if (metric.code === "cas_major") return { label: String(metric.value), tone: "cas" };
    if (metric.code === "cas_top") return { label: "TOP", tone: "top" };
    if (metric.code === "esi_category") return { label: "ESI " + metric.value, tone: "esi" };
    if (metric.code === "indexing") return { label: String(metric.value), tone: "index" };
    return null;
  }

  function publicationMetricsColumnValue(latest) {
    if (!latest || !YEAR_RE.test(String(latest.year)) || !Array.isArray(latest.metrics) || !latest.metrics.length) return "";
    return String(latest.year) + "|" + JSON.stringify(latest.metrics);
  }

  function publicationMetricsFromColumnValue(value) {
    if (typeof value !== "string") return [];
    const separator = value.indexOf("|");
    if (separator === -1) return [];
    try {
      const raw = JSON.parse(value.slice(separator + 1));
      if (!Array.isArray(raw)) return [];
      return raw.map(publicationMetricPresentation).filter(Boolean);
    }
    catch (_error) { return []; }
  }

  function citationColumnValue(citation) {
    if (!citation || !Number.isInteger(citation.citation_count) || citation.citation_count < 0) return "";
    return String(citation.citation_count).padStart(20, "0") + "|" + String(citation.citation_count);
  }

  function displayFromColumnValue(value) {
    if (typeof value !== "string") return "";
    const separator = value.indexOf("|");
    return separator === -1 ? "" : value.slice(separator + 1);
  }

  function displayFromIfColumnValue(value) {
    return displayFromColumnValue(value);
  }

  return Object.freeze({
    PREFIX,
    SCHEMA_VERSION,
    parseExtra,
    getMetric,
    getCitation,
    latestPublicationMetrics,
    years,
    ifSortValue,
    ifColumnValue,
    if5ColumnValue,
    zoneColumnValue,
    publicationMetricPresentation,
    publicationMetricsColumnValue,
    publicationMetricsFromColumnValue,
    citationColumnValue,
    displayFromColumnValue,
    displayFromIfColumnValue,
  });
})();
