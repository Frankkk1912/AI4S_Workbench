# EasyScholar 新导入默认化：实现设计稿

> 状态：Frank 已批准；插件实现与测试已完成  
> 目标：凡新的 Zotero 文献导入任务，默认查询 EasyScholar 并自动写入最新期刊指标；已有 collection 的指标回填仍只在用户显式要求时执行。

## 1. 更新的 skills

### `literature-research`

**更新后描述要点：** 当检索结果将进入 Zotero 时，对最终选定的期刊论文默认执行 EasyScholar enrichment；只查询 selected evidence，跳过 preprint，使用缓存和跨进程限速，失败时保留文献导入并生成缺失指标摘要。

### `literature-manager`

**更新后描述要点：** 新导入默认消费 EasyScholar-enriched evidence，并在受限 metrics namespace 内自动写入 IF/JCR/CAS；create 和 reuse 都处理。已有 collection 的批量回填仍要求用户显式触发，并继续走独立 reviewed plan。

不创建新的 umbrella skill；继续复用 `literature-research → literature-manager` 的窄职责交接。

## 2. 已确认的行为契约

1. 默认范围仅为**新导入任务**。
2. 已有 collection 的指标刷新/回填不自动运行。
3. EasyScholar API 返回值视为最新可用指标。
4. Zotero 显示年份不读取 API 配置，按任务年份减一：

   ```text
   display_metric_year = year(search_date) - 1
   ```

   例如 2026 年任务显示 `IF(2025)`。
5. create 和 reuse 都自动补写指标。
6. EasyScholar API 失败或无指标时，文献导入继续；最终摘要报告缺失项。
7. 新导入指标写入不展示 plan hash，不要求第二次确认。
8. IF、5-Year IF、JCR、CAS 都保存在 versioned `AI4S-Metrics` Extra，并都由 Zotero 自定义指标列渲染为带颜色的“皮肤”；此外，仅 JCR/CAS 同步为 `JCR:*`、`CAS:*` 原生 Zotero tags，供 Tags 面板筛选。
9. 不把连续数值 IF/5-Year IF 镜像成原生 tags，避免产生大量 `IF:28.3` 一类的高基数标签；其排序继续使用 Extra 中的原始数值。
10. 星级、Agent Tags、Article Type、人工标签及其他 Extra 文本必须保留。

## 3. 实施文件结构

```text
literature-research/
├── SKILL.md                                  # 默认 EasyScholar handoff 规则
├── references/workflow-contract.md          # selected-only enrichment 契约
├── scripts/literature_search.py             # selected-only/preprint-skip 支持
└── tests/test_literature_search.py           # 默认 enrichment 行为测试

literature-manager/
├── SKILL.md                                  # 新导入自动 metrics 契约
├── references/project-sync.md               # create/reuse 自动写入边界
├── references/import-contract.md            # metrics namespace 安全约束
├── scripts/zotero_literature_manager.py      # 共享 EasyScholar→metrics 规范化
└── tests/test_zotero_literature_manager.py   # 年份、create/reuse、skip 测试

runtime/
├── src/features/evidence-metrics.ts          # EasyScholar→metrics、Extra/tag 安全合并
├── src/features/evidence-metrics.test.ts     # 年份、preprint、reuse 回归测试
├── src/features/project-sync/sync.ts         # project sync 自动 metrics
├── src/features/import-plan/apply.ts         # reuse 安全合并
└── src/tools/sync-literature-project.ts      # 输入/输出摘要扩展

README.md                                     # 默认行为说明
literature-to-zotero-standard-workflow.md     # 已批准标准工作流
```

## 4. 现有能力复用

- `literature-research`：继续负责检索、selection 和 EasyScholar API enrichment，不在 MCP 内重复实现期刊查询。
- `literature-manager`：继续负责 DOI/PMID 匹配、Priority、collection、metrics 和语义标签的 Zotero 写入边界。
- `web-access`：只处理需要真实网页/登录态的来源；EasyScholar 使用现有 API 客户端。
- 现有 EasyScholar 客户端：复用 1 秒间隔、文件缓存、瞬时错误退避和密钥遮蔽。
- 现有 metrics contract：复用 versioned Extra、`JCR:*`/`CAS:*` 标签替换、item version 检查和 receipt。

## 5. 脚本和接口变更

### 5.1 `literature_search.py`

扩展现有 `enrich-easyscholar`，不新建独立脚本：

- 增加 `--selection-json`：只 enrichment 选定 stable evidence IDs。
- 默认识别并跳过 `article_types` 包含 `Preprint` 或期刊容器为 preprint server 的记录。
- 输出明确统计：selected、journal records、preprints skipped、unique journals、cache hits、API calls、matched、unmatched。
- 保留现有 `--min-interval` 和 `--cache`。

### 5.2 `zotero_sync_literature_project`

