# Literature Fulltext MCP 设计文档

> 状态：V1 设计草案，待评审（2026-07-22）  
> V1 支持范围：开放获取优先；用户已有合法订阅权限时，可选机构访问回退；将验证通过的主文 PDF 幂等附加到精确 Zotero 父条目  
> 定位：为 `literature-manager` 提供独立、可恢复的全文获取执行层；不承担文献检索决策、Zotero 凭据管理或任意文件上传。

## 1. 设计结论

新增独立的 **Literature Fulltext MCP**。它与 Literature Database Browser MCP、
Zotero MCP 分离，由 Agent 按 Skills 的 workflow contract 统一编排，而不是让
三个 MCP 互相调用。

```text
用户自然语言请求
  → literature-research Skill
      ├─ 开放数据库/API/CLI
      └─ 可选 Database Browser MCP（例如 WoS 官方检索与导出）
  → ranked evidence + selection
  → literature-manager Skill
      ├─ Zotero MCP：创建/复用父条目并检查已有附件
      ├─ Fulltext MCP：只为缺失全文的精确条目获取并验证 PDF
      └─ Zotero MCP：将 verified handoff 幂等写为 child attachment
```

全文获取遵循 **Open Access first, institutional access only when needed**：

1. 优先尝试无需校园网、VPN 或登录的合法开放获取来源。
2. OA 不可用时，才检查当前网络是否已经具有机构订阅权限。
3. 仍不可用且用户配置了自己的订阅机构时，才进入可见浏览器中的机构认证流程。
4. MCP 不自动启动学校 VPN 客户端，不接收或保存学校密码，不绕过 CAPTCHA、
   访问控制、许可限制或下载限制。

因此，校园网络不是 Fulltext MCP 的前置条件，而是闭源全文的一条可选授权回退路径。

## 2. 为什么是第三个独立 MCP

三个执行层的外部系统、主要状态和失败模式不同：

| 维度 | Database Browser MCP | Fulltext MCP | Zotero MCP |
|---|---|---|---|
| 主要目标 | 商业数据库检索与官方导出 | 获取并验证主文 PDF | 管理 library、item 与附件 |
| 外部系统 | WoS 等数据库网页 | OA 服务、出版社、机构认证页 | Zotero Desktop/Web API/File Storage |
| 主要状态 | query/export job、浏览器页面 | route attempt、浏览器、PDF staging | item version、collection、attachment receipt |
| 常见阻塞 | 数据库授权、页面变化、导出失败 | 无 OA、未订阅、登录、下载/验证失败 | identifier 歧义、版本冲突、配额、上传失败 |
| 用户接管 | 数据库认证或验证码 | 机构 SSO、2FA、验证码 | 通常不需要 GUI |
| 成功产物 | 经验证的官方导出文件 | 经验证的 PDF handoff | Zotero child attachment |

隔离后应满足：

- Fulltext MCP 缺失或安装失败，不影响检索、报告、Zotero bibliographic import 和写作。
- 浏览器崩溃、出版社页面变化或长时间下载，不影响 Zotero MCP 的稳定性。
- Fulltext MCP 不持有 Zotero API key；Zotero MCP 不持有机构登录状态。
- Zotero 上传失败时复用已经下载的 PDF，不重新访问出版社。
- MCP 之间只交换小型、版本化、可哈希的 handoff；PDF bytes 不经过对话上下文。

## 3. 角色与所有权

### 3.1 `literature-research`

负责：

- 理解科学问题并规划检索；
- 从 PubMed、arXiv、WoS 等来源获取、去重和排名记录；
- 产生稳定 `evidence_id`、DOI/PMID/arXiv ID、标题、年份和候选全文链接；
- 产生最终 selection。

不负责：

- 批量下载 PDF；
- 判断 Zotero 父条目；
- 上传或替换 Zotero 附件。

### 3.2 `literature-manager`

作为全文入库子流程的 Skill 编排者，负责：

- 将 selected evidence 同步到 Zotero 并取得精确 item key；
- 请求 Zotero MCP 检查已有附件；
- 只把缺失 PDF 的精确记录交给 Fulltext MCP；
- 将 verified handoff 交回 Zotero MCP；
- 汇总真实结果并隐藏正常路径的内部 plan、hash 和 receipt。

### 3.3 Literature Fulltext MCP

负责：

- 按安全路由顺序寻找候选全文；
- 维护异步 fetch job、浏览器会话、route attempts 和本地 staging；
- 验证文件确实是目标论文的主文 PDF；
- 生成不可变、可哈希的 fulltext handoff；
- 在需要时返回明确的人工接管状态。

不负责：

- 修改检索 selection 或科学排名；
- 创建、匹配、更新或删除 Zotero item；
- 读取 Zotero API key；
- 把 PDF 直接上传 Zotero；
- 返回整篇全文文本到 MCP 对话。

