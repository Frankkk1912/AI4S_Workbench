# Parallel Database Subagents

Use this pattern when one research question needs multiple independent sources,
such as PubMed, arXiv, and Web of Science. The main agent owns the shared query
plan and final synthesis. Subagents only retrieve source-specific evidence and
return concise handoffs.

## When to Split
- Split by independent database/source, not by final conclusion.
- Use subagents when each source requires separate search mechanics, browser
  access, exports, or enough retrieval work to justify parallelism.
- Do not split tiny one-source searches, dependent screening steps, or tasks
  where one result must change the next query.

## Subagent Prompt Rules
- Every prompt must say: load `literature-research` and follow **No Evidence, No
  Conclusion**.
- If the route requires browser access, the prompt must also say: load
  `web-access` and follow its CDP/tab isolation guidance.
- Describe the source-level goal and expected files; do not over-prescribe UI
  clicks unless the database pattern has a verified requirement.
- Ask for a handoff summary, not a final scientific answer.

## Required Handoff
Each subagent should return:
- database/source name,
- exact query used,
- filters, limits, date, and access mode,
- record count and output file paths,
- top 5 candidate records with stable IDs, DOI, PMID/arXiv ID/WoS accession, or URL,
- source-specific limitations or failures.

## Main-Agent Aggregation
1. Wait for every subagent or record a source failure explicitly.
2. Reject unsupported handoffs that lack saved evidence files.
3. Run `merge-rank` on all produced JSON files using the shared query plan or
   explicit keywords.
4. Inspect `score_reasons`, duplicates, source labels, and limitations.
5. Run `render-report`, then revise conclusions only from saved evidence.

## Safety Boundaries
- API sources still use the helper script rate limiters.
- Browser subagents must create and close their own `web-access` tabs.
- Do not commit private exports, PDFs, cookies, browser profiles, or
  subscription-derived full text.
