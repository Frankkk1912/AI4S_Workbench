# Zotero 期刊指标与标签展示设计

> 当前实现版本：`literature-metrics 0.1.11`

## 1. 目标

为 `literature-metrics` Zotero add-on 建立一套可排序、可审计、低干扰的期刊指标与文献标签展示。

核心原则是区分三类信息，并把底层排序值与视觉“皮肤”分离：

- **连续型指标**：IF、5 年 IF。使用独立数值列和连续数值排序键；颜色只按区间提供冗余视觉提示，不替代原始数值。
- **有序分类指标**：JCR、CAS。保留独立列和显式等级排序键，颜色与文字共同表达 1–4 级。
- **离散语义指标**：中科院学科分区、TOP、ESI 学科、EI 收录等。集中进入 `Journal Metrics` 列，以紧凑标签展示。
- **文献分类与阅读优先级**：`Article Type` 显示结构化文献类型；`Priority` 显示用户拥有的项目阅读/使用优先级。二者均以命名空间 Zotero tags 为持久层。

Zotero add-on 只负责解析和展示。EasyScholar 请求、期刊匹配、缓存、数据年份判定、计划审核和 Zotero 写入继续由 `literature-research`、`literature-manager` 与 `literature-zotero-mcp` 负责。

## 2. 数据年份

当前 EasyScholar 返回的 `sciif`、`sciif5`、`sci/esci`、`sciUp` 等字段没有显式携带指标年份。本工作流将本批已核对数据统一记录为 **2025**：

- `IF(2025)`
- `5-Year IF(2025)`
- `JCR(2025)`
- `CAS(2025)`

API 查询时间单独记录为 `retrieved_at`，不得用查询年份制造 `IF(2026)` 等未经证实的新年度指标。后续若数据源能够提供明确版本年份，才创建新的年度记录。

## 3. 列设计

| 列 | 类型 | 数据字段 | 排序行为 | 视觉表达 |
| --- | --- | --- | --- | --- |
| `IF(YYYY)` | 连续数值 | `impact_factor` | 原始数值升降序；空值置后 | 五档序列色 chip，文字保留原值 |
| `5-Year IF(YYYY)` | 连续数值 | `impact_factor_5y` | 原始数值升降序；空值置后 | 与 IF 相同的五档序列色 chip |
| `JCR(YYYY)` | 有序分类 | `jcr_zone` | 显式等级键；降序为 Q1 → Q4 | 四级分类色 chip |
| `CAS(YYYY)` | 有序分类 | `cas_zone` | 显式等级键；降序为 1区 → 4区 | 与 JCR 对应的四级分类色 chip |
| `Journal Metrics` | 离散语义 | `publication_metrics[]` | 主要用于扫读；使用稳定的标签优先级 | 单行紧凑语义 chip |
| `Article Type` | 离散分类 | `AI4S:ArticleType:*` tags | 稳定词典顺序 | article、review、clinical study 等紧凑标签 |
| `Priority` | 有序分类 | `AI4S:Priority:1\|2\|3` tag | 1 → 3 的数值顺序 | `★`、`★★`、`★★★` 交互式评级；冲突时显示 `⚠` |

`Journal Metrics` 为单一列，默认展示最新已核验年度的语义指标，不为每个年份重复注册一列。底层 JSON 字段继续使用 `publication_metrics[]`，仅用于兼容现有 schema v2 记录，不作为界面名称。

## 4. Journal Metrics 标签

第一阶段只启用跨领域、含义稳定的字段：

| EasyScholar 字段 | 结构化 code | 显示示例 |
| --- | --- | --- |
| `sciUp` 的完整大类分区 | `cas_major` | `医学1区` |
| `sciUpTop` | `cas_top` | `TOP` |
| `esi` | `esi_category` | `ESI 临床医学` |
| `eii` | `indexing` | `EI` |

默认不展示学校榜单、`xr/xrSmall/xrTop` 或来源含义尚未核实的字段。它们可在未来通过明确的用户配置加入，而不是进入默认标签集合。

标签数据保存为结构化对象，显示文案由 add-on 生成，避免将颜色或最终文案写死在数据层：

```json
{
  "schema_version": 2,
  "by_year": {
    "2025": {
      "impact_factor": 9.2,
      "impact_factor_5y": 8.5,
      "jcr_zone": "Q1",
      "cas_zone": "1区",
      "publication_metrics": [
        {"code": "cas_major", "value": "医学1区"},
        {"code": "cas_top", "value": true},
        {"code": "esi_category", "value": "临床医学"}
      ],
      "retrieved_at": "2026-07-16",
      "source_label": "easyscholar-2025",
      "source_sha256": "..."
    }
  }
}
```

## 5. 展示语言

借鉴 Zotero Style 的多标签扫读方式，但不复制其代码或数据架构。所有指标使用低饱和背景、深色文字、1 px 边框和 3 px 圆角的紧凑 chip。颜色始终是冗余编码：真实数值或分区文字必须可见，不能只依赖颜色传达信息。

### 5.1 IF 与 5-Year IF

IF 保留连续数值排序键，显示层按以下无空档区间着色。边界值 40 进入最高档：