### 3.4 Zotero MCP

负责：

- 创建或复用 bibliographic parent item；
- 返回 `evidence_id → zotero_item_key` 的精确映射；
- 检查现有 child attachments；
- 重新验证父条目身份和 fulltext handoff；
- 使用 Zotero File Storage 协议上传 verified PDF；
- 保存可恢复的 attachment receipt。

## 4. 用户触发与默认行为

普通“检索并导入 Zotero”不隐式下载全文。以下意图视为显式启用：

- “同时获取全文/PDF”；
- “把能下载的全文加到 Zotero”；
- “为这个 collection 补全文”；
- 项目已经由用户明确启用持久设置 `fulltext_policy: selected-missing`。

建议的项目级策略：

| 策略 | 行为 |
|---|---|
| `off` | 不运行全文获取；默认值 |
| `selected-missing` | 只为本轮最终 selected 且 Zotero 中缺少 PDF 的条目获取 |
| `collection-missing` | 用户显式要求时，为指定 collection 的缺失条目补全文 |

V1 不提供“自动替换已有 PDF”。已有任意可用主文 PDF 时默认跳过；刷新、替换、
多版本管理和删除旧附件均不在 V1 自动路径中。

目标交互：

```text
用户：调研这个主题，精选文献导入 Zotero，并把能合法获取的全文也加进去。

Agent：
1. 完成检索、排名、报告和 selection
2. 创建/复用 Zotero 条目并检查已有 PDF
3. 对缺失项执行 OA-first 全文获取
4. 必要时在可见浏览器中请用户完成机构认证
5. 将验证通过的 PDF 幂等附加到对应 Zotero 条目
6. 返回 collection、文献导入数、已有 PDF 数、新增 PDF 数和未获取原因摘要
```

## 5. 全文路由顺序

### 5.1 路由原则

路由不是简单的“OA 或校园网”二选一，而是按合法性、稳定性和用户负担排序：

```text
已有 Zotero 主文 PDF
  → skip_existing

否则：
  → 开放获取的 Version of Record
  → PubMed Central / Europe PMC 等可信开放全文库
  → Unpaywall 指向的合法 OA location
  → arXiv 等与当前 evidence version 一致的预印本来源
  → 出版社官方 API / direct PDF（当前网络已经授权）
  → 出版社可见浏览器 + 用户自己的机构认证
  → unavailable / auth_required / not_entitled
```

OA-first 不表示无条件选择第一个 PDF。候选选择还必须考虑：

- 是否为目标 DOI/标题；
- 是否是主文而不是 supplement、supporting information、correction 或 editorial；
- 文献版本是否与 Zotero 记录一致；
- 是否存在更优先的开放 Version of Record；
- 来源是否允许在用户自己的授权范围内访问。

### 5.2 访问模式

V1 使用稳定枚举：

| `access_mode` | 含义 | 是否需要校园网络 |
|---|---|---|
| `open_access_http` | 公开 OA URL/API | 否 |
| `publisher_open_access` | 出版社公开 PDF | 否 |
| `direct_entitled_network` | 当前校园网或用户已连接的官方 VPN 提供 IP 授权 | 可能需要，但 MCP 不负责连接 |
| `publisher_api_entitled` | 出版社官方 API + 当前机构授权 | 可能需要 |
| `federated_visible_browser` | Shibboleth/OpenAthens/CARSI 等可见浏览器认证 | 需要用户自己的机构权限 |
| `institution_gateway_visible_browser` | 用户机构提供并明确允许的 WebVPN/EZproxy 路径 | 需要用户手动认证 |

Fulltext MCP 不默认任何学校。订阅机构解析顺序：

1. 当前请求显式提供的 institution；
2. 用户私有配置中已确认的 institution；
3. 缺失时返回 `institution_required`，由 Agent 向用户询问。

### 5.3 明确排除的来源与行为

生产插件不得启用或集成：

- Sci-Hub、LibGen 或其他未授权全文来源；
- Tor、代理池轮换或通过切换出口规避出版商限制；
- 自动填写机构密码、OTP、恢复码或 CAPTCHA；
- Cookie JSON、localStorage dump 或凭据导入导出；
- 未公开出版社接口逆向、token 重放或许可限制绕过；
- 以隐藏浏览器或高并发方式模拟批量人工访问；
- 在共享校园出口持续请求已返回 403/429/IP blocked 的站点。

参考项目可以用于理解合法 OA、官方 API、publisher adapter、可见浏览器和 PDF
验证，但进入生产代码前必须逐项审查来源策略、许可证和安全边界。

## 6. 版本与主文选择

Handoff 使用以下 `document_version`：

- `version_of_record`
- `accepted_manuscript`
- `submitted_manuscript`
- `preprint`
- `unknown`

默认优先级：

