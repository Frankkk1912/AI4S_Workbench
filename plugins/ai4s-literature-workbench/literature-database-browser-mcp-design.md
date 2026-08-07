# Literature Database Browser MCP 设计文档

> 状态：V1 设计已确认，待实现（2026-07-22）  
> V1 支持范围：仅 `wos-core-collection`  
> 定位：为 `literature-research` 提供商业文献数据库的有状态浏览器执行层；V1 在校园网直接 IP 授权环境中自动执行 Web of Science Core Collection 检索与官方导出。

## 1. 设计结论

`literature-research` 继续采用 **Skill + CLI** 作为主链路，新增独立的 **Literature Database Browser MCP** 处理 WoS 这种有状态、动态、可能需要人工接管的浏览器任务。

```text
literature-research Skill
  ├─ 理解科学问题、规划 WoS 检索式和筛选条件
  ├─ 调用 Database Browser MCP 完成搜索与官方导出
  └─ 调用 literature_search.py 完成导入、去重、排名和报告

Literature Database Browser MCP
  ├─ 持久浏览器会话
  ├─ WoS 页面状态机
  ├─ 异步 search/export jobs
  ├─ 下载校验与失败恢复
  └─ 必要时让用户在可见浏览器中接管
```

MCP 不替代现有 CLI，不返回大批文献记录，也不负责科学检索决策。它只把“精确查询与筛选条件”可靠地变成“经过验证的 WoS 官方导出文件”。

## 2. 产品目标

V1 必须实现：

1. 在校园网可直接访问 WoS 的环境下启动独立、可见、持久化的浏览器。
2. 由 Agent 提交精确的 WoS Core Collection Advanced Search 检索式。
3. 验证检索确实执行成功，而不是仅验证 click/fill 调用没有报错。
4. 应用年份、文献类型和排序等首版筛选条件。
5. 先返回筛选后的结果数量，让 Agent 决定保留、缩窄或重新检索。
6. 对最终选中的 query attempt 自动完成官方导出，最多 1000 条。
7. 将官方导出文件交给现有 `import-wos-export` CLI，而不是通过 MCP 传递数百条记录。
8. 登录失效、验证码、页面异常或浏览器关闭时提供明确状态和人工接管路径。
9. 保存紧凑、可恢复的内部 job state 与 receipt，正常情况下只向用户反馈真实结果摘要。

## 3. V1 非目标

V1 不实现：

- Crossref；该数据源暂缓，未来仍应使用 API + CLI，而不是本 MCP；
- Scopus、Embase、EBSCOhost、ProQuest、CNKI 等第二个数据库 adapter；
- 自动连接学校 VPN、EasyConnect、aTrust 或 WebVPN；
- 学校账号、密码、Cookie JSON 或 localStorage 导入导出；
- WoS 官方 API、未公开内部接口逆向或网络请求重放；
- DOM 抓取文献列表来代替 WoS 官方导出；
- CAPTCHA、访问控制、许可限制、下载限制或反自动化机制绕过；
- 全文获取、PDF 下载或 Zotero 写入；
- 系统综述协议自动生成或检索质量的自动认证。

## 4. 为什么是独立 MCP

WoS 与 Zotero 的职责、依赖和故障模式完全不同，因此不能放进 `literature-zotero-mcp`：

| 维度 | Database Browser MCP | Zotero MCP |
|---|---|---|
| 外部系统 | 商业数据库网页 | Zotero Desktop/Web API |
| 主要状态 | 浏览器、页面、下载、job | library、item version、collection |
| 主要依赖 | Playwright + Chrome/Chromium | Zotero API clients |
| 常见阻塞 | 页面加载、授权、验证码、下载 | 429、版本冲突、匹配歧义 |
| 用户接管 | 可见浏览器 | 通常不需要 GUI |
| 数据结果 | 官方导出文件 | Zotero item 写入/读取 |

