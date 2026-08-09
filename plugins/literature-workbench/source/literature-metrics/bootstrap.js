/*
 * Literature Metrics, Article Type, Agent Tags, AI Summary, and Priority bootstrap entrypoint.
 *
 * Metrics and article-type data remain read-only. The only direct write path
 * is an explicit user action through the Priority star control, scoped number
 * shortcut, or item context menu; these replace only AI4S:Priority:1|2|3 tags.
 * The add-on never fetches journal data.
 */

var { Services } = ChromeUtils.importESModule("resource://gre/modules/Services.sys.mjs");
var LiteratureMetricsRuntime = null;

async function startup(data) {
  await Zotero.initializationPromise;
  const scope = {
    Zotero,
    rootURI: data.rootURI,
  };
  Services.scriptloader.loadSubScript(data.rootURI + "src/metrics-payload.js", scope);
  Services.scriptloader.loadSubScript(data.rootURI + "src/article-types.js", scope);
  Services.scriptloader.loadSubScript(data.rootURI + "src/semantic-tags.js", scope);
  Services.scriptloader.loadSubScript(data.rootURI + "src/ai-summaries.js", scope);
  Services.scriptloader.loadSubScript(data.rootURI + "src/priorities.js", scope);
  Services.scriptloader.loadSubScript(data.rootURI + "src/literature-metrics.js", scope);
  LiteratureMetricsRuntime = scope.LiteratureMetrics;
  await LiteratureMetricsRuntime.start({ id: data.id, version: data.version, rootURI: data.rootURI });
}

async function shutdown() {
  if (LiteratureMetricsRuntime) {
    await LiteratureMetricsRuntime.stop();
    LiteratureMetricsRuntime = null;
  }
}

function install() {}

function uninstall() {}
