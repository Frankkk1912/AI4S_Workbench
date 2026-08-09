# Advanced Retrieval Recipes

Read this reference only when the user explicitly needs an advanced or
diagnostic path beyond the PubMed-first `review` command. Keep every result
file auditable and avoid adding a second default workflow.

## Choose the Smallest Explicit Extension

| Need | Use | Read first |
|---|---|---|
| Add preprints | `review --arxiv` | `database-patterns/arxiv.md` |
| Add authorized Web of Science results | `review --wos-export <official.csv>` | `database-patterns/webofscience.md` and `web-access` |
| Add point-in-time citation counts | `review --citation-provider auto` | `source-policy.md` |
| Filter by CAS/JCR/IF data | `review --journal-metrics references/jcr_journals_2025.csv` plus explicit filter flags | `query-planning.md` |
| Inspect or revise query semantics | `plan`; use `expand-query` only for an explicit LLM-assisted expansion | `query-planning.md` |
| Custom source pipeline or recovery | low-level retrieval/ranking commands | `workflow-contract.md` |
| Independent, separable source work | `subagent-plan` only when a complete source handoff is useful | `parallel-subagents.md` |

## Advanced Commands Are Not the Default Surface

The following remain available for explicit troubleshooting, reproducibility,
or unusual source requirements. They must not become automatic agent steps:

- Planning/routing: `workflow-plan`, `pubmed-review-workflow`, `plan`,
  `database-route`, `subagent-plan`.
- Query scaffolds: `expand-query`, `journal-filter-query`,
  `compose-pubmed-query`.
- Source transforms: `search-pubmed`, `search-arxiv`, `import-wos-export`,
  `merge-rank`, `render-report`.
- Enrichment: `enrich-journal-metrics`, `enrich-citations`,
  `extract-conclusions`.

For a custom pipeline, preserve the saved query, source route, limits, filters,
retrieval date, and score reasons. The result must still converge on
`ranked_all.json`, `ranked_all.csv`, and one integrated `report.md` unless the
user explicitly requests a distinct artifact.

## Explicit Fallbacks

- Use an ISSN-filtered second PubMed pass only when the broad result is too
  large to retrieve and the generated filter is short enough for NCBI.
- Use LLM query expansion only after the user or agent has identified a real
  synonym, MeSH, CJK segmentation, organism, or exclusion gap worth auditing.
- Use Web of Science through authorized campus/browser access and official
  exports only; do not scrape around its controls.
- Use citation enrichment as a time-stamped ranking aid, not as a scientific
  quality verdict.

## References

- `query-planning.md`: query-plan schema, local metric filters, second-pass and
  LLM-expansion contracts.
- `source-policy.md`: API, authorization, and database policy.
- `ranking.md`: score interpretation and limitations.
- `workflow-contract.md`: custom pipeline, agent, and downstream-skill
  boundaries.
- `parallel-subagents.md`: the narrow conditions for parallel source work.