独立进程可以保证浏览器崩溃、长任务和 Playwright 依赖不会影响 Zotero MCP。插件中注册第二个 MCP server，但缺少该可选 runtime 时 PubMed、arXiv、Zotero 和写作能力必须继续正常工作。

## 5. 命名与未来兼容

项目和 MCP server 使用通用名称：

```text
package: literature-database-browser
MCP server: ai4s-literature-database-browser
```

工具使用 `database_*` 前缀，不使用 `wos_*`。V1 capability registry 只声明：

```json
{
  "supported_databases": ["wos-core-collection"]
}
```

内部采用 Broker core + adapter registry，但 V1 只实现 WoS adapter。不得为了尚未支持的数据库预先构造复杂通用 DSL；未来 adapter 通过带判别字段的 schema union 扩展。

## 6. 用户体验

目标交互：

```text
用户：检索 2020 年以来心肌纤维化单细胞研究，并加入这个项目。

Agent：
1. 生成并保存 WoS query plan
2. 检查/打开专用 WoS 浏览器
3. 提交检索并等待结果验证
4. 读取结果数量
5. 数量过大时调整检索式并保留 query history
6. 对最终 attempt 发起官方导出
7. CLI 解析、去重、排名并生成报告
8. 通过 literature-manager 同步精选证据到 Zotero
```

正常路径不要求用户选择浏览器、文件格式、导出字段或保存目录。只有以下情况打断用户：

- 校园网/IP 授权不可用；
- WoS 要求机构登录、验证码或其他人工操作；
- 页面结构无法安全识别；
- 导出上限或许可提示需要用户判断；
- 浏览器被关闭且自动恢复失败。

## 7. MCP 工具设计

### 7.1 `database_browser_capabilities`

只读。让 Skill 在规划前确认实际支持范围和 V1 限制。

输入：无。

输出示例：

```json
{
  "schema_version": 1,
  "supported_databases": [
    {
      "id": "wos-core-collection",
      "display_name": "Web of Science Core Collection",
      "access_mode": "campus-ip-visible-browser",
      "query_modes": ["advanced-search"],
      "filters": ["year-range", "document-types"],
      "sorts": ["relevance", "date-desc", "citations-desc"],
      "export_formats": ["tab-delimited-full-record"],
      "max_export_records": 1000
    }
  ]
}
```

### 7.2 `database_session_open`

启动或复用数据库专用持久浏览器会话。该工具会产生可见浏览器窗口，因此不能标记为 read-only。

输入：

```json
{
  "database": "wos-core-collection"
}
```

输出：

```json
{
  "database": "wos-core-collection",
  "session_state": "ready",
  "user_action_required": false,
  "message": "WoS Core Collection search is ready."
}
```

若校园授权不可用，浏览器保持可见并返回 `auth_required`；工具不得尝试其他代理、VPN 或机构凭据。

### 7.3 `database_session_status`

只读。检查已有会话，不隐式启动浏览器。

会话状态：

- `closed`
- `starting`
- `ready`
- `auth_required`
- `manual_intervention_required`
- `unavailable`
- `stale`

输出不包含 Cookie、storage、完整 DOM 或含查询参数的敏感 URL。

### 7.4 `database_search_submit`

提交一个精确 query attempt。V1 只执行检索、筛选、排序和结果数验证，**不自动导出**。

输入示例：

```json
{
  "database": "wos-core-collection",
  "attempt_id": "wos-01",
  "query": {
    "mode": "advanced-search",
    "value": "TS=((cardiac fibrosis) AND (single-cell OR single nucleus))"
  },
  "filters": {
    "from_year": 2020,
    "until_year": 2026,
    "document_types": ["Article", "Review"]
  },
  "sort": "relevance",
  "request_id": "sha256-of-canonical-input"
}
```

规则：