扩展 high-level project sync：

- 输入 evidence 使用 EasyScholar-enriched ranked JSON。
- 根据 `search_date` 推导 `display_metric_year = year - 1`。
- create：创建时直接写入 metrics Extra，并同步当前 JCR/CAS 原生 tags；IF、5-Year IF、JCR、CAS 都在自定义指标列中显示彩色“皮肤”。
- reuse：在加入 collection 的同一次受控更新中合并 metrics Extra，并同步当前 JCR/CAS 原生 tags。
- EasyScholar 缺失不阻塞同步；结果摘要增加：

  ```text
  metrics_updated
  metrics_missing
  metrics_preprint_skipped
  display_metric_year
  ```

- 内部保留计划和 receipt，但普通结果不暴露 hash/path。

### 5.3 独立 metrics backfill

现有 `plan-easyscholar-metrics-backfill` 和 `zotero_apply_metrics_plan` 保留，专用于：

- 用户显式要求刷新已有 collection。
- 修正错误历史年份。
- 批量迁移或审计。

该路径继续保留 dry-run + exact-hash 审批，不受新导入自动化影响。

## 6. 严格与灵活边界

### 严格

- 新导入必须尝试 EasyScholar；不得静默跳过。
- 只 enrichment selected evidence，不对全部命中查询。
- create/reuse 都处理 metrics。
- 显示年份必须是 `search_date.year - 1`，不得使用 fetched_at 年份。
- preprint 不得获得 IF/JCR/CAS。
- 自动写入只能修改 AI4S metrics block 与当前 JCR/CAS 标签。
- item version 冲突时不得覆盖。

### 灵活

- PubMed/arXiv/WoS 的来源组合随研究问题调整。
- selected evidence 数量和筛选标准由任务决定。
- EasyScholar 无数据时允许继续导入并报告。
- Agent Tags 和 Priority 仍按项目语义生成，不与期刊指标绑定。

## 7. 限速和缓存

- 继续使用现有 EasyScholar 1 request/second 默认限制。
- 缓存键为标准化期刊名；一个期刊在同一批和后续批次只请求一次。
- 多篇同刊共享一次 API 结果。
- 429 抛出专用 rate-limit error；5xx/网络错误指数退避。
- API key 只从私有配置或环境读取，永不进入计划、日志、报告或 repo。

## 8. 错误处理

| 情况 | 默认处理 |
|---|---|
| EasyScholar key 未配置 | 文献导入继续；结果明确报告 metrics unavailable/config missing |
| EasyScholar 瞬时失败 | 退避重试；仍失败则继续导入并报告 |
| 期刊无匹配 | 继续导入；记为 metrics missing |
| Preprint | 不调用或不消费期刊指标；记为 preprint skipped |
| DOI/PMID 冲突 | 沿用 project sync 高风险暂停，不因 metrics 自动化绕过 |
| reuse item version conflict | 暂停该条受控更新并报告；不覆盖用户修改 |
| metrics block 损坏/重复 | 不写入该条，报告 invalid metrics block |
| 大于 50 个 create | 仍保留现有 large-create review gate |

## 9. 验证计划

### 单元测试

1. selected-only enrichment 只查询入选期刊。
2. 同一期刊只调用一次 EasyScholar。
3. preprint 不调用 EasyScholar。
4. 2026 search date 生成 `by_year.2025`，绝不生成 `by_year.2026`。
5. create item 含 IF/5-Year IF、JCR/CAS 和正确标签。
6. reuse item 补写 metrics，同时保留已有 Priority、Semantic、Article Type、人工标签和 Extra。
7. API missing/error 不阻塞 bibliographic import。
8. existing collection refresh 不被自动触发。
9. version conflict 不覆盖。

### 集成测试

使用本次虚拟细胞样例作为回归场景：

- 输入：30 篇 selected evidence，其中 25 篇期刊、5 篇 preprint。
- 预期：30 篇完成 create/reuse；25 篇自动获得 `by_year.2025`；5 篇报告 preprint skipped；无需 metrics hash 确认。
- 抽查 scGPT：存在 `IF(2025)`、`5-Year IF(2025)`、`JCR:Q1`、`CAS:1区`，且星级和 Agent Tags 保留。

### Bundle 验证

```bash
node scripts/assemble-plugin.mjs sync
node scripts/assemble-plugin.mjs check
npm test
npm run build
```

并运行 repository-root Python tests、MCP integration tests 和 plugin runtime verification。

## 10. 不在本次升级范围

- 不自动刷新任意已有 collection。
- 不上传 PDF。
- 不自动合并/删除 Zotero 重复项。
- 不生成 `IF:*` 高基数标签。
- 不改变 Priority 或 Agent Tags 的所有权规则。
- 不把 EasyScholar 指标当作论文质量或阅读优先级。
