# Visualization Intent Contract

The Agent owns conversion of user language and optional reference images into
`visualization_request.json`. The renderer never uses an LLM or network.

## Required discipline

- Record the raw user request in `request_trace.user_request`.
- Treat reference images as style cues only: composition, palette family,
  opacity, lighting, label density, and global/local framing.
- Preserve ambiguous scientific language in `warnings`; use conservative
  geometry inference instead of asserting a contact.
- Prefer ChimeraX unless the user asks for PyMOL or environment verification
  selects PyMOL.

## Phrase-to-parameter examples

| User phrase | Normalized rendering intent |
|---|---|
| “半透明气泡/玻璃包裹” | `template: pocket-glass`, local surface, 60–75% transparency, white background, soft lighting. |
| “突出袋口氢键” | `annotations.hbond_candidates: true`; label lines as candidates and report geometric limits. |
| “简洁论文图” | restrained palette, white background, sparse labels, no decorative effects. |
| “看界面热点” | `template: ppi-interface`; infer interface residues within 5 Å when possible and disclose the criterion. |

## Request-file extension

The default template may be extended with:

```json
{
  "request_trace": {
    "user_request": "渲染这个PDB复合物，半透明气泡+内部骨架，重点看口袋氢键",
    "reference_image": "optional local attachment path",
    "reference_style_observations": ["white background", "local transparent surface"],
    "interpretation_confidence": "medium"
  }
}
```

The path is local-only metadata and must not be exposed in external reports.