- `attempt_id` 在当前 query plan 中唯一；
- `request_id` 用于幂等提交，同一 canonical input 不得创建重复 job；
- `query.value` 必须是 Skill 已保存的精确 WoS Advanced Search 语句；
- MCP 不添加同义词、不改变逻辑、不自动删改检索式；
- 首版不操作 Basic Search 的多行 query builder，减少受控输入框和动态行状态带来的不稳定性。

提交后立即返回 `job_id`，不阻塞等待页面完成。

### 7.5 `database_search_status`

只读。查询 search/export job 的状态。

当检索完成时：

```json
{
  "job_id": "job-...",
  "attempt_id": "wos-01",
  "phase": "search",
  "state": "results_ready",
  "reported_result_count": 842,
  "applied_filters": {
    "from_year": 2020,
    "until_year": 2026,
    "document_types": ["Article", "Review"]
  },
  "can_export": true,
  "user_action_required": false
}
```

Agent 将该结果追加到 `search_plan.json.query_history`。若结果过多或过少，Agent 创建新的 attempt；旧 attempt 保留审计信息，但不导出。

### 7.6 `database_export_submit`

只允许对 `results_ready` 的 job 发起官方导出。Agent 已经判断该 attempt 为最终候选时自动调用，不需要再次询问用户。

输入：

```json
{
  "job_id": "job-...",
  "limit": 1000,
  "format": "tab-delimited-full-record",
  "request_id": "sha256-of-job-and-export-options"
}
```

规则：

- `limit` 为 `1..1000`，实际导出数为 `min(result_count, limit)`；
- 使用 WoS 官方 Full Record 导出路径；若当前 UI 单批上限较低，则按连续区间分批；
- 同一个 export `request_id` 幂等，重试不得产生不可识别的重复批次；
- 完成后仍通过 `database_search_status` 返回结果，不增加另一个 status 工具。

### 7.7 `database_job_cancel`

取消尚未完成的 search/export job。已经由浏览器开始的下载允许完成落盘，但 canceled job 的文件不得作为成功证据交给 CLI。

取消是显式动作；Agent 只在用户撤销任务、提交了错误检索式或已有替代 attempt 时调用。

## 8. 两阶段执行模型

搜索和导出必须分开：

```text
database_search_submit
  → results_ready + result_count
      ├─ 数量/语义不合适 → 新 attempt
      └─ 接受该 attempt → database_export_submit
                             → complete + export handoff
```

原因：如果搜索后立即导出，Agent 无法根据真实结果数缩窄检索式，会产生无用的大文件和额外许可负担。两阶段模型仍然是“Agent 自动检索和导出”，只是把科学判断留在 Skill 层，而不是交给浏览器 Broker。

## 9. 状态模型

### 9.1 会话状态机

```text
closed
  → starting
  → ready
      ├─ auth_required
      ├─ manual_intervention_required
      ├─ stale
      └─ closed
```

`ready` 的判定至少需要：

- 浏览器进程和 context 存活；
- 页面属于允许的 WoS/Clarivate 导航范围；
- Core Collection Advanced Search 可访问；
- 检索表单可见且可交互；
- 页面没有明确显示无机构权限、登录要求或阻塞提示。

### 9.2 Job 状态机

```text
queued
  → starting_session
  → navigating
  → search_form_ready
  → query_committed
  → search_submitted
  → waiting_results
  → applying_filters
  → results_ready
  → export_queued
  → exporting
  → verifying_download
  → complete
```

分支状态：

- `user_action_required`
- `retrying`
- `failed`
- `canceled`
- `stale`

job state 必须持久化到仓库外的私有应用数据目录。Broker 重启后：

- `complete`、`failed`、`canceled` 保持终态；
- 下载文件已经验证的 job 可以恢复为 `complete`；
- 页面中间状态不得盲目续点，重新验证会话和当前页面后从最近安全 checkpoint 重做幂等步骤；
- 无法证明已完成的 job 不能标记成功。

