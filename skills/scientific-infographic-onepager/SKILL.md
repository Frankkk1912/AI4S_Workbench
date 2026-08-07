---
name: scientific-infographic-onepager
description: >-
  Create Chinese science-popularization single-image infographics for social media, especially Xiaohongshu-style vertical long images. Use when Codex needs to turn a scientific method, biomedical mechanism, omics/AI4S workflow, paper summary, misconception correction, or data interpretation into one editable HTML+PNG onepager with content-routed layout recipes, schematic/data-backed provenance, visual QA, and optional domain-skill or nature-figure routing. Not for multi-page carousel production, Live Photo cards, WeChat cover pairs, or manuscript figure panels.
---

# Scientific Infographic Onepager

## Overview
Use this skill to produce vertical scientific "onepager" infographics: one standalone HTML file rendered to a high-resolution PNG. The default V1 template is a three-column method primer for topics such as PCA, omics preprocessing, MD analysis concepts, docking workflows, and biological mechanism summaries.

The workflow is schematic-first. When the user does not provide data, create clearly educational schematic visuals. When the user provides real data or asks for data-backed claims, route chart generation through `nature-figure` or an appropriate analysis skill before building the onepager.

## Dependencies
- `nature-figure`: use for real-data plots, source-data traceability, publication-grade chart logic, or journal-ready figure panels.
- `imagegen`: use only for optional raster decorative assets; never use it for final text-heavy infographic layout.
- `web-access`: use only when the user explicitly asks for live reference search or web-sourced background information.

## Quick Start
Create a sample specification:

```bash
node /path/to/scientific-infographic-onepager/scripts/render_onepager.mjs sample --output pca_onepager.json
```

Render HTML and PNG:

```bash
node /path/to/scientific-infographic-onepager/scripts/render_onepager.mjs render --spec pca_onepager.json --output-dir out --width 1080 --height 1620
```

Check an existing HTML:

```bash
node /path/to/scientific-infographic-onepager/scripts/render_onepager.mjs check --html out/onepager.html
```

## Required References
- `references/platform-specs.md`: single-image Xiaohongshu dimensions, safe areas, export naming, and preview rules.
- `references/content-planning.md`: route the source into a science communication type before choosing a layout.
- `references/template-recipes.md`: recipe selection, slot contracts, and when to adapt or create a task-specific variant.
- `references/science-copywriting-zh.md`: Chinese hook, title, module-copy, caveat, and anti-hype rules.
- `references/visual-grammar.md`: schematic vs data-backed visual conventions and scientific image placement rules.
- `references/onepager-spec.md`: JSON spec contract for legacy `columns` and V2 `template/modules`.
- `references/qa-checklist.md`: final QA before delivery.

## Utility Scripts

### `render_onepager.mjs sample`
Writes a PCA-style sample JSON spec. Use it as the starting point for a new topic.

Required arguments:
- `--output <path>`: JSON file to create.

### `render_onepager.mjs render`
Reads a JSON spec and writes `onepager.html`, `onepager.png` when Playwright is available, and `render-report.json`.

Required arguments:
- `--spec <path>`: structured onepager spec.
- `--output-dir <path>`: destination directory.
- `--width <px>`: output canvas width.
- `--height <px>`: output canvas height.

Optional arguments:
- `--no-png`: write HTML and report only.

### `render_onepager.mjs check`
Runs QA on a rendered HTML file. With Playwright installed, it checks dimensions, overflow, blank rendering, and clipping. Without Playwright, it performs static checks and exits with a clear setup warning.

Required arguments:
- `--html <path>`: rendered HTML file.


## Design Defaults
- For Chinese onepagers, prefer a sans-serif CJK stack: Source Han Sans SC / Noto Sans SC / Noto Sans CJK SC / Microsoft YaHei. Use `theme.fontBody` and `theme.fontSans` when the user specifies a local installed font.
- Footer icons should be semantic inline SVG icons, not placeholder text such as `BT`, `in`, or `#`. Defaults are account/person, learning-plan/book, and schematic-data icons.
- Dense social-media onepagers may use `1080 x 1440` when content is compact; use `1080 x 1620` when more vertical breathing room is needed.
- For schematic mini-plots, avoid square plot boxes unless the scientific geometry requires it. Horizontal 4:3 or 5:3 boxes usually scan better in three-column layouts and avoid empty side gutters.
- Loading plots should be frameless or ellipse-bounded, with visibly varied arrow lengths. Do not make every vector appear equal; arrow length communicates contribution strength.
- Keep labels short and inside safe visual bounds. Use A-E short labels when metabolite/gene names would collide, then explain the abbreviation in the visual caption.

## Workflow
1. Define the communication contract: target platform, audience, language, core claim, output size, and whether visuals are schematic or data-backed.
2. Read `references/content-planning.md` and classify the source as `method-primer`, `mechanism-map`, `myth-vs-fact`, `paper-digest`, `workflow-map`, or `comparison-matrix`.
3. Read `references/template-recipes.md` and choose the closest recipe. Do not ask the user to pick a template unless style or scientific emphasis changes the result.
4. Adapt the recipe when the content shape demands it: prioritize real evidence, structure images, pathway diagrams, readable Chinese copy, and one main claim.
5. Build a JSON spec. Use legacy `columns` only for `method-primer`; use `template` plus `modules` for V2 recipes.
6. Route real-data charts through `nature-figure` or the relevant domain skill before placing them in the onepager. Schematic visuals must be labeled as schematic.
7. Render with `render_onepager.mjs render`.
8. Run `render_onepager.mjs check`. If Playwright is unavailable, use another browser screenshot path before claiming visual QA passed.
9. Deliver the PNG plus editable HTML and JSON spec when useful.

## Rate Limiting
This skill does not call external APIs. If live literature, web, or image-source retrieval is needed, use `web-access` and follow that skill's rate and browser-access rules.

## Common Mistakes
- Do not use image generation for the final text-heavy layout; generated text is unreliable.
- Do not present schematic mini-plots as real analysis output.
- Do not use `nature-figure` for the entire long-form layout; use it only for real-data figure panels that need publication-level rigor.
- Do not overload sections with paragraph text. Split dense material into more sections or reduce body copy.
- Do not use square mini-plot boxes by default in three-column social layouts; they often create side gutters and cramped labels.
- Do not use footer placeholder letters when semantic icons would communicate the footer role more clearly.
