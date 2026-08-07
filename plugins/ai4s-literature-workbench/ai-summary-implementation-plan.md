# AI Summary 实施计划

> 状态：Frank 已批准；实现与验证已完成（2026-07-21）  
> 目标：补齐 `literature-workbench 插件设计.md` 中 V1 拓展功能 3 的 AI Summary，使用户可以显式要求 Agent 基于 Zotero 条目的标题与摘要生成一句话概括，并安全写回该条目的 metadata。

## 0. 拓展功能 1–3 的当前缺口

| 拓展功能 | 当前状态 | 本计划处理 |
| --- | --- | --- |
| 1. 旧文献期刊信息回填 | 已有独立 metrics backfill plan/apply 路径 | 不改 |
| 2. 领域文献更新 | 已有 project sync、增量去重和 Current Report Note 更新闭环 | 不改 |
| 3. AI Tags、report、AI Summary | Agent Tags 与 Current Report 已实现；AI Summary 尚无字段契约和受控写入工具 | **补齐 AI Summary** |

因此，本次不是再造一套文献工作流，而是在现有 `literature-manager + Zotero MCP + literature-metrics add-on` 三层中补一个窄能力。

## 1. 从原始要求推导出的真实需求

Frank 给出的三个要求是：

1. 存放到 Zotero metadata 字段中；
2. 用一句话总结概括，依据标题和摘要；
3. 由用户显式触发。

结合现有插件的低心智负担、No Evidence, No Conclusion 和受限写入原则，这实际对应以下行为契约：

1. **它是每篇文献的快速阅读提示，不是原始摘要的替代品。** 原始 `Abstract` 必须完整保留，AI Summary 也不能作为科学写作中的独立证据来源。
2. **生成依据严格限制为当前 Zotero item 的 `title + abstractNote`。** 不读取 PDF、不补充网页内容、不根据期刊指标、标签或 Agent 常识扩写结论。
3. **结果必须是一个可复用的 item-level metadata 值。** 不创建 child Note，不混入 collection report，也不写入原始 `abstractNote`。
4. **一次自然语言命令就是一次授权。** 普通检索、导入、项目续更、metrics 回填、Agent Tags 或 report 更新都不得顺带生成 AI Summary，也不在导入后主动追问用户是否生成。
5. **批量操作必须幂等且不误覆盖。** 默认只补齐缺失项；已有 Summary 在相同输入下保持不变。只有用户明确说“刷新、重新生成、覆盖”等时才重算已有值。
6. **缺少摘要时不降级为标题猜测。** 该条目跳过并报告 `missing-abstract`；这与“基于标题和摘要”及 No Evidence, No Conclusion 一致。
7. **功能必须适用于单篇、多篇和 collection。** 这是文献库管理能力，而不应只绑定 `literature-research` 新导入批次。

## 2. 建议的用户体验

支持以下自然语言入口：

- “给这篇文献生成 AI Summary。”
- “给这个 collection 中还没有 AI Summary 的文献补一句话总结。”
- “重新生成这 8 篇文献的 AI Summary。”
- “用中文概括这个 collection；每篇一句话。”

默认行为：

- `missing` 模式：只处理尚无有效 `AI4S-Summary` 的条目。
- `refresh` 模式：仅当用户明确表达刷新或覆盖时，重新生成目标范围内已有的 AI Summary。
- **默认输出语言固定为中文（`zh-CN`）**。只有用户显式指定英文或其他语言时才切换；语言值随 metadata 保存，不把语言选择变成额外确认问题。
- 正常完成后只返回紧凑结果，例如：`目标 36，新增 28，保持 5，跳过 3（无摘要）`。内部 plan、hash 和 receipt 默认隐藏。

以下情况才暂停并向用户给出精简风险摘要：

- collection 名称不能唯一解析；
- item version 冲突在重新读取后仍无法解决；
- `Extra` 中存在重复或损坏的 `AI4S-Summary` 管理块；
- 单次范围过大，导致上下文或写入无法安全分批完成。

## 3. Metadata 字段决策

| 候选位置 | 决策 | 原因 |
| --- | --- | --- |
| `abstractNote` | 不使用 | 会污染或覆盖出版方原始摘要，破坏证据来源 |
| child Note | 不使用 | 它是独立内容对象，不是 item metadata；大量生成会污染条目树 |
| `shortTitle`、`rights` 等标准字段 | 不使用 | 字段语义不匹配，会影响引用导出或与用户数据冲突 |
| 原生 tags | 不使用 | 一句话是高基数长文本，不适合筛选标签 |
| `Extra` 中独立管理块 | **采用** | 是合法 metadata；可版本化、可审计、可安全合并，并能由现有 add-on 只读展示 |