## 10. WoS 页面适配策略

### 10.1 浏览器所有权

- Playwright 使用 `launchPersistentContext`；
- `headless: false`；
- Broker 使用独立 Profile，不附着用户日常 Chrome；
- 优先使用本机稳定版 Chrome，找不到时才使用插件明确安装的 Chromium；
- Profile 按 database adapter 隔离；V1 只有 WoS Profile；
- MCP server 启动时不自动打开浏览器，首次 `database_session_open` 时惰性启动；
- 空闲超过配置 TTL 且没有活动 job 时可以关闭浏览器，但保留 Profile。

### 10.2 Locator 优先级

1. accessibility role + label；
2. 稳定表单语义、placeholder 或明确属性；
3. 经测试的 adapter fallback。

禁止把以下内容作为唯一定位方式：

- 屏幕坐标；
- 短期生成的 CSS class；
- DOM 第几个元素；
- 单一语言的按钮文本；
- 一次页面快照中的 locator handle。

WoS 重渲染后必须重新解析 locator。不得长期缓存 element handle。

### 10.3 动作后验证

| 动作 | 成功证据 |
|---|---|
| 打开检索页 | Core Collection 与 Advanced Search 表单可交互 |
| 输入 query | 读回值与 canonical query 一致 |
| 提交 query | 页面进入结果状态，出现可解析结果数或明确 0 records |
| 应用筛选 | 页面展示的已选条件与请求一致，结果刷新结束 |
| 设置排序 | 当前排序标签与请求一致 |
| 发起导出 | 捕获官方 download 事件或明确批次下载开始 |
| 下载完成 | 文件存在、非空、格式/表头有效、批次范围连续 |

“Playwright click 成功”不是业务成功证据。每一步都必须等待可验证状态变化，固定 sleep 只能作为短暂节流，不能作为完成判据。

## 11. 错误与人工接管

稳定错误码：

| 错误码 | 含义 | 默认处理 |
|---|---|---|
| `CAMPUS_ACCESS_REQUIRED` | 当前网络没有机构访问权 | 提示切换校园网；不尝试 VPN |
| `AUTH_REQUIRED` | WoS 要求登录/机构认证 | 保持可见浏览器，等待用户完成 |
| `CAPTCHA_OR_CHALLENGE` | 验证码或风控挑战 | 人工接管；不绕过 |
| `PAGE_CONTRACT_CHANGED` | 关键页面状态无法识别 | 保存精简诊断，停止自动动作 |
| `QUERY_NOT_COMMITTED` | 输入值未被 WoS 接受 | 重新定位与有限重试 |
| `RESULTS_NOT_VERIFIED` | 提交后无法证明结果状态 | 有限重试，随后失败 |
| `FILTER_NOT_APPLIED` | 页面条件与请求不一致 | 不导出，返回失败 |
| `EXPORT_LIMIT_REJECTED` | UI/许可拒绝导出区间 | 降到允许范围或请求人工判断 |
| `DOWNLOAD_INVALID` | 文件为空、表头错误或批次不连续 | 不交给 CLI，有限重试 |
| `BROWSER_CLOSED` | 用户或系统关闭浏览器 | 无下载副作用时可重启恢复 |

`user_action_required` 返回给 Agent 的信息只包含用户可以执行的动作，例如“请在已打开的 WoS 窗口完成机构认证，然后告诉我继续”。内部 selector、trace 路径和堆栈默认不显示给用户。

## 12. 文件与 Handoff 契约

MCP 私有数据目录示意：

```text
<app-data>/literature-database-browser/
├── profiles/
│   └── wos-core-collection/
├── jobs/
│   └── <job-id>/
│       ├── state.json
│       ├── search_receipt.json
│       ├── exports/
│       │   ├── batch-0001.txt
│       │   └── batch-0002.txt
│       └── diagnostics/            # 仅失败时按配置保留
└── broker.json
```

