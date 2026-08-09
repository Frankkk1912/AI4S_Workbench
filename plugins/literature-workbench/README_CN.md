# Literature Workbench

[English](README.md)

> **No Evidence, No Conclusion（无证据，不结论）。** 获取可审计证据，将审核后的记录交给 Zotero，并且只依据已保存的证据写作。

Literature Workbench v0.1.0 是一个面向 Coding Agent 的文献工作流插件，支持文献检索、受控 Zotero 工作流、经验证的公共开放获取（OA）全文交接，以及证据可追溯的科学写作。它由三个 Agent Skill、两个活动 MCP Server 和一个可选的 Zotero Desktop Add-on 组成。

## 概览

```mermaid
flowchart LR
    R["literature-research<br/>排序证据 + report.md"] --> M["literature-manager<br/>审核导入 + 项目同步"]
    M --> Z["ai4s-literature-zotero<br/>Zotero MCP"]
    M --> F["ai4s-literature-fulltext<br/>经验证的 OA 交接"]
    F --> Z
    Z --> W["literature-writing<br/>证据可追溯正文"]
```

默认路径以 PubMed 为先：`literature-research` 生成 `search_plan.json`、`ranked_all.json`、`ranked_all.csv` 和 `report.md`；`literature-manager` 导入或同步审核过的选定记录；Zotero MCP 与可选的 Fulltext MCP 将文献库写入和 OA 验证分离；`literature-writing` 再将已保存证据写成带可追溯占位符的正文。

<!-- Screenshot: 真实的 evidence-to-Zotero 产出样本，同时展示 report.md 与 ranked_all.json 和 ranked_all.csv 排序结果。 -->
<!-- ![Evidence-to-Zotero 产出样本](assets/evidence-to-zotero-output.png) -->

## 功能特性

- **可审计检索与排序：** 支持 PubMed 和 arXiv 检索、去重、显式结果上限、排序理由，以及内置且经过审核的 2025 JCR/IF 查询表。用户手动取得的 Web of Science 官方导出可以用 `import-wos-export` 规范化。
- **受控 Zotero 变更：** 精确 DOI/PMID 匹配、高风险写入的审核与哈希门禁、幂等项目/报告同步、回执、只读重复项审计，并且绝不自动合并或删除。
- **指标与组织：** 仅对选定文献进行 EasyScholar 增强、版本化 `AI4S-Metrics`、`AI4S:ArticleType:*`、受控英文 `AI4S:Semantic:*` Agent Tags，以及安全清理 Zotero 自动标签。
- **显式 AI Summary：** 默认中文、每篇一句；只有用户直接请求后才会生成，且只依据返回的标题与摘要。普通导入、同步、指标、标签和报告更新绝不会触发它。
- **经验证的公共 OA 交接：** PMC 和经审核的公共 HTTP 候选先经过 PDF 验证以及严格 DOI/标题匹配，再产生私有哈希交接；Zotero 附件写入是另一个受控步骤。
- **证据可追溯写作：** 基于已保存证据撰写综述、项目背景、引言、讨论、双语正文、引文占位符和参考文献审计表。

## 快速开始

### Agent 引导启动

先通过下方任一受支持 Harness 安装插件，在已安装插件目录中打开 Coding Agent 会话，然后发送：

```text
请在当前插件目录中引导启动 Literature Workbench。检查 Node.js 和 npm 是否至少为 20.19，运行当前操作系统的原生 bootstrap 脚本，然后运行 `node scripts/onboard.mjs status --output onboarding-status.json`。只报告脱敏后的能力状态。说明 Zotero Web API、PubMed 和 EasyScholar 凭据均为可选；绝不要让我把密钥粘贴到聊天中；并提醒我 Zotero Desktop metrics XPI 需要单独手动安装。
```

Bootstrap 会构建并验证必需的 Zotero MCP，同时尝试构建可选的仅公共 OA Fulltext MCP。即使没有 API 凭据，基础检索、排序和写作仍然可用。

### 手动启动