1. 合法开放的 `version_of_record`；
2. 合法开放的 `accepted_manuscript`；
3. OA 均不可用时，用户有权访问的出版社 `version_of_record`；
4. 仅当 Zotero 条目本身是 preprint/arXiv 记录时自动选择 `preprint`；
5. journal article 与 preprint 的版本关系无法证明时，不把 preprint 自动附成该
   journal article 的主文 PDF。

V1 只处理 `file_role: main_article`。补充材料、数据附件、图集、审稿文件和
correction PDF 可以保留为诊断候选，但不得进入自动 Zotero attachment handoff。

## 7. 跨组件执行顺序

### 7.1 为什么先建立 Zotero 父条目

推荐顺序是“Zotero parent ready → 查缺 → 下载 → 附件写入”，而不是边检索边下载：

- 精确知道 PDF 应挂到哪个 item；
- 可先跳过用户已有附件；
- import receipt 已提供稳定 evidence-to-item 映射；
- 失败后可以只恢复未完成阶段；
- 避免下载最终没有进入 selection 的论文；
- 避免同一 DOI 因多个来源记录重复下载。

### 7.2 正常路径

```text
ranked evidence + selection
  → zotero_sync_literature_project / zotero_apply_import_plan
  → evidence_id → zotero_item_key
  → zotero_fulltext_context
      ├─ existing_pdf → skip_existing
      ├─ ambiguous_parent/attachments → review_required
      └─ missing_pdf → fulltext_fetch_submit
  → fulltext_job_status
      ├─ auth_required → 用户在可见浏览器中认证后恢复
      ├─ unavailable/unverified → 不写 Zotero
      └─ verified → immutable handoff
  → zotero_apply_fulltext_handoff
  → attachment receipt
```

### 7.3 不进行 MCP-to-MCP 调用

Fulltext MCP 不连接 Zotero MCP，Zotero MCP 也不启动 Fulltext MCP。原因：

- MCP client/Agent 才拥有当前用户意图和 Skill workflow；
- server-to-server 调用会隐藏授权边界并增加部署耦合；
- 独立 handoff 更容易测试、恢复和跨平台迁移；
- 任一 optional runtime 缺失时，Agent 可以明确降级而不是级联失败。

## 8. Zotero 前置上下文工具

在 Zotero workbench profile 新增只读工具：

### `zotero_fulltext_context`

输入：

```json
{
  "item_keys": ["ABCD1234", "EFGH5678"],
  "library_type": "user",
  "library_id": 123456
}
```

输出按 item 提供：

```json
{
  "item_key": "ABCD1234",
  "item_version": 42,
  "doi": "10.1234/example",
  "title": "Example article",
  "attachment_state": "missing_pdf",
  "existing_pdf_attachments": []
}
```

`attachment_state`：

- `existing_file_pdf`
- `linked_pdf_url_only`
- `non_pdf_attachments_only`
- `multiple_pdf_files`
- `missing_pdf`
- `unsupported_parent`

默认只将 `existing_file_pdf` 和 `multiple_pdf_files` 视为无需自动下载。仅有
linked URL 或 snapshot 不证明 Zotero 已持有可离线阅读的 PDF。

若 DOI 缺失或多个 item 对同一 identifier 产生所有权歧义，返回
`review_required`；不得仅按模糊标题将 PDF 自动挂到父条目。

## 9. Fulltext MCP 工具设计

### 9.1 `fulltext_capabilities`

只读。返回 runtime 版本、可用 provider、访问模式、浏览器状态和限制，不发起网络请求。

```json
{
  "schema_version": 1,
  "providers": ["pmc", "unpaywall", "arxiv", "publisher-direct"],
  "access_modes": ["open_access_http", "publisher_open_access"],
  "institutional_browser_available": false,
  "max_records_per_job": 50
}
```

provider registry 只声明当前经过测试的能力；不得把“理论上可能支持”报告为可用。

### 9.2 `fulltext_access_status`

只读。检查本地配置、持久 Profile 和最近一次已验证的访问状态，不隐式启动浏览器，
不返回外部 IP、Cookie、账号或完整 URL。

状态：

- `oa_only_ready`
- `institution_config_required`
- `institution_session_closed`
- `institution_session_ready`
- `auth_required`
- `stale`
- `unavailable`

即使机构访问不可用，也应返回 `oa_only_ready`，而不是把整个 Fulltext MCP 标记失败。

### 9.3 `fulltext_session_open`

仅在某个 job 已经证明 OA 路径不足并需要机构访问时调用。启动或复用独立、可见、
持久化的 publisher browser Profile。

输入：

```json
{
  "institution": "User-selected institution"
}
```

规则：

