#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const DEFAULT_WIDTH = 1080;
const DEFAULT_HEIGHT = 1620;

const SUPPORTED_TEMPLATES = [
  "method-primer",
  "mechanism-map",
  "myth-vs-fact",
  "paper-digest",
  "workflow-map",
  "comparison-matrix",
];

const RECIPE_CONTRACTS = {
  "method-primer": {},
  "mechanism-map": { minModules: 5, requiredRoles: ["claim", "caveat"] },
  "myth-vs-fact": { minModules: 5, requiredRoles: ["myth", "fact"] },
  "paper-digest": { minModules: 5, requiredRoles: ["finding", "design", "evidence", "limit", "takeaway"] },
  "workflow-map": { minModules: 5, requiredRoles: ["step"] },
  "comparison-matrix": { minModules: 4, requiredRoles: ["option", "decision"] },
};

function supportedTemplateList() {
  return SUPPORTED_TEMPLATES.join(", ");
}

function normalizeTemplate(specOrName) {
  const value = typeof specOrName === "string"
    ? specOrName
    : specOrName?.template ?? (Array.isArray(specOrName?.columns) ? "method-primer" : "method-primer");
  if (!SUPPORTED_TEMPLATES.includes(value)) {
    fail(`Unsupported template "${value}". Supported templates: ${supportedTemplateList()}`);
  }
  return value;
}

function parseArgs(argv) {
  const command = argv[2];
  const args = { _: [] };
  for (let i = 3; i < argv.length; i += 1) {
    const token = argv[i];
    if (token.startsWith("--")) {
      const key = token.slice(2);
      const next = argv[i + 1];
      if (!next || next.startsWith("--")) {
        args[key] = true;
      } else {
        args[key] = next;
        i += 1;
      }
    } else {
      args._.push(token);
    }
  }
  return { command, args };
}

function usage() {
  return `Usage:
  node render_onepager.mjs sample --template method-primer --output input.json
  node render_onepager.mjs render --spec input.json --output-dir out --width 1080 --height 1620
  node render_onepager.mjs check --html out/onepager.html`;
}

function fail(message) {
  console.error(`Error: ${message}`);
  process.exit(1);
}

