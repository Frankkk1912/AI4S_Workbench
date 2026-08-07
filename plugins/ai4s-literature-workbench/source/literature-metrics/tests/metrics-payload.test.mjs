import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/metrics-payload.js", import.meta.url), "utf8");
const context = {};
vm.createContext(context);
vm.runInContext(source, context, { filename: "metrics-payload.js" });
const payload = context.LiteratureMetricsPayload;

test("reads valid per-year AI4S metrics without reading unrelated Extra text", () => {
  const extra = [
    "PMID: 12345678",
    'AI4S-Metrics: {"schema_version":2,"by_year":{"2025":{"impact_factor":12.4,"impact_factor_5y":13.1,"jcr_zone":"Q1","cas_zone":"1区","publication_metrics":[{"code":"cas_major","value":"医学1区"},{"code":"cas_top","value":true},{"code":"esi_category","value":"临床医学"}],"retrieved_at":"2026-07-16","source_label":"reviewed-2025","source_sha256":"abc"},"2027":{"impact_factor":13.1,"jcr_zone":"Q2"}}}',
    "Human note: preserve this line",
  ].join("\n");
  assert.deepEqual(Array.from(payload.years(extra)), ["2025", "2027"]);
  assert.equal(payload.getMetric(extra, "2025").impact_factor, 12.4);
  assert.equal(payload.getMetric(extra, "2025").impact_factor_5y, 13.1);
  assert.equal(payload.getMetric(extra, "2027").jcr_zone, "Q2");
});

test("renders typed publication metrics from the latest available semantic year", () => {
  const extra = 'AI4S-Metrics: {"schema_version":2,"by_year":{"2025":{"impact_factor":9.2,"publication_metrics":[{"code":"cas_major","value":"医学1区"},{"code":"cas_top","value":true},{"code":"esi_category","value":"临床医学"},{"code":"indexing","value":"EI"}]},"2026":{"impact_factor":10}}}';
  const latest = payload.latestPublicationMetrics(extra);
  assert.equal(latest.year, "2025");
  const value = payload.publicationMetricsColumnValue(latest);
  assert.deepEqual(Array.from(payload.publicationMetricsFromColumnValue(value), (entry) => entry.label), [
    "医学1区", "TOP", "ESI 临床医学", "EI",
  ]);
});

test("rejects duplicate or malformed managed blocks safely", () => {
  assert.equal(payload.parseExtra('AI4S-Metrics: {"schema_version":2,"by_year":{}}').error, "invalid-ai4s-metrics-schema");
  assert.equal(payload.parseExtra("AI4S-Metrics: {}\nAI4S-Metrics: {}").error, "multiple-ai4s-metrics-blocks");
  assert.equal(payload.getMetric("unmanaged text", "2026"), null);
});

test("uses a lexical value that preserves numeric IF ordering", () => {
  const low = payload.ifColumnValue({ impact_factor: 9.9 });
  const high = payload.ifColumnValue({ impact_factor: 100 });
  assert.ok(low < high);
  assert.equal(payload.displayFromIfColumnValue(high), "100");
  assert.equal(payload.ifColumnValue({}), "");
  assert.ok(payload.if5ColumnValue({ impact_factor_5y: 10.1 }) > payload.if5ColumnValue({ impact_factor_5y: 4.8 }));
});

test("encodes JCR and CAS zones for best-first descending order", () => {
  assert.ok(payload.zoneColumnValue("Q1") > payload.zoneColumnValue("Q4"));
  assert.ok(payload.zoneColumnValue("1区") > payload.zoneColumnValue("4区"));
  assert.equal(payload.displayFromColumnValue(payload.zoneColumnValue("Q2")), "Q2");
  assert.equal(payload.zoneColumnValue("unknown"), "");
});

test("reads a Semantic Scholar citation snapshot and preserves numeric ordering", () => {
  const extra = 'AI4S-Metrics: {"schema_version":2,"by_year":{},"citation":{"latest":{"citation_count":128,"provider":"semantic-scholar","retrieved_at":"2026-07-13","source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}}';
  assert.equal(payload.getCitation(extra).citation_count, 128);
  assert.ok(payload.citationColumnValue({ citation_count: 128 }) > payload.citationColumnValue({ citation_count: 9 }));
});