- 产生可见窗口，不能标为 read-only；
- 不接收 password、OTP、Cookie 或 token 参数；
- 用户在浏览器中手动完成 SSO、2FA、CAPTCHA；
- 认证成功必须由允许的 publisher/article page 状态重新验证；
- 页面未验证时不得仅根据 Cookie 存在判断 session ready。

### 9.4 `fulltext_fetch_submit`

提交异步 job，不阻塞等待下载完成。

输入示例：

```json
{
  "request_id": "sha256-of-canonical-request",
  "records": [
    {
      "evidence_id": "doi:10.1234/example",
      "zotero_item_key": "ABCD1234",
      "doi": "10.1234/example",
      "title": "Example article",
      "year": 2025,
      "item_type": "journalArticle",
      "candidate_urls": ["https://example.org/article"]
    }
  ],
  "route_policy": "oa_then_institutional"
}
```

`route_policy`：

- `oa_only`
- `oa_then_current_entitlement`
- `oa_then_institutional`

规则：

- 同一 canonical request 使用稳定 `request_id`，重试不得生成重复 job；
- 每个 record 必须有稳定 evidence ID，并至少有 DOI、arXiv ID 或可信 repository ID；
- `zotero_item_key` 只是返回映射用的 opaque target，不授权 Fulltext MCP 写 Zotero；
- MCP 不改变 selection，不根据下载成功率重新排名；
- job 可以先完成所有 OA route，再把确需机构访问的记录置为 `auth_required`；
- V1 单 job 最多 50 条，与 Zotero 大批量创建确认边界保持一致；
- provider 并发受各自限流约束，publisher/机构浏览器默认串行；
- 收到 429、Backoff、IP blocked 或明确许可限制时立即节流或停止该 provider。

### 9.5 `fulltext_job_status`

只读。返回 compact status，不返回 PDF bytes 或全文正文。

```json
{
  "job_id": "ft-...",
  "state": "partial",
  "counts": {
    "requested": 12,
    "verified": 8,
    "auth_required": 2,
    "unavailable": 1,
    "failed": 1
  },
  "user_action_required": true,
  "next_action": "Complete institutional sign-in in the visible browser.",
  "handoff_id": null
}
```

完成后返回 `handoff_id`、`handoff_hash` 和记录摘要；真实 handoff 文件保存在共享的
私有 exchange directory，正常路径不向用户显示文件路径。

### 9.6 `fulltext_job_cancel`

取消 queued 或 running job。已写入 staging 的文件允许完成校验，但 canceled job
不得生成可应用 handoff。取消不删除用户已经明确导出到自选目录的 PDF。

## 10. Job 状态模型

### 10.1 Job 状态

```text
queued
  → resolving_open_access
  → validating_oa_candidates
      ├─ verified_complete
      └─ checking_current_entitlement
          ├─ validating_publisher_candidate
          └─ institution_auth_required
              → visible_browser_ready
              → retrieving_institutional_pdf
              → validating_institutional_candidate
  → building_handoff
  → complete
```

分支状态：

- `partial`
- `auth_required`
- `retrying`
- `failed`
- `canceled`
- `stale`

### 10.2 单条记录状态

- `queued`
- `skipped_existing`（通常在提交前由 Zotero context 过滤）
- `resolving`
- `candidate_found`
- `downloading`
- `validating`
- `verified`
- `unverified`
- `auth_required`
- `not_entitled`
- `unavailable`
- `failed`
- `canceled`

完整 job 可以包含 verified 与 unavailable 的混合结果；“部分文献没有全文”不应让
已经验证的其他 PDF 无法进入 Zotero。

## 11. PDF 验证契约

只有通过以下层级验证的文件可以进入自动 handoff。

### 11.1 文件级验证

- 响应和文件内容符合 PDF signature，而不是 HTML 登录页、错误页或 JSON；
- 文件非空并超过合理的最小尺寸；
- PDF parser 可以打开，页数大于零；
- 文件未加密到完全不可读，未严重损坏；
- SHA-256、MD5、byte size、MIME 和 page count 被记录；
- 下载文件位于私有 staging allowlist 内。

### 11.2 文献身份验证

`verification_level`：

- `strong_identifier`：PDF text/metadata 中的规范 DOI 或 repository ID 与目标一致；
- `strong_context`：从目标 DOI 的官方/OA landing page 得到主文 PDF，且标题/作者/年份
  交叉验证一致；
- `weak_title`：只有标题相似；
- `unverified`：无法证明身份；
- `mismatch`：identifier 或题名指向其他文献。

只有 `strong_identifier` 和 `strong_context` 可以自动附加。`weak_title`、扫描件无
可验证 metadata、`unverified` 和 `mismatch` 均不自动写 Zotero。

### 11.3 主文验证

adapter 必须把候选分类为：

- `main_article`
- `supplement`
- `correction`
- `editorial_or_cover`
- `unknown`

