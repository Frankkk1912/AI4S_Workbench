# Query Planning Reference

Use this reference when converting a user request into a search strategy.

## Query Plan Fields
- `question`: the user's scientific or bibliographic question.
- `constraints`: time range, organism, article type, journal, database, language,
  and any inclusion/exclusion criteria.
- `core_terms`: required entities such as genes, proteins, compounds, diseases,
  pathways, methods, or phenotypes. Now includes CJK terms (e.g. 心血管疾病).
- `expanded_terms`: synonyms, spelling variants, capitalization variants,
  MeSH-style disease terms, and related biomedical phrases.
- `exclude_terms`: terms that would create false positives.
- `mesh_terms`: MeSH descriptor terms for diseases, processes, and entities
  (populated by `expand-query` apply mode).
- `pubmed_query`: Boolean query suitable for PubMed.
- `journal_filter`: optional CAS/JCR/impact-factor limits and the external CSV
  used to derive an ISSN filter.
- `arxiv_query`: compact keyword query suitable for arXiv.
- `wos_query`: Boolean query suitable for Web of Science Topic search.
- `campus_access_notes`: whether campus IP, VPN, institutional login, or a
  visible browser is needed for paid databases or full text.
- `screening_notes`: what makes a hit relevant or irrelevant.
- `expansion_source`: `null` for naive plans, `"llm-assisted"` when
  `expand-query` apply mode has been used.
- `expansion_detail`: structured record of what was expanded (synonyms,
  related diseases, exclusions, organism, study types).
- `expansion_applied_at`: ISO date when expansion was applied.

## Expansion Rules
- Preserve the user's exact terms.
- Add biological aliases only when they are standard or clearly derivable.
- Expand disease families carefully. Example: cardiovascular disease can include
  heart failure, myocardial infarction, cardiomyopathy, atherosclerosis, and
  vascular dysfunction when the user asks broadly.
- Keep organism constraints explicit. Do not mix human, mouse, cell-line, and
  computational-only evidence without labeling them.
- Record every expansion in the plan so the user can audit it.

## CJK Term Extraction
The `plan` command now captures continuous CJK character runs (e.g. 心血管疾病,
心肌病) as candidate terms. This is naive extraction — it does not perform
word segmentation. Use `expand-query` for domain-aware splitting of CJK runs
into individual biomedical terms.

## Query Pattern
For PubMed, prefer:

```text
(ENTITY_SYNONYMS) AND (DISEASE_OR_PROCESS_SYNONYMS) AND (OPTIONAL_METHOD_OR_CONTEXT)
```

When `expand-query` is used, the PubMed query also includes MeSH clauses,
organism constraints, year ranges, and exclusion terms:

```text
(TERM1) AND (TERM2) AND ... AND ("MeSH Term"[MeSH Terms] OR ...) AND "organism"[Organism] AND "YYYY:YYYY"[dp] NOT "excluded"
```

For arXiv, use shorter keyword strings. arXiv is less reliable for biomedical
synonym-heavy Boolean searches, so keep the query compact.

For Web of Science, prefer a Topic-style Boolean query that preserves the same
core concepts but avoids PubMed-only field syntax:

```text
TS=((ENTITY_SYNONYMS) AND (DISEASE_OR_PROCESS_SYNONYMS) AND (OPTIONAL_CONTEXT))
```

Record WoS filters separately, such as publication years, document types,
research areas, Web of Science Core Collection scope, language, and citation
sorting. Do not silently translate WoS result counts into PubMed-style evidence
coverage; the databases index different records and metadata.

## Local Journal-Quality Filter Pattern
Use this pattern when the user requests journal quality restrictions such as
中科院分区, JCR quartile, impact factor, or "top journals":

1. Create `search_plan.json` with the executable PubMed query, time range,
   database, inclusion/exclusion criteria, and journal-quality constraints.
