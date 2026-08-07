# Crossref 与 WoS 自动检索实施计划

> 状态：Crossref 暂缓；本文不再作为 WoS V1 的实施依据（2026-07-22）  
> 目标：为 `literature-research` 增加 Crossref 开放元数据检索，并把现有 WoS“人工浏览器导出”升级为校园网环境下由 Agent 自动检索、筛选和官方导出的可靠工作流。

> WoS V1 已拆分为独立设计，当前 source of truth 为
> [`literature-database-browser-mcp-design.md`](literature-database-browser-mcp-design.md)。
> 保留本文仅用于记录此前的 Crossref 需求分析，不进入当前实施范围。

## 0. 已确认的产品决策

1. Crossref 与 WoS 是两个不同的数据源模块，不共享认证或浏览器实现。
2. Crossref 使用公开 REST API；首版不要求 API key，推荐通过 `CROSSREF_MAILTO` 提供联系邮箱并使用现有请求节流、重试和缓存约定。
3. WoS 首版只面向校园网直接 IP 授权，不实现学校 VPN、WebVPN URL 改写、Cookie 导出或凭据托管。
4. WoS 默认数据库为 **Web of Science Core Collection**，不使用 `All Databases` 作为默认入口。
5. WoS 使用独立、可见、持久化的浏览器 Profile，由专用 Broker 启动并拥有浏览器进程；不依赖 web-access/CDP 附着到用户正在使用的浏览器。
6. 用户只处理首次授权、验证码、风控或会话失效；会话可用时，Agent 自动完成检索、筛选、排序和官方导出。
7. WoS 单次最多自动导出前 1000 条，再由本地脚本去重和排名；进入 Zotero 的条目仍遵守现有默认精选和超过 50 个新建条目时的确认门槛。
8. 初始结果过多时，Agent 可以调整同义词、字段或筛选条件并再次检索，但不得悄悄改变科学问题；每次尝试必须写入 query history。
9. WoS 记录必须来自官方导出文件，不用 DOM 抓取结果列表替代正式证据文件，不调用未公开的 WoS 内部接口。

## 1. 能力边界

| 能力 | Crossref | WoS |
|---|---|---|
| 主要价值 | 跨学科 DOI/出版物元数据发现、补全与去重 | 订阅级引文索引检索、主题筛选和官方记录导出 |
| 访问方式 | 公开 REST API | 校园网 IP 授权下的可见浏览器 |
| API key | 不需要；`mailto` 推荐但不作为阻塞条件 | 首版不使用官方 API |
| 摘要 | 覆盖不稳定，缺失时必须保留为空 | 取决于机构订阅与官方导出字段 |
| 引用数 | `is-referenced-by-count` 只能作为 Crossref 时点快照 | 使用官方导出可用字段；不得与其他来源假定等价 |
| 全文 | 不负责 | 不负责；导出的 DOI 可后续交给全文获取模块 |
| 默认角色 | 条件性补充源，不取代 PubMed | 用户明确要求或问题需要引文数据库覆盖时启用 |

Crossref、PubMed、arXiv、可选引用数据源和 WoS 的结果统一进入现有 `merge-rank`，但必须保留 `source`、稳定 ID、检索时间、查询上限和各数据库限制。Zotero 库存在性不能替代任何源数据库检索。

## 2. 总体架构

```text
自然语言科学问题
  → literature-research 生成共享 query plan
      ├─ Crossref adapter → Crossref JSON
      ├─ PubMed/arXiv adapters → source JSON
      └─ WoS browser broker
           → Core Collection 检索
           → 结果数验证与可选查询迭代
           → 官方 CSV/TSV 导出
           → import-wos-export → WoS JSON
  → merge-rank → ranked_all.json / ranked_all.csv
  → report.md
  → literature-manager（精选证据与 Zotero 同步）
```

不创建新的 umbrella skill。`literature-research` 继续拥有检索规划、源路由、证据规范化和排名；WoS Broker 是一个独立、可选的本地运行时，只负责可靠浏览器会话和官方导出，不接管科学检索决策。

## 3. Crossref 实施设计

### 3.1 CLI 与查询契约

新增命令：

```bash
uv run literature-research/scripts/literature_search.py search-crossref \
  --query 'cardiac fibrosis AND single-cell' \
  --limit 100 \
  --from-year 2020 \
  --until-year 2026 \
  --type journal-article \
  --output crossref_raw.json
```