只有 `main_article` 进入 V1 handoff。页面上名为 PDF 的链接本身不是主文成功证据。

## 12. Fulltext Handoff 契约

### 12.1 共享目录

插件配置助手为 Fulltext MCP 和 Zotero MCP 配置一个共同的私有 exchange root：

```text
<app-data>/ai4s-literature-workbench/fulltext-exchange/
├── handoffs/
│   └── <handoff-id>.json
├── artifacts/
│   └── <sha256>.pdf
└── receipts/
    └── <handoff-id>.json
```

规则：

- 不放在仓库、桌面、Downloads 或云同步目录；
- POSIX 尽可能使用 owner-only 权限；Windows 使用当前用户私有应用数据目录；
- Zotero apply tool 只能读取该 allowlisted root 内、由 handoff 引用且 hash 相符的文件；
- 不允许 MCP 参数传入任意本地文件路径；
- handoff 和 receipt 长期保留，成功 artifact 作为本地 cache 按配置 TTL 清理；
- 用户显式要求保留本地副本时，可额外导出到用户指定目录，导出不改变 Zotero handoff。

### 12.2 Handoff 示例

```json
{
  "schema_version": 1,
  "handoff_id": "fth-...",
  "job_id": "ft-...",
  "request_id": "...",
  "created_at": "2026-07-22T00:00:00Z",
  "records": [
    {
      "evidence_id": "doi:10.1234/example",
      "zotero_item_key": "ABCD1234",
      "expected_parent": {
        "doi": "10.1234/example",
        "title": "Example article"
      },
      "retrieval": {
        "status": "verified",
        "provider": "unpaywall",
        "access_mode": "open_access_http",
        "document_version": "version_of_record",
        "file_role": "main_article",
        "retrieved_at": "2026-07-22T00:00:00Z"
      },
      "artifact": {
        "artifact_id": "sha256:...",
        "sha256": "...",
        "md5": "...",
        "bytes": 1234567,
        "content_type": "application/pdf",
        "page_count": 12
      },
      "verification": {
        "level": "strong_identifier",
        "doi_match": true,
        "title_match": true
      }
    }
  ],
  "handoff_hash": "sha256-of-canonical-handoff-without-this-field"
}
```

Handoff 不包含：

- password、token、Cookie、localStorage 或 institution account；
- 带会话参数的原始下载 URL；
- PDF 全文正文；
- 浏览器 trace、截图或 DOM；
- Zotero API key。

## 13. Zotero 附件写入工具

在 Zotero workbench profile 新增受控工具：

### `zotero_apply_fulltext_handoff`

输入：

```json
{
  "handoff_id": "fth-...",
  "handoff_hash": "...",
  "library_type": "user",
  "library_id": 123456
}
```

普通路径不接收 `file_path`、任意 parent key 或任意 MIME。工具从 allowlisted exchange
root 读取 handoff，并执行：

1. 校验 schema、canonical hash 和每个 artifact SHA-256；
2. 重新读取 Zotero parent item；
3. 要求 parent 为受支持 bibliographic item；
4. 要求 live DOI 与 `expected_parent.doi` 完全一致；
5. 重新读取 child attachments；
6. 已有可用文件 PDF 时幂等 `skip_existing`；
7. 仅对 `verified + main_article` 创建 `imported_file` child attachment；
8. 通过 Zotero File Storage 协议上传 bytes；
9. 回读 attachment metadata 并保存 receipt；
10. 返回 compact counts，不显示私有路径。

普通、精确、只增加附件的路径属于用户已经显式请求的低风险操作，可以像 Agent Tags
一样把内部 plan/hash/receipt 隐藏并自动执行。以下情况必须停止并返回精简风险摘要：

- live parent DOI 与 handoff 不一致或为空；
- parent item 缺失、重复或不是 bibliographic item；
- handoff hash、artifact hash 或 PDF 验证失败；
- 存在多个疑似主文附件且无法判断是否应跳过；
- 操作需要替换、删除或移动已有附件；
- 单轮超过 50 条；
- Zotero storage quota、权限或 group-library file policy 阻止上传。

## 14. Zotero 上传幂等与部分失败恢复

File Storage 上传包含“创建 attachment item → 请求 upload authorization → 上传 bytes →
register upload”。任一步失败都不能在重试时创建重复 child attachment。

每条 receipt 至少记录：

```json
{
  "evidence_id": "doi:10.1234/example",
  "parent_item_key": "ABCD1234",
  "artifact_sha256": "...",
  "attachment_item_key": "IJKL9012",
  "phase": "attachment_created|bytes_uploaded|registered|verified",
  "status": "pending|complete|conflict|failed"
}
```

恢复规则：