2. Run the core PubMed query and save the retrieved records to `pubmed_raw.json`.
3. Run `merge-rank` on the broad retrieved records and save
   `ranked_all.json` plus `ranked_all.csv`.
4. Run `enrich-journal-metrics` with the same CAS/JCR/IF constraints and
   `--filter-to-matches` to perform the actual local filtering by saved ISSNs.
   For JCR Q1 and IF >=5, save `filtered_q1_if_gt5.json` plus
   `filtered_q1_if_gt5.csv`.
5. Render `report.md` from the locally filtered ranked JSON.

For multi-database workflows, raw/normalized source outputs use stable
database-prefixed names such as `pubmed_raw.json`, `arxiv_raw.json`, and
`wos_raw.json`.

This is the default because large Q/IF journal sets can produce PubMed ISSN
queries that exceed NCBI URL/request limits. Do not generate journal-filter
audit files in the default path.

## Explicit PubMed Second-Pass Fallback
Use this only when the biological topic result set is too large to download and
the generated ISSN filter is short enough for NCBI:

1. Generate an ISSN filter from the bundled journal metrics CSV (or an explicit
   reviewed override) with `journal-filter-query`.
2. Run a second PubMed query:

```text
(CORE_QUERY) AND (ISSN_FILTER_QUERY)
```

3. Merge/rank the second-pass records and enrich them with
   `enrich-journal-metrics`.

Keep the ISSN filter file as audit evidence. If no journals match the filter,
report that the journal-quality constraint eliminated the search space.

### MeSH-Enhanced Fallback Pattern
When `expand-query` has populated `mesh_terms`, you can combine the ISSN filter
with MeSH terms for a tighter second pass:

```bash
uv run literature-research/scripts/literature_search.py journal-filter-query \
  --journal-metrics journal_metrics.csv \
  --cas-zones 1区 2区 \
  --mesh-terms "GPLD1 protein, human" "Cardiovascular Diseases" \
  --output journal_filter.json
```

PowerShell:

```powershell
uv run literature-research/scripts/literature_search.py journal-filter-query `
  --journal-metrics journal_metrics.csv `
  --cas-zones 1区 2区 `
  --mesh-terms "GPLD1 protein, human" "Cardiovascular Diseases" `
  --output journal_filter.json
```

This produces both `pubmed_issn_query` and `pubmed_mesh_query`, plus a
`pubmed_combined_query` that ANDs them together.

## LLM-Assisted Query Expansion (scaffold/apply contract)

The `expand-query` subcommand uses a two-step contract that keeps the Python
script deterministic while allowing LLM intelligence to enter the pipeline:

### Step 1: scaffold
The script reads the query plan and emits a JSON skeleton with `current_core_terms`
and empty `expansion` fields. The agent (LLM) fills the expansion fields.

### Step 2: apply
The script merges the filled expansion into the query plan:
- `expanded_terms` = core_terms + synonyms + related_diseases (deduplicated, case-insensitive)
- `exclude_terms` = original + new exclusions
- `mesh_terms` = populated from expansion
- `pubmed_query` / `arxiv_query` / `wos_query` = regenerated from expanded terms
- `expansion_source` = `"llm-assisted"` (audit marker)
- `expansion_applied_at` = current date (audit marker)

### Auditability
Every LLM expansion is traceable:
- `expansion_source` distinguishes naive vs LLM-assisted plans
- `expansion_detail` records exactly what was added and from which category
- `core_terms` is never modified — expansions go into `expanded_terms`
- Downstream `merge-rank` reads `expanded_terms` for ranking, so expanded
  terms contribute to scoring

## When to Ask Before Searching
Ask the user only if the ambiguity changes the biological target, such as:
- same abbreviation maps to multiple genes/proteins,
- disease acronym has multiple meanings,
- user asks for "best papers" but does not specify review vs original studies,
- paid or logged-in databases such as Web of Science are required and the agent
  cannot determine whether the current browser has campus access.
