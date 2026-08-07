> literature-workbench：面向硕博研究生，提供从文献调研到写作（插入引文）的全流程管理周期的ai4s 科研插件

1. 文献检索、导入

2. Agent 文献库管理：评级、标签、期刊metrics、ai summary

3. 基于 zotero 文献库的科学写作，联动 word 插件，自动插入 zotero 文献

## 设计原则

1. 减少用户心智负担，尽量让用户以自然语言指挥 agent，不要给用户额外的决定成本，最理想状态是用户在前端一句话命令，agent 调用插件在后端执行后，反馈真实结果到前端（如 zotero 库更新），不乱编、不打扰、不越界
2. 合理调用 agent 本身强大的能力、但又有硬约束保证不超过边界，基于真实文献数据，保持科学严谨性，这是插件 区别于 其他 ai 工具或者 ai 本身的最大特点
3. 中间文件和 handoff 应足够精炼高效，足够必要，不冗余，不过度工程化，不浪费额外的 token，不占用用户后期审核的精力
4. 工程审计机制默认隐藏在插件内部。正常、可幂等恢复的低风险路径只向用户反馈真实结果；只有歧义匹配、所有权冲突、覆盖风险、破坏性操作或超大批量写入等高风险场景，才升级为用户可见的确认步骤

## 插件设计

Plugin = Skills + Zotero MCP + 可选 Database Browser MCP + 可选 Fulltext MCP +
Zotero add-on + 配置助手

Skills： literature research + literature manager + literature writing；skill 既可以单独使用，又可以handoff

MCP：按外部系统和故障域拆分。Zotero MCP 管理文献库、metadata、报告与附件；
Database Browser MCP 处理 WoS 等商业数据库的有状态检索与官方导出；Fulltext
MCP 负责 OA-first 的全文获取和 PDF 验证。三个执行层由 Skills/Agent 编排，
不进行 MCP-to-MCP 调用。

add-on：提供分区影响因子等标签列

配置助手：初次使用检查环境、路径、让用户提供 api 配置等

api：PubMed 等开放文献接口；easyscholar 提供期刊标签和影响因子。Crossref
已完成前期需求分析，但暂不进入当前实施范围。

Web of Science 不与开放 API 数据源共用访问层。首版面向校园网直接 IP 授权，
使用独立、可见、持久化的 Literature Database Browser MCP 自动完成 Core
Collection 检索、筛选和官方导出，不依赖附着用户日常浏览器的 web-access/CDP 会话；
授权、验证码或风控发生时才让用户人工接管。默认最多导出前 1000 条，再由
本地脚本去重、排名和精选。具体接口、状态机与验收标准见
[`literature-database-browser-mcp-design.md`](literature-database-browser-mcp-design.md)。

## V1核心功能：文献深度调研（MCP+插件）

**V1 主要打通的是文献检索到文献管理（zotero mcp+add-on）的流程**

基于用户给定的主题、科学问题+限定条件（时间、分区、影响因子），

自动规划、拓展生成检索关键词和检索式，

在多个数据库（默认为 PubMed）中进行调研，筛选得到所需的文献集

基于文献，生成调研报告

并将检索到的文献集导入 zotero 作为 collection。`report.md` 同步为该
collection 中唯一的 AI4S Current Report Note，使报告和支撑文献作为一个
持续更新的研究项目共同管理。

首次同步时，用户指定一次 collection；插件保存 project slug、collection
key 和 report Note key 的私有绑定。后续深度检索完成后，agent 直接调用
`zotero_sync_literature_project`：按 DOI/PMID 增量去重、导入新增文献、复用
已有文献，并更新同一份报告 Note。正常路径不向用户暴露 plan、hash、
receipt path 或逐条 JSON，只反馈 collection、创建数、复用数和报告更新状态。

`report.md` 和 ranked evidence 仍是可审计的数据源；Zotero Note 是跨设备
阅读和管理副本。Current Report 由 AI4S 管理，人工批注应放在另一份 Note，
避免下次更新覆盖用户内容。

导入前，若启用 easyscholar，工作流在 `merge_rank` 后将期刊分区与影响因子写回 `ranked_all.json`，再由 `literature-manager plan-import` 将 `AI4S-Metrics:`（schema v2）payload 嵌入新建 Zotero item 的 `Extra`。`literature-metrics` add-on 据此展示 `IF(YYYY)`、`JCR(YYYY)`、`CAS(YYYY)` 列。

对于已存在的旧文献，使用 `literature-manager plan-easyscholar-metrics-backfill` 生成经哈希的 `zotero-metrics` plan，先 dry-run，再通过 `zotero_apply_metrics_plan` 回填同一套列。API key 只从环境变量或本地配置读取，不写入 workflow plan。

默认带有分区、影响因子、文献类型（review、article、clinical study 等）展示在标签栏

同时用户可以决定是否启用 Agent Tags。启用后，Agent 基于 title + abstract
为每篇文献生成零至四个 canonical English semantic tags；无摘要时最多两个
且不生成 mechanism。MCP 优先复用 library-scoped `vocabulary.json` 的
canonical/aliases，只在主要概念确实不存在时新增，并自动写入
`AI4S:Semantic:*`、替换旧语义标签、清除同一批 item 的 Zotero automatic
tags (`type: 1`)。所有手工、Article Type、Priority、JCR/CAS tags 均保留；
每次自动写入仍保存内部 hash plan 与 receipt。add-on 在只读 `Agent Tags`
列显示隐藏 namespace 后的英文 chip。