- 创建 attachment item 成功后立即原子保存其 key；
- 后续失败时复用同一 attachment key 完成 upload/register，不再创建新 item；
- receipt 已 complete 且 live attachment 仍存在时重试为 no-op；
- receipt complete 但 live attachment 缺失或 parent 改变时返回 conflict；
- 不自动删除半完成 attachment；无法恢复时留给用户在 Zotero Desktop 检查；
- 不利用文件存储层的 blob `exists` 响应替代 child attachment 去重；两者语义不同。

## 15. 错误与人工接管

稳定错误码：

| 错误码 | 含义 | 默认处理 |
|---|---|---|
| `NO_STABLE_IDENTIFIER` | 缺少可靠 DOI/arXiv/repository ID | 不下载，要求人工核对 |
| `NO_OPEN_ACCESS_COPY` | OA route 均无合法全文 | 若策略允许则进入机构回退 |
| `INSTITUTION_REQUIRED` | 闭源回退需要用户指定订阅机构 | 询问一次并存私有配置 |
| `INSTITUTION_ACCESS_UNAVAILABLE` | 当前网络/会话没有机构权限 | 提示连接官方校园网/VPN或稍后重试 |
| `AUTH_REQUIRED` | 需要机构 SSO/2FA | 保持可见浏览器等待用户 |
| `CAPTCHA_OR_CHALLENGE` | 出现验证或风控 | 人工接管，不绕过 |
| `NOT_ENTITLED` | 当前机构未订阅目标内容 | 记录 unavailable，不重复轰击站点 |
| `RATE_LIMITED` | 429/Backoff/共享 IP 限流 | 停止或按服务端要求退避 |
| `PUBLISHER_ROUTE_CHANGED` | 页面或官方下载路径无法安全识别 | 保存精简诊断，停止自动动作 |
| `DOWNLOAD_NOT_PDF` | 下载得到 HTML/错误页等 | 不进入 handoff |
| `PDF_INVALID` | PDF 损坏、为空或无法解析 | 不进入 handoff |
| `IDENTITY_MISMATCH` | PDF 与目标 identifier 不一致 | 隔离文件并报告失败 |
| `MAIN_ARTICLE_NOT_VERIFIED` | 只能找到 supplement/unknown 文件 | 不附加 Zotero |
| `ZOTERO_PARENT_CONFLICT` | live parent 与 handoff 不一致 | 停止写入 |
| `EXISTING_PDF` | 已存在主文 PDF | 幂等跳过 |
| `ZOTERO_STORAGE_QUOTA` | 存储配额不足 | 保留 artifact，提示用户处理配额 |
| `ZOTERO_UPLOAD_FAILED` | 附件上传中断 | 按 receipt 从最近阶段恢复 |

正常 unavailable 不是系统故障。面向用户的摘要应区分：无 OA、未订阅、需登录、
下载失败、验证失败和 Zotero 上传失败，不能笼统报告“无法获取”。

## 16. 浏览器、安全与合规

- OA-only job 不启动浏览器。
- 机构浏览器使用独立 Profile，不附着用户日常浏览器。
- 浏览器始终可见，允许用户完成合法机构认证。
- MCP 不启动 EasyConnect、aTrust、VPN 或其他系统网络客户端；用户自行连接后重试。
- 不把机构名之外的身份信息写入 handoff；详细 session state 保留在 Fulltext MCP 私有目录。
- 关键 UI 动作之后必须验证可见页面状态；click 成功、URL 变化或 Cookie 存在不是 PDF 成功证据。
- 不把 HTTP preflight 当作闭源 PDF 最终成功证据；成功必须有经过验证的 PDF artifact。
- 对 publisher route 使用保守并发和 provider-specific rate limit；不以批量速度牺牲机构共享出口。
- 不在日志中记录完整带签名下载 URL、认证重定向参数、API key 或用户账户信息。
- 失败截图/trace 可能包含研究主题或机构页面，只在诊断需要时保存并按 TTL 清理。

## 17. 私有文件与生命周期

Fulltext MCP 私有数据目录示意：

```text
<app-data>/ai4s-literature-workbench/fulltext/
├── profiles/
│   └── publishers/
├── jobs/
│   └── <job-id>/
│       ├── state.json
│       ├── attempts.jsonl
│       ├── candidates/
│       └── diagnostics/
├── cache/
│   └── <sha256>.pdf
└── broker.json
```

生命周期：

- job state、handoff 和 receipt 使用原子写入；
- verified artifact 复制/链接到 exchange artifacts 后不可原地修改；
- 上传失败的 artifact 保留到成功恢复或用户明确清理；
- 上传成功后 artifact 进入本地 cache，默认按可配置 TTL 清理；
- 用户显式导出的本地 PDF 不受自动 cache 清理影响；
- repository、plugin bundle 和 Git 永远不包含 PDF、Profile、Cookie、trace 或 receipt。

## 18. 上游复用策略

`forge/vpnsci` 当前对应上游 InstSci，可作为以下能力的研究和原型来源：