参数：

- `--query` 或 `--query-json` + `--query-field crossref_query` 二选一；
- `--limit` 必填，禁止无上限检索；
- `--from-year`、`--until-year`、`--type` 为可选的受控过滤器；
- `--mailto` 为本轮覆盖值，否则读取 `CROSSREF_MAILTO` 或现有私有本地配置中的 email；
- 首版不暴露任意原始 `filter` 字符串，避免不可审计参数和转义错误。

普通小批量请求使用 `rows`；超过单页容量时使用 cursor 分页，直到达到显式 `--limit`、API 返回结束或出现不可恢复错误。分页去重以规范化 DOI 为主，缺少 DOI 时以标题、年份和第一作者的保守组合键为辅。

### 3.2 标准化记录

Crossref 输出沿用现有 source JSON 外壳，每条记录至少包含：

```json
{
  "source": "crossref",
  "id": "10.1234/example",
  "doi": "10.1234/example",
  "title": "Example title",
  "abstract": "",
  "year": 2025,
  "authors": ["Family, Given"],
  "journal": "Example Journal",
  "issn": ["1234-5678"],
  "article_types": ["journal-article"],
  "url": "https://doi.org/10.1234/example",
  "citation": {
    "count": 12,
    "provider": "crossref",
    "retrieved_at": "2026-07-21"
  }
}
```

规则：

- DOI 去掉 `https://doi.org/`、`doi:` 前缀并小写；显示 URL 统一为 `https://doi.org/<doi>`。
- 标题、期刊名和作者数组按 Crossref message 的候选字段保守提取，不凭空补齐。
- 发表年份采用明确的字段优先级并保存解析规则；无法可靠解析时为 `null`。
- Crossref 的 JATS/XML 摘要只做安全纯文本清理；没有摘要就保持空值，不能用标题生成摘要。
- `is-referenced-by-count` 标记为 Crossref 时点快照，不与 WoS 或其他数据源的引用数直接比较。
- API 原始响应不作为默认第五份工作流产物；测试 fixture 与错误诊断样本除外。

### 3.3 路由与工作流集成

更新 `DATABASE_ROUTES`，新增：

```python
"crossref": {
    "display_name": "Crossref",
    "access_mode": "api-first",
    "primary_tool": "search-crossref",
    "requires_web_access": False,
    "pattern_reference": "references/database-patterns/crossref.md"
}
```

同时：

- `plan`/query expansion 增加 `crossref_query`，默认使用紧凑的题名/摘要关键词，不照搬 PubMed MeSH 语法；
- `workflow-plan`、`database-route` 和可选数据库规划能够识别 Crossref；
- `review` 增加显式 `--crossref` 开关，但仍保持 PubMed-first 默认路径；
- 复用当前 Crossref citation lookup 的 `CROSSREF_BASE`、联系邮箱解析、rate limiter 和错误分类，抽取共享 HTTP/解析函数，避免两套实现漂移；
- `429`、`5xx` 和瞬时网络错误按现有退避策略重试；最终失败必须写出明确 source failure，不能伪装为空结果。

## 4. WoS 专用浏览器 Broker

### 4.1 为什么不用现有 web-access 主路径

现有路径可以打开已有登录态的 WoS，但搜索动作依赖附着到用户浏览器的 CDP target。标签页重建、React 重新渲染、受控输入框、旧 locator、重定向或 CDP 连接变化，都可能导致“页面已打开但检索没有真正提交”。

WoS 首版改为 Playwright `launchPersistentContext`：

- Broker 自己启动并关闭专用 Chrome/Chromium；
- 使用独立 `userDataDir` 保存完整浏览器状态；
- `headless: false`，始终允许用户看见并接管；
- 优先使用本机稳定版 Chrome，找不到时才使用经过验证的 bundled Chromium；
- 不通过坐标点击，不复用用户日常浏览器 Profile，不使用 Cookie JSON 重放；
- CloakBrowser 只保留为后续经证据证明需要时的可替换 adapter，不进入首版依赖。

### 4.2 MCP/Broker 接口

浏览器任务可能超过普通 MCP 调用超时，因此采用异步 job，而不是一个长时间阻塞的 `wos_search_export`：