| IF 区间 | 背景色 | 文字色 | 边框色 |
| --- | --- | --- | --- |
| `<5` | `#EEF1F4` | `#4B5563` | `#D5DAE0` |
| `5–<10` | `#E5EEF7` | `#28577A` | `#BED1E3` |
| `10–<20` | `#DDF1EE` | `#17685E` | `#A9D9D1` |
| `20–<40` | `#EAE7F4` | `#57427C` | `#CBC2E0` |
| `≥40` | `#E8DFF0` | `#673D73` | `#CBB7D3` |

区间转换只影响皮肤，不把 IF 数据离散化存储，也不参与排序。悬停提示同时显示原始 IF 与所属区间。

### 5.2 JCR 与 CAS

JCR/CAS 使用相同的四级视觉层级，并使用隐藏等级键实现有序分类排序。Q1/1区 编码为最高等级，降序排序时优先显示：

| 等级 | JCR/CAS 示例 | 背景色 | 文字色 | 边框色 |
| --- | --- | --- | --- | --- |
| 1 | `Q1` / `1区` | `#DDF1EC` | `#176B5B` | `#A9D9CE` |
| 2 | `Q2` / `2区` | `#E3EEF8` | `#285F8F` | `#B8D0E5` |
| 3 | `Q3` / `3区` | `#F7EDD4` | `#7A5A16` | `#E5CF98` |
| 4 | `Q4` / `4区` | `#F8E4DF` | `#8B3E2F` | `#E4BDB3` |

### 5.3 Journal Metrics

`Journal Metrics` 使用以下低干扰语义色：

- CAS 大类分区：青蓝色系，突出“学科 + 分区”。
- TOP：单一深紫强调色，作为本列唯一高显著性标签。
- ESI 学科：中性蓝灰。
- EI：石板蓝。

同一单元格强制单行、不换行；超出列宽的内容裁切，并通过悬停提示提供完整标签文本。不使用进度条、渐变或动画。标签的记忆点来自学术分类语言本身，而不是装饰。

默认显示顺序：`cas_major` → `cas_top` → `esi_category` → `indexing`。重复标签在写入前去重。

## 6. Article Type 与 Priority

### 6.1 Article Type

`Article Type` 从 PubMed publication types、Web of Science document type 等结构化来源读取，经 `literature-manager` 规范化后存入 `AI4S:ArticleType:*` Zotero tags。不得仅凭标题或摘要猜测类型。用户也可以通过 Zotero 原生标签面板手动添加或删除这些 tags。

一篇文献可以同时具有多个 Article Type，例如 `article` 与 `clinical study`。add-on 负责去重、稳定排序和隐藏被更具体类型覆盖的宽泛冗余类型，不修改底层 tags。

### 6.2 Priority 的含义与自动初始化

`Priority` 表示某一项目中的个人阅读/使用优先级，不代表证据质量、偏倚风险、期刊水平或检索排序分数：

| Zotero tag | 显示 | 含义 |
| --- | --- | --- |
| `AI4S:Priority:1` | `★` | 背景或补充阅读 |
| `AI4S:Priority:2` | `★★` | 重要文献 |
| `AI4S:Priority:3` | `★★★` | 核心、必须阅读或直接支撑关键结论 |

`literature-research` 可在报告撰写的同一轮判断中输出紧凑的 `priority_recommendations.json`。入选文献默认初始化为 Priority 1，sidecar 只记录明确提升为 Priority 2/3 的文献、稳定 evidence ID 和简短 reason codes，不进行第二轮逐篇 LLM 审计。

`literature-manager` 将 sidecar 哈希及每条推荐写入带哈希的导入计划。Priority 首次写入后归用户所有：规划阶段和 MCP 实际 apply 阶段都必须检查已有 `AI4S:Priority:1|2|3`，普通导入或同步不得覆盖用户设置。

### 6.3 用户手动新增、修改与清除 Priority

当前版本同时提供 `Priority` 列内星级控件与 Zotero 原生标签面板：

1. 单元格以 `★` 显示已保存等级，以低强调度 `☆` 显示其余可选位置。
2. 已保存星级使用醒目的金色，鼠标悬停某颗星时使用更亮的金色临时预览 1–3 级，不写入数据；移出单元格恢复已保存等级。
3. 星星自身拦截 Zotero 的行选择鼠标事件，因此第一次点击即可提交；单元格其他空白区域仍可正常选中整条文献。
4. 点击某颗星时，在一次 Zotero transaction 中移除旧的有效 Priority tags 并写入所选等级；点击当前已保存等级则清除 Priority。
5. 键盘焦点进入单元格后，方向键调整预览，Enter/Space 确认，Escape 取消预览，Delete/Backspace 清除。
6. 原生标签面板继续作为透明、可审计的备用编辑入口。

`0.1.11` 的批量功能是在原有鼠标星级控件之上新增，不替代或削弱单条交互。四种入口并存：鼠标悬停负责无写入预览，鼠标单击负责单条提交，数字键或右键菜单负责单条/多条统一设置，原生标签面板负责透明的备用编辑。无论是否已多选条目，Priority 单元格中的悬停预览和单击评级都必须继续可用。

