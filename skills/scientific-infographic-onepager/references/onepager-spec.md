# Onepager Specification

## Input Contract
The renderer accepts one JSON object:

```json
{
  "title": "Mastering PCA in Metabolomics",
  "subtitle": "A chemometrics guide to biological insights",
  "brand": {
    "name": "Behind the Feature Table",
    "mark": "omics-grid"
  },
  "footer": {
    "left": "Behind the Feature Table",
    "center": "Follow and connect",
    "right": "Read more"
  },
  "theme": {
    "accent": "#d93612",
    "accent2": "#f06a00",
    "ink": "#14120f",
    "paper": "#fffaf2",
    "line": "#efc9a7",
    "fontBody": "\"Source Han Sans SC\", \"Noto Sans SC\", \"Microsoft YaHei\", sans-serif",
    "fontSans": "\"Source Han Sans SC\", \"Noto Sans SC\", \"Microsoft YaHei\", Arial, sans-serif"
  },
  "columns": [
    {
      "number": "1",
      "title": "The Core Functions",
      "sections": [
        {
          "number": "1.1",
          "heading": "Dimensionality Reduction",
          "body": "Condense high-dimensional omics data into a few orthogonal components.",
          "note": "Schematic",
          "visual": { "type": "simple-diagram" }
        }
      ]
    }
  ]
}
```

## Legacy Columns Required Fields
- `title`: main headline.
- `columns`: array of one to four columns. V1 is optimized for three columns.
- each column requires `title` and `sections`.
- each section requires `heading` and `body`.

## Optional Fields
- `subtitle`, `brand`, `footer`, `theme`.
- `theme.fontBody` and `theme.fontSans` can override the default CJK font stacks when the user wants a specific installed font.
- `footer.leftIcon`, `footer.centerIcon`, and `footer.rightIcon` can choose semantic footer icons: `account`, `plan`, or `schematic`.
- column `number`.
- section `number`, `note`, `visual`.

## V2 Recipe Spec

The renderer accepts either the legacy `columns` format or the V2 recipe format.

```json
{
  "template": "mechanism-map",
  "language": "zh-CN",
  "audience": "public-science",
  "claimType": "schematic-only",
  "title": "PCA 图到底在看什么？",
  "subtitle": "先看距离，再看变量贡献",
  "modules": [
    {
      "role": "claim",
      "heading": "一张图不是结论",
      "body": "PCA 先展示样本之间的主要差异方向，再帮助你决定下一步该查什么。"
    }
  ],
  "visuals": []
}
```

Supported `template` values:

- `method-primer`
- `mechanism-map`
- `myth-vs-fact`
- `paper-digest`
- `workflow-map`
- `comparison-matrix`

If `template` is omitted and `columns` is present, the renderer uses `method-primer`.

### V2 Required Fields
- `template`: one of the supported recipe names listed above.
- `title`: main headline.
- `modules`: non-empty array of recipe modules.
- each module requires `heading` and `body`.

## Visual Types
- `scatter`: schematic score-plot style points with groups.
- `loading-plot`: loading-vector biplot style diagram.
- `bars-before-after`: paired bar charts for preprocessing comparisons.
- `distribution-before-after`: skewed-to-normal or unequal-to-equal schematic curves.
- `ellipse-outlier`: Hotelling-style ellipse with potential outliers.
- `simple-diagram`: generic before-to-after conceptual diagram.
- `custom-svg`: raw SVG fragment supplied by the agent or user.

Each visual is schematic unless `visual.dataBacked` is `true`. If `dataBacked` is true, record the source data or upstream script in the working notes and prefer using `nature-figure` to create the panel.

## Template Rules
- Use the `three-column-method-primer` template for V1.
- Keep body paragraphs short: usually 16 to 45 words per section.
- Use direct labels inside visuals when possible.
- Use the accent color for numbering and one signal element only.
- Keep the background light and text dark for scientific readability.
- Prefer horizontal 4:3 or 5:3 mini-plot boxes in three-column social layouts. Use square plot boxes only when the scientific geometry needs a square coordinate system.
- Loading plots should avoid unnecessary rectangular frames, use an ellipse or axes as the visual boundary, and show clearly varied arrow lengths.
- Use short labels inside dense mini-plots; move explanations into the caption when full labels would overlap.

## QA Checklist
- The rendered PNG is nonblank.
- Output dimensions match the requested width and height.
- No horizontal overflow.
- Section headings and footer are visible.
- Labels remain readable at mobile/social viewing size.
- Mini-plot labels do not touch plot borders or overlap arrows/points.
- Footer icons are semantic SVGs rather than placeholder letters.
- Schematic visuals are not described as measured data.