1. `wos_session_status`
   - 启动或检查专用浏览器；
   - 返回 `ready | auth_required | unavailable | blocked`；
   - 不返回 Cookie、localStorage 或完整页面内容。
2. `wos_search_submit`
   - 输入精确 WoS query、过滤器、排序、上限和 query attempt ID；
   - 立即返回 `job_id`，由 Broker 后台执行。
3. `wos_search_status`
   - 返回当前状态、结果数、是否需要人工接管、简短错误码和完成后的官方导出/receipt 位置；
   - Agent 以有限频率轮询，不并发重复提交同一任务。

输入草案：

```json
{
  "database": "wos-core-collection",
  "query": "TS=((cardiac fibrosis) AND (single-cell OR single nucleus))",
  "filters": {
    "from_year": 2020,
    "until_year": 2026,
    "document_types": ["Article", "Review"]
  },
  "sort": "relevance",
  "export_limit": 1000,
  "attempt_id": "wos-01"
}
```

Broker 不生成或修改科学检索式，只执行经过 Agent 规划的精确输入。

### 4.3 浏览器状态机

```text
SESSION_STARTING
  → SESSION_READY
  → SEARCH_FORM_READY
  → QUERY_COMMITTED
  → SEARCH_SUBMITTED
  → RESULTS_VERIFIED
  → FILTERS_APPLIED
  → EXPORT_STARTED
  → DOWNLOAD_VERIFIED
  → COMPLETE
```

可恢复分支：

- `AUTH_REQUIRED`：页面提示授权、登录或机构访问不可用，等待用户处理后继续；
- `MANUAL_INTERVENTION_REQUIRED`：验证码、风控或页面结构无法安全识别；
- `RETRYABLE_FAILURE`：导航超时、短暂断网、元素被重新渲染；从最近安全状态有限重试；
- `FAILED`：达到重试上限或导出校验失败，保留诊断信息但不声称已完成；
- `STALE`：Broker/浏览器进程丢失或 heartbeat 超时，任务可由 receipt 判断是否恢复。

每一状态都必须用页面事实验证，而不是依赖固定 sleep：

- 搜索页：Core Collection 标识和可交互检索表单已出现；
- 查询提交：输入框值或查询条件 chip 与请求语义一致；
- 结果页：URL/页面标题改变并出现可解析的结果总数；
- 筛选：页面展示的已选条件与请求一致，结果状态完成刷新；
- 导出：Playwright 捕获 download 事件，文件落盘、非空、扩展名和表头通过校验。

### 4.4 Locator 与交互策略

WoS Page Object 使用分层 locator：

1. 可访问性 role + 明确 label；
2. 稳定的表单语义、placeholder 或官方可识别属性；
3. 经 fixture 验证的受控 fallback。

禁止把短期 CSS class、DOM 序号、屏幕坐标或单一英文按钮文本作为唯一定位依据。输入流程使用 `fill` 后读回值，必要时触发 blur/键盘提交，并在 React 重渲染后重新解析 locator。点击后必须等待可验证的状态变化；“click resolved”不等于“搜索成功”。

### 4.5 查询迭代策略

Agent 读取首次结果数后：

- 结果为 0：检查字段语法、括号、术语过窄和年份限制；
- 结果过多：优先增加关键概念、限定 Topic 字段、年份或文献类型；
- 结果适中：保持原查询并进入导出；
- 无论是否调整，都把 `attempt_id`、精确 query、filters、result_count、时间和调整理由追加到 `search_plan.json.query_history`；
- 最终报告只把实际导出的那一次标记为 selected attempt，并披露 1000 条上限。

不得为了获得“漂亮数量”删除关键科学概念，也不得把检索迭代描述成系统综述的完整敏感性/特异性验证。

### 4.6 导出与 receipt

默认选择 WoS 官方支持且现有 parser 可处理的 CSV 或 tab-delimited full record 字段。若官方单次导出上限低于目标数量，Broker 按 UI 允许的区间顺序分批导出，再由 importer 合并、按 UT/DOI 去重。

每个 job 保存紧凑 `search_receipt.json`：

