# Report-Stage Priority Recommendations

Create `priority_recommendations.json` during the same reasoning pass that
finalizes `report.md`. Do not launch a separate paper-by-paper audit.

Priority is a personal reading/use priority for one project:

- `1`: background or supporting paper. This is the default for selected papers.
- `2`: important mechanism, method, evidence, review, or contrasting result.
- `3`: core/must-read paper directly supporting a core report conclusion.

Priority is not evidence quality, risk of bias, journal prestige, or a reusable
absolute ranking across research questions. `rank` and `score_reasons` may inform
the decision but must not be converted mechanically into stars.

## Compact Contract

```json
{
  "schema_version": "1.0",
  "artifact_type": "literature-priority-recommendations",
  "scope": "gpld1-cvd",
  "review_depth": "abstract",
  "default_for_selected": 1,
  "recommendations": {
    "doi:10.1000/core": {
      "priority": 3,
      "reason_codes": ["core-conclusion", "direct-question-match"]
    },
    "pmid:12345678": {
      "priority": 2,
      "reason_codes": ["important-mechanism"]
    }
  }
}
```

Use stable evidence IDs exactly as defined in ranked evidence. `scope` is the
project slug. `review_depth` is one of `metadata`, `abstract`, `mixed`, or
`full-text`. `default_for_selected` is always `1`.

Only Priority 2 and 3 overrides belong in `recommendations`; omitting Priority
1 papers keeps the artifact compact. Reason codes must be lower-kebab-case and
should normally come from this small vocabulary:

- `core-conclusion`
- `direct-question-match`
- `important-mechanism`
- `important-method`
- `important-background`
- `high-value-review`
- `contrasting-evidence`
- `landmark-or-field-defining`
- `user-selected`

Do not add natural-language mini-reviews. The report and ranked evidence already
contain the scientific context.