AI Summary 只在用户显式要求时运行，不随导入、项目续更、metrics、Agent
Tags 或 report 自动生成。Agent 先调用 `zotero_ai_summary_context`，仅基于每篇
文献当前的 title + abstract 生成一句话概括，默认语言为中文；无摘要时跳过，
不做 title-only 猜测。随后 `zotero_apply_ai_summaries` 校验 item version、输入
hash 和单句约束，只合并 `Extra` 中唯一的 `AI4S-Summary:` schema v1 管理块，
保留原始 Abstract、metrics、tags、collection 和其他 Extra。默认 `missing`
模式只补缺失项；用户明确说刷新/重新生成/覆盖时才使用 `refresh`。add-on 在
只读 `AI Summary` 栏单行显示，hover 展示完整句子，title/abstract 变化后显示
stale 警告；整句话不写成原生 Zotero tag。

### Zotero 项目同步的风险边界

低风险路径自动执行：

1. 唯一 DOI/PMID 匹配与复用
2. 完整实时查询未发现 identifier match 后，创建具有 DOI/PMID 的受支持文献类型
3. 只增加 project tag 和 collection membership，不移除用户已有内容
4. 创建缺失的唯一 collection，或创建、更新唯一的 AI4S Current Report Note
5. 根据插件私有 receipt 幂等恢复部分失败的同步
6. 继续消费 `priority_recommendations.json`，并保留用户已有 Priority

以下情况暂停并给出精简风险摘要：

1. 标题模糊匹配、identifier 冲突或重复条目
2. 文献缺少 DOI/PMID，或 Zotero item type 不受支持
3. collection/Current Report Note 缺失、重名、改名或所有权不一致
4. Current Report Note 被人工修改
5. 任何删除、合并、移除标签或移出 collection 的操作
6. 单轮需要新建超过 50 篇文献；该场景经用户一次明确确认后可继续

为了避免长期项目产生运行痕迹污染，项目同步只维护稳定的
`project:<slug>` 归属，不给所有历史文献逐轮累积 `search-date:*` 标签；检索
日期保留在 report、同步状态和内部 receipt 中。

### 当前实现状态（2026-07-21）

- 已新增 `zotero_sync_literature_project`、`zotero_ai_summary_context` 和
  `zotero_apply_ai_summaries`，workbench MCP 工具数增至 15
- 已实现 Markdown 到 Zotero Note HTML 的保守转换，包括标题、列表、表格、链接和代码块
- 已实现首次项目绑定、后续仅凭 project slug 恢复、报告原位更新和远端 HTML 回读校验
- 已实现稳定 ID 增量导入、Priority sidecar、私有状态、内部 receipt、版本检查和高风险升级
- Runtime 全套测试 345 项通过，7 项 live 测试按环境跳过；literature skills 134 项通过
- Zotero add-on 19 项测试、结构检查和 `0.1.13` XPI 打包通过
- Plugin bundle、manifest、15-tool MCP smoke 和本地重装验证通过；当前开发缓存版本为 `0.1.0+codex.20260721025727`
- AI Summary contract、受限写入、内部 plan/receipt、中文默认语言、stale
  检测和 Zotero `AI Summary` 栏已实现；不得把 Summary 当作科学写作证据

## V1 拓展功能

1. 期刊信息补充回填：对于文献库中 已有的旧文献（不是经过本流程得到的），也可以补充 IF 、分区信息等 metadata
2. 领域文献更新（V1 已实现基础闭环）：对于某个已调研过的领域主题，Zotero 中已有 collection 和 Current Report Note；用户可不定时让 agent 继续检索，将去重后的新增文献追加到 collection，并基于累计证据更新同一份报告
3. AI Tags、report and AI Summary（已实现基础闭环）：自动推荐 tags；将调研
   report 存放到 collection；用户显式触发后，按 title + abstract 为目标文献
   生成默认中文的一句话 Summary，安全写入 metadata 并在 Zotero 自定义栏显示
4. PDF 全文获取：根据精确 DOI、arXiv ID 或可信全文链接，优先从无需校园网的
   开放获取来源取得主文 PDF；OA 不可用时，才按用户已有的合法订阅权限回退到
   校园网、用户已连接的官方 VPN、出版社 API 或可见机构认证浏览器。PDF 经
   identifier、主文角色和文件完整性验证后，由 Zotero MCP 幂等附加到精确父条目。
   普通检索/导入不隐式下载全文，需用户明确请求或为项目启用
   `fulltext_policy: selected-missing`。具体职责、工具、handoff、状态机、合规边界与
   验收标准见
   [`literature-fulltext-mcp-design.md`](literature-fulltext-mcp-design.md)。
5. 数据源拓展：第一版只增加 WoS Core Collection，通过校园网环境下的
   Literature Database Browser MCP 获取官方导出，而不是把网页 DOM 当作正式
   检索记录。MCP 使用通用 `database_*` 接口，但 V1 capability registry 只声明
   WoS；Crossref 及其他数据库暂缓。