```json
{
  "schema_version": 1,
  "job_id": "...",
  "database": "wos-core-collection",
  "attempt_id": "wos-01",
  "query_sha256": "...",
  "filters": {},
  "sort": "relevance",
  "reported_result_count": 842,
  "requested_export_limit": 1000,
  "exported_record_count": 842,
  "export_files": ["savedrecs.txt"],
  "status": "complete",
  "started_at": "...",
  "completed_at": "..."
}
```

receipt 保存 query hash，精确 query 继续由 `search_plan.json` 作为 source of truth，避免多份冗余长文本。普通用户反馈只显示数据库、结果数、导出数和是否完成，不暴露 job 私有目录、heartbeat 或截图路径。

## 5. 数据与安全策略

- 浏览器 Profile、WoS 导出、截图、trace、receipt 和 subscription records 全部保存在仓库外的私有应用数据目录。
- POSIX 上新建目录尽可能使用 owner-only 权限；Windows 使用当前用户应用数据目录，不放入同步盘。
- 不保存用户名、密码、API key、Cookie JSON、完整 localStorage dump 或带敏感查询参数的日志。
- 截图和 trace 可能包含检索主题，只在失败时按配置保存并设置过期清理；默认成功任务不留全程 trace。
- 不绕过 CAPTCHA、机构授权、许可条款、导出上限、反自动化保护或并发限制。
- 校园网权限不可用时返回 `auth_required`，不自动尝试 WebVPN、代理或其他机构凭据。
- Crossref 与 WoS 网络错误、空结果和解析失败必须区分；任何失败都不得被报告成“未发现相关文献”。

## 6. 计划修改的源文件

以下以仓库 source-of-truth 根目录为准；实现完成后再 assemble 到 plugin bundle：

```text
literature-research/
├── SKILL.md
├── references/
│   ├── advanced-recipes.md
│   ├── query-planning.md
│   ├── source-policy.md
│   └── database-patterns/
│       ├── crossref.md                 # 新增
│       └── webofscience.md             # 改为专用 Broker 路径
├── scripts/literature_search.py        # Crossref search、route、plan、review 集成
└── tests/
    ├── fixtures/crossref_sample.json   # 新增
    ├── fixtures/wos_sample.tsv
    └── test_literature_search.py

literature-database-browser/            # 新的独立 Node/Playwright runtime
├── package.json
├── src/
│   ├── index.ts
│   ├── server.ts
│   ├── broker/
│   │   ├── job-store.ts
│   │   ├── session.ts
│   │   └── state-machine.ts
│   └── wos/
│       ├── contract.ts
│       ├── page-object.ts
│       ├── search.ts
│       ├── export.ts
│       └── verify.ts
├── tests/
│   ├── fixtures/                       # 本地仿真页，不提交 WoS 页面副本
│   ├── state-machine.test.ts
│   ├── wos-page-object.test.ts
│   └── wos-contract.test.ts
└── scripts/configure.mjs

plugins/ai4s-literature-workbench/
├── .mcp.json                           # 注册第二个、可选的 browser MCP
├── scripts/assemble-plugin.mjs         # bundle 新 runtime
├── scripts/bootstrap-runtime.sh
├── scripts/bootstrap-runtime.ps1
├── scripts/verify-runtime.mjs
├── literature-workbench 插件设计.md
└── crossref-wos-implementation-plan.md
```

WoS 浏览器能力不应塞入 `literature-zotero-mcp`：它与 Zotero 的身份、数据权限和写入风险完全不同，拆分运行时可以避免 Playwright 依赖、浏览器崩溃或长任务影响 Zotero MCP。

## 7. 实施阶段

### Phase A：Crossref 独立数据源

1. 抽取并复用 Crossref HTTP、mailto、节流和错误处理。
2. 实现搜索分页、字段规范化和 fixture 测试。
3. 注册 database route、query plan 和 `review --crossref`。
4. 更新 skill/reference 文档和报告 limitation。

完成标准：无 API key 情况下可用；显式 limit 生效；DOI/标题/作者/年份/期刊正确规范化；429/5xx/空结果/坏记录均有测试；可与 PubMed/arXiv/WoS JSON 一起 `merge-rank`。

### Phase B：WoS Broker 骨架

1. 创建独立 runtime、持久 Profile、私有 job store 和 heartbeat。
2. 注册三个 MCP tools 与输入 schema。
3. 用本地仿真页验证 React 重渲染、locator 重取、异步下载和状态恢复。
4. 增加截图/trace 的失败诊断与过期策略。