- OA-first route；
- publisher adapter registry；
- 可见浏览器与人工认证；
- DOI batch jobs、状态持久化和恢复；
- PDF bytes、解析和 identifier 验证；
- 机构身份路由与“不保存密码”边界。

它仍是 forge 资产，不能直接作为生产 bundle。进入生产前必须：

1. 审查并只提取符合本设计的合法 route；
2. 移除/禁用本设计排除的网络与访问策略；
3. 保留 MIT 许可证与第三方 notices；
4. 将 MCP 接口改造成异步、compact handoff，而不是返回整篇全文；
5. 使用插件私有 app-data 和 exchange directory；
6. 通过 macOS、Windows 和 WSL 的安装与可见浏览器验证。

Rimagination/scansci-pdf 可用于参考批量下载、provider fallback 和 MCP UX，但生产
设计不得引入其 Sci-Hub/LibGen、Tor、代理池规避、专有预编译 core 或与本设计冲突
的默认行为。任何代码复用需单独审查 Apache-2.0 和二进制例外。

## 19. Runtime 与插件集成

建议命名：

```text
runtime/package: literature-fulltext-runtime
MCP server: ai4s-literature-fulltext
tools: fulltext_*
```

考虑到 publisher adapter、PDF 解析和可见浏览器上游均以 Python 为主，V1 可采用
Python 3.10+ sidecar，并使用锁定依赖和独立虚拟环境。最终实现前仍应以跨平台安装
可靠性验证该选择；接口契约不绑定具体语言。

插件集成规则：

- `.mcp.json` 注册第三个可选 server；
- bootstrap 先保证 Skills + Zotero MCP 可用，再尝试安装 Fulltext MCP；
- Fulltext 安装失败只输出 warning，不让插件整体安装失败；
- browser/PDF parser 可作为分层 optional dependency，OA HTTP 最小路径优先可用；
- 配置助手分别检查 Zotero 写权限、fulltext exchange root、Python/runtime 和可选浏览器；
- capabilities 必须反映真实已安装组件，不允许静默假装 institutional browser 可用。

## 20. 并发、限流与批量策略

- 单 job 最多 50 条；更大集合按明确批次并经用户确认。
- OA provider 使用 provider-specific 并发、rate limit、Backoff 和 Retry-After。
- 同一 publisher host 默认串行；不得沿用高并发通用下载器默认值。
- 机构浏览器一次只处理一个交互状态，避免多个登录页和 download listener 竞争。
- 同一 DOI 在一个 active job 中只允许一个 canonical record。
- 相同 `request_id` 返回同一 job；不同项目请求同一 DOI 可复用已验证且未过期的本地 cache，
  但仍需为各自 Zotero parent 生成独立 attachment receipt。
- 连续出现 403、429、IP blocked 或 challenge 时停止该 host 的剩余任务，不能切换代理绕过。

## 21. 用户可见结果

普通成功结果示例：

```text
已将本轮 24 篇精选文献同步到 Zotero：
- 已有 PDF：6
- 新增 PDF：15（开放获取 11，机构授权 4）
- 未获取：3（无可用全文 2，当前机构未订阅 1）
- Zotero 上传：15 成功，0 待恢复
```

正常情况下不显示：

- handoff/receipt 路径；
- hash、逐条 route attempts 或长 JSON；
- institution session、浏览器 Profile 或诊断文件；
- PDF 本地私有 cache 路径。

用户要求诊断时可以按 DOI 给出 compact provenance：provider、access mode、结果、
验证级别、错误码和下一步；不得泄露凭据或带 token URL。

## 22. 测试策略

### 22.1 单元测试

- DOI/arXiv ID 规范化和 request hash；
- provider route ordering 与 OA-first；
- PDF signature、parser、page count 和文件 hash；
- DOI/title/document version/file role 验证；
- HTML 登录页伪装成 PDF、supplement、mismatch 和损坏文件；
- path allowlist、handoff canonicalization 和 schema validation；
- job/record 状态迁移和 canceled handoff 禁止；
- rate-limit、Backoff、403/429 自动停损。

### 22.2 Fulltext MCP 集成测试

- 本地 mock OA/publisher server；
- redirect、content-disposition、signed URL 脱敏和 partial download；
- 相同 request ID 幂等；
- mixed verified/unavailable partial job；
- runtime 重启后的安全恢复；
- OA-only 环境无浏览器依赖仍可工作。

### 22.3 Zotero MCP 集成测试

- exact parent DOI revalidation；
- 已有 PDF、linked URL、snapshot 和多个 PDF 分类；
- handoff/artifact hash mismatch 拒绝；
- attachment create/upload/register 全流程；
- 每个阶段注入失败并验证使用同一 attachment key 恢复；
- quota、权限、group-library policy 和 stale/deleted parent；
- receipt complete 重试 no-op；
- 任意 file path 输入不可达。

