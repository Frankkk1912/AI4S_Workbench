# Literature Writing Contract

Use this reference when drafting review, proposal, manuscript, or background
sections from `literature-research` and Zotero handoff artifacts.

## Inputs

Require saved evidence before writing:

- `literature-research` ranked evidence JSON/CSV, usually `ranked_all.json`.
- `literature-research` report scaffold or final `report.md`.
- Optional `literature-manager` match/sync JSON for citation keys,
  collection status, tags, and item provenance.
- Verified full text or abstracts when the claim depends on details beyond
  title/metadata.

Do not write conclusions from memory, topic familiarity, or Zotero presence
alone. Zotero is a library-management layer, not a search-completeness proof.
An `AI4S-Summary` sentence is navigation metadata derived from an abstract; it
must not replace the saved abstract/full text or independently support a claim.

## Outputs

Default outputs are Markdown sections that can later be converted to DOCX or
manuscript format:

- `review_section.md`
- `proposal_background.md`
- `introduction.md`
- `references_to_check.md`, only when unresolved reference issues exist

When the user asks for a Word-ready artifact, draft in Markdown first, then route
to a document skill for DOCX rendering and visual QA.

## Claim Traceability

Every scientific claim must trace to at least one saved evidence record:

- Use inline citation placeholders such as `[EV:12]` while drafting.
- Preserve DOI/PMID/Zotero key metadata in a reference table.
- Label abstract-only claims explicitly when full text was not checked.
- Separate established findings, mechanistic hypotheses, and speculative
  interpretation.

If a paragraph has no evidence IDs, either add evidence or remove the paragraph.

## Bilingual Style

Frank's final reports often need English/Chinese output. Keep terminology
rigorous and consistent:

- English first when drafting manuscript-facing prose unless the user asks for
  Chinese-first.
- Chinese explanation can follow as a clearly separated section or paragraph.
- Avoid loose translations of structural biology, omics, or clinical terms; use
  standard technical terminology.

## Quality Gate

Before delivery:

1. List the evidence IDs supporting each section.
2. Check that no claim rests only on Zotero metadata.
   This includes `AI4S-Summary`, Agent Tags, Priority, and journal metrics.
3. If unresolved citation gaps exist, mark them in `references_to_check.md`;
   otherwise do not create an empty file.
4. State search limits, database coverage, time range, and whether full text was
   verified.