完成标准：MCP 调用不因浏览器长任务阻塞；Broker 重启后可识别未完成 job；所有返回状态都是稳定枚举。

### Phase C：WoS Core Collection adapter

1. 实现 Core Collection readiness、检索提交和结果数验证。
2. 实现年份、Article/Review 类型、relevance 排序。
3. 实现最多 1000 条的官方 CSV/TSV 导出与分批处理。
4. 对接现有 `import-wos-export`，生成规范化 JSON 与 receipt。

完成标准：在 Frank 的校园网环境中连续完成 3 次不同查询；每次均能证明 query 已提交、结果数已出现、过滤器已应用、下载已落盘且 importer 记录数与导出一致。

### Phase D：Agent 自动迭代与插件集成

1. 在 `literature-research` 中加入 query history/selected attempt 契约。
2. 更新 WoS database pattern，不再把 web-access 作为默认执行器，只保留人工排障 fallback。
3. 更新 assemble/bootstrap/verify，使 Playwright runtime 是明确的可选组件；Crossref 不依赖它。
4. 完成 plugin smoke、bundle drift 和安装验证。

完成标准：用户一句自然语言命令可触发“规划 → WoS 搜索 → 必要时调整 → 官方导出 → normalize → merge-rank”；授权失效或风控时只要求用户完成必要的可见浏览器操作。

## 8. 测试与验收矩阵

### Crossref

- 单页与 cursor 多页；
- DOI 大小写、前缀和重复记录；
- 缺摘要、缺作者、多个 ISSN、online/print 日期差异；
- JATS/XML 摘要清理；
- `429`、`5xx`、超时、畸形 JSON、部分坏记录；
- Crossref citation snapshot provenance；
- `database-route`、`workflow-plan`、`review --crossref`；
- 与其他来源的 DOI 去重和合并排名。

### WoS 本地自动化

- 表单延迟可用、React 重渲染和旧节点失效；
- fill 后值未提交、按钮点击无页面变化；
- 结果为 0、结果过多和结果数延迟出现；
- 筛选后结果刷新；
- 单文件、分批文件、空文件、错误表头和下载超时；
- Broker 心跳丢失、浏览器被用户关闭、job 恢复；
- `AUTH_REQUIRED` 与 `FAILED` 不被误报为 0 records。

### WoS live（显式启用，不进入普通 CI）

- 仅在校园网和用户授权环境运行；
- 连续 3 次不同检索；
- 至少一次包含年份和文献类型过滤；
- 至少一次触发查询调整并保留 history；
- 至少一次超过单批导出范围的分段导出（若当前 UI 限制允许安全测试）；
- 对导出文件运行 `import-wos-export` 并核对 receipt。

### Plugin

- literature-research Python 全套测试；
- browser runtime typecheck、unit、local Playwright integration；
- Zotero MCP 原有测试不得因第二个 MCP runtime 回归；
- assemble `sync/check`、bootstrap、plugin manifest 和双 MCP smoke；
- 干净环境未安装浏览器可选组件时，Crossref/PubMed/Zotero 仍能正常使用，并给 WoS 返回可操作的 unavailable 状态。

## 9. 非目标与后续候选

首版明确不做：

- 自动连接学校 VPN、EasyConnect/aTrust 或 WebVPN；
- 保存或注入学校账号密码；
- WoS 内部接口逆向、DOM 结果抓取或 CAPTCHA 绕过；
- Scopus、Embase 等第二个商业数据库；
- 自动下载全文或把全文返回给 Agent；
- 把 Crossref 作为 PubMed 的默认替代来源；
- 用不同数据库的 citation count 做未经校准的直接排名比较。

首版稳定后，可评估把 Page Object/Broker 抽象成通用 `institutional-database-browser` adapter，并按数据库逐个验证；不得在 WoS 未稳定前预先设计一个复杂的通用商业数据库框架。

## 10. 实施顺序结论

先实现 Crossref，因为它是无浏览器依赖、可离线 fixture 完整测试的低风险数据源；再实现独立 WoS Broker 骨架和本地仿真测试；最后只在校园网环境进行 WoS live 适配。这样即使 WoS 页面结构发生变化，也不会影响 PubMed、Crossref、arXiv、Zotero 或科学写作主链路。
