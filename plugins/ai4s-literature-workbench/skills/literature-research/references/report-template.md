# Literature Report Template

Use this structure for the final Markdown report.

```markdown
# Literature Search Report / 文献检索报告: [Topic]

## 1. Search Question / 检索问题
[English question]
[中文问题]

## 2. Search Strategy / 检索策略
- Databases / 数据库:
- Campus-access sources / 校园网资源: [WoS/library/full text, if used]
- Date searched / 检索日期:
- Query terms / 检索词:
- Journal filters / 期刊限定: [CAS/JCR/IF/ISSN source if used]
- Citation data source / 引用数据来源: [Crossref or another verified provider, if used]
- Limits / 限定条件:

## 3. Evidence Map / 证据概览
[Short bilingual synthesis. Every factual claim needs citations.]

## 4. Ranked Literature / 排序文献表
| Rank | Citation | Source | Year | Core conclusion / 核心结论 | Citations / 引用数 | Why included | Link |
|---|---|---|---|---|---|---|---|

The "Core conclusion" column is populated when `extract-conclusions` has been
run; otherwise it shows "abstract-level only / 仅摘要层面". The "Citations"
column is populated when `enrich-citations` has been run; otherwise it is
omitted from the table.

## 5. Answer / 科学问题回答
[Evidence-based answer with citations. Use footnote-style [^N] references.]

## 6. Limitations / 局限性
- Abstract-level screening only unless full text was retrieved.
- Result caps and database coverage.
- Preprint status if arXiv records are included.
- Core conclusions are abstract-level only unless full text was separately reviewed.

## References / 参考文献
[^1]: ...
```

During the same synthesis pass, write the compact
`priority_recommendations.json` sidecar described in
`priority-recommendations.md`. Papers used for core conclusions may be Priority
3; important supporting papers may be Priority 2; selected papers omitted from
the sidecar default to Priority 1 downstream. Do not perform a second LLM pass.

## Writing Rules
- Use cautious language when only abstracts are available.
- Separate review articles, original studies, preprints, and computational work.
- Do not mention impact factor or JCR quartile unless retrieved from a verified
  source.
- Keep links and DOI/PMID/arXiv IDs traceable.
- When journal metrics are used, state the metrics source file generically
  without exposing private local paths in user-facing reports.
- When core conclusions are extracted, label them as "abstract-level" and do not
  present them as full-text findings.
- When citation counts are displayed, note the data source provider and that
  counts are point-in-time snapshots.
- Priority expresses project reading/use priority, never evidence quality.