### 22.4 跨 MCP 端到端测试

使用受控 fixtures 验证：

```text
selected evidence
  → Zotero parent mapping
  → existing-PDF preflight
  → OA fulltext job
  → verified handoff
  → Zotero attachment receipt
```

机构访问 live tests：

- 只在用户明确授权的真实环境中手动运行；
- 不进入普通 CI；
- 使用可见浏览器，不使用真实密码 fixture；
- 每个 publisher 记录最近一次验证日期、route、结果和 blocker；
- 一次 publisher 成功不能推断其他 publisher 或其他年份订阅成功。

## 23. V1 验收标准

V1 完成必须同时满足：

1. 一个公开 OA DOI 在没有校园网、VPN、机构配置和浏览器的环境中成功获取并验证。
2. OA-only 路径不会启动 browser 或询问 institution。
3. OA 不可用时按 policy 返回 `NO_OPEN_ACCESS_COPY`，而不是伪造成功。
4. 用户已连接合法校园网/VPN时，可把该网络作为普通 direct entitlement 使用，MCP
   不启动或控制 VPN 客户端。
5. 需要 SSO/2FA/CAPTCHA 时只返回人工接管，不保存或填写敏感凭据。
6. Zotero 中已有文件 PDF 时不下载、不上传重复附件。
7. verified PDF 只挂到 exact DOI parent；identifier mismatch 永不写入。
8. supplement、HTML 错误页、损坏 PDF 和 unverified scan 永不自动写入。
9. upload 任一阶段失败后能在不创建第二个 child attachment 的前提下恢复。
10. Fulltext MCP 不可用、机构未订阅或部分下载失败不阻塞报告和 bibliographic import。
11. 正常用户结果只返回真实计数和可操作失败摘要，内部审计信息默认隐藏。
12. macOS 和 Windows 原生环境完成 OA + Zotero attachment smoke；WSL 根据 Zotero 与
    visible browser 的宿主边界提供明确支持说明和验证记录。

## 24. 实施阶段

### Phase A：契约与受控 fixtures

1. 固化 fulltext job、handoff、attachment receipt schema。
2. 建立 PDF/HTML/supplement/mismatch/scan fixtures。
3. 在 Zotero MCP 实现 `zotero_fulltext_context`。
4. 为现有 File Storage 上传补充部分失败幂等恢复能力。

### Phase B：OA MVP

1. 创建独立 Fulltext MCP runtime 和 `fulltext_*` 工具。
2. 实现 OA provider registry、下载、验证、私有 cache 和 handoff。
3. 实现 `zotero_apply_fulltext_handoff`。
4. 打通一个公开 OA DOI 到 Zotero child attachment 的端到端测试。

Phase B 不需要校园网络或可见浏览器，应先独立达到可发布质量。

### Phase C：机构访问回退

1. 审查并吸收 `forge/vpnsci` 中符合本设计的 InstSci 能力。
2. 实现独立可见 browser Profile、institution policy 和 publisher adapters。
3. 实现 auth-required/resume、provider matrix 和保守限流。
4. 在用户授权环境中逐 publisher 校准，不从单次成功泛化。

### Phase D：项目级编排与私有 Alpha

1. 在 `literature-manager` 增加 fulltext trigger、context 和 compact summary contract。
2. 允许项目记住 `fulltext_policy: selected-missing`。
3. 更新 plugin manifest、bootstrap、配置助手、README 和验证脚本。
4. 完成跨平台 smoke、失败恢复、存储配额和大批量风险测试。

## 25. 暂不进入 V1 的功能

- 自动替换或删除已有 PDF；
- 同一 Zotero item 的多版本主文管理；
- 自动下载 supplements、datasets、video 或 peer-review files；
- 对扫描 PDF 自动 OCR 后即视为 identifier verified；
- 全文翻译、问答、embedding 或 AI 摘要；这些属于读取/写作层，不属于获取层；
- 将 InstSci/ScanSci 的所有 provider、学校和网络策略原样搬入生产；
- 远程多租户托管机构浏览器或集中保存用户 entitlement；
- 跨用户共享闭源 PDF cache；
- 任何删除、合并或 Zotero attachment replacement。

## 26. 最终架构原则

全文获取是一个可选增强层，而不是文献调研和 Zotero 管理的单点依赖：

```text
检索证据是真实来源
Zotero parent 是管理目标
Fulltext handoff 是验证过的文件事实
Zotero attachment receipt 是最终写入事实
```

每一层都可独立失败、独立恢复、独立审计。Agent 负责把用户的一句话意图转换为
这些受约束的调用，但不得把“找到链接”“点击 PDF”或“存在 Zotero item”误报为
“全文已经验证并进入 Zotero”。