建议使用一行 JSON 管理块，和 `AI4S-Metrics` 相互独立：

```text
AI4S-Summary: {"schema_version":1,"text":"……。","language":"zh-CN","basis":"title-abstract","title_sha256":"…","abstract_sha256":"…","generated_at":"2026-07-21T10:00:00Z"}
```

字段规则：

- `schema_version`：首版固定为 `1`。
- `text`：无 Markdown、无换行的一句话。
- `language`：BCP 47 风格语言标签，如 `zh-CN`、`en`。
- `basis`：首版固定为 `title-abstract`，禁止让后续调用误认为基于全文。
- `title_sha256` / `abstract_sha256`：对规范化后的输入分别计算，用于判断 Summary 是否因 metadata 更新而过期；不在 Extra 中复制长摘要。
- `generated_at`：生成时间，仅用于 provenance，不作为是否刷新判断。
- 不保存用户原始 prompt、API key、私有路径或模型密钥。
- 解析和合并时只替换唯一的 `AI4S-Summary:` 行，保留所有其他 Extra 文本及 `AI4S-Metrics:`。
- 缺失、重复、JSON 损坏或 schema 不支持必须区分；不得用空值覆盖旧内容。

## 4. 一句话生成契约

### 4.1 输入

每条只向 Agent 提供：

- Zotero item key 与 version；
- title；
- abstractNote；
- 已有 AI Summary 的状态与输入 hashes；
- 用户本轮指定或推导出的输出语言。

### 4.2 输出约束

每条候选 Summary 必须：

1. 只有一个句子，不含项目符号、标题、引文占位符或 Markdown；
2. 概括摘要明确支持的研究对象/问题、方法或证据类型、主要发现；不要求机械塞入所有维度；
3. 不使用“首次、突破性、显著改善、证明、最佳”等超出摘要证据或带评价色彩的措辞，除非摘要本身明确支持且准确保留限定条件；
4. 不把相关性改写为因果性，不把动物/体外结果泛化到人，不删除关键否定词或不确定性；
5. 建议不超过 240 个 Unicode 字符。超过上限、含换行或明显多句时由 apply 工具拒绝，而不是静默截断；
6. 在摘要只有背景、没有结果时，概括论文研究目的或综述范围，不虚构结论。

### 4.3 缺失与陈旧判定

- title 为空：跳过 `missing-title`。
- abstractNote 为空或只有空白：跳过 `missing-abstract`。
- 现有管理块有效且两个 input hashes 均相同：
  - `missing` 模式：`unchanged`；
  - `refresh` 模式：允许替换，但仍需通过所有验证。
- 现有管理块有效但任一 input hash 改变：标记 `stale`；`missing` 模式不自动覆盖，并在结果中提示可显式刷新。
- 管理块损坏或重复：不写该条，报告 `invalid-summary-block`。

## 5. 架构与职责

不创建新的 umbrella skill。继续由 `literature-manager` 承担 Zotero 管理语义，在 Zotero MCP 中加入一个与 Agent Tags 相似的两阶段窄写入工作流：

计划更新的 skill 标识保持不变：

```yaml
name: literature-manager
description: >-
  Manage ranked literature evidence and recurring reports in Zotero through
  stable-ID matching, auditable import/sync plans, metrics, semantic tags, and
  explicitly requested one-sentence AI summaries based only on each item's
  title and abstract, while preserving user metadata and Zotero write safety.
```

```text
用户显式命令
  → zotero_ai_summary_context（只读、解析范围与输入）
  → Agent 按契约生成每篇一句话
  → zotero_apply_ai_summaries（验证、合并 Extra、写 receipt）
  → literature-metrics add-on 只读显示 AI Summary 列
```

### 5.1 `zotero_ai_summary_context`

只读工具，职责是：

- 接受且只接受 `collection_key` 或 `item_keys` 其中之一；
- 接受 `mode: missing | refresh` 和输出语言；语言未提供时规范化为 `zh-CN`；
- 过滤 attachment、note、annotation 等非普通文献条目；
- 返回 title、abstract、item version、现有 Summary 状态和 input hashes；
- 默认在 `missing` 模式下不返回无需生成的完整摘要文本，只返回紧凑状态；
- 对大 collection 分页，并给出明确的 batch token/cursor，避免一次输出过长。

### 5.2 `zotero_apply_ai_summaries`

窄写入工具，输入每条：

- item key、预期 item version；
- context 阶段返回的 title/abstract hashes；
- 一句话 Summary 与 language；
- `mode`；
- 固定枚举 `trigger: explicit-user-request`。