要求：Node.js 20.19+ 与 npm。Skill 脚本还需要 Python 3 和 [`uv`](https://docs.astral.sh/uv/)。在插件目录运行：

```bash
bash scripts/bootstrap-runtime.sh
node scripts/onboard.mjs status --output onboarding-status.json
```

Windows PowerShell：

```powershell
.\scripts\bootstrap-runtime.ps1
node .\scripts\onboard.mjs status --output .\onboarding-status.json
```

如需配置可选凭据，请使用本地掩码向导，而不是 Agent 聊天：

```bash
node scripts/onboard.mjs setup --output onboarding-result.json
```

## 安装

| Harness | 已确认的安装路径 |
| --- | --- |
| Claude Code | `/plugin marketplace add Frankkk1912/AI4S_Workbench`，然后运行 `/plugin install literature-workbench@ai4s-workbench` |
| Codex CLI | 从本地 checkout 安装：`codex plugin marketplace add <repo-path>`，然后运行 `codex plugin add literature-workbench@personal` |
| OpenCode / Agent Skill Standard | 将本插件的 `skills/` 目录复制或链接到 Harness 文档指定的本地 Skill 位置。先构建 Runtime；仅当 Harness 支持 MCP 配置时加载 [`.mcp.json`](.mcp.json)。 |

受支持 Harness 列表有意限定为以上三行。MCP Runtime 以源码提供；每次安装都必须执行目标操作系统的原生 bootstrap，不能复用另一个操作系统的 `node_modules`、`dist` 或私有环境文件。

## 配置

以下三类凭据都只是可选增强：

| 提供方 | 用途 | 申请页面 |
| --- | --- | --- |
| Zotero Web API | 云端身份，以及获批的条目、标签、Note、Group Library 或文件写入 | <https://www.zotero.org/settings/keys> |
| PubMed / NCBI | 更高的 E-utilities 配额与更稳定的批量检索 | <https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/api-keys/> |
| EasyScholar | 对选定期刊进行分区与指标增强 | <https://www.easyscholar.cc/> |

运行 `node scripts/onboard.mjs reconfigure --provider zotero|pubmed|easyscholar --output onboarding-result.json` 可修改单个提供方。向导会掩码并验证输入；验证失败或网络故障时保留原有设置；输出文件只包含脱敏状态。**绝不要把凭据粘贴到 Agent 聊天中，也不要将其作为命令参数传递。**

私有配置位置：

| 平台 | Zotero MCP | PubMed / EasyScholar |
| --- | --- | --- |
| macOS | `~/Library/Application Support/literature-workbench/zotero.env` | `~/.config/frank-ai4s/academic-research.json` |
| Windows | `%LOCALAPPDATA%\literature-workbench\zotero.env` | `%LOCALAPPDATA%\frank-ai4s\academic-research.json` |
| Linux / WSL | `${XDG_CONFIG_HOME:-~/.config}/literature-workbench/zotero.env` | `${XDG_CONFIG_HOME:-~/.config}/frank-ai4s/academic-research.json` |

相关覆盖变量包括 `ZOTERO_API_KEY`、`ZOTEUS_LOCAL=auto|on|off`、`LITERATURE_ZOTERO_MCP_ENV_FILE`、`AI4S_ACADEMIC_CONFIG_FILE` 和 `LITERATURE_FULLTEXT_EXCHANGE_ROOT`。[`.mcp.json`](.mcp.json) 将 Zotero 工具面固定为 `LITERATURE_ZOTERO_MCP_TOOL_PROFILE=workbench`，并关闭 Embedding。Zotero Desktop Local API 用于免 Key 读取；获批的云端写入需要有写权限的 Zotero Web API Key，上传文件附件还需要文件权限。

## Prompt 示例

### 1. 检索并排序证据

```text
请检索 GPLD1 在心血管疾病中作用的 PubMed 文献，查询式为 `(GPLD1) AND (cardiovascular disease OR heart failure)`。最多获取 50 篇，排序前 30 篇，保留 search_plan.json、ranked_all.json、ranked_all.csv 和 report.md；标注仅摘要证据与预印本；并明确说明这次有上限的检索并非穷尽性检索。
```

### 2. 将审核后的证据同步到 Zotero

```text
请使用我选定并经 EasyScholar 增强的排序证据和最终 report.md，把项目 `gpld1-cvd` 同步到 Zotero 集合 `GPLD1 cardiovascular disease`。如有歧义或大批量新建审查，请先展示给我；保留现有 Priority；随后生成受控英文 Agent Tags，并且只清理 Zotero 自动来源标签。同步完成后，我在此显式请求：只依据标题和摘要，为每篇文献生成一句中文 AI Summary；使用 missing 模式，不要覆盖当前 Summary。
```

### 3. 获取经验证的公共 OA PDF

```text
请先检查我选定的精确 Zotero 父条目的 fulltext context。仅通过合法公共 OA 路径获取全文，轮询 Fulltext MCP 任务，并且只应用经验证的哈希交接。不要使用机构登录、VPN、Cookie 或绕过访问控制；已经有文件 PDF 或需要身份审核的父条目应跳过。
```

### 4. 撰写证据可追溯正文

```text
请依据已保存的 ranked_all.json 和 report.md，撰写 GPLD1 在心血管疾病中作用机制的双语综述章节。每个科学结论都添加 [EV:<index>] 占位符；区分直接证据、解释与开放问题；披露检索上限和全文状态；并提供参考文献审计表。不要仅依据 Agent Tags 或 AI Summary 推理。
```

## 可用 Skills

| Skill | 适用场景 | 主要交接物 |
| --- | --- | --- |
| `literature-research` | 来源数据库检索、去重、排序、期刊查询与可审计报告 | `search_plan.json`、`ranked_all.json`、`ranked_all.csv`、`report.md` |
| `literature-manager` | Zotero 匹配、审核导入、Collection/报告同步、指标、重复项审计、Agent Tags 与显式请求的 AI Summary | 私有 Plan/Receipt，以及 Zotero Collection、条目、标签、Extra 和报告 Note |
| `literature-writing` | 证据可追溯的综述、项目申请、论文段落、双语正文和引文审计 | 带 `[EV:*]`/可选 `[ZOT:*]` 占位符及审计表的 Markdown |

每个阶段使用职责最窄的 Skill。Zotero 文献库中存在条目并不能证明检索完整，检索报告也不等于论文正文。

## MCP Tools

只有 [`.mcp.json`](.mcp.json) 中注册的两个 Server 处于活动状态。下列输入名来自随附 Tool Schema；注明时可用 `library_type` 和 `library_id` 进行可选文献库路由。

### Zotero MCP — `ai4s-literature-zotero`（workbench profile）

| 分类 | Tool | Schema 输入 |
| --- | --- | --- |
| 身份 | `zotero_whoami` | 无 |
| 搜索/读取 | `zotero_search_items` | `q`、`qmode`、`itemType`、`tag`、`collectionKey`、`top`、`since`、`includeTrashed`、`sort`、`direction`、`limit`、`start`、`response_format`、`library_type`、`library_id` |
| 搜索/读取 | `zotero_get_item` | `item_key`；可选 `include_children`、`include`、`style`、`locale`、`library_type`、`library_id` |
| 搜索/读取 | `zotero_get_fulltext` | `item_key`；可选 `query`、`page_range`、`max_passages`、`max_chars`、`precise_pages`、`library_type`、`library_id` |
| OA 准备 | `zotero_fulltext_context` | `item_keys`；可选 `library_type`、`library_id` |
| OA 写入 | `zotero_apply_fulltext_handoff` | `handoff_id`、`handoff_hash`；可选 `library_type`、`library_id` |
| 审核 Plan | `zotero_apply_import_plan` | `plan_path`、`mode`；apply 还需要 `receipt_path`、`confirm_plan_hash` |
| 审核 Plan | `zotero_apply_metrics_plan` | `plan_path`、`mode`；可选 `confirm_plan_hash`、`receipt_path`、`library_type`、`library_id` |
| 审核 Plan | `zotero_apply_citation_plan` | `plan_path`、`mode`；可选 `confirm_plan_hash`、`receipt_path`、`library_type`、`library_id` |
| 重复项审计 | `zotero_find_duplicates` | `collection_key`/`tag` 二选一，必需 `limit`；可选 `title_threshold`、`library_type`、`library_id` |
| Agent Tags | `zotero_semantic_tag_context` | `item_keys`/`collection_key` 二选一；可选 `limit`、`start`、`vocabulary_limit`、`vocabulary_query`、`library_type`、`library_id` |
| Agent Tags | `zotero_apply_semantic_tags` | `scope`、`vocabulary_revision`、`items`；可选 `cleanup_auto_tags`、`library_type`、`library_id` |
| Agent Tags | `zotero_cleanup_auto_tags` | `scope_type`、`max_items`；可选 `collection_key`、`start`、`library_type`、`library_id` |
| Agent Tags | `zotero_semantic_tag_vocabulary` | `action`；可选 `path`、`expected_revision`、`limit`、`library_type`、`library_id` |
| 项目同步 | `zotero_sync_literature_project` | `project_slug`、`search_date`、`report_path`、`evidence_path`；可选 `collection_name`、`selection_path`、`priority_recommendations_path`、`confirm_review_id`、`library_type`、`library_id` |
| AI Summary | `zotero_ai_summary_context` | `item_keys`/`collection_key` 二选一；可选 `mode`、`language`、`limit`、`start`、`library_type`、`library_id` |
| AI Summary | `zotero_apply_ai_summaries` | `trigger="explicit-user-request"`、`items`；可选 `mode`、`library_type`、`library_id` |

Import、Metrics 和 Citation 的 apply 模式需要精确匹配的审核 Hash 与 Receipt 路径。重复项检测只读；确认合并必须在 Zotero Desktop 中手动完成。AI Summary `refresh` 需要用户明确表达覆盖意图。

### Fulltext MCP — `ai4s-literature-fulltext`

| 分类 | Tool | Schema 输入 |
| --- | --- | --- |
| 能力 | `fulltext_capabilities` | 无 |
| 能力 | `fulltext_access_status` | 无 |
| 延期接口 | `fulltext_session_open` | `institution`；仅 OA 的 v0.1.0 返回 `INSTITUTION_ACCESS_UNAVAILABLE`，且不接受凭据 |
| OA 任务 | `fulltext_fetch_submit` | `request_id`、`route_policy`、`records[]`（`evidence_id`、`zotero_item_key`、`doi`/`arxiv_id`/`repository_id` 至少一个、`title`、`item_type`；可选 `year`、`candidate_urls`） |
| OA 任务 | `fulltext_job_status` | `job_id` |
| OA 任务 | `fulltext_job_cancel` | `job_id` |

活动的 v0.1.0 Runtime 只支持公共 OA。它不会在聊天中返回 PDF 字节/全文、直接上传 Zotero、启动浏览器、连接 VPN、处理机构凭据或绕过访问控制。

## Zotero Desktop Metrics

可选的 `source/literature-metrics` Add-on 支持 Zotero 7.0–10.9，需要与 Agent 插件分开安装。从仓库 checkout 构建：

```bash
cd source/literature-metrics
npm ci
npm test
npm run check
npm run package
```

在 Zotero Desktop 中打开 **Tools → Add-ons → gear menu → Install Add-on From File…**，选择 `source/literature-metrics/dist/literature-metrics-0.1.13.xpi`，并在提示时重启。

它的八个核心只读证据/元数据列是 `IF(YYYY)`、`5-Year IF(YYYY)`、`JCR(YYYY)`、`CAS(YYYY)`、`Journal Metrics`、`Article Type`、`Agent Tags` 和 `AI Summary`；显式刷新的 Semantic Scholar 快照还可以填充 `Citations`。`Priority` 是唯一的交互列：悬停并点击一至三星，重复点击已保存等级可清除；也可以用 `1`/`2`/`3` 批量设置选中的常规条目，用 `0` 清除。Add-on 不发起网络请求，唯一直接条目写入是用户的 Priority 操作。

Priority 表示个人阅读/使用优先级，而非证据质量。Agent 可以依据审核后的报告建议初始化缺失值，但普通导入绝不会覆盖已有 `AI4S:Priority:1|2|3`。Priority 标签冲突时会显示警告，而不是静默解决。

<!-- Screenshot: 真实的 Zotero Desktop 视图，展示八个核心列以及可交互的一至三星 Priority 控件。 -->
<!-- ![Zotero Desktop 八个核心列与 Priority 星级](assets/zotero-desktop-core-columns-priority.png) -->

## Roadmap 与支持边界

### v0.1.0 范围

- 三个协作 Skill、包含 17 个 Tool 的 workbench-profile Zotero MCP，以及包含 6 个 Tool 的仅 OA Fulltext MCP。
- PubMed/arXiv 检索与排序；规范化用户手动取得的 WoS 官方文本导出。
- 审核后的 Zotero 导入、周期性 Collection/报告同步、新导入的 EasyScholar 指标、只读重复项审计、Agent Tags、显式请求的 AI Summary，以及用户拥有的 Priority。
- 经验证的 PMC/公共 HTTP PDF 交接，随后执行独立且受控的 Zotero 附件写入。
- 原生 macOS 与 Windows bootstrap。WSL 是需要单独安装的兼容目标，不是发布门禁。

### 明确延期

- Web of Science Core Collection 实时浏览器自动化、筛选、数量核验和官方导出。保留的 database-browser runtime **没有注册**到 `.mcp.json`，不是活动 MCP Server。
- Crossref 与其他商业数据库适配器。
- 机构 SSO、VPN/WebVPN、凭据/Cookie 处理、CAPTCHA 绕过、隐藏浏览器和机构全文回退。
- Zotero 重复项自动合并/删除，以及自动修改用户拥有的 Priority。

公共 OA 是 v0.1.0 唯一受支持的 Fulltext 路径。有上限的来源检索绝非全面检索；仅摘要记录和预印本必须保持标注；任何指标、Summary 或 Tag 都不能替代科学证据。

## 项目结构

```text
literature-workbench/
├── .claude-plugin/             # Claude Code manifest
├── .codex-plugin/              # Codex CLI manifest
├── .mcp.json                   # 活动 Zotero 与 Fulltext MCP Server
├── docs/onboarding.md          # 凭据与首次运行指南
├── runtime/                    # Zotero MCP Runtime
├── fulltext-runtime/           # 仅 OA Fulltext MCP Runtime
├── scripts/                    # Bootstrap、Onboarding、验证
├── skills/
│   ├── literature-research/
│   ├── literature-manager/
│   └── literature-writing/
├── source/literature-metrics/  # 单独构建的 Zotero Desktop XPI
├── CHANGELOG.md
└── v0.1.0-release-plan.md
```

## 开发与验证

以下面向用户的验证路径均由已提交脚本支撑：

```bash
# 构建两个 Runtime，并验证 MCP Tool 表面
bash scripts/bootstrap-runtime.sh

# 首次运行/Onboarding 合约
node --test tests/*.test.mjs

# Zotero Desktop Add-on
cd source/literature-metrics
npm ci
npm test
npm run check
npm run package
```

Windows 使用 `.\scripts\bootstrap-runtime.ps1`；Add-on 的 npm 命令在 PowerShell 中保持不变。发布候选状态与验收边界见 [`CHANGELOG.md`](CHANGELOG.md) 和 [`v0.1.0-release-plan.md`](v0.1.0-release-plan.md)。

## 许可证

Agent 插件、Skills 与随附 MCP Runtime 使用 [MIT License](LICENSE)。捆绑的第三方声明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
