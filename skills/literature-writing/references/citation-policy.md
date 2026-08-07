# Citation Policy

Use this reference when managing citations in literature-writing outputs.

## Placeholder Format

Use evidence placeholders during drafting:

- `[EV:<index>]` for records from ranked evidence JSON.
- `[ZOT:<itemKey>]` only when Zotero match metadata is available.
- `[PMID:<id>]` and `[DOI:<doi>]` when external identifiers are needed.

Do not replace placeholders with numbered references until the final reference
order is stable.

## Reference Table

Every draft should end with a compact reference audit table:

| Evidence ID | Zotero Key | PMID | DOI | Claim Role | Verification |
|---|---|---|---|---|---|

`Claim Role` examples:

- mechanism
- clinical association
- disease model
- method support
- contradiction
- limitation

`Verification` examples:

- full text checked
- abstract only
- metadata only, do not cite for scientific claim

## No Evidence, No Conclusion

When evidence is missing:

- Write a gap note instead of filling with plausible prose.
- Ask to run `literature-research` for missing evidence if the section requires a
  new claim.
- Ask to run `literature-manager` only when citation/library metadata is
  missing for evidence that already exists.

Collect these gaps in `references_to_check.md` only when at least one gap
exists. Do not create an empty placeholder file for a clean reference audit.
