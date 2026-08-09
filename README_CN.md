# AI4S Workbench v0.1.0

[English](README.md)

[![许可证：MIT](https://img.shields.io/badge/License-MIT-0F766E.svg)](LICENSE) [![版本：v0.1.0](https://img.shields.io/badge/Release-v0.1.0-2563EB.svg)](https://github.com/Frankkk1912/AI4S_Workbench/releases/tag/v0.1.0)

> 不只是一套科研skills，而是为生物医药研究者赋能的AI4S工作流。

## 概览（Overview）

AI4S Workbench 是一套面向生物医药研究者的开源插件和可复用 Agent Skill。当前仓库中包含两条证据优先的工作流：Literature Workbench 负责文献检索、 Zotero 操作、公共开放获取、全文交接和证据可追溯写作；Molecular Modeling Workbench 负责 WSL2 原生的分子对接到分子动力学（Molecular Dynamics, MD）工作流。**持续开发新workbench与改进中。**

希望把长周期研究转化为文件化、可审阅的交接，减少AI幻觉的产生。文献工作流先保存检索计划、排序证据和报告，再写入 Zotero 或综合成正文；分子工作流则从环境引导一路保存环境凭证、项目简报、manifest、哈希、阶段记录和分析数据，贯通对接、GROMACS 与绘图。

安全边界清晰可见。可选文献凭据只保存在有掩码保护的本地配置中；高风险 Zotero 写入必须经过审核门禁；全文自动化仅限经验证的公共 OA 路径。分子环境引导会 fail closed，不静默执行特权操作，并要求科学项目位于 WSL Linux home 文件系统，而不是 `/mnt/*`。

## 功能特性（Features）

### 文献工作台（Literature Workbench）

- 检索、去重、限制数量并排序 PubMed 和 arXiv 证据，生成 `search_plan.json`、`ranked_all.json`、`ranked_all.csv` 与 `report.md`。
- 将审核后的记录和报告同步到 Zotero；审计重复项但不自动删除；管理受控 Agent Tags；只有用户显式请求后才生成 AI Summary。
- 验证合法的公共 OA PDF 候选，再通过独立的哈希绑定交接写入 Zotero 附件。
- 严格遵循 **No Evidence, No Conclusion（无证据，不结论）**，撰写综述、项目背景、引言和讨论。
- 可选安装独立的 Zotero Desktop metrics Add-on，展示证据/元数据列和可交互的个人 Priority 评分。

<!-- Screenshot: Zotero Desktop 展示 AI4S Priority 与 AI Summary 列。 -->

<!-- ![Zotero Desktop 中的 AI4S Priority 与 AI Summary 列](assets/zotero-ai4s-priority-ai-summary.png) -->

### 分子建模工作台（Molecular Modeling Workbench）

- 审计 Windows 11、名称严格为 `Ubuntu-22.04` 的 WSL2 发行版、原生 ext4 路径、锁定 Python、科学 CLI、Docker 与 NVIDIA GPU 证据，绝不静默提权。
- 运行以 GNINA 为先、明确回退到 AutoDock Vina 的对接，保留规范化 pose、引擎特异评分、manifest 和报告。
- 分析蛋白–配体或蛋白–蛋白接触，并生成 ChimeraX 优先、PyMOL 回退的可编辑场景。
- 完成配体参数化，将受保护输入绑定到 `md_handoff.json`；拓扑、力场或哈希不匹配时立即 fail closed。
- 分阶段运行 GROMACS 能量最小化、NVT、NPT 与 production，再分析 RMSD、RMSF、Rg、SASA、DSSP、PCA 或 DCCM，并生成可追溯图件。

<!-- Screenshot: 使用 ChimeraX 或 PyMOL 渲染对接复合物的 3D 图。 -->

<!-- ![ChimeraX 或 PyMOL 对接复合物 3D 渲染图](assets/docked-complex-3d-render.png) -->

## 快速开始（Quick Start）

```text
请从 https://github.com/Frankkk1912/AI4S_Workbench 拉取并为 Codex CLI 或 Claude Code 安装我选择的 AI4S Workbench 插件，同时严格区分两个工作台：如果选择 Literature Workbench，先确认当前是受支持的原生 macOS 或 Windows 环境，运行对应操作系统的 Runtime bootstrap，再运行 `node scripts/onboard.mjs status --output onboarding-status.json`；如果选择 Molecular Modeling Workbench，先确认 Windows 11、名称严格为 Ubuntu-22.04 的 WSL2 发行版，以及位于 WSL Linux home 而非 `/mnt/*` 的工作区；适用时运行只读 Windows 预检，初始化 WSL 工作台，并使用 `molecular-modeling-environment` 审计和验证当前 `environment_receipt.json`。请报告每项缺失要求；未经我审阅，不执行特权或破坏性变更；绝不要让我把凭据粘贴到聊天中；开始科研任务前，引导我完成首次配置。
```

请为当前任务选择一个工作台。Literature Workbench 支持原生 macOS 与 Windows bootstrap，需要 Node.js 20.19+ 和 npm；其 Skill 脚本还会使用 Python 3 与 `uv`。Molecular Modeling Workbench 的科学计算锁定在 Windows 11 + WSL2 `Ubuntu-22.04`，要求 Python `>=3.10,<3.13`、`uv` 和原生 ext4 工作区；外部科学工具始终由用户明确管理。

## 手动安装与配置（Manual installation & configuration）

请在所选工作台实际运行的操作系统中克隆仓库：

```bash
git clone https://github.com/Frankkk1912/AI4S_Workbench.git
cd AI4S_Workbench
```

### 文献工作台（Literature Workbench）

进入 `plugins/literature-workbench`，运行当前操作系统的原生 bootstrap，并检查脱敏后的 onboarding 状态：

```bash
cd plugins/literature-workbench
bash scripts/bootstrap-runtime.sh
node scripts/onboard.mjs status --output onboarding-status.json
```

Windows PowerShell：

```powershell
cd plugins\literature-workbench
.\scripts\bootstrap-runtime.ps1
node .\scripts\onboard.mjs status --output .\onboarding-status.json
```

### 分子建模工作台（Molecular Modeling Workbench）

在 Windows PowerShell 中运行只读预检；它会创建一个新的诊断目录：

```powershell
cd plugins\molecular-modeling-workbench
.\scripts\Start-AI4S-Workbench.ps1
```

在 WSL Linux home 文件系统下克隆或移动 checkout，禁止使用 `/mnt/*`；随后从 `Ubuntu-22.04` 初始化：

```bash
cd "$HOME/AI4S_Workbench/plugins/molecular-modeling-workbench"
node scripts/assemble-plugin.mjs check
node scripts/verify-plugin.mjs
bash scripts/setup-wsl-workbench.sh \
  --agent codex \
  --workspace "$HOME/AI4S-Workbench-Projects"
```

Claude Code 请改用 `--agent claude`。审阅生成的 checklist，只配置你批准的缺失工具，并让 Agent 运行 `molecular-modeling-environment`，直到当前 `environment_receipt.json` 显示 `ready: true`；否则对接与 MD 始终保持阻塞。

## 安装（Installation）

安装插件后，仍需执行上方对应工作台的原生 bootstrap 或 WSL 初始化。

### Codex CLI

安装 Codex CLI，将本地 checkout 添加为 marketplace；然后把 `codex plugin marketplace add` 输出的 marketplace 别名填入 `<marketplace-alias>`：

```bash
npm install -g @openai/codex
codex plugin marketplace add <repo-path>
codex plugin add literature-workbench@<marketplace-alias>
# 或
codex plugin add molecular-modeling-workbench@<marketplace-alias>
```

不要假设 `personal` 这类机器本地别名在另一套安装中仍然存在。

### Claude Code

以下是 Claude Code 插件命令，不是 shell 命令：

```text
/plugin marketplace add Frankkk1912/AI4S_Workbench
/plugin install literature-workbench@ai4s-workbench
```

添加同一 marketplace 后，也可以安装分子插件：

```text
/plugin install molecular-modeling-workbench@ai4s-workbench
```

## 配置（Configuration）

### 文献工作台（Literature Workbench）

无需 API Key，即可完成核心 PubMed/arXiv 检索、去重、排序，以及依据已保存证据写作。Zotero Desktop Local API 可免 Key 读取；获批的 Zotero 云端写入需要具备写权限的 Zotero Web API Key，文件上传还需要文件权限。

所有可选凭据都只是本地增强：

| 变量                    | 用途                                             |
| ----------------------- | ------------------------------------------------ |
| `ZOTERO_API_KEY`      | Zotero Web API 身份与获批的云端文献库写入        |
| `NCBI_API_KEY`        | 提高 PubMed E-utilities 配额，增强批量检索稳定性 |
| `EASYSCHOLAR_API_KEY` | 对选定期刊补充分区与指标                         |

不要把 Key 粘贴到 Agent 聊天中，也不要作为命令参数传递。请在 `plugins/literature-workbench` 中运行带掩码保护的本地向导：

```bash
node scripts/onboard.mjs setup --output onboarding-result.json
```

如需修改单个提供方，运行 `node scripts/onboard.mjs reconfigure --provider zotero|pubmed|easyscholar --output onboarding-result.json`。向导会先验证再替换，输出中只有脱敏状态。可选的 Zotero Desktop XPI 需要单独构建和安装；onboarding 结果会给出相应提醒。

### 分子建模工作台（Molecular Modeling Workbench）

无需 API Key，也不需要项目 `.env`。harness只能通过提供商官方流程认证。科学命令和大型计算文件必须保存在 WSL Linux `$HOME` 下；严禁在 `/mnt/c` 或任何其他 `/mnt/*` 路径执行科学计算。

受支持的 onboarding 目标是 Windows 11 与名称严格为 `Ubuntu-22.04` 的 WSL2 发行版。锁定 Runtime 使用 Python `>=3.10,<3.13`、`pyproject.toml`、`uv.lock` 和 `uv`。环境凭证会记录 GNINA、Vina、GROMACS（`gmx`）、acpype、Open Babel（`obabel`）、ChimeraX 与 PyMOL 的绝对路径和版本。缺少工具意味着能力检查失败，绝不代表可以静默替换后端或科学参数。

## Prompt 示例（Prompt Examples）

### 1. 审计分子建模环境

```text
请使用 molecular-modeling-environment 在对接前审计这个 Ubuntu-22.04 WSL2 工作区。检查原生 ext4 路径、锁定的 Python 与 uv Runtime、GNINA/Vina、GROMACS、acpype、Open Babel、ChimeraX/PyMOL、Docker 和 NVIDIA GPU 证据。不要安装任何内容，也不要使用 sudo。写出 checklist 与 environment receipt，报告每项缺失能力，并提出可审阅的配置计划。
```

**涉及组件：** `molecular-modeling-environment`。

### 2. 对接、分析并准备 3D 场景

```text
请为受体 [receptor.pdb] 和配体 [ligand.sdf] 创建可审计的 docking 项目。验证 ready 环境凭证，要求我确认质子化、配体电荷、结合位点中心与 box size；GNINA GPU 能力通过验证时运行 GNINA，否则明确记录 Vina 回退。排序单个 pose、分析接触信息并准备以 ChimeraX 为先的可视化；不要把 docking score 转述为结合能结论。
```

**涉及组件：** `docking-project-manager`、`docking-simulation-run`、`docking-complex-analysis`、`docking-visualization`。

### 3. 检索证据并同步审核后的选定文献

```text
请检索 NLRP3 在心血管疾病中作用的 PubMed 文献，自行拟定查询式。最多获取 50 篇，排序前 30 篇，保留 search_plan.json、ranked_all.json、ranked_all.csv 和 report.md。等我审核选定文献后，把项目 `nlrp3-cvd` 同步到 Zotero 集合 `NLRP3 cardiovascular disease`；继续前展示歧义或大批量新建审核，并且不要覆盖已有 Priority。
```

**涉及组件：** `literature-research`、`literature-manager`，以及 `ai4s-literature-zotero` 的 `zotero_sync_literature_project` 等 Tool。

### 4. 获取公共 OA 证据并据此写作

```text
对于我选定的精确 Zotero 父条目，只使用合法公共 OA 路径，轮询 Fulltext MCP 任务，并且只应用经验证的哈希交接。不要使用机构登录、VPN、Cookie 或绕过访问控制。随后依据已保存的 ranked_all.json 与 report.md 撰写综述章节，为每个科学结论添加 [EV:<index>] 占位符，披露检索上限和全文状态，并提供参考文献审计表。
```

**涉及组件：** `literature-manager`、`literature-writing`、`ai4s-literature-fulltext` 与 `ai4s-literature-zotero`。

## 可用技能（Available Skills）

插件 Skill 目录会随对应工作台打包；匹配的公共安全源文件也位于 [`skills/`](skills/) 下。内部 helper `molecular-geometry-common` 不作为独立的用户工作流提供。

### 文献工作台（Literature Workbench）

| 技能                    | 适用场景                                                                 |
| ----------------------- | ------------------------------------------------------------------------ |
| `literature-research` | 来源检索、去重、排序与可审计证据文件                                     |
| `literature-manager`  | 审核后的 Zotero 导入/同步、指标、重复项审计、Tag 与显式请求的 AI Summary |
| `literature-writing`  | 证据可追溯的综述、论文段落、双语正文与引文审计                           |

### 分子建模工作台（Molecular Modeling Workbench）

| 技能                               | 适用场景                                         |
| ---------------------------------- | ------------------------------------------------ |
| `molecular-modeling-environment` | 环境审计、onboarding、规划、bootstrap 与验证     |
| `docking-project-manager`        | 持久化 docking brief、决策、路由与最终报告       |
| `docking-simulation-run`         | GNINA 优先或 Vina 回退的蛋白–配体对接           |
| `docking-complex-analysis`       | 确定性的蛋白–配体或蛋白–蛋白接触几何分析       |
| `docking-visualization`          | ChimeraX 优先或 PyMOL 回退的离线 3D 场景         |
| `ligand-parameterization`        | 可审计的小分子参数化与`ligand_parameters.json` |
| `docking-to-md-handoff`          | 以哈希绑定选定 pose，完成配体 MD 准入            |
| `md-project-manager`             | 模拟前 brief 与基于证据的最终报告                |
| `md-simulation-run`              | 分阶段 GROMACS 准备、执行与恢复                  |
| `md-trajectory-analysis`         | 基础 QC 与由假说驱动的高级轨迹分析               |
| `md-simulation-plotting`         | 发表级 QC、FEL、DCCM/network 与几何分析图        |

### 独立可复用技能（Standalone reusable skills）

| 技能                                | 适用场景                                                 |
| ----------------------------------- | -------------------------------------------------------- |
| `scientific-infographic-onepager` | 生成可编辑 HTML + PNG 科学科普单图长图                   |
| `western-blot-processor`          | Western Blot 自动裁剪与 Gamma 对比度调整                 |
| `workflow-skill-creator`          | 经过强制头脑风暴，将已完成工作流提炼为可复用 Agent Skill |

## MCP 工具（MCP Tools）

Literature Workbench 在 [`plugins/literature-workbench/.mcp.json`](plugins/literature-workbench/.mcp.json) 中注册了恰好两个活动 Server。Molecular Modeling Workbench 不注册 MCP Server。

### `ai4s-literature-zotero`

workbench profile 提供受控的 Zotero 身份、搜索/读取、审核写入、组织和项目同步能力。以下是具有代表性的真实 Tool 与关键输入：

| 能力          | Tool                                                           | 关键输入                                                                                          |
| ------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 身份          | `zotero_whoami`                                              | 无                                                                                                |
| 搜索          | `zotero_search_items`                                        | `q`、`itemType`、`tag`、`collectionKey`、`limit`；可选 `library_type`、`library_id` |
| 条目/全文读取 | `zotero_get_item`、`zotero_get_fulltext`                   | `item_key`；全文还可传入 `query`、`page_range`、`max_passages`                            |
| 审核导入      | `zotero_apply_import_plan`                                   | `plan_path`、`mode`；apply 需要 `receipt_path`、`confirm_plan_hash`                       |
| 重复项审计    | `zotero_find_duplicates`                                     | `collection_key`/`tag` 二选一，并传入 `limit`                                               |
| 项目同步      | `zotero_sync_literature_project`                             | `project_slug`、`search_date`、`report_path`、`evidence_path`                             |
| AI Summary    | `zotero_ai_summary_context`、`zotero_apply_ai_summaries`   | 选定条目/Collection；apply 需要`trigger="explicit-user-request"` 与 `items`                   |
| OA 附件交接   | `zotero_fulltext_context`、`zotero_apply_fulltext_handoff` | 先传`item_keys`，再传 `handoff_id`、`handoff_hash`                                          |

重复项检测只读；确认合并仍需在 Zotero Desktop 中手动完成；高风险 apply 操作需要审核后的 Plan 与匹配哈希。

### `ai4s-literature-fulltext`

这个仅 OA 的 Server 提供 `fulltext_capabilities`、`fulltext_access_status`、`fulltext_fetch_submit`、`fulltext_job_status` 与 `fulltext_job_cancel`。提交任务使用 `request_id`、`route_policy="oa_only"` 和 `records[]`；每条记录都要标识其证据和 Zotero 父条目，并提供标题以及 DOI、arXiv ID 或 repository ID。轮询与取消使用 `job_id`。

全文支持**仅限公共 OA**。它不会自动访问机构或 SSO，不接收机构凭据，不连接 VPN，不绕过访问控制，不在聊天中返回 PDF 字节/全文，也不直接上传 Zotero。`fulltext_session_open` 是延期接口，在当前 Runtime 中返回 `INSTITUTION_ACCESS_UNAVAILABLE`。

## 项目结构（Project Structure）

```text
AI4S_Workbench/
├── .claude-plugin/                    # Claude Code marketplace manifest
├── .github/workflows/                 # CI 与发布契约
├── plugins/
│   ├── literature-workbench/
│   │   ├── .mcp.json                  # 两个活动 MCP Server
│   │   ├── skills/                    # 三个已打包文献技能
│   │   ├── runtime/                   # 已装配 Zotero MCP
│   │   ├── fulltext-runtime/          # 已装配 OA Fulltext MCP
│   │   └── source/                    # 可编辑 MCP 与 Zotero Add-on 源码
│   └── molecular-modeling-workbench/
│       ├── source-skills/             # 可编辑分子技能源码
│       ├── skills/                    # 生成的打包技能
│       ├── scripts/                   # 装配、检查、测试、onboarding
│       └── runtime-contract.json       # WSL/Python/工具证据策略
├── skills/                             # 独立公共安全技能源码
├── AGENTS.md                           # 开发规范唯一事实来源
├── CITATION.cff
├── LICENSE
├── package.json                        # 根 v0.1.0 版本来源
├── README.md
└── README_CN.md
```

## 开发（Development）

遵循 [`AGENTS.md`](AGENTS.md)，不要让私有数据和本地 Agent 状态进入 Git；生成区域只能通过对应源码工作流更新。

Molecular Modeling Workbench 应先编辑 `source-skills/`，再重新生成并验证：

```bash
cd plugins/molecular-modeling-workbench
npm run sync
npm run check
npm test
```

Literature Workbench MCP 代码只能编辑 `source/`，随后装配并检查 Runtime bundle：

```bash
cd plugins/literature-workbench
node scripts/assemble-plugin.mjs sync
node scripts/assemble-plugin.mjs check
```

Molecular 的 Ubuntu CPU contract 与 Literature 的 macOS/Windows release contract 是必需的 CI 门禁。根 Tag 代表整个仓库；插件版本仍由各自 manifest 与 changelog 管理。

## 许可证与引用（License & Citation）

AI4S Workbench 采用 [MIT License](LICENSE) 发布。使用 Molecular Modeling Workbench 时，请遵循 [`CITATION.cff`](CITATION.cff) 中的说明与元数据，并同时引用工作流实际使用的底层科学软件。根仓库 Release 版本由 `package.json` 与 `release-meta.json` 定义。
