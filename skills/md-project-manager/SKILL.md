---
name: md-project-manager
description: Acts as the Principal Investigator (PI) for Molecular Dynamics projects. Enforces the creation of a Pre-Simulation Brief (literature/structure research) and a Final Simulation Report (synthesis of plots and biology) to prevent context amnesia during long MD runs.
---

# MD Project Manager (`md-project-manager`)

## Overview
This skill governs the "Head and Tail" of the AI4S Molecular Dynamics workflow. Because MD simulations take days or weeks to complete, the Agent's conversational context window will inevitably forget the biological rationale discussed before the simulation started.

This skill solves "Context Amnesia" by establishing a **File-Based Memory System** using strict Markdown templates.

---

## Phase 1: Project Initiation (Pre-Simulation)

**Trigger:** When the user proposes a new MD simulation project, BEFORE running `md-simulation-run`.

### Agent Actions:
1. **Target Research**: Use `uniprot-database` and `pdb-database` to map domains, mutations, and missing regions.
2. **Literature Search**: Use `pubmed-database` to find existing MD papers on this target (look for known active sites, critical loops, required simulation times).
3. **Artifact Creation**: Generate a persistent artifact named `md_project_brief.md` in the current workspace using the template below.

### Template: `md_project_brief.md`
```markdown
# MD Project Brief: [System Name]

## 1. Biological Rationale & Hypothesis
*我们为什么要运行这个模拟？我们要回答什么生物学问题？（例如：“假设：D23A 突变破坏了盐桥，导致 loop 3 构象打开。”）*

## 2. Structural Target Profiling
*   **UniProt ID**: 
*   **PDB ID / Source**: 
*   **Domains of Interest**: (例如：激酶结构域 Res 100-300)
*   **Missing Regions / Mutations**: (指出哪些部分需要进行同源建模补全或手动突变)

## 3. Literature Precedents
*总结该靶点已有的 MD 研究文献。他们使用了什么力场？是否提到了高柔性区域？*

## 4. Simulation Strategy
*   **Force Field**: 
*   **Water Model**: 
*   **Target Duration**: (例如：100 ns)
*   **Key Observables**: (分析流水线需要重点关注什么？例如：残基 45 和 90 之间的距离变化)
```

---

## Phase 5: Final Conclusion (Post-Simulation)

**Trigger:** When `md-simulation-plotting` successfully finishes rendering the PDFs/PNGs.

### Agent Actions (CRITICAL STYLE ENFORCEMENT):
1. **Memory Retrieval**: Read the original `md_project_brief.md` from the workspace to recall the hypothesis.
2. **Data Integration**: Extract numerical evidence from the generated visual
plots before interpreting it alongside the original biological hypothesis and
saved docking outputs.
3. **Publication-Grade Formatting**: The report MUST be written in **Bilingual English/Chinese format** throughout the document.
4. **Academic Tone**: Use Nature/Science-tier structural biology terminology (e.g., "Conformational phase space", "Thermodynamic driver", "Allosteric restriction", "van der Waals packing").
5. **Artifact Creation**: Generate a persistent artifact named `md_final_report.md` using the precise template below.

### Golden Template: `md_final_report.md` (MUST FOLLOW)
```markdown
# [Project Title / 中英双语结题报告标题]
> [Date / Agent Name]

## 1. Executive Summary / 执行摘要
[English: One paragraph synthesizing whether the simulation confirmed the hypothesis in the Project Brief.]
[Chinese: 对应英文的精准学术翻译，总结模拟是否证实了项目假设。]

## 2. Simulation Parameters / 模拟参数
- **Force Fields / 力场**: [e.g., CHARMM36, GAFF]
- **Solvent Model / 溶剂环境**: [e.g., TIP3P, 150 mM NaCl]
...
[Must use bilingual bullet points]

## 3. Structural Stability & QC / 结构稳定性与质量控制 (Tier 1)
![QC Plot](/absolute/path/to/basic_qc_4panel.pdf)
### Key Stability Insights / 稳定性深入分析:
- **Structural Deviation (Backbone RMSD) / 骨架偏离度**: [Bilingual analysis of convergence and domain unfolding]
- **Local Fluctuation (RMSF) / 残基局部柔性**: [Bilingual analysis of loop mobility and active site locking]

## 4. Interactions & Secondary Structure / 界面相互作用与二级结构
![Hbonds](/absolute/path/to/basic_hbonds.pdf)
### Key Insights / 相互作用动力学分析:
- [Bilingual analysis of persistent polar contacts and internal networks]

## 5. Advanced Analysis / 高级动力学分析
### A. Conformational Phase Space (Free Energy Landscapes) / 构象相空间与自由能景观
![FEL Plot](/absolute/path/to/fel.pdf)
- [Bilingual analysis of deep energy basins, narrow global minimum vs broad multi-basin searches]

### B. Dynamic Network Analysis / 协同运动与动态网络分析 (If applicable)
![Network Plot](/absolute/path/to/network.pdf)
- [Bilingual analysis of coordinated domain motions and allosteric communication]

## 6. Docking Scores and Energetics / 对接评分与热力学数据 (If applicable)
[Include a well-formatted markdown table that keeps Vina/GNINA CNN scores and
post-MD MM/PBSA estimates in separate, explicitly named columns.]
### Energetic Interpretation / 热力学驱动机制剖析:
- [Bilingual interpretation of steric packing, electrostatics, or shape complementarity]

## 7. Conclusion & Next Steps / 结论与后续研究建议
1. **Verdict / 研究定论**: [Bilingual summary of final structural/dynamic ruling]
2. **Recommendations / 后续计算化学建议**: [Bilingual actionable next steps, e.g. MM/PBSA, mutagenesis]
```