工具必须：

- 在写入前重新读取 item，校验 version 与 title/abstract hashes；
- 验证句子、长度、换行、语言字段和目标 item 类型；
- 仅合并 `AI4S-Summary` 管理块；
- 在 `missing` 模式下再次确认没有有效现存 Summary，防止并发覆盖；
- 分批写入并生成内部 hashed plan 与 receipt；
- 将每条结果记录为 `created`、`refreshed`、`unchanged`、`stale`、`skipped`、`conflicted` 或 `failed`；
- 不修改 Abstract、tags、collections、Priority、Article Type、Agent Tags、metrics 或 child Notes。

用户已通过本轮自然语言命令显式授权该受限 namespace 的写入，因此正常路径不需要第二次 hash 审批。`trigger` 枚举和内部 receipt 用于让调用意图可审计，但不能替代 skill/prompt 层的显式触发规则。

### 5.3 Zotero add-on

把只读 `AI Summary` 栏纳入本次最小可用范围，因为 metadata 如果只能在 Extra 详情中查看，无法实现文献库快速扫读的主要价值。它和现有 `Agent Tags` 一样出现在 Zotero 主文献列表的可选自定义栏中。

- 从唯一有效的 `AI4S-Summary:` 块读取 `text`；不联网、不生成、不写入。
- item tree 的 `AI Summary` 栏显示单行省略文本，hover 显示完整的一句话。
- input hashes 与当前 title/abstract 不一致时显示 `Stale` 视觉提示，但不自动刷新。
- 损坏或重复块显示为空，并记录可诊断日志；不得让 Zotero 主界面报错。
- 列可排序；排序只按可见 Summary 文本，不把时间戳混进排序值。

这里的“栏显示”是自定义 item-tree column，不是把整句话写成原生 Zotero tag。Summary 属于长文本；若写成 tag，会造成高基数标签污染、降低筛选可用性，并可能被 Zotero Tags 面板误当作分类词。

## 6. 现有 skills 与能力复用

- `literature-manager`：新增 AI Summary 的触发、写入边界、错误处理和常见误用规则；不另建 skill。
- `literature-research`：新检索得到的 title/abstract 仍由其提供，但 AI Summary 不成为检索或导入默认步骤。
- `literature-writing`：读取 AI Summary 时只把它当导航 metadata，不得据此建立论文论断或替代摘要/全文证据。
- `literature-zotero-mcp`：复用 library identity、Local/Web API 读取、Web API 写入、分页、版本检查、Backoff/429、内部 receipt 和工具注册机制。
- Agent Tags 两阶段工作流：复用“context → Agent 生成 → restricted apply”的接口模式，但不复用 semantic vocabulary 或 tag cleanup。
- `literature-metrics` add-on：复用 custom column 注册、单行渲染、tooltip、notifier 刷新和无网络原则。

本功能不需要新的外部 LLM API 客户端。生成由调用插件的 Agent 完成，MCP 只负责提供受限上下文、验证和持久化。

不新增 Python/CLI helper script；本功能是现有 Node MCP runtime 的接口扩展。主要步骤分别落在两个 MCP tools 和共享 TypeScript feature modules 中，避免再维护一套离线写入脚本。

## 7. 计划修改的源文件

以下路径以仓库根目录为准；`skills/literature-*` 是公开 skill source，
`plugins/ai4s-literature-workbench/source` 是 MCP 与 Zotero add-on source；插件内的
`skills`、`runtime` 和 `fulltext-runtime` 是 assemble 后的 bundle，不应成为唯一
source of truth。

```text
skills/literature-manager/
├── SKILL.md
└── references/
    └── ai-summaries.md

skills/literature-writing/
└── references/writing-contract.md

plugins/ai4s-literature-workbench/source/literature-zotero-mcp/
├── src/features/ai-summaries/
│   ├── contract.ts
│   ├── context.ts
│   ├── extra.ts
│   └── apply.ts
├── src/tools/
│   ├── ai-summary-context.ts
│   └── apply-ai-summaries.ts
├── src/tools/index.ts
├── src/server.ts
├── src/prompts/index.ts
└── tests/features/
    └── ai-summaries.test.ts

plugins/ai4s-literature-workbench/source/literature-metrics/
├── src/ai-summaries.js
├── src/literature-metrics.js
├── tests/ai-summaries.test.mjs
├── tests/literature-metrics.test.mjs
├── README.md
├── manifest.json
└── package.json

plugins/ai4s-literature-workbench/
├── literature-workbench 插件设计.md
├── README.md
├── scripts/verify-runtime.mjs
└── ai-summary-implementation-plan.md
```