批量设置时，在 Zotero 主条目列表中多选文献后可直接按 `1`、`2`、`3` 统一设置相应星级，按 `0` 清除；右键菜单“Set Priority”提供相同的 `★`、`★★`、`★★★` 与清除命令。裸数字快捷键仅在焦点位于主条目列表时生效，在搜索框、编辑器、PDF 阅读器、组合键或按键重复状态下必须忽略。批量操作只处理普通且可编辑的文献，去重后逐条原子替换 Priority namespace；完成提示必须分别报告已更新、未变化、只读跳过和失败数量。

同一文献出现多个有效 Priority tags 时，add-on 必须显示 `⚠`，悬停提示列出冲突 tags，且不得自动选择或删除。用户明确点击某颗星时视为主动解决冲突：控件可以原子替换为用户选择的唯一等级。导入规划器和 MCP 仍不得静默解决冲突。

## 7. 与 Zotero Style 的边界

可借鉴：

- 多个彩色 chip 集中显示在一个列中。
- 原始字段、显示文本和颜色映射相互分离。
- 用户可快速扫读不同期刊的语义属性。

不采用：

- add-on 内直接携带 key 调用 EasyScholar。
- 仅按期刊名即时匹配。
- 按 item 保存无年份、无来源哈希的本地缓存。
- 将数值指标与语义标签混在同一展示和排序逻辑中。
- 大量学校榜单默认进入界面。

参考项目采用 AGPL-3.0。本项目只采用经过独立分析后的交互思想，不复制其源码。

## 8. 写入与安全边界

- `AI4S-Metrics:` 仍是唯一受管理的 Extra 行。
- 非 AI4S Extra 文本必须保留。
- add-on 不联网、不持有 API key；期刊指标、引文和 Article Type 保持只读。
- 唯一直接写入范围是用户通过 Priority 星级控件、限定作用域数字快捷键或条目右键菜单发起的明确操作，且只能原子替换 `AI4S:Priority:1|2|3`，必须保留其他 tags 与所有条目字段。
- 新字段只能通过经哈希的 metrics plan 写入。
- dry-run、准确 plan hash 确认和 receipt 规则保持不变。
- 默认只把 `JCR:*`、`CAS:*` 同步为真实 Zotero tags；`Journal Metrics` 只在列内显示，避免污染标签选择器。
- `AI4S:ArticleType:*` 与 `AI4S:Priority:1|2|3` 是专用展示 tags；已有 Priority 是用户拥有的数据，普通 Agent 工作流不得覆盖。

## 9. 年度列生命周期

- add-on 启动时只注册当前 `AI4S-Metrics:` payload 中实际存在的年度。
- 新增年度数据时动态注册该年度的 IF、5-Year IF、JCR、CAS 列。
- 当最后一条对应年度数据被修改、删除或移入回收站后，重新扫描受管理记录并注销该年度的四个列。
- `retrieved_at` 只表示检索日期，不能触发新的指标年度列。

## 10. 验收标准

1. IF 和 5 年 IF 均按原始连续数值而非字符串或颜色区间排序。
2. 4.99、5、10、20、40 分别进入五个不同的 IF 颜色档。
3. JCR/CAS 降序排序分别为 Q1 → Q4、1区 → 4区。
4. JCR、CAS 和 Journal Metrics 可在列选择器中独立启用。
5. `Journal Metrics` 能以单行显示学科分区、TOP、ESI 与 EI 标签，并省略冗余“中科院”前缀。
6. 所有颜色编码同时保留可读文字，不以颜色作为唯一信息载体。
7. 旧 schema v2 payload 继续正常显示。
8. 缺失或损坏字段显示为空，不触发网络请求或写入。
9. 2025 数据不会因为 2026 年查询而自动生成 2026 指标列；已无数据的年度列会被注销。
10. metrics apply 保留用户 Extra、普通 tags、collection 和 citation 数据。
11. `Article Type` 只读取 `AI4S:ArticleType:*`，支持多类型、去重和稳定显示。
12. `Priority` 将 1–3 分别显示为一至三星，并按隐藏数值键排序。
13. Priority 支持亮色悬停预览、第一次点击直接提交、再次点击同级清除及完整键盘操作；悬停本身不得写入，星星点击不得先触发行选择，批量功能不得移除或改变这些单条鼠标交互。
14. 主条目列表支持 `1/2/3` 批量设级和 `0` 批量清除，并提供等价右键菜单；输入控件、PDF 阅读器、组合键和长按重复不得触发。
15. 批量操作跳过附件、笔记和只读条目，保留所有非 Priority tags，并报告已更新、未变化、跳过和失败数量。
16. 用户仍可在 Zotero 原生标签面板新增、修改或清除 Priority；后续 Agent 导入不得覆盖已有值。
17. 多个有效 Priority tags 同时存在时显示 `⚠`；只有用户明确选择星级才能原子解决，其他组件不得静默解决冲突。
18. Priority 推荐与报告撰写共用一次判断过程，默认 1，仅把显式 2/3 提升写入 sidecar。
