# Report-Stage Semantic Tag Candidates

When Agent Tags are enabled for a retrieved batch, create
`semantic_tag_candidates.json` during the same evidence-synthesis pass that
finalizes `report.md` and Priority recommendations. Do not launch a second
paper-by-paper model pass merely for tagging.

These are English semantic candidates, not final Zotero tags. The
`literature-manager` workflow must compare them with the current library
vocabulary after import and decide `reuse` versus `new` before applying them.

## Selection rules

- Use zero to four tags per paper; never fill a dimension merely to reach four.
- Dimensions are `topic`, `entity`, `method`, and `mechanism`.
- A narrow gene, protein, compound, cell type, organism, or assay is eligible
  only when it is a principal study subject.
- Prefer reusable concepts over title fragments, outcomes, directions of
  change, or one-off phrases.
- With a usable title and abstract, set `evidence_depth` to `title-abstract`.
- Without an abstract, set `evidence_depth` to `metadata-only`, use no more
  than two conservative tags, and never propose a `mechanism` tag.
- Zero candidates with reason code `no-confident-tag` is valid.
- Tags are navigation metadata, not evidence for a scientific conclusion.

## Compact contract

```json
{
  "schema_version": "1.0",
  "artifact_type": "literature-semantic-tag-candidates",
  "language": "en",
  "scope": "gpld1-cvd",
  "items": {
    "doi:10.1000/example": {
      "evidence_depth": "title-abstract",
      "tags": [
        {
          "canonical": "Macrophage",
          "dimension": "entity",
          "aliases": ["Macrophages"],
          "description": "Macrophages as a principal biological study subject"
        },
        {
          "canonical": "Single-cell transcriptomics",
          "dimension": "method",
          "aliases": ["scRNA-seq", "Single-cell RNA sequencing"],
          "description": "Transcriptome profiling at single-cell resolution"
        }
      ]
    }
  }
}
```

Use stable evidence IDs exactly as defined in `ranked_all.json`. Keep aliases
short and scientifically equivalent; do not invent an alias merely to make the
array non-empty. Descriptions define vocabulary meaning and must not summarize
paper results.