实现完成后运行 bundle assemble，把 source-of-truth 更新同步进当前 plugin 的 `skills/`、`runtime/` 和 `bundle-manifest.json`。

## 8. 接口草案

### Context

```json
{
  "collection_key": "ABCD1234",
  "mode": "missing",
  "language": "zh-CN",
  "limit": 50,
  "cursor": null
}
```

或：

```json
{
  "item_keys": ["AAAA1111", "BBBB2222"],
  "mode": "refresh",
  "language": "en",
  "limit": 50
}
```

### Apply

```json
{
  "trigger": "explicit-user-request",
  "mode": "missing",
  "items": [
    {
      "item_key": "AAAA1111",
      "expected_version": 42,
      "title_sha256": "…",
      "abstract_sha256": "…",
      "text": "该研究……。",
      "language": "zh-CN"
    }
  ]
}
```

工具输出只暴露紧凑 summary 与需要用户处理的冲突；详细 receipt 保存在插件私有状态目录。

## 9. 严格边界与灵活项

### 严格边界

- 必须有用户显式触发；不得绑定到 import、project sync、metrics、Agent Tags 或 report 自动执行。
- 必须同时有 title 和 abstract；首版不读取 PDF 或网络来源。
- 不覆盖原始 Abstract，不创建 Note，不写 tag。
- 自动 apply 只能替换唯一 `AI4S-Summary` block。
- 相同输入默认幂等；覆盖已有值需要 `refresh` 明确信号。
- 写入前校验 live item version 和输入 hashes。
- AI Summary 不能在 `literature-writing` 中充当论断证据。

### 灵活项

- 默认生成中文；用户可在显式触发时指定英文或其他输出语言。
- 句子可以侧重研究问题、方法、结果或综述范围，取决于摘要实际提供的信息。
- 单篇、多篇、collection 使用相同底层 contract。
- batch 大小可按 Agent 上下文和 Zotero API 状态调整，但每批上限必须显式且有硬限制。

## 10. 限速与资源控制

- 不新增外部 API，因此没有新的模型 API key 或第三方限速策略。
- Zotero Web API 继续复用现有 1 request/second 默认节流、跨进程 file lock、`Backoff`、`Retry-After`、429 和 5xx 重试逻辑。
- collection context 使用分页；建议首版硬上限为每批 50 条，超出时通过 cursor 继续。
- 工具输出只返回当前批次所需字段，详细 plan/receipt 写文件，避免大 collection 占满上下文。
- Agent 可按批次生成，但 apply receipt 必须支持中断后幂等恢复。

## 11. 错误处理

| 情况 | 默认处理 |
| --- | --- |
| 用户没有显式要求 AI Summary | 不调用 context/apply，也不主动追问 |
| collection 名称不唯一 | 停止，返回候选 collection 的精简信息 |
| attachment/note/annotation | 跳过 `unsupported-item-type` |
| title 缺失 | 跳过 `missing-title` |
| abstract 缺失 | 跳过 `missing-abstract`，不做 title-only 猜测 |
| Summary 多句、过长、换行或含 Markdown | apply 拒绝该条，Agent 修正后可重试 |
| title/abstract 在生成期间改变 | 标记 `stale-input`，重新获取 context 后再生成 |
| item version 冲突 | 重新读取一次；输入未变则按新 version 重试，输入已变则停止该条 |
| 已有有效 Summary，mode=missing | `unchanged`，不覆盖 |
| 已有 Summary 已陈旧，mode=missing | `stale`，提示用户可明确刷新 |
| Summary block 重复或损坏 | 不写，报告 `invalid-summary-block` |
| Web API key 缺失 | context 可完成；apply 明确报告配置缺失，不假装已写入 |
| 429/Backoff/5xx | 沿用现有退避与恢复；receipt 保留未完成条目 |
| 部分 batch 失败 | 返回 partial 摘要；只重试 receipt 中未完成条目 |

## 12. 测试与验收计划

### 12.1 Contract/Extra 单元测试

1. 正确解析、编码和 round-trip `AI4S-Summary` schema v1。
2. 合并 Summary 时保留人工 Extra 和 `AI4S-Metrics`。
3. 只替换唯一 Summary 行；重复或损坏管理块拒绝写入。
4. title/abstract 规范化 hash 稳定，内容变化会产生不同 hash。
5. 多句、换行、Markdown、空文本和超过 240 字符均被拒绝。

### 12.2 Context 测试