完成输出：

```json
{
  "job_id": "job-...",
  "attempt_id": "wos-02",
  "phase": "export",
  "state": "complete",
  "reported_result_count": 842,
  "requested_export_limit": 1000,
  "exported_record_count": 842,
  "export_files": [
    "<private-job-dir>/exports/batch-0001.txt"
  ],
  "receipt_file": "<private-job-dir>/search_receipt.json",
  "next_step": {
    "owner": "literature-research-cli",
    "command": "import-wos-export"
  }
}
```

MCP 只返回文件位置和紧凑统计。Agent 随后运行现有 CLI：

```bash
uv run literature-research/scripts/literature_search.py import-wos-export \
  --input <official-export> \
  --query '<selected exact query>' \
  --limit 1000 \
  --output wos_raw.json
```

如果存在多个批次，CLI importer 应扩展为接受多个输入或 manifest；合并时优先按 WoS UT、其次按 DOI 去重。官方原始文件不提交到仓库。

## 13. Receipt 与审计边界

`search_receipt.json` 至少记录：

- schema version；
- database/adapter version；
- job ID、attempt ID 和 request IDs；
- query hash；
- filters、sort 和 export options；
- WoS 页面报告的结果数；
- 导出批次、文件 hash 与规范化记录数；
- session/job 状态时间线；
- 最终状态和稳定错误码。

精确 query 的 source of truth 是 `literature-research` 保存的 `search_plan.json`。私有 job state 为恢复任务可以保存完整 query；最终 receipt 默认只保存 hash，避免不必要的重复。正常用户反馈不暴露 receipt 路径和内部状态时间线。

## 14. 数据安全与许可边界

- Profile、导出、截图、trace 和 receipts 保存在仓库外；
- POSIX 尽可能使用 owner-only 权限，Windows 使用当前用户应用数据目录；
- 不记录账号、密码、Cookie 值、authorization header 或完整 storage dump；
- 日志 URL 移除 query string 和 fragment；
- 成功任务默认不保存 trace，失败诊断按 TTL 清理；
- subscription exports 不进入 Git、插件 bundle 或测试 fixture；
- 测试 fixture 使用自建的最小仿真页面，不复制 WoS 页面源码或受版权保护内容；
- 并发、批次和导出数量服从当前 UI 与机构许可；
- 不把授权失败、页面失败或解析失败报告成“未发现相关文献”。

## 15. 配置设计

V1 配置保持窄且有默认值：

```json
{
  "browser": {
    "channel": "chrome",
    "headless": false,
    "idle_ttl_minutes": 30
  },
  "wos": {
    "database": "wos-core-collection",
    "max_export_records": 1000,
    "default_export_format": "tab-delimited-full-record"
  },
  "diagnostics": {
    "save_on_failure": true,
    "retention_days": 7
  }
}
```

硬约束：

- V1 不允许 `headless: true`；
- `max_export_records` 不能通过配置提高到 1000 以上；
- 配置文件不能包含机构账号或密码；
- 环境变量只用于本地路径、日志级别和 opt-in live tests，不保存到 plan/receipt。

## 16. 与 literature-research 的职责契约

### Skill 负责

- 判断是否需要 WoS；
- 生成语义正确的 Advanced Search query；
- 保存 query plan 和每次 attempt；
- 根据结果数与科学问题决定是否调整检索；
- 选择最终 attempt 并调用 export；
- 调用 CLI 规范化、合并、排名和生成报告；
- 在报告中披露数据库、精确 query、筛选条件、日期和截断上限。

### MCP 负责

- 可靠执行精确输入；
- 维护浏览器/session/job/download 状态；
- 验证页面动作产生了预期业务结果；
- 生成官方导出和内部 receipt；
- 在不能安全继续时停止并返回明确状态。

### CLI 负责