function requireArg(args, name) {
  const value = args[name];
  if (!value || value === true) fail(`Missing required --${name}\n${usage()}`);
  return value;
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(path.resolve(filePath)), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("\n", " ");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function hasNonEmptyArray(value) {
  return Array.isArray(value) && value.length > 0;
}

function hasSourceMetadata(value) {
  const hasExplicitSource = ["source", "sourceNote", "dataSource"].some((key) => {
    const field = value?.[key];
    return Array.isArray(field) ? field.length > 0 : Boolean(field);
  });
  if (hasExplicitSource) return true;
  const provenance = value?.provenance;
  if (Array.isArray(provenance)) return provenance.length > 0;
  return Boolean(provenance) && typeof provenance === "object" && Object.keys(provenance).length > 0;
}

function themeOf(spec) {
  return {
    accent: "#d93612",
    accent2: "#f06a00",
    ink: "#16120f",
    muted: "#70655d",
    paper: "#fffaf2",
    panel: "#fffdf8",
    line: "#efc9a7",
    blue: "#2f67a6",
    olive: "#8e8b73",
    fontBody: '"Source Han Sans SC", "Noto Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", "SimSun", sans-serif',
    fontSans: '"Source Han Sans SC", "Noto Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", Arial, sans-serif',
    ...spec.theme,
  };
}

function methodPrimerSampleSpec() {
  return {
    title: "Mastering PCA in Metabolomics & Lipidomics",
    subtitle: "A Chemometrics Guide to Biological Insights",
    brand: {
      name: "Behind the Feature Table",
      tagline: "Methods that turn omics tables into decisions",
      mark: "omics-grid",
    },
    footer: {
      left: "Behind the Feature Table",
      center: "Follow & connect",
      right: "Read more: example.org",
    },
    theme: {
      accent: "#d93612",
      accent2: "#f06a00",
      ink: "#14120f",
      paper: "#fffaf2",
      line: "#efc9a7",
    },
    columns: [
      {
        number: "1",
        title: "The Core Functions",
        sections: [
          {
            number: "1.1",
            heading: "Dimensionality Reduction",
            body: "Condense high-dimensional omics data into a few orthogonal components that capture the dominant variance structure.",
            note: "Schematic",
            visual: { type: "simple-diagram", labels: ["3D feature space", "2D PCA map"] },
          },
          {
            number: "1.2",
            heading: "Quality Control",
            body: "Detect outliers, batch effects, and analytical drift before biological interpretation.",
            note: "Schematic T2 monitoring",
            visual: { type: "ellipse-outlier" },
          },
          {
            number: "1.3",
            heading: "Unsupervised Discovery",
            body: "Reveal natural groupings and metabolic signatures without prior class labels.",
            visual: { type: "scatter" },
          },
        ],
      },
      {
        number: "2",
        title: "The Interpretation",
        sections: [
          {
            number: "2.1",
            heading: "Score Plots",
            body: "Visualize sample relationships and clustering in the space of principal components.",
            visual: { type: "scatter", xLabel: "PC1 (34.7%)", yLabel: "PC2 (19.4%)" },
          },
          {
            number: "2.2",
            heading: "Loading Plots",
            body: "Identify variables that drive separation and contribute most to each component.",
            note: "Arrow length indicates contribution strength.",
            visual: { type: "loading-plot" },
          },
          {
            number: "2.3",
            heading: "Hotelling's T2 Ellipse",
            body: "Define multivariate statistical boundaries to flag potential outliers.",
            visual: { type: "ellipse-outlier" },
          },
        ],
      },
      {
        number: "3",
        title: "The Scaling Toolbox",
        sections: [
          {
            number: "3.1",
            heading: "Pareto Scaling",
            body: "Balances large and small abundances without making noise dominate the model.",
            note: "Omics favorite",
            visual: { type: "bars-before-after" },
          },
          {
            number: "3.2",
            heading: "Autoscaling",
            body: "Centers and scales variables to equal variance, giving each variable similar weight.",
            note: "Unit variance",
            visual: { type: "distribution-before-after", mode: "variance" },
          },
          {
            number: "3.3",
            heading: "Log Transformation",
            body: "Reduces right-skewness and stabilizes variance for more interpretable omics data.",
            note: "e.g., log10",
            visual: { type: "distribution-before-after", mode: "skew" },
          },
        ],
      },
    ],
  };
}

function legacyColumnsFromModules(modules) {
  const columnCount = Math.min(3, Math.max(1, modules.length));
  return Array.from({ length: columnCount }, (_, columnIndex) => {
    const start = Math.floor((columnIndex * modules.length) / columnCount);
    const end = Math.floor(((columnIndex + 1) * modules.length) / columnCount);
    const columnModules = modules.slice(start, end);
    return {
      number: String(columnIndex + 1),
      title: columnModules[0]?.heading ?? `Part ${columnIndex + 1}`,
      sections: columnModules.map((module, sectionIndex) => ({
        number: `${columnIndex + 1}.${sectionIndex + 1}`,
        heading: module.heading,
        body: module.body,
        note: module.role,
        visual: { type: "simple-diagram", labels: [module.role, "Schematic"] },
      })),
    };
  });
}

function withLegacyColumnFallback(spec) {
  return {
    ...spec,
    columns: legacyColumnsFromModules(spec.modules ?? []),
  };
}

function mechanismMapSampleSpec() {
  const modules = [
    { role: "claim", heading: "核心结论", body: "炎症不是单个开关，而是一串局部信号把神经末梢推向更容易放电的状态。" },
    { role: "step", heading: "1 组织受损", body: "细胞释放危险信号，免疫细胞进入局部环境。" },
    { role: "step", heading: "2 因子升高", body: "前列腺素、IL-1β、TNF-α 等信号改变神经末梢阈值。" },
    { role: "step", heading: "3 神经敏化", body: "同样刺激更容易被解释成疼痛，范围和持续时间都可能扩大。" },
    { role: "caveat", heading: "不要过度推断", body: "这张图是机制示意，不代表某个患者的真实炎症水平或疼痛强度。" }
  ];
  return withLegacyColumnFallback({
    template: "mechanism-map",
    language: "zh-CN",
    audience: "public-science",
    claimType: "schematic-only",
    title: "炎症因子为什么会放大疼痛？",
    subtitle: "从组织损伤到神经敏化的一条因果链",
    brand: { name: "科学一图流", tagline: "机制先讲清，再谈结论" },
    footer: { left: "Schematic", center: "机制解释", right: "非临床诊断建议" },
    modules,
  });
}

function mythVsFactSampleSpec() {
  const modules = [
    { role: "myth", heading: "误区", body: "条带更黑，就说明蛋白表达一定更高。" },
    { role: "fact", heading: "现实", body: "曝光饱和后，灰度不再和蛋白量线性对应，黑条带可能只是过曝。" },
    { role: "evidence", heading: "正确读法", body: "确认曝光在线性范围内，再做归一化和重复统计。" },
    { role: "avoid", heading: "别这样", body: "只截一张最黑的图就下结论。" },
    { role: "do", heading: "应该这样", body: "保留原图、曝光梯度、内参和独立重复。" }
  ];
  return withLegacyColumnFallback({
    template: "myth-vs-fact",
    language: "zh-CN",
    audience: "beginner",
    claimType: "schematic-only",
    title: "WB 条带不是越黑越好",
    subtitle: "先看线性范围，再谈表达变化",
    brand: { name: "实验结果怎么读", tagline: "把常见误区拆开" },
    footer: { left: "Schematic", center: "Western blot", right: "需要原始灰度验证" },
    modules,
  });
}

function paperDigestSampleSpec() {
  const modules = [
    { role: "finding", heading: "一句话发现", body: "作者提出一个可解释的分子特征，能够区分两类疾病状态。" },
    { role: "design", heading: "研究设计", body: "队列数据训练，独立数据验证，再用机制实验解释可能来源。" },
    { role: "evidence", heading: "关键证据", body: "模型性能、特征稳定性、机制扰动结果共同支持主张。" },
    { role: "limit", heading: "局限", body: "样本来源和平台差异会影响外推，不能直接等同临床诊断。" },
    { role: "takeaway", heading: "怎么用", body: "把它当成候选机制线索，而不是已经落地的检测工具。" }
  ];
  return withLegacyColumnFallback({
    template: "paper-digest",
    language: "zh-CN",
    audience: "researcher",
    claimType: "schematic-only",
    title: "这篇论文真正回答了什么？",
    subtitle: "把发现、证据和局限拆成一张图",
    brand: { name: "Paper Digest", tagline: "读结论，也读证据链" },
    footer: { left: "Paper reading", center: "Evidence map", right: "示例内容" },
    modules,
  });
}

function workflowMapSampleSpec() {
  const modules = [
    { role: "step", heading: "1 质控", body: "先过滤低质量细胞和异常线粒体比例。" },
    { role: "step", heading: "2 归一化", body: "让测序深度差异不主导后续聚类。" },
    { role: "step", heading: "3 降维聚类", body: "UMAP 用来展示结构，不是单独的细胞类型证明。" },
    { role: "step", heading: "4 标记基因", body: "用 marker 组合判断，而不是只看一个基因。" },
    { role: "checkpoint", heading: "5 生物学复核", body: "把注释结果和组织来源、实验条件、文献知识对齐。" }
  ];
  return withLegacyColumnFallback({
    template: "workflow-map",
    language: "zh-CN",
    audience: "beginner",
    claimType: "schematic-only",
    title: "从 FASTQ 到细胞类型注释",
    subtitle: "单细胞分析最容易漏看的 5 个检查点",
    brand: { name: "分析流程图", tagline: "每一步都有风险" },
    footer: { left: "Workflow", center: "scRNA-seq", right: "示意流程" },
    modules,
  });
}

function comparisonMatrixSampleSpec() {
  const modules = [
    { role: "option", heading: "同一靶点同一流程", body: "可以作为粗筛排序线索，但仍需看构象和相互作用。" },
    { role: "option", heading: "跨靶点比较", body: "风险很高，打分函数和口袋环境差异会放大误读。" },
    { role: "option", heading: "跨软件比较", body: "通常不能直接横向比较，需要统一流程和验证集。" },
    { role: "decision", heading: "结论", body: "把 docking 分数当成假设生成工具，不当成亲和力测量。" }
  ];
  return withLegacyColumnFallback({
    template: "comparison-matrix",
    language: "zh-CN",
    audience: "researcher",
    claimType: "schematic-only",
    title: "Docking 分数能不能比较亲和力？",
    subtitle: "先分清筛选排序和定量结论",
    brand: { name: "结构分析怎么读", tagline: "分数不是答案本身" },
    footer: { left: "Comparison", center: "Docking", right: "需要实验验证" },
    modules,
  });
}

function sampleSpecForTemplate(template) {
  switch (template) {
    case "method-primer": return methodPrimerSampleSpec();
    case "mechanism-map": return mechanismMapSampleSpec();
    case "myth-vs-fact": return mythVsFactSampleSpec();
    case "paper-digest": return paperDigestSampleSpec();
    case "workflow-map": return workflowMapSampleSpec();
    case "comparison-matrix": return comparisonMatrixSampleSpec();
    default:
      fail(`Unsupported template "${template}". Supported templates: ${supportedTemplateList()}`);
  }
}

function validateSpec(spec) {
  const errors = [];
  if (!spec || typeof spec !== "object") {
    errors.push("Spec must be a JSON object.");
    return errors;
  }

  const hasColumns = Array.isArray(spec.columns) && spec.columns.length > 0;
  const selectedTemplate = spec.template ?? (hasColumns ? "method-primer" : null);
  if (!selectedTemplate) {
    errors.push("Missing template.");
  } else if (!SUPPORTED_TEMPLATES.includes(selectedTemplate)) {
    errors.push(`Unsupported template "${selectedTemplate}". Supported templates: ${supportedTemplateList()}.`);
  }
  if (!spec.title) errors.push("Missing title.");

  if (spec.claimType === "data-backed") {
    const hasSpecSource = hasNonEmptyArray(spec.sourceNotes) || hasNonEmptyArray(spec.sources);
    const modulesHaveSources = Array.isArray(spec.modules)
      && spec.modules.length > 0
      && spec.modules.every((module) => hasSourceMetadata(module));
    if (!hasSpecSource && !modulesHaveSources) {
      errors.push("Data-backed specs require sourceNotes, sources, or module-level source/provenance fields.");
    }
  }

  if (selectedTemplate && selectedTemplate !== "method-primer") {
    if (!Array.isArray(spec.modules) || spec.modules.length === 0) {
      errors.push("Missing modules array.");
    } else {
      spec.modules.forEach((module, moduleIndex) => {
        if (!module.heading) errors.push(`Module ${moduleIndex + 1} is missing heading.`);
        if (!module.body) errors.push(`Module ${moduleIndex + 1} is missing body.`);
      });
      const contract = RECIPE_CONTRACTS[selectedTemplate] ?? {};
      if (contract.minModules && spec.modules.length < contract.minModules) {
        errors.push(`Template ${selectedTemplate} requires at least ${contract.minModules} modules.`);
      }
      const presentRoles = new Set(spec.modules.map((module) => module.role).filter(Boolean));
      (contract.requiredRoles ?? []).forEach((role) => {
        if (!presentRoles.has(role)) {
          errors.push(`Template ${selectedTemplate} requires a module with role "${role}".`);
        }
      });
    }
    return errors;
  }

  if (!Array.isArray(spec.columns) || spec.columns.length === 0) {
    errors.push("Missing columns array.");
  } else {
    spec.columns.forEach((column, columnIndex) => {
      if (!column.title) errors.push(`Column ${columnIndex + 1} is missing title.`);
      if (!Array.isArray(column.sections) || column.sections.length === 0) {
        errors.push(`Column ${columnIndex + 1} is missing sections.`);
      } else {
        column.sections.forEach((section, sectionIndex) => {
          if (!section.heading) errors.push(`Column ${columnIndex + 1} section ${sectionIndex + 1} is missing heading.`);
          if (!section.body) errors.push(`Column ${columnIndex + 1} section ${sectionIndex + 1} is missing body.`);
        });
      }
    });
  }
  return errors;
}

function baseStyle(width, height, theme) {
  return `
    :root {
      --accent: ${theme.accent};
      --accent2: ${theme.accent2};
      --ink: ${theme.ink};
      --muted: ${theme.muted};
      --paper: ${theme.paper};
      --panel: ${theme.panel};
      --line: ${theme.line};
      --blue: ${theme.blue};
      --olive: ${theme.olive};
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      width: ${width}px;
      min-width: ${width}px;
      background: var(--paper);
      color: var(--ink);
    }
    body {
      font-family: ${theme.fontBody};
      letter-spacing: 0;
    }
    .onepager {
      width: ${width}px;
      height: ${height}px;
      padding: 22px 24px 18px;
      background:
        radial-gradient(circle at 0 0, rgba(217, 54, 18, 0.045), transparent 28%),
        var(--paper);
      overflow: hidden;
    }
    .header {
      display: grid;
      grid-template-columns: 215px 1px 1fr;
      gap: 24px;
      align-items: center;
      height: 210px;
      margin-bottom: 16px;
    }
    .brand {
      display: grid;
      grid-template-columns: 82px 1fr;
      gap: 12px;
      align-items: center;
    }
    .brand-name {
      font-size: 24px;
      line-height: 1.02;
      max-width: 120px;
    }
    .brand-tagline {
      grid-column: 1 / -1;
      color: var(--muted);
      font-family: ${theme.fontSans};
      font-size: 11px;
      line-height: 1.25;
      margin-top: 8px;
    }
    .header-rule {
      width: 1px;
      height: 176px;
      background: var(--accent);
    }
    .title {
      font-size: 58px;
      line-height: 0.98;
      margin: 0;
      font-weight: 700;
      letter-spacing: 0;
      max-width: 790px;
    }
    .subtitle {
      margin: 14px 0 0;
      font-size: 24px;
      font-style: italic;
      color: #2e2924;
    }
    .columns {
      display: grid;
      grid-template-columns: repeat(var(--column-count), 1fr);
      gap: 14px;
      height: calc(100% - 306px);
    }
    .column {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 253, 248, 0.78);
      padding: 14px 15px 12px;
      display: flex;
      flex-direction: column;
      min-width: 0;
    }
    .column-head {
      display: grid;
      grid-template-columns: 58px 1fr;
      gap: 10px;
      align-items: center;
      border-bottom: 2px solid rgba(217, 54, 18, 0.6);
      padding-bottom: 11px;
      margin-bottom: 8px;
      min-height: 76px;
    }
    .column-num {
      width: 58px;
      height: 58px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      color: white;
      font-size: 35px;
      font-weight: 700;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.08);
    }
    .column-title {
      color: var(--accent);
      font-size: 30px;
      line-height: 0.98;
      margin: 0;
      font-weight: 700;
    }
    .section {
      border-bottom: 1px solid rgba(217, 54, 18, 0.42);
      padding: 11px 0 12px;
      min-height: 0;
    }
    .section:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }
    .section-head {
      display: grid;
      grid-template-columns: 40px 1fr;
      gap: 9px;
      align-items: start;
    }
    .section-num {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      background: var(--accent);
      color: #fff;
      display: grid;
      place-items: center;
      font-family: ${theme.fontSans};
      font-size: 17px;
      font-weight: 700;
      margin-top: 1px;
    }
    .section-title {
      margin: 0;
      font-size: 22px;
      line-height: 1.05;
      font-weight: 700;
    }
    .section-body {
      margin: 5px 0 0;
      font-size: 16px;
      line-height: 1.24;
    }
    .note {
      color: var(--accent);
      font-size: 15px;
      font-style: italic;
      line-height: 1.1;
      margin-top: 3px;
    }
    .visual {
      margin-top: 10px;
      width: 100%;
      display: block;
    }
    svg {
      max-width: 100%;
      height: auto;
      display: block;
    }
    .caption {
      font-family: ${theme.fontSans};
      fill: var(--ink);
      font-size: 11px;
    }
    .footer {
      height: 66px;
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      grid-template-columns: 1.2fr 1fr 1.15fr;
      align-items: center;
      background: rgba(255, 253, 248, 0.75);
      overflow: hidden;
    }
    .footer-cell {
      min-width: 0;
      height: 100%;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 20px;
      border-right: 1px solid var(--line);
      font-family: ${theme.fontSans};
      font-size: 15px;
      line-height: 1.2;
    }
    .footer-cell:last-child { border-right: 0; }
    .footer-icon {
      width: 36px;
      height: 36px;
      flex: 0 0 36px;
      border-radius: 6px;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      display: grid;
      place-items: center;
      color: #fff;
      font-weight: 700;
    }
    .small-muted {
      color: var(--muted);
      font-size: 12px;
    }
  `;
}

function v2Style(width, height, theme, template) {
  const templateAccent = {
    "mechanism-map": theme.accent,
    "myth-vs-fact": "#b42318",
    "paper-digest": theme.blue,
    "workflow-map": "#26735d",
    "comparison-matrix": "#7a5a16",
  }[template] ?? theme.accent;
  return `
    :root {
      --accent: ${templateAccent};
      --accent2: ${theme.accent2};
      --ink: ${theme.ink};
      --muted: ${theme.muted};
      --paper: ${theme.paper};
      --panel: ${theme.panel};
      --line: ${theme.line};
      --blue: ${theme.blue};
      --olive: ${theme.olive};
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      width: ${width}px;
      min-width: ${width}px;
      background: var(--paper);
      color: var(--ink);
    }
    body {
      font-family: ${theme.fontBody};
      letter-spacing: 0;
    }
    .onepager.v2 {
      width: ${width}px;
      height: ${height}px;
      padding: 34px 42px 30px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.62), rgba(255, 250, 242, 0.3)),
        var(--paper);
      overflow: hidden;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 22px;
    }
    .v2-header {
      display: grid;
      grid-template-columns: 156px 1fr;
      gap: 24px;
      align-items: center;
      border-bottom: 3px solid color-mix(in srgb, var(--accent) 72%, transparent);
      padding-bottom: 20px;
    }
    .v2-brand {
      display: grid;
      grid-template-columns: 64px 1fr;
      gap: 11px;
      align-items: center;
      min-width: 0;
    }
    .v2-brand .brand-name {
      font-size: 20px;
      line-height: 1.05;
      font-weight: 700;
    }
    .v2-brand .brand-tagline {
      grid-column: 1 / -1;
      color: var(--muted);
      font-family: ${theme.fontSans};
      font-size: 11px;
      line-height: 1.25;
      margin-top: 2px;
    }
    .v2-title {
      margin: 0;
      font-size: 54px;
      line-height: 1.02;
      letter-spacing: 0;
      font-weight: 800;
      max-width: 770px;
    }
    .v2-subtitle {
      margin: 10px 0 0;
      font-family: ${theme.fontSans};
      color: #2e2924;
      font-size: 22px;
      line-height: 1.25;
    }
    .v2-modules {
      min-height: 0;
      display: grid;
      grid-template-columns: repeat(var(--module-columns), minmax(0, 1fr));
      grid-auto-rows: minmax(0, 1fr);
      gap: 16px;
    }
    .v2-module {
      min-width: 0;
      min-height: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 253, 248, 0.82);
      padding: 18px 18px 16px;
      display: grid;
      grid-template-rows: auto auto 1fr;
      gap: 10px;
      overflow: hidden;
      box-shadow: 0 10px 20px rgba(22, 18, 15, 0.035);
    }
    .v2-module-role {
      display: inline-flex;
      width: fit-content;
      max-width: 100%;
      align-items: center;
      gap: 8px;
      border: 1px solid color-mix(in srgb, var(--accent) 54%, white);
      border-radius: 999px;
      padding: 4px 10px;
      color: var(--accent);
      font-family: ${theme.fontSans};
      font-size: 13px;
      line-height: 1;
      font-weight: 700;
      text-transform: uppercase;
    }
    .v2-module-role::before {
      content: attr(data-index);
      width: 20px;
      height: 20px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      color: #fff;
      background: var(--accent);
      font-size: 12px;
    }
    .v2-module-title {
      margin: 0;
      font-size: 28px;
      line-height: 1.08;
      letter-spacing: 0;
      font-weight: 800;
    }
    .v2-module-body {
      margin: 0;
      color: #2c2721;
      font-size: 20px;
      line-height: 1.36;
      overflow-wrap: anywhere;
    }
    .v2-module[data-role="claim"],
    .v2-module[data-role="finding"],
    .v2-module[data-role="takeaway"],
    .v2-module[data-role="decision"] {
      border-top: 8px solid var(--accent);
    }
    .v2-module[data-role="caveat"],
    .v2-module[data-role="limit"],
    .v2-module[data-role="avoid"] {
      background: rgba(255, 248, 238, 0.96);
    }
    .v2-footer {
      height: 64px;
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      grid-template-columns: 1.2fr 1fr 1.15fr;
      align-items: center;
      background: rgba(255, 253, 248, 0.76);
      overflow: hidden;
    }
    .v2-footer .footer-cell {
      min-width: 0;
      height: 100%;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 18px;
      border-right: 1px solid var(--line);
      font-family: ${theme.fontSans};
      font-size: 15px;
      line-height: 1.2;
    }
    .v2-footer .footer-cell:last-child { border-right: 0; }
    .footer-icon {
      width: 34px;
      height: 34px;
      flex: 0 0 34px;
      border-radius: 6px;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      display: grid;
      place-items: center;
      color: #fff;
      font-weight: 700;
    }
    svg {
      max-width: 100%;
      height: auto;
      display: block;
    }
  `;
}

function brandMark(theme) {
  return `<svg width="82" height="82" viewBox="0 0 82 82" aria-hidden="true">
    <polygon points="41,5 74,24 74,58 41,77 8,58 8,24" fill="none" stroke="${theme.ink}" stroke-width="2"/>
    <g fill="${theme.accent}">
      ${Array.from({ length: 22 }, (_, i) => {
        const x = 21 + (i % 5) * 6;
        const y = 25 + Math.floor(i / 5) * 6;
        return `<circle cx="${x}" cy="${y}" r="1.6"/>`;
      }).join("")}
    </g>
    <path d="M52 53 C55 42, 57 28, 60 42 S66 52, 70 39" fill="none" stroke="${theme.ink}" stroke-width="1.7"/>
    <path d="M28 59 L41 50 L54 59 M41 50 L41 38" fill="none" stroke="${theme.ink}" stroke-width="1.5"/>
    <circle cx="28" cy="59" r="3" fill="#fff" stroke="${theme.ink}" stroke-width="1.4"/>
    <circle cx="41" cy="38" r="3" fill="#fff" stroke="${theme.ink}" stroke-width="1.4"/>
    <circle cx="54" cy="59" r="3" fill="#fff" stroke="${theme.ink}" stroke-width="1.4"/>
  </svg>`;
}

function footerIcon(kind, theme) {
  const icons = {
    account: '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="12" cy="7" r="3.2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M5.5 20c.8-4 3.1-6.1 6.5-6.1s5.7 2.1 6.5 6.1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M18.5 6.2h2.2M19.6 5.1v2.2M3.3 10.8h2.2M4.4 9.7v2.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    plan: '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M5 5.5c2.8 0 4.9.6 7 2.2 2.1-1.6 4.2-2.2 7-2.2v12.8c-2.8 0-4.9.6-7 2.2-2.1-1.6-4.2-2.2-7-2.2z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 7.7v12.5M7.4 9.1h2.2M14.4 9.1h2.2M7.4 12h2.2M14.4 12h2.2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    schematic: '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M4 18.5h16M5.5 17V5.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="8.2" cy="13.5" r="1.8" fill="currentColor"/><circle cx="11.8" cy="9.2" r="1.8" fill="currentColor"/><circle cx="16.8" cy="12.4" r="1.8" fill="currentColor"/><path d="M7.8 8.2c2.4-2 6.6-2.4 10-.6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2.2 2.2" stroke-linecap="round"/></svg>',
  };
  const svg = icons[kind] ?? icons.schematic;
  return `<div class="footer-icon" aria-label="${escapeAttr(kind)}">${svg}</div>`;
}

function pointCloud(points, color, radius = 4) {
  return points.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="${radius}" fill="${color}" opacity="0.95"/>`).join("");
}

function scatterSvg(visual, theme) {
  const groups = visual?.groups ?? [
    { color: theme.blue, points: [[67, 70], [82, 55], [92, 78], [75, 92], [105, 62], [118, 88], [97, 102], [66, 112]] },
    { color: theme.accent2, points: [[210, 62], [228, 78], [238, 98], [198, 96], [220, 118], [248, 112], [205, 134]] },
    { color: theme.olive, points: [[142, 142], [158, 152], [175, 132], [183, 162], [132, 174], [160, 188], [194, 180]] },
  ];
  return `<svg viewBox="0 0 300 220" class="visual" role="img" aria-label="schematic scatter plot">
    <rect x="38" y="18" width="228" height="160" fill="#fff" stroke="${theme.ink}" stroke-width="1"/>
    <path d="M152 18 V178 M38 98 H266" stroke="${theme.line}" stroke-width="1"/>
    ${groups.map((g) => pointCloud(g.points, g.color, 4.8)).join("")}
    <text x="152" y="206" text-anchor="middle" class="caption">${escapeHtml(visual?.xLabel ?? "PC1")}</text>
    <text x="17" y="100" text-anchor="middle" transform="rotate(-90 17 100)" class="caption">${escapeHtml(visual?.yLabel ?? "PC2")}</text>
    <circle cx="65" cy="196" r="4" fill="${theme.blue}"/><text x="75" y="200" class="caption">Group A</text>
    <circle cx="145" cy="196" r="4" fill="${theme.accent2}"/><text x="155" y="200" class="caption">Group B</text>
    <circle cx="225" cy="196" r="4" fill="${theme.olive}"/><text x="235" y="200" class="caption">Group C</text>
  </svg>`;
}

function loadingPlotSvg(theme) {
  const vectors = [
    [150, 92, 234, 49, "A"],
    [150, 92, 218, 102, "B"],
    [150, 92, 179, 62, "C"],
    [150, 92, 93, 52, "D"],
    [150, 92, 122, 125, "E"],
  ];
  return `<svg viewBox="0 0 300 205" class="visual" role="img" aria-label="schematic loading plot">
    <defs>
      <marker id="arrow-accent" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
        <path d="M0,0 L7,3.5 L0,7 Z" fill="${theme.accent2}"/>
      </marker>
    </defs>
    <ellipse cx="150" cy="92" rx="100" ry="58" fill="#fff" stroke="${theme.ink}" stroke-width="1"/>
    <path d="M42 92 H258 M150 24 V160" stroke="${theme.ink}" stroke-width="1"/>
    ${vectors.map(([x1, y1, x2, y2, label]) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${theme.accent2}" stroke-width="1.4" marker-end="url(#arrow-accent)"/><text x="${x2 + (x2 > 150 ? 5 : -5)}" y="${y2 - 4}" text-anchor="${x2 > 150 ? "start" : "end"}" class="caption">${escapeHtml(label)}</text>`).join("")}
    <text x="150" y="188" text-anchor="middle" class="caption">A-E = variables; longer arrows = stronger contribution</text>
  </svg>`;
}

function barsBeforeAfterSvg(theme) {
  const left = [78, 48, 36, 28];
  const right = [54, 45, 38, 32];
  const bars = (x0, values, accentIndex) => values.map((h, i) => {
    const x = x0 + i * 19;
    const y = 122 - h;
    const fill = i === accentIndex ? theme.accent2 : "#e9e3d5";
    return `<rect x="${x}" y="${y}" width="12" height="${h}" fill="${fill}" stroke="${theme.ink}" stroke-width="0.8"/>`;
  }).join("");
  return `<svg viewBox="0 0 300 205" class="visual" role="img" aria-label="schematic before and after bar chart">
    <path d="M42 42 V130 H125 M178 42 V130 H262" fill="none" stroke="${theme.ink}" stroke-width="1"/>
    ${bars(55, left, 0)}
    ${bars(191, right, 0)}
    <path d="M139 88 H165" stroke="${theme.ink}" stroke-width="2"/><path d="M165 88 L156 82 V94 Z" fill="${theme.ink}"/>
    <text x="83" y="150" text-anchor="middle" class="caption">Raw Data</text>
    <text x="220" y="150" text-anchor="middle" class="caption">After Scaling</text>
    <path d="M82 178 L102 178 M92 178 L92 150 M78 150 L106 150" stroke="${theme.ink}" stroke-width="1"/>
    <path d="M78 150 Q86 171 92 171 Q98 171 106 150" fill="none" stroke="${theme.accent}" stroke-width="1.3"/>
    <text x="122" y="181" class="caption">Compromise between abundance and variability</text>
  </svg>`;
}

function distributionBeforeAfterSvg(visual, theme) {
  const leftPath = visual?.mode === "skew"
    ? "M40 138 C48 72, 70 54, 82 82 C98 118, 122 134, 132 138"
    : "M40 138 C50 38, 65 38, 76 138 M92 138 C116 88, 144 88, 166 138";
  const rightPath = visual?.mode === "skew"
    ? "M178 138 C192 76, 240 76, 256 138"
    : "M178 138 C188 82, 206 82, 216 138 M211 138 C224 76, 244 76, 256 138 M238 138 C251 82, 269 82, 282 138";
  const leftLabel = visual?.mode === "skew" ? "Right-skewed" : "Unequal variance";
  const rightLabel = visual?.mode === "skew" ? "More symmetric" : "Equal variance";
  return `<svg viewBox="0 0 300 205" class="visual" role="img" aria-label="schematic distribution transformation">
    <path d="M35 142 H135 M35 142 V56" stroke="${theme.ink}" stroke-width="1" fill="none"/>
    <path d="${leftPath}" fill="none" stroke="${theme.accent}" stroke-width="2"/>
    <path d="M169 96 H195" stroke="${theme.ink}" stroke-width="2"/><path d="M195 96 L186 90 V102 Z" fill="${theme.ink}"/>
    <path d="M175 142 H282 M175 142 V56" stroke="${theme.ink}" stroke-width="1" fill="none"/>
    <path d="${rightPath}" fill="none" stroke="${theme.accent}" stroke-width="2"/>
    <text x="85" y="162" text-anchor="middle" class="caption">${escapeHtml(leftLabel)}</text>
    <text x="230" y="162" text-anchor="middle" class="caption">${escapeHtml(rightLabel)}</text>
  </svg>`;
}

function ellipseOutlierSvg(theme) {
  const inliers = [[118, 92], [135, 110], [154, 96], [174, 118], [190, 97], [138, 134], [160, 142], [188, 138], [110, 125], [205, 115], [148, 76], [178, 80]];
  const outliers = [[64, 82], [238, 72], [245, 153], [80, 165]];
  return `<svg viewBox="0 0 300 205" class="visual" role="img" aria-label="schematic Hotelling ellipse">
    <path d="M52 108 H260 M156 35 V178" stroke="${theme.ink}" stroke-width="1"/>
    <ellipse cx="156" cy="108" rx="88" ry="55" fill="rgba(142,139,115,0.12)" stroke="${theme.ink}" stroke-width="1.2"/>
    ${pointCloud(inliers, "#c7c4b5", 4.4)}
    ${pointCloud(outliers, "#e21b12", 5)}
    <line x1="54" y1="190" x2="92" y2="190" stroke="${theme.ink}" stroke-width="1.3"/>
    <text x="99" y="194" class="caption">95% T2 ellipse</text>
    <circle cx="206" cy="190" r="5" fill="#e21b12"/>
    <text x="216" y="194" class="caption">Potential outlier</text>
  </svg>`;
}

function simpleDiagramSvg(visual, theme) {
  const leftLabel = visual?.labels?.[0] ?? "High-D";
  const rightLabel = visual?.labels?.[1] ?? "Reduced";
  return `<svg viewBox="0 0 300 210" class="visual" role="img" aria-label="schematic dimensionality reduction">
    <polygon points="74,42 124,70 124,130 74,164 24,130 24,70" fill="#fff" stroke="${theme.ink}" stroke-width="1.1"/>
    <path d="M74 42 V164 M24 70 L74 99 L124 70 M24 130 L74 99 L124 130" stroke="${theme.line}" stroke-width="0.9"/>
    ${pointCloud([[58,90],[72,82],[88,96],[64,112],[82,124],[96,110],[74,138],[104,82]], theme.blue, 4)}
    ${pointCloud([[92,90],[108,104],[100,126],[116,118]], theme.accent2, 4)}
    ${pointCloud([[70,104],[82,108],[90,116],[76,118],[88,132]], theme.olive, 4)}
    <path d="M140 104 H174" stroke="${theme.ink}" stroke-width="2"/><path d="M174 104 L164 97 V111 Z" fill="${theme.ink}"/>
    <rect x="190" y="54" width="86" height="100" fill="#fff" stroke="${theme.ink}" stroke-width="1.1"/>
    ${pointCloud([[214,78],[228,72],[238,88],[220,96],[242,104]], theme.blue, 4.8)}
    ${pointCloud([[246,78],[258,92],[238,116],[262,112]], theme.accent2, 4.8)}
    ${pointCloud([[218,124],[232,134],[248,128],[236,146]], theme.olive, 4.8)}
    <text x="74" y="190" text-anchor="middle" class="caption">${escapeHtml(leftLabel)}</text>
    <text x="233" y="190" text-anchor="middle" class="caption">${escapeHtml(rightLabel)}</text>
  </svg>`;
}

function visualHtml(visual, theme) {
  if (!visual || !visual.type) return "";
  const label = visual.dataBacked ? "Data-backed" : "Schematic";
  let svg = "";
  switch (visual.type) {
    case "scatter":
      svg = scatterSvg(visual, theme);
      break;
    case "loading-plot":
      svg = loadingPlotSvg(theme);
      break;
    case "bars-before-after":
      svg = barsBeforeAfterSvg(theme);
      break;
    case "distribution-before-after":
      svg = distributionBeforeAfterSvg(visual, theme);
      break;
    case "ellipse-outlier":
      svg = ellipseOutlierSvg(theme);
      break;
    case "simple-diagram":
      svg = simpleDiagramSvg(visual, theme);
      break;
    case "custom-svg":
      svg = String(visual.svg ?? "");
      break;
    default:
      svg = simpleDiagramSvg(visual, theme);
      break;
  }
  return `<div class="visual-wrap" data-visual-type="${escapeAttr(visual.type)}" data-provenance="${label}">${svg}</div>`;
}

function sectionHtml(section, sectionIndex, theme) {
  const number = section.number ?? String(sectionIndex + 1);
  const note = section.note ? `<div class="note">${escapeHtml(section.note)}</div>` : "";
  const schematicNote = section.visual && !section.visual.dataBacked && !section.note
    ? `<div class="note">Schematic</div>`
    : "";
  return `<section class="section">
    <div class="section-head">
      <div class="section-num">${escapeHtml(number)}</div>
      <div>
        <h3 class="section-title">${escapeHtml(section.heading)}</h3>
        ${note || schematicNote}
        <p class="section-body">${escapeHtml(section.body)}</p>
      </div>
    </div>
    ${visualHtml(section.visual, theme)}
  </section>`;
}

function columnHtml(column, columnIndex, theme) {
  const number = column.number ?? String(columnIndex + 1);
  return `<article class="column">
    <header class="column-head">
      <div class="column-num">${escapeHtml(number)}</div>
      <h2 class="column-title">${escapeHtml(column.title)}</h2>
    </header>
    ${column.sections.map((section, i) => sectionHtml(section, i, theme)).join("\n")}
  </article>`;
}

function provenanceLabel(value) {
  if (value === "data-backed") return "Data-backed";
  if (value === "schematic-only") return "Schematic";
  return value ?? "Schematic";
}

function moduleHtml(module, moduleIndex, spec) {
  const role = module.role ?? "module";
  const provenance = provenanceLabel(module.provenance ?? spec.claimType);
  return `<article class="v2-module" data-role="${escapeAttr(role)}" data-visual-type="module-card" data-provenance="${escapeAttr(provenance)}">
    <div class="v2-module-role" data-index="${moduleIndex + 1}">${escapeHtml(role)}</div>
    <h2 class="v2-module-title">${escapeHtml(module.heading)}</h2>
    <p class="v2-module-body">${escapeHtml(module.body)}</p>
  </article>`;
}

function buildV2Html(spec, width, height, template) {
  const theme = themeOf(spec);
  const title = escapeHtml(spec.title);
  const subtitle = spec.subtitle ? `<p class="v2-subtitle">${escapeHtml(spec.subtitle)}</p>` : "";
  const brand = spec.brand ?? {};
  const footer = spec.footer ?? {};
  const moduleCount = spec.modules.length;
  const moduleColumns = moduleCount <= 4 ? 2 : 3;
  const body = `<main class="onepager v2" data-template="${escapeAttr(template)}" style="--module-columns:${moduleColumns}">
    <header class="v2-header">
      <div class="v2-brand">
        ${brandMark(theme)}
        <div class="brand-name">${escapeHtml(brand.name ?? "Scientific Onepager")}</div>
        ${brand.tagline ? `<div class="brand-tagline">${escapeHtml(brand.tagline)}</div>` : ""}
      </div>
      <div>
        <h1 class="v2-title">${title}</h1>
        ${subtitle}
      </div>
    </header>
    <section class="v2-modules" aria-label="onepager modules">
      ${spec.modules.map((module, i) => moduleHtml(module, i, spec)).join("\n")}
    </section>
    <footer class="v2-footer">
      <div class="footer-cell">${footerIcon(footer.leftIcon ?? "account", theme)}<div>${escapeHtml(footer.left ?? brand.name ?? "Scientific Onepager")}</div></div>
      <div class="footer-cell">${footerIcon(footer.centerIcon ?? "plan", theme)}<div>${escapeHtml(footer.center ?? "Recipe layout")}</div></div>
      <div class="footer-cell">${footerIcon(footer.rightIcon ?? "schematic", theme)}<div>${escapeHtml(footer.right ?? "Schematic, no measured data")}</div></div>
    </footer>
  </main>`;

  const templatePath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../assets/templates/three-column-method-primer.html");
  let htmlTemplate = "";
  try {
    htmlTemplate = fs.readFileSync(templatePath, "utf8");
  } catch {
    htmlTemplate = "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>{{TITLE}}</title><style>{{STYLE}}</style></head><body>{{BODY}}</body></html>";
  }
  return htmlTemplate
    .replace("{{TITLE}}", title)
    .replace("{{STYLE}}", v2Style(width, height, theme, template))
    .replace("{{BODY}}", body);
}

function buildHtml(spec, width, height) {
  const selectedTemplate = normalizeTemplate(spec);
  if (selectedTemplate !== "method-primer") {
    return buildV2Html(spec, width, height, selectedTemplate);
  }
  if (!Array.isArray(spec.columns) || spec.columns.length === 0) {
    fail("Method-primer specs require legacy columns.");
  }
  const theme = themeOf(spec);
  const title = escapeHtml(spec.title);
  const subtitle = spec.subtitle ? `<p class="subtitle">${escapeHtml(spec.subtitle)}</p>` : "";
  const brand = spec.brand ?? {};
  const footer = spec.footer ?? {};
  const columnCount = clamp(spec.columns.length, 1, 4);
  const body = `<main class="onepager" style="--column-count:${columnCount}">
    <header class="header">
      <div>
        <div class="brand">
          ${brandMark(theme)}
          <div class="brand-name">${escapeHtml(brand.name ?? "Scientific Onepager")}</div>
          ${brand.tagline ? `<div class="brand-tagline">${escapeHtml(brand.tagline)}</div>` : ""}
        </div>
      </div>
      <div class="header-rule"></div>
      <div>
        <h1 class="title">${title}</h1>
        ${subtitle}
      </div>
    </header>
    <div class="columns">
      ${spec.columns.map((column, i) => columnHtml(column, i, theme)).join("\n")}
    </div>
    <footer class="footer">
      <div class="footer-cell">${footerIcon(footer.leftIcon ?? "account", theme)}<div>${escapeHtml(footer.left ?? brand.name ?? "Scientific Onepager")}</div></div>
      <div class="footer-cell">${footerIcon(footer.centerIcon ?? "plan", theme)}<div>${escapeHtml(footer.center ?? "Learning plan")}</div></div>
      <div class="footer-cell">${footerIcon(footer.rightIcon ?? "schematic", theme)}<div>${escapeHtml(footer.right ?? "Schematic, no measured data")}</div></div>
    </footer>
  </main>`;

  const templatePath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../assets/templates/three-column-method-primer.html");
  let template = "";
  try {
    template = fs.readFileSync(templatePath, "utf8");
  } catch {
    template = "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>{{TITLE}}</title><style>{{STYLE}}</style></head><body>{{BODY}}</body></html>";
  }
  return template
    .replace("{{TITLE}}", title)
    .replace("{{STYLE}}", baseStyle(width, height, theme))
    .replace("{{BODY}}", body);
}

async function maybeLoadPlaywright() {
  const require = createRequire(import.meta.url);
  const errors = [];
  try {
    const mod = await import("playwright");
    return { chromium: mod.chromium, error: null };
  } catch (error) {
    errors.push(error.message);
  }
  try {
    const mod = require("playwright");
    return { chromium: mod.chromium, error: null };
  } catch (error) {
    errors.push(error.message);
  }
  const candidateRoots = [
    ...(process.env.NODE_PATH ? process.env.NODE_PATH.split(path.delimiter) : []),
    process.env.USERPROFILE ? path.join(process.env.USERPROFILE, ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "node_modules") : null,
  ].filter(Boolean);
  for (const root of candidateRoots) {
    try {
      const mod = require(path.join(root, "playwright"));
      return { chromium: mod.chromium, error: null };
    } catch (error) {
      errors.push(`${root}: ${error.message}`);
    }
  }
  return { chromium: null, error: new Error(errors.join(" | ")) };
}

async function renderPng(html, pngPath, width, height) {
  const { chromium, error } = await maybeLoadPlaywright();
  if (!chromium) {
    return {
      ok: false,
      warning: `Playwright is not available: ${error.message}. HTML was written; install Playwright to enable PNG export.`,
    };
  }
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    await page.setContent(html, { waitUntil: "load" });
    await page.screenshot({ path: pngPath, fullPage: false });
    return { ok: true };
  } catch (error) {
    return {
      ok: false,
      warning: `PNG render failed: ${error.message}. HTML was written; run Playwright browser installation if needed.`,
    };
  } finally {
    if (browser) await browser.close();
  }
}

async function runQa(html, width, height) {
  const staticProblems = [];
  const hasLegacyVisual = html.includes("data-visual-type=");
  const hasV2Template = html.includes("class=\"onepager v2\"");
  if (!/class="[^"]*\bonepager\b/.test(html)) staticProblems.push("Missing .onepager root.");
  if (hasLegacyVisual && !hasV2Template && !html.includes("data-provenance=\"Schematic\"") && !html.includes("data-provenance=\"Data-backed\"")) {
    staticProblems.push("No visual provenance markers found.");
  }
  if (!hasLegacyVisual && !hasV2Template) staticProblems.push("No legacy visual blocks or V2 template root found.");
  const { chromium, error } = await maybeLoadPlaywright();
  if (!chromium) {
    return {
      mode: "static",
      ok: staticProblems.length === 0,
      problems: staticProblems,
      warning: `Playwright is not available: ${error.message}. Ran static checks only.`,
    };
  }
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    await page.setContent(html, { waitUntil: "load" });
    const metrics = await page.evaluate(() => {
      const root = document.querySelector(".onepager");
      const rootBox = root ? root.getBoundingClientRect() : null;
      const overflowX = document.documentElement.scrollWidth > window.innerWidth || document.body.scrollWidth > window.innerWidth;
      const overflowY = document.documentElement.scrollHeight > window.innerHeight || document.body.scrollHeight > window.innerHeight;
      const clipped = Array.from(document.querySelectorAll(".section-title, .footer-cell, .column-title"))
        .filter((el) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)
        .map((el) => el.textContent.trim().slice(0, 80));
      const textLength = document.body.innerText.trim().length;
      const visualCount = document.querySelectorAll("[data-visual-type]").length;
      const mainClaim = document.querySelector(".title, .v2-title");
      const mainClaimBox = mainClaim ? mainClaim.getBoundingClientRect() : null;
      const moduleBoxes = Array.from(document.querySelectorAll(".module, .v2-module")).map((el) => {
        const box = el.getBoundingClientRect();
        return {
          text: el.textContent.trim().slice(0, 80),
          width: Math.round(box.width),
          height: Math.round(box.height),
          top: Math.round(box.top),
          bottom: Math.round(box.bottom),
        };
      });
      return {
        rootWidth: rootBox ? Math.round(rootBox.width) : 0,
        rootHeight: rootBox ? Math.round(rootBox.height) : 0,
        overflowX,
        overflowY,
        clipped,
        textLength,
        visualCount,
        mainClaimTop: mainClaimBox ? Math.round(mainClaimBox.top) : null,
        mainClaimBottom: mainClaimBox ? Math.round(mainClaimBox.bottom) : null,
        moduleBoxes,
      };
    });
    const problems = [...staticProblems];
    if (metrics.rootWidth !== width) problems.push(`Expected width ${width}, got ${metrics.rootWidth}.`);
    if (metrics.rootHeight !== height) problems.push(`Expected height ${height}, got ${metrics.rootHeight}.`);
    if (metrics.overflowX) problems.push("Horizontal overflow detected.");
    if (metrics.overflowY) problems.push("Vertical overflow detected.");
    if (metrics.clipped.length > 0) problems.push(`Clipped text detected: ${metrics.clipped.join("; ")}`);
    if (metrics.mainClaimBottom !== null && metrics.mainClaimBottom > height * 0.35) {
      problems.push("Main claim extends beyond the top 35% preview region.");
    }
    metrics.moduleBoxes
      .filter((box) => box.height < 120 || box.width < 240)
      .forEach((box) => problems.push(`V2 module too small to read: ${box.text} (${box.width}x${box.height}).`));
    if (metrics.textLength < 80) problems.push("Rendered text is unexpectedly short.");
    if (!hasV2Template && metrics.visualCount === 0) problems.push("No visual blocks rendered.");
    return { mode: "playwright", ok: problems.length === 0, problems, metrics };
  } catch (error) {
    return {
      mode: "static",
      ok: staticProblems.length === 0,
      problems: staticProblems,
      warning: `Playwright QA failed: ${error.message}. Static checks completed.`,
    };
  } finally {
    if (browser) await browser.close();
  }
}

async function commandSample(args) {
  const output = requireArg(args, "output");
  const template = normalizeTemplate(args.template ?? "method-primer");
  writeJson(output, sampleSpecForTemplate(template));
  console.log(`Success! Sample spec written to: ${output}`);
}

async function commandRender(args) {
  const specPath = requireArg(args, "spec");
  const outputDir = requireArg(args, "output-dir");
  const width = Number(requireArg(args, "width"));
  const height = Number(requireArg(args, "height"));
  if (!Number.isInteger(width) || width <= 0) fail("--width must be a positive integer.");
  if (!Number.isInteger(height) || height <= 0) fail("--height must be a positive integer.");
  const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
  const errors = validateSpec(spec);
  if (errors.length) fail(errors.join("\n"));
  fs.mkdirSync(outputDir, { recursive: true });
  const html = buildHtml(spec, width, height);
  const htmlPath = path.join(outputDir, "onepager.html");
  const pngPath = path.join(outputDir, "onepager.png");
  fs.writeFileSync(htmlPath, html, "utf8");
  const renderResult = args["no-png"] ? { ok: false, warning: "PNG export skipped by --no-png." } : await renderPng(html, pngPath, width, height);
  const qa = await runQa(html, width, height);
  const report = {
    html: htmlPath,
    png: renderResult.ok ? pngPath : null,
    width,
    height,
    render: renderResult,
    qa,
  };
  writeJson(path.join(outputDir, "render-report.json"), report);
  if (renderResult.warning) console.error(`Warning: ${renderResult.warning}`);
  if (!qa.ok) {
    console.error(`Warning: QA found issues: ${qa.problems.join("; ")}`);
  }
  console.log(`Success! Onepager HTML written to: ${htmlPath}`);
  if (renderResult.ok) console.log(`Success! Onepager PNG written to: ${pngPath}`);
}

async function commandCheck(args) {
  const htmlPath = requireArg(args, "html");
  const width = Number(args.width ?? DEFAULT_WIDTH);
  const height = Number(args.height ?? DEFAULT_HEIGHT);
  const html = fs.readFileSync(htmlPath, "utf8");
  const qa = await runQa(html, width, height);
  const output = args.output ? String(args.output) : path.join(path.dirname(htmlPath), "check-report.json");
  writeJson(output, qa);
  if (qa.warning) console.error(`Warning: ${qa.warning}`);
  if (!qa.ok) fail(`QA failed. Report written to: ${output}`);
  console.log(`Success! QA passed. Report written to: ${output}`);
}

async function main() {
  const { command, args } = parseArgs(process.argv);
  if (command === "sample") return commandSample(args);
  if (command === "render") return commandRender(args);
  if (command === "check") return commandCheck(args);
  fail(`Unknown command: ${command ?? "(none)"}\n${usage()}`);
}

main().catch((error) => fail(error.stack || error.message));