1. item keys 与 collection key 互斥且至少提供一个。
2. 未提供 language 时返回 `zh-CN`，显式指定其他语言时正确保留。
3. `missing` 只返回需要生成的条目及紧凑 skip 状态。
4. `refresh` 返回已有有效 Summary 的条目。
5. 无 title/abstract、非普通 item 正确跳过。
6. 大 collection 分页稳定且不重复、不遗漏。

### 12.3 Apply 测试

1. 新 Summary 写入成功且其他 fields/tags/collections 不变。
2. `missing` 模式绝不覆盖并发新增的有效 Summary。
3. `refresh` 只替换 Summary namespace。
4. live input hash 改变时不写。
5. version 冲突可安全重试或准确停止。
6. partial receipt 可恢复；complete receipt 重放为 no-op。
7. apply 未带固定 explicit trigger 枚举时拒绝执行。

### 12.4 Add-on 测试

1. 有效 Summary 显示为单行，tooltip 为完整文本。
2. 缺失、损坏、重复块不导致 UI 错误。
3. title/abstract 改变后显示 stale 状态。
4. Summary 更新后 notifier 刷新列。
5. 排序值只基于文本，且 add-on 不产生任何网络或 item 写入。

### 12.5 端到端验收场景

使用一个含 10 篇普通文献的测试 collection：

- 6 篇 title + abstract 完整且无 Summary；
- 1 篇无 abstract；
- 1 篇已有且 hashes 相同；
- 1 篇已有但 stale；
- 1 篇含损坏 Summary block。

首次显式执行 `missing` 的预期：新增 6、保持 1、跳过无摘要 1、报告 stale 1、冲突 1；原始 Abstract、metrics、tags 和 collection membership 全部不变。

随后用户明确要求 `refresh`，对 stale 条目重新获取 context 并生成；预期只更新其 `AI4S-Summary` 管理块。Zotero 的 `AI Summary` 列显示新文本，原始 Abstract 保持原样。

### 12.6 仓库验证

```bash
cd plugins/ai4s-literature-workbench/source/literature-zotero-mcp && npm test && npm run build
cd plugins/ai4s-literature-workbench/source/literature-metrics && npm test && npm run package
cd plugins/ai4s-literature-workbench
node scripts/assemble-plugin.mjs sync
node scripts/assemble-plugin.mjs check
node scripts/verify-runtime.mjs
```

并运行 repository-root skill tests、plugin package/check 和安装验证。

## 13. 实施顺序

1. Frank 审批本计划整体；中文默认语言和 add-on 同批显示已确认为固定需求。
2. 先实现并测试 Summary schema、hash 和 Extra merge helper。
3. 实现 context 工具与分页/过滤。
4. 实现 apply、内部 plan/receipt、版本冲突与幂等恢复。
5. 更新 MCP 工具注册、server instructions 和显式触发 prompt。
6. 更新 `literature-manager` 与 `literature-writing` 契约。
7. 实现 add-on 的只读 `AI Summary` 列和 stale 提示。
8. 更新设计文档、README、bundle 与 manifest。
9. 完成单元、集成、package、assemble、runtime smoke 和安装验证。

## 14. 本次不做

- 不自动在新导入、项目续更或 Agent Tags 后生成 Summary。
- 不基于 PDF 全文、网页、citation graph 或 Agent 外部知识生成。
- 不翻译或改写原始 Abstract。
- 不生成 collection 级综述；collection report 继续由现有 report 工作流负责。
- 不把 Summary 写入 tag、child Note 或标准 bibliographic 字段。
- 不用 AI Summary 支撑 manuscript claim、Priority 或证据质量判断。
- 不允许 add-on 自行联网调用模型。

## 15. 审批点

建议按以下默认决策实施：

1. metadata 使用独立的 `AI4S-Summary:` Extra schema v1；
2. 缺摘要直接跳过，不做 title-only 降级；
3. 默认只补缺失项，覆盖需要明确 `refresh`；
4. 一次显式自然语言命令即可授权受限写入，不增加第二轮 hash 审批；
5. 默认语言为中文，只有用户明确要求时才改用其他语言；
6. 同批加入只读 `AI Summary` add-on 栏与 stale 提示；不创建长文本原生 tag。

Frank 已批准并完成本计划。最终实现包含 15-tool workbench MCP、默认中文的
`AI4S-Summary` schema v1、显式 `missing/refresh` 两阶段工作流、内部 plan/receipt、
写作证据隔离，以及 `literature-metrics` 0.1.13 的只读 `AI Summary` 栏和 stale
提示。验证结果：MCP 345 passed / 7 live skipped，literature skills 134 passed，
Zotero add-on 19 passed，plugin assemble/check、manifest validation、runtime bootstrap、
15-tool smoke、XPI package 和个人 marketplace cachebuster 重装均通过。