- 解析一个或多个官方导出文件；
- 字段标准化；
- UT/DOI 去重；
- 与其他 source JSON 合并和排名；
- 生成审计文件和报告 scaffold。

任何一层都不能声称另一层没有验证的事实。

## 17. 包装与安装

插件结构目标：

```text
plugins/ai4s-literature-workbench/
├── skills/
├── runtime/                         # Zotero MCP
├── database-browser-runtime/        # 新的可选 browser MCP
├── .mcp.json                        # 注册两个 MCP servers
└── scripts/
    ├── assemble-plugin.mjs
    ├── bootstrap-runtime.sh
    ├── bootstrap-runtime.ps1
    └── verify-runtime.mjs
```

安装原则：

- Cross-platform Node 20+ runtime；
- Playwright 作为 database browser runtime 的依赖；
- 优先复用本机 Chrome，避免无必要下载浏览器；
- 找不到可支持浏览器时，bootstrap 明确提示可选安装步骤；
- database browser runtime 安装失败不能阻止 Zotero MCP 和 Skills 安装；
- `.mcp.json` 使用独立 command/cwd，两个 MCP server 不共享 data directory。

## 18. 测试设计

### 单元测试

- tool schema 和枚举；
- request ID 幂等；
- session/job 状态转换；
- retry budget；
- receipt 和文件 hash；
- 错误码映射；
- Profile/job 路径隔离。

### 本地 Playwright 仿真测试

自建最小页面模拟：

- React/SPA 式输入框重渲染；
- fill 成功但 query 未 commit；
- 点击后无状态变化；
- 结果数延迟出现；
- 筛选条件异步刷新；
- 下载事件、空文件、错误表头；
- 多批导出和缺失批次；
- 用户关闭浏览器与 Broker 恢复。

### WoS live tests

仅在校园网、用户明确运行和可见浏览器环境启用，不进入普通 CI：

1. 连续完成 3 个不同 Advanced Search 查询；
2. 至少一次包含年份与 Article/Review 筛选；
3. 至少一次根据结果数创建第二个 attempt；
4. 对最终 attempt 完成官方导出；
5. CLI 导入记录数与 receipt 一致；
6. 人工关闭浏览器后能够给出正确错误并恢复；
7. 校园授权不可用时返回 `CAMPUS_ACCESS_REQUIRED`，而不是 0 records。

## 19. V1 验收标准

V1 完成必须同时满足：

1. capability registry 只报告 `wos-core-collection`；
2. Agent 可以通过通用 `database_*` tools 完成会话、搜索、结果检查和导出；
3. 所有长操作都是异步 job，不阻塞单次 MCP 调用；
4. query 未提交、筛选未应用或下载未验证时绝不返回成功；
5. 搜索和导出是两阶段，允许 Agent 在导出前调整 query；
6. 最多导出 1000 条，并尊重更低的实时 UI/许可上限；
7. 官方导出能由现有/扩展后的 `import-wos-export` CLI 规范化；
8. Profile、导出和诊断文件不进入仓库；
9. 用户只在授权、验证码、风控或无法安全恢复时被打断；
10. WoS live acceptance 连续 3 次通过；
11. database browser runtime 故障不影响 PubMed、arXiv、Zotero MCP 和 writing workflow；
12. 不实现或暗示 Crossref、Scopus、Embase 等 V1 未支持能力。

## 20. 后续扩展原则

V1 稳定后可以新增 database adapter，但每个 adapter 必须单独定义并验证：

- query syntax；
- readiness/auth 状态；
- locators 和动作后验证；
- filters/sorts；
- export format/limit；
- official export importer；
- institution/license 边界；
- live acceptance。

新增 adapter 只扩展 `database_browser_capabilities` 和带 `database` 判别字段的输入 schema，不改变现有 WoS contract。若某数据库存在稳定、授权的公开/官方 API，仍优先使用 Skill + CLI/API，不因为已有 Browser MCP 而强制走浏览器。
