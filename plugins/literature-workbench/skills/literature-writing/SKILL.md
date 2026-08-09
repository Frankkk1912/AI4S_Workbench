---
name: literature-writing
description: >-
  Evidence-traced scientific literature writing for reviews, proposal
  backgrounds, manuscript introductions/discussions, and DOCX-ready section
  drafts. Use when the user has literature-research ranked evidence and/or Zotero
  match metadata and wants synthesized prose, bilingual research background,
  citation placeholders, reference audit tables, or manuscript-ready narrative
  under a strict No Evidence, No Conclusion policy.
---

# Literature Writing

## First-run API Onboarding

When installed through `literature-workbench`, honor the plugin-local
first-run onboarding status before the first workbench task. If the redacted
status reports `first_run`, tell the user that Zotero Web API, PubMed, and
EasyScholar credentials are optional, provide the returned application links,
and offer the plugin's local masked `setup` wizard. Also remind the user to
install the separate Zotero Desktop XPI manually for AI4S columns and Priority
controls, using `zotero_desktop_xpi` from the status report. Never ask for keys
in chat. Missing credentials never block writing from existing evidence. Mark
the guide offered after presenting it so the full introduction is not repeated.

## Overview

Use this skill to write scientific prose from saved evidence artifacts. It does
not search databases or manage a Zotero library directly; it consumes outputs
from `literature-research` and optionally `literature-manager`.

The hard rule is **No Evidence, No Conclusion**. Every claim must trace to saved
evidence, not memory, plausible mechanisms, or library metadata alone.

## Dependencies

- `literature-research`: required for search strategy, ranked evidence, abstracts,
  source links, and `report.md`.
- `literature-manager`: optional for Zotero keys, collection metadata,
  duplicate status, tags, and note handoffs.
- `documents:documents`: use only after Markdown prose is stable and the user
  asks for a DOCX or Word-targeted artifact.
- `nature-figure`: use only when the writing needs a manuscript-grade evidence
  figure or visual summary.

## Quick Start

Start from evidence files, not from a blank document:

```text
Inputs:
- ranked_all.json
- report.md
- optional zotero_sync_plan.json
- optional zotero_import_receipt.json

Output:
- review_section.md with [EV:<index>] and optional [ZOT:<key>] placeholders
- references_to_check.md only when weak, abstract-only, or unresolved citations exist
```

If the user asks for writing before evidence exists, route to
`literature-research` first. If evidence exists but Zotero keys are missing, use
`literature-manager` only for citation/library metadata.

## Workflow

1. Inventory inputs: ranked evidence JSON/CSV, report scaffold, Zotero match,
   sync, or import-receipt metadata, full-text notes, and user target format.
2. Build a claim outline. Each paragraph must list supporting evidence IDs
   before prose is drafted.
3. Draft in Markdown with placeholders such as `[EV:12]`, `[PMID:123]`,
   `[DOI:10.xxxx]`, and optional `[ZOT:ABCD1234]`.
4. Separate evidence tiers: established results, mechanistic interpretation,
   contradictions, limitations, and open questions.
5. Add a reference audit table with evidence ID, Zotero key, PMID, DOI, claim
   role, and verification status.
6. Inventory missing full text, weak matches, unsupported claims, and
   citation-order tasks. Create `references_to_check.md` only when this
   inventory is non-empty; otherwise record no extra audit artifact.
7. For DOCX output, hand the final Markdown to a document skill and verify
   rendered layout.

Read `references/writing-contract.md` for input/output and quality-gate rules.
Read `references/citation-policy.md` when citation placeholders, reference
tables, or final citation ordering matter.

## Writing Modes

- Review section: synthesize themes across ranked evidence and mark conflicts.
- Proposal background: state problem, knowledge gap, rationale, and hypothesis
  with explicit evidence IDs.
- Manuscript introduction: move from field context to mechanism to study gap.
- Discussion support: compare findings against prior evidence and separate
  direct support from speculation.
- Bilingual report prose: write rigorous English/Chinese sections while
  preserving scientific terminology and evidence traceability.

## Common Mistakes

- Do not write a literature narrative from Zotero titles alone.
- Do not hide search limitations; state database coverage, time range, caps, and
  full-text status.
- Do not convert placeholders to numbered references before claim order and
  evidence coverage are stable.
- Do not treat `AI4S:Semantic:*` Agent Tags as claim evidence. They are compact
  navigation metadata; trace every conclusion back to ranked evidence or
  verified full text.
- Do not cite or reason from `AI4S-Summary` alone. It is a one-sentence
  title-and-abstract navigation aid, not a replacement for the abstract or full
  text.
