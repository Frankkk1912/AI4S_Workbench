/* global Zotero, LiteratureMetricsPayload, LiteratureArticleTypes, LiteratureSemanticTags, LiteratureAiSummaries, LiteraturePriorities */

var LiteratureMetrics = (function () {
  "use strict";

  const PLUGIN_ID = "literature-metrics@frank-ai4s.local";
  const registeredColumns = new Map();
  let citationColumnKey = null;
  let publicationColumnKey = null;
  let articleTypeColumnKey = null;
  let agentTagsColumnKey = null;
  let aiSummaryColumnKey = null;
  let priorityColumnKey = null;
  let notifierID = null;
  let mainWindow = null;
  let priorityKeyHandler = null;
  let priorityMenuNode = null;
  let priorityMenuPopupHandler = null;
  let bulkPrioritySaving = false;
  let started = false;
  const pendingPriorityWrites = new Set();

  function log(message, level) {
    if (Zotero && Zotero.logError && level === "error") Zotero.logError(message);
    else if (Zotero && Zotero.debug) Zotero.debug("[literature-metrics] " + message);
  }

  function validYear(value) {
    return /^(?:19|20)\d{2}$/.test(String(value));
  }

  function metricFor(item, year) {
    try {
      return LiteratureMetricsPayload.getMetric(item.getField("extra"), year);
    }
    catch (_error) {
      return null;
    }
  }

  function citationFor(item) {
    try { return LiteratureMetricsPayload.getCitation(item.getField("extra")); }
    catch (_error) { return null; }
  }

  function renderTextCell(_index, data, column, _isFirstColumn, doc) {
    const cell = doc.createElement("span");
    cell.className = "cell " + column.className;
    cell.textContent = LiteratureMetricsPayload.displayFromIfColumnValue(data);
    return cell;
  }

  const IF_TONES = [
    { max: 5, label: "<5", background: "#EEF1F4", color: "#4B5563", border: "#D5DAE0" },
    { max: 10, label: "5–<10", background: "#E5EEF7", color: "#28577A", border: "#BED1E3" },
    { max: 20, label: "10–<20", background: "#DDF1EE", color: "#17685E", border: "#A9D9D1" },
    { max: 40, label: "20–<40", background: "#EAE7F4", color: "#57427C", border: "#CBC2E0" },
    { max: Infinity, label: "≥40", background: "#E8DFF0", color: "#673D73", border: "#CBB7D3" },
  ];
  const ZONE_TONES = {
    1: { background: "#DDF1EC", color: "#176B5B", border: "#A9D9CE" },
    2: { background: "#E3EEF8", color: "#285F8F", border: "#B8D0E5" },
    3: { background: "#F7EDD4", color: "#7A5A16", border: "#E5CF98" },
    4: { background: "#F8E4DF", color: "#8B3E2F", border: "#E4BDB3" },
  };

  function renderToneCell(data, column, doc, tone, title) {
    const cell = doc.createElement("span");
    cell.className = "cell " + column.className;
    cell.style.display = "flex";
    cell.style.alignItems = "center";
    const label = LiteratureMetricsPayload.displayFromColumnValue(data);
    if (!label || !tone) return cell;
    const chip = doc.createElement("span");
    chip.textContent = label;
    chip.title = title || label;
    chip.style.display = "inline-block";
    chip.style.padding = "1px 6px";
    chip.style.borderRadius = "3px";
    chip.style.fontSize = "0.92em";
    chip.style.lineHeight = "1.35";
    chip.style.whiteSpace = "nowrap";
    chip.style.backgroundColor = tone.background;
    chip.style.color = tone.color;
    chip.style.border = "1px solid " + tone.border;
    cell.appendChild(chip);
    return cell;
  }

  function renderIfCell(_index, data, column, _isFirstColumn, doc) {
    const display = LiteratureMetricsPayload.displayFromColumnValue(data);
    const value = Number(display);
    if (!Number.isFinite(value)) return renderToneCell("", column, doc, null, "");
    const tone = IF_TONES.find((candidate) => value < candidate.max);
    return renderToneCell(data, column, doc, tone, "IF " + display + " · " + tone.label);
  }

  function renderZoneCell(_index, data, column, _isFirstColumn, doc) {
    const display = LiteratureMetricsPayload.displayFromColumnValue(data);
    const match = display.match(/([1-4])/);
    const level = match ? Number(match[1]) : null;
    return renderToneCell(data, column, doc, ZONE_TONES[level], display);
  }

  function renderPublicationMetricsCell(_index, data, column, _isFirstColumn, doc) {
    const cell = doc.createElement("span");
    cell.className = "cell " + column.className;
    cell.style.display = "flex";
    cell.style.alignItems = "center";
    cell.style.flexWrap = "nowrap";
    cell.style.gap = "3px";
    cell.style.overflow = "hidden";
    cell.style.whiteSpace = "nowrap";
    const tones = {
      cas: { background: "#E6F0F2", color: "#1D5260", border: "#B8D4D9" },
      top: { background: "#EDE8F5", color: "#503C78", border: "#CFC2E3" },
      esi: { background: "#EBEFF5", color: "#344A67", border: "#CBD5E1" },
      index: { background: "#E8EDF7", color: "#314B7A", border: "#C3CEE4" },
    };
    const metrics = LiteratureMetricsPayload.publicationMetricsFromColumnValue(data);
    cell.title = metrics.map((metric) => metric.label).join(" · ");
    for (const metric of metrics) {
      const tone = tones[metric.tone] || tones.esi;
      const chip = doc.createElement("span");
      chip.textContent = metric.label;
      chip.style.display = "inline-block";
      chip.style.padding = "1px 6px";
      chip.style.borderRadius = "3px";
      chip.style.fontSize = "0.92em";
      chip.style.lineHeight = "1.35";
      chip.style.whiteSpace = "nowrap";
      chip.style.backgroundColor = tone.background;
      chip.style.color = tone.color;
      chip.style.border = "1px solid " + tone.border;
      cell.appendChild(chip);
    }
    return cell;
  }

  function renderArticleTypeCell(_index, data, column, _isFirstColumn, doc) {
    const cell = doc.createElement("span");
    cell.className = "cell " + column.className;
    cell.style.display = "flex";
    cell.style.alignItems = "center";
    cell.style.flexWrap = "nowrap";
    cell.style.gap = "3px";
    cell.style.overflow = "hidden";
    cell.style.whiteSpace = "nowrap";
    const tones = {
      review: { background: "#EAE7F4", color: "#57427C", border: "#CBC2E0" },
      clinical: { background: "#E3EEF8", color: "#285F8F", border: "#B8D0E5" },
      study: { background: "#DDF1EE", color: "#17685E", border: "#A9D9D1" },
      editorial: { background: "#F7EDD4", color: "#7A5A16", border: "#E5CF98" },
      alert: { background: "#F8E4DF", color: "#8B3E2F", border: "#E4BDB3" },
      preprint: { background: "#EEF1F4", color: "#4B5563", border: "#D5DAE0" },
      article: { background: "#EBEFF5", color: "#344A67", border: "#CBD5E1" },
    };
    const labels = LiteratureArticleTypes.labelsFromColumnValue(data);
    cell.title = labels.join(" · ");
    for (const label of labels.slice(0, 2)) {
      const tone = tones[LiteratureArticleTypes.tone(label)] || tones.article;
      const chip = doc.createElement("span");
      chip.textContent = label;
      chip.style.display = "inline-block";
      chip.style.padding = "1px 6px";
      chip.style.borderRadius = "3px";
      chip.style.fontSize = "0.92em";
      chip.style.lineHeight = "1.35";
      chip.style.whiteSpace = "nowrap";
      chip.style.backgroundColor = tone.background;
      chip.style.color = tone.color;
      chip.style.border = "1px solid " + tone.border;
      cell.appendChild(chip);
    }
    if (labels.length > 2) {
      const more = doc.createElement("span");
      more.textContent = "+" + (labels.length - 2);
      more.title = cell.title;
      cell.appendChild(more);
    }
    return cell;
  }

  function renderAgentTagsCell(_index, data, column, _isFirstColumn, doc) {
    const cell = doc.createElement("span");
    cell.className = "cell " + column.className;
    cell.style.display = "flex";
    cell.style.alignItems = "center";
    cell.style.flexWrap = "nowrap";
    cell.style.gap = "3px";
    cell.style.overflow = "hidden";
    cell.style.whiteSpace = "nowrap";
    const labels = LiteratureSemanticTags.labelsFromColumnValue(data);
    cell.title = labels.join(" · ");
    const tone = { background: "#E9EFF1", color: "#31545D", border: "#C5D4D8" };
    for (const label of labels.slice(0, 4)) {
      const chip = doc.createElement("span");
      chip.textContent = label;
      chip.style.display = "inline-block";
      chip.style.padding = "1px 6px";
      chip.style.borderRadius = "3px";
      chip.style.fontSize = "0.92em";
      chip.style.lineHeight = "1.35";
      chip.style.whiteSpace = "nowrap";
      chip.style.backgroundColor = tone.background;
      chip.style.color = tone.color;
      chip.style.border = "1px solid " + tone.border;
      cell.appendChild(chip);
    }
    if (labels.length > 4) {
      const more = doc.createElement("span");
      more.textContent = "+" + (labels.length - 4);
      more.title = cell.title;
      cell.appendChild(more);
    }
    return cell;
  }

  function renderAiSummaryCell(_index, data, column, _isFirstColumn, doc) {
    const cell = doc.createElement("span");
    cell.className = "cell " + column.className;
    cell.style.display = "flex";
    cell.style.alignItems = "center";
    cell.style.overflow = "hidden";
    const value = LiteratureAiSummaries.fromColumnValue(data);
    if (!value || !value.text) return cell;
    const chip = doc.createElement("span");
    chip.textContent = value.text;
    chip.title = value.stale ? "AI Summary 已过期：标题或摘要已变化，请显式刷新。\n" + value.text : value.text;
    chip.style.display = "block";
    chip.style.maxWidth = "100%";
    chip.style.overflow = "hidden";
    chip.style.textOverflow = "ellipsis";
    chip.style.whiteSpace = "nowrap";
    chip.style.padding = "1px 6px";
    chip.style.borderRadius = "3px";
    chip.style.fontSize = "0.92em";
    chip.style.lineHeight = "1.35";
    chip.style.backgroundColor = value.stale ? "#F7EDD4" : "#EEF1F4";
    chip.style.color = value.stale ? "#7A5A16" : "#3F4A54";
    chip.style.border = "1px solid " + (value.stale ? "#E5CF98" : "#D5DAE0");
    if (value.stale) chip.textContent = "⚠ " + value.text;
    cell.title = chip.title;
    cell.appendChild(chip);
    return cell;
  }

  async function setItemPriority(itemID, requestedLevel, toggleSame = true) {
    if (!Number.isInteger(itemID) || itemID <= 0 || ![0, 1, 2, 3].includes(requestedLevel)) {
      throw new Error("Priority write requires a valid item ID and level 0–3.");
    }
    const loaded = await Zotero.Items.getAsync([itemID]);
    const item = Array.isArray(loaded) ? loaded[0] : loaded;
    if (!item || !item.isRegularItem || !item.isRegularItem()) {
      throw new Error("Priority can only be set on a regular Zotero item.");
    }
    if (typeof item.isEditable === "function" && !item.isEditable()) {
      throw new Error("This Zotero item is read-only.");
    }

    const tags = item.getTags();
    const currentLevels = LiteraturePriorities.levelsFromTags(tags);
    const nextLevel = toggleSame && requestedLevel > 0 && currentLevels.length === 1 && currentLevels[0] === requestedLevel
      ? 0
      : requestedLevel;
    const retainedTags = tags.filter((entry) => {
      const tag = typeof entry === "string" ? entry : entry && entry.tag;
      return typeof tag !== "string" || !/^AI4S:Priority:[1-3]$/.test(tag);
    });
    item.setTags(nextLevel
      ? [...retainedTags, { tag: LiteraturePriorities.PREFIX + nextLevel }]
      : retainedTags);

    pendingPriorityWrites.add(itemID);
    try {
      await item.saveTx();
    }
    catch (error) {
      pendingPriorityWrites.delete(itemID);
      throw error;
    }
    return nextLevel;
  }

  function renderPriorityCell(_index, data, column, _isFirstColumn, doc) {
    const cell = doc.createElement("span");
    cell.className = "cell " + column.className;
    cell.style.display = "flex";
    cell.style.alignItems = "center";
    cell.style.gap = "1px";
    cell.style.whiteSpace = "nowrap";
    const priority = LiteraturePriorities.fromColumnValue(data);
    if (!priority) return cell;

    let savedLevel = priority.conflict ? 0 : (priority.levels[0] || 0);
    let previewLevel = savedLevel;
    let saving = false;
    const stars = [];

    cell.setAttribute("role", "group");
    cell.setAttribute("aria-label", "Priority star rating");
    cell.tabIndex = 0;
    cell.addEventListener("focus", () => {
      cell.style.outline = "1px solid #6B7280";
      cell.style.outlineOffset = "-1px";
      cell.style.borderRadius = "3px";
    });
    cell.addEventListener("blur", () => {
      cell.style.outline = "none";
      paint(savedLevel);
    });

    function tooltip(level) {
      const action = savedLevel === level ? "Click again to clear." : "Click to set.";
      return LiteraturePriorities.tooltip(level) + " " + action;
    }

    function paint(level, isPreview) {
      previewLevel = level;
      for (let index = 0; index < stars.length; index++) {
        const active = index < level;
        const star = stars[index];
        star.textContent = active ? "★" : "☆";
        star.style.color = active ? (isPreview ? "#FFB300" : "#F4A300") : "#9AA0A6";
        star.style.opacity = active ? "1" : "0.55";
        star.style.textShadow = active ? "0 0 1px rgba(180, 105, 0, 0.35)" : "none";
        star.setAttribute("aria-pressed", String(savedLevel === index + 1));
      }
    }

    async function commit(level, event) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      if (saving || !priority.itemID) return;
      saving = true;
      cell.style.opacity = "0.6";
      cell.style.pointerEvents = "none";
      try {
        savedLevel = await setItemPriority(priority.itemID, level, true);
        paint(savedLevel);
        cell.title = savedLevel
          ? LiteraturePriorities.tooltip(savedLevel)
          : "Priority cleared. Hover over a star to set it.";
      }
      catch (error) {
        paint(savedLevel);
        cell.title = "Could not update Priority: " + error;
        log("Could not update Priority for item " + priority.itemID + ": " + error, "error");
      }
      finally {
        saving = false;
        cell.style.opacity = "1";
        cell.style.pointerEvents = "auto";
      }
    }

    if (priority.conflict) {
      const warning = doc.createElement("span");
      warning.textContent = "⚠";
      warning.style.color = "#8B3E2F";
      warning.style.marginRight = "2px";
      warning.title = "Conflicting Priority tags: " + priority.levels.map((level) => LiteraturePriorities.PREFIX + level).join(", ") + ". Choose a star to replace them explicitly.";
      cell.appendChild(warning);
      cell.title = warning.title;
    }
    else {
      cell.title = savedLevel
        ? LiteraturePriorities.tooltip(savedLevel) + " Click the same star again to clear."
        : "No Priority. Hover over a star and click to set it.";
    }

    for (let level = 1; level <= 3; level++) {
      const star = doc.createElement("span");
      star.className = "priority-star";
      star.dataset.level = String(level);
      star.setAttribute("role", "button");
      star.setAttribute("aria-label", "Set Priority " + level + ": " + LiteraturePriorities.LABELS[level]);
      star.title = tooltip(level);
      star.tabIndex = -1;
      star.style.display = "inline-flex";
      star.style.alignItems = "center";
      star.style.justifyContent = "center";
      star.style.width = "20px";
      star.style.height = "20px";
      star.style.fontSize = "16px";
      star.style.lineHeight = "1";
      star.style.cursor = priority.itemID ? "pointer" : "default";
      const blockRowSelection = (event) => {
        event.preventDefault();
        event.stopPropagation();
      };
      // Zotero selects and redraws virtualized rows during the mouse sequence.
      // Keep star presses inside the rating control so the first click reaches
      // the star instead of being consumed by row selection.
      star.addEventListener("mousedown", blockRowSelection);
      star.addEventListener("mouseup", blockRowSelection);
      star.addEventListener("mouseenter", () => paint(level, true));
      star.addEventListener("click", async (event) => { await commit(level, event); });
      stars.push(star);
      cell.appendChild(star);
    }
    paint(savedLevel);
    cell.addEventListener("mouseleave", () => paint(savedLevel));
    cell.addEventListener("keydown", async (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowUp") {
        event.preventDefault();
        event.stopPropagation();
        paint(Math.min(3, previewLevel + 1));
      }
      else if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
        event.preventDefault();
        event.stopPropagation();
        paint(Math.max(1, previewLevel - 1));
      }
      else if (event.key === "Enter" || event.key === " ") {
        await commit(previewLevel || 1, event);
      }
      else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        paint(savedLevel);
      }
      else if (event.key === "Delete" || event.key === "Backspace") {
        if (savedLevel) await commit(savedLevel, event);
      }
    });
    return cell;
  }

  function isEditableTextTarget(target) {
    if (!target) return false;
    const name = String(target.localName || target.tagName || "").toLowerCase();
    if (["input", "textarea", "select", "textbox", "search-textbox"].includes(name)) return true;
    if (target.isContentEditable) return true;
    return Boolean(target.closest && target.closest("input, textarea, select, textbox, search-textbox, [contenteditable='true'], [contenteditable='']"));
  }

  function selectedRegularItems(win) {
    const pane = win && win.ZoteroPane;
    const items = pane && typeof pane.getSelectedItems === "function" ? pane.getSelectedItems() : [];
    return Array.isArray(items)
      ? items.filter((item) => item && item.isRegularItem && item.isRegularItem())
      : [];
  }

  function showBulkPriorityResult(level, summary) {
    const action = level ? "Set Priority to " + "★".repeat(level) : "Cleared Priority";
    const parts = [summary.updated + " updated"];
    if (summary.unchanged) parts.push(summary.unchanged + " unchanged");
    if (summary.skipped) parts.push(summary.skipped + " read-only skipped");
    if (summary.failed) parts.push(summary.failed + " failed");
    try {
      if (Zotero.ProgressWindow) {
        const popup = new Zotero.ProgressWindow();
        popup.changeHeadline("Literature Metrics · " + action);
        popup.addDescription(parts.join(" · "));
        popup.show();
        popup.startCloseTimer();
      }
    }
    catch (error) {
      log("Could not show bulk Priority result: " + error, "error");
    }
  }

  async function setPriorityForItems(items, level) {
    const summary = { updated: 0, unchanged: 0, skipped: 0, failed: 0 };
    if (bulkPrioritySaving || ![0, 1, 2, 3].includes(level)) return summary;
    bulkPrioritySaving = true;
    const seen = new Set();
    try {
      for (const item of Array.isArray(items) ? items : []) {
        if (!item || !item.isRegularItem || !item.isRegularItem() || !Number.isInteger(item.id) || seen.has(item.id)) continue;
        seen.add(item.id);
        if (typeof item.isEditable === "function" && !item.isEditable()) {
          summary.skipped += 1;
          continue;
        }
        const currentLevels = LiteraturePriorities.levelsFromTags(item.getTags());
        if ((level === 0 && currentLevels.length === 0) || (currentLevels.length === 1 && currentLevels[0] === level)) {
          summary.unchanged += 1;
          continue;
        }
        try {
          await setItemPriority(item.id, level, false);
          summary.updated += 1;
        }
        catch (error) {
          summary.failed += 1;
          log("Could not bulk-update Priority for item " + item.id + ": " + error, "error");
        }
      }
    }
    finally {
      bulkPrioritySaving = false;
    }
    showBulkPriorityResult(level, summary);
    return summary;
  }

  function registerPriorityShortcuts(win) {
    if (!win || !win.document || priorityKeyHandler) return;
    priorityKeyHandler = async (event) => {
      if (!event || !["0", "1", "2", "3"].includes(event.key) || event.repeat || event.isComposing) return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || isEditableTextTarget(event.target)) return;
      const tree = win.document.getElementById("zotero-items-tree");
      if (!tree || !(event.target === tree || (tree.contains && tree.contains(event.target)))) return;
      const items = selectedRegularItems(win);
      if (!items.length || bulkPrioritySaving) return;
      event.preventDefault();
      event.stopPropagation();
      await setPriorityForItems(items, Number(event.key));
    };
    win.document.addEventListener("keydown", priorityKeyHandler, true);
  }

  function registerPriorityMenu(win) {
    if (!win || !win.document || priorityMenuNode) return;
    const doc = win.document;
    const itemMenu = doc.getElementById("zotero-itemmenu");
    if (!itemMenu || !doc.createElementNS) return;
    const xul = "http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul";
    const menu = doc.createElementNS(xul, "menu");
    const popup = doc.createElementNS(xul, "menupopup");
    menu.id = "literature-metrics-priority-menu";
    menu.setAttribute("label", "Set Priority");
    menu.appendChild(popup);
    for (const option of [
      { level: 1, label: "★  Priority 1" },
      { level: 2, label: "★★  Priority 2" },
      { level: 3, label: "★★★  Priority 3" },
      { level: 0, label: "Clear Priority" },
    ]) {
      const item = doc.createElementNS(xul, "menuitem");
      item.setAttribute("label", option.label);
      item.addEventListener("command", async () => {
        await setPriorityForItems(selectedRegularItems(win), option.level);
      });
      popup.appendChild(item);
    }
    priorityMenuPopupHandler = () => {
      menu.hidden = selectedRegularItems(win).length === 0;
    };
    itemMenu.addEventListener("popupshowing", priorityMenuPopupHandler);
    itemMenu.appendChild(menu);
    priorityMenuNode = menu;
  }

  function registerYear(year) {
    if (!validYear(year) || registeredColumns.has(year) || !Zotero.ItemTreeManager) return;
    const keys = [];
    const definitions = [
      {
        kind: "if",
        label: "IF(" + year + ")",
        dataProvider: (item) => LiteratureMetricsPayload.ifColumnValue(metricFor(item, year)),
        renderCell: renderIfCell,
      },
      {
        kind: "if5",
        label: "5-Year IF(" + year + ")",
        dataProvider: (item) => LiteratureMetricsPayload.if5ColumnValue(metricFor(item, year)),
        renderCell: renderIfCell,
      },
      {
        kind: "jcr",
        label: "JCR(" + year + ")",
        dataProvider: (item) => LiteratureMetricsPayload.zoneColumnValue((metricFor(item, year) || {}).jcr_zone),
        renderCell: renderZoneCell,
      },
      {
        kind: "cas",
        label: "CAS(" + year + ")",
        dataProvider: (item) => LiteratureMetricsPayload.zoneColumnValue((metricFor(item, year) || {}).cas_zone),
        renderCell: renderZoneCell,
      },
    ];
    for (const definition of definitions) {
      const dataKey = Zotero.ItemTreeManager.registerColumn({
        dataKey: "metrics-" + definition.kind + "-" + year,
        label: definition.label,
        pluginID: PLUGIN_ID,
        enabledTreeIDs: ["main"],
        width: "90",
        minWidth: 64,
        showInColumnPicker: true,
        columnPickerSubMenu: true,
        dataProvider: definition.dataProvider,
        renderCell: definition.renderCell,
        zoteroPersist: ["width", "hidden", "sortDirection"],
      });
      if (dataKey) keys.push(dataKey);
    }
    if (keys.length) {
      registeredColumns.set(year, keys);
      Zotero.ItemTreeManager.refreshColumns();
    }
  }

  function registerYears(years) {
    for (const year of years) registerYear(String(year));
  }

  function unregisterYear(year) {
    const dataKeys = registeredColumns.get(String(year));
    if (!dataKeys || !Zotero.ItemTreeManager) return;
    for (const dataKey of dataKeys) Zotero.ItemTreeManager.unregisterColumn(dataKey);
    registeredColumns.delete(String(year));
    Zotero.ItemTreeManager.refreshColumns();
  }

  function syncRegisteredYears(years) {
    const desired = new Set([...years].map(String).filter(validYear));
    for (const year of [...registeredColumns.keys()]) {
      if (!desired.has(year)) unregisterYear(year);
    }
    registerYears([...desired]);
  }

  function registerCitationColumn() {
    if (citationColumnKey || !Zotero.ItemTreeManager) return;
    citationColumnKey = Zotero.ItemTreeManager.registerColumn({
      dataKey: "citation-count",
      label: "Citations",
      pluginID: PLUGIN_ID,
      enabledTreeIDs: ["main"],
      width: "90",
      minWidth: 64,
      showInColumnPicker: true,
      columnPickerSubMenu: true,
      dataProvider: (item) => LiteratureMetricsPayload.citationColumnValue(citationFor(item)),
      renderCell: renderTextCell,
      zoteroPersist: ["width", "hidden", "sortDirection"],
    });
    Zotero.ItemTreeManager.refreshColumns();
  }

  function registerPublicationMetricsColumn() {
    if (publicationColumnKey || !Zotero.ItemTreeManager) return;
    publicationColumnKey = Zotero.ItemTreeManager.registerColumn({
      dataKey: "publication-metrics",
      label: "Journal Metrics",
      pluginID: PLUGIN_ID,
      enabledTreeIDs: ["main"],
      width: "260",
      minWidth: 150,
      showInColumnPicker: true,
      columnPickerSubMenu: true,
      dataProvider: (item) => LiteratureMetricsPayload.publicationMetricsColumnValue(
        LiteratureMetricsPayload.latestPublicationMetrics(item.getField("extra"))
      ),
      renderCell: renderPublicationMetricsCell,
      zoteroPersist: ["width", "hidden", "sortDirection"],
    });
    Zotero.ItemTreeManager.refreshColumns();
  }

  function registerArticleTypeColumn() {
    if (articleTypeColumnKey || !Zotero.ItemTreeManager) return;
    articleTypeColumnKey = Zotero.ItemTreeManager.registerColumn({
      dataKey: "article-type",
      label: "Article Type",
      pluginID: PLUGIN_ID,
      enabledTreeIDs: ["main"],
      width: "220",
      minWidth: 120,
      showInColumnPicker: true,
      columnPickerSubMenu: true,
      dataProvider: (item) => LiteratureArticleTypes.columnValue(item.getTags()),
      renderCell: renderArticleTypeCell,
      zoteroPersist: ["width", "hidden", "sortDirection"],
    });
    Zotero.ItemTreeManager.refreshColumns();
  }

  function registerPriorityColumn() {
    if (priorityColumnKey || !Zotero.ItemTreeManager) return;
    priorityColumnKey = Zotero.ItemTreeManager.registerColumn({
      dataKey: "priority",
      label: "Priority",
      pluginID: PLUGIN_ID,
      enabledTreeIDs: ["main"],
      width: "105",
      minWidth: 76,
      showInColumnPicker: true,
      columnPickerSubMenu: true,
      dataProvider: (item) => LiteraturePriorities.columnValue(item.getTags(), item.id),
      renderCell: renderPriorityCell,
      zoteroPersist: ["width", "hidden", "sortDirection"],
    });
    Zotero.ItemTreeManager.refreshColumns();
  }

  function registerAgentTagsColumn() {
    if (agentTagsColumnKey || !Zotero.ItemTreeManager) return;
    agentTagsColumnKey = Zotero.ItemTreeManager.registerColumn({
      dataKey: "agent-tags",
      label: "Agent Tags",
      pluginID: PLUGIN_ID,
      enabledTreeIDs: ["main"],
      width: "300",
      minWidth: 150,
      showInColumnPicker: true,
      columnPickerSubMenu: true,
      dataProvider: (item) => LiteratureSemanticTags.columnValue(item.getTags()),
      renderCell: renderAgentTagsCell,
      zoteroPersist: ["width", "hidden", "sortDirection"],
    });
    Zotero.ItemTreeManager.refreshColumns();
  }

  function registerAiSummaryColumn() {
    if (aiSummaryColumnKey || !Zotero.ItemTreeManager) return;
    aiSummaryColumnKey = Zotero.ItemTreeManager.registerColumn({
      dataKey: "ai-summary",
      label: "AI Summary",
      pluginID: PLUGIN_ID,
      enabledTreeIDs: ["main"],
      width: "420",
      minWidth: 180,
      showInColumnPicker: true,
      columnPickerSubMenu: true,
      dataProvider: (item) => LiteratureAiSummaries.columnValue(
        item.getField("extra"), item.getField("title"), item.getField("abstractNote")
      ),
      renderCell: renderAiSummaryCell,
      zoteroPersist: ["width", "hidden", "sortDirection"],
    });
    Zotero.ItemTreeManager.refreshColumns();
  }

  async function discoverYearsFromItems(ids) {
    if (!ids || !ids.length) return;
    try {
      const items = await Zotero.Items.getAsync(ids);
      const years = new Set();
      for (const item of items) {
        if (!item || !item.isRegularItem || !item.isRegularItem()) continue;
        for (const year of LiteratureMetricsPayload.years(item.getField("extra"))) years.add(year);
      }
      registerYears([...years]);
    }
    catch (error) {
      log("Could not discover metric years: " + error, "error");
    }
  }

  async function discoverYearsFromLibrary() {
    try {
      const itemIDs = new Set();
      for (const library of Zotero.Libraries.getAll()) {
        const search = new Zotero.Search();
        search.libraryID = library.libraryID;
        search.addCondition("extra", "contains", LiteratureMetricsPayload.PREFIX);
        for (const itemID of await search.search()) itemIDs.add(itemID);
      }
      const items = await Zotero.Items.getAsync([...itemIDs]);
      const years = new Set();
      for (const item of items) {
        if (!item || !item.isRegularItem || !item.isRegularItem()) continue;
        for (const year of LiteratureMetricsPayload.years(item.getField("extra"))) years.add(year);
      }
      syncRegisteredYears(years);
    }
    catch (error) {
      log("Could not scan existing AI4S metric years: " + error, "error");
    }
  }

  async function start() {
    if (started) return;
    if (!Zotero.ItemTreeManager) throw new Error("Zotero ItemTreeManager is unavailable; Zotero 7+ is required.");
    started = true;
    // Register only years that actually occur in managed payloads. Retrieval
    // year must never create a metric-year column by itself.
    registerCitationColumn();
    registerPublicationMetricsColumn();
    registerArticleTypeColumn();
    registerAgentTagsColumn();
    registerAiSummaryColumn();
    registerPriorityColumn();
    mainWindow = Zotero.getMainWindow ? Zotero.getMainWindow() : null;
    registerPriorityShortcuts(mainWindow);
    registerPriorityMenu(mainWindow);
    notifierID = Zotero.Notifier.registerObserver({
      notify: async (action, type, ids) => {
        if (type !== "item") return;
        if (action === "add") await discoverYearsFromItems(ids);
        else if (action === "modify" || action === "delete" || action === "trash") {
          if (action === "modify" && ids.length && ids.every((id) => pendingPriorityWrites.has(id))) {
            for (const id of ids) pendingPriorityWrites.delete(id);
            return;
          }
          // A modified/deleted item may have contained the final payload for a
          // year. Rescan managed items so obsolete year columns are removed.
          await discoverYearsFromLibrary();
        }
      },
    }, ["item"], "literature-metrics");
    // Search only the managed Extra prefix, so all historical metric years get
    // a column on startup without parsing unrelated library records.
    await discoverYearsFromLibrary();
    log("Registered metrics columns for years " + [...registeredColumns.keys()].join(", "));
  }

  async function stop() {
    if (mainWindow && mainWindow.document && priorityKeyHandler) {
      mainWindow.document.removeEventListener("keydown", priorityKeyHandler, true);
    }
    if (priorityMenuNode && priorityMenuNode.parentNode && priorityMenuPopupHandler) {
      priorityMenuNode.parentNode.removeEventListener("popupshowing", priorityMenuPopupHandler);
    }
    if (priorityMenuNode && typeof priorityMenuNode.remove === "function") priorityMenuNode.remove();
    priorityKeyHandler = null;
    priorityMenuNode = null;
    priorityMenuPopupHandler = null;
    mainWindow = null;
    bulkPrioritySaving = false;
    if (notifierID !== null) {
      Zotero.Notifier.unregisterObserver(notifierID);
      notifierID = null;
    }
    for (const dataKeys of registeredColumns.values()) {
      for (const dataKey of dataKeys) Zotero.ItemTreeManager.unregisterColumn(dataKey);
    }
    if (citationColumnKey) Zotero.ItemTreeManager.unregisterColumn(citationColumnKey);
    if (publicationColumnKey) Zotero.ItemTreeManager.unregisterColumn(publicationColumnKey);
    if (articleTypeColumnKey) Zotero.ItemTreeManager.unregisterColumn(articleTypeColumnKey);
    if (agentTagsColumnKey) Zotero.ItemTreeManager.unregisterColumn(agentTagsColumnKey);
    if (aiSummaryColumnKey) Zotero.ItemTreeManager.unregisterColumn(aiSummaryColumnKey);
    if (priorityColumnKey) Zotero.ItemTreeManager.unregisterColumn(priorityColumnKey);
    citationColumnKey = null;
    publicationColumnKey = null;
    articleTypeColumnKey = null;
    agentTagsColumnKey = null;
    aiSummaryColumnKey = null;
    priorityColumnKey = null;
    pendingPriorityWrites.clear();
    registeredColumns.clear();
    if (Zotero.ItemTreeManager) Zotero.ItemTreeManager.refreshColumns();
    started = false;
  }

  return Object.freeze({ start, stop });
})();
