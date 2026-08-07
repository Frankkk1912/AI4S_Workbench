# Template Recipes

## `method-primer`

Purpose: Explain a scientific method, analysis concept, or readout so the reader understands what it can and cannot tell them.

Slots:
- Hook claim: one sentence that reframes the method in reader language.
- What it measures: the input, transformation, and output.
- How to read it: 2-3 interpretation rules.
- Common trap: one misread that causes overclaiming.
- Caveat or next step: what evidence is still needed.

Visual grammar: Use schematic mini-plots, labeled axes, before/after transformations, and callouts. Keep all invented values qualitative unless real data is routed through an upstream skill.

Adaptation triggers: Use legacy `columns` when the concept naturally splits into three pillars. Switch to V2 modules when the method needs a story sequence, myth correction, or comparison.

Minimum module count: 4.

## `mechanism-map`

Purpose: Show a biological mechanism, pathway, causal chain, drug action, or molecular-to-phenotype explanation.

Slots:
- Core mechanism claim: what changes what.
- Trigger or input: upstream event, ligand, mutation, condition, or perturbation.
- Intermediate steps: 2-4 mechanistic nodes.
- Output phenotype: cellular, tissue, behavioral, or assay-level consequence.
- Uncertainty: where the mechanism is simplified or context-dependent.

Visual grammar: Use left-to-right or top-to-bottom flow, directional arrows, inhibition bars, pathway nodes, structure thumbnails, and pathway labels. Label schematic pathways as schematic.

Adaptation triggers: Expand a node into its own module when it carries the scientific claim. Reserve extra space for molecular structures, microscopy, pathway diagrams, or disease-context images when they are the evidence.

Minimum module count: 5.

## `myth-vs-fact`

Purpose: Correct a common scientific misunderstanding without turning the image into a scolding list.

Slots:
- Myth: the tempting but wrong reading.
- Why it feels plausible: the hidden assumption.
- Correct interpretation: the safer reading.
- Evidence check: what data or control distinguishes the two.
- Do this instead: practical interpretation rule.

Visual grammar: Use paired contrast blocks, warning labels, crossed-out bad inference arrows, corrected flow arrows, and small evidence panels. Avoid fake quantitative proof for the correction.

Adaptation triggers: Add more fact modules when the misconception has multiple independent failure modes. Use a caveat module when the myth is sometimes true under strict conditions.

Minimum module count: 5.

## `paper-digest`

Purpose: Compress one paper into its finding, design, evidence chain, limitation, and practical takeaway.

Slots:
- One-sentence finding: what the paper actually claims.
- Study design: sample, model, assay, cohort, or computational setup.
- Key evidence: 2-3 results that support the claim.
- Limitation: what the paper does not prove.
- Takeaway: how to use the result without overextending it.

Visual grammar: Use evidence ladders, study-design strips, compact result thumbnails, and citation/source notes. Data-backed plots should come from `nature-figure` or a domain skill.

Adaptation triggers: Give more space to study design when confounding is the main risk. Give more space to evidence panels when the paper has real figures or numeric outputs to inspect.

Minimum module count: 5.

## `workflow-map`

Purpose: Explain an experimental, computational, omics, AI4S, docking, MD, or analysis pipeline as a sequence of decisions and checks.

Slots:
- Workflow promise: what the pipeline turns into what.
- Inputs: data, samples, structures, or files.
- Steps: 4-6 ordered operations.
- Checkpoints: QC gates, failure points, or validation decisions.
- Output interpretation: what the final output can support.

Visual grammar: Use numbered lanes, arrows, checkpoint badges, input/output boxes, and small tool or file icons. Keep labels short enough to read on mobile.

Adaptation triggers: Split a step into a checkpoint module when failure there changes the conclusion. Route plots, trajectories, docking complexes, or omics charts through their domain skills before placement.

Minimum module count: 5.

## `comparison-matrix`

Purpose: Compare 2-4 methods, tools, choices, hypotheses, interpretations, or experimental conditions.

Slots:
- Decision question: what the reader is choosing or comparing.
- Options: 2-4 compared items.
- Criteria: what matters for this decision.
- Tradeoffs: where each option is strong or weak.
- Recommendation or boundary: when to use each option.

Visual grammar: Use compact matrices, option cards, check/caution markers, ranked criteria, and short contrast labels. Do not imply measured superiority unless the source provides comparable data.

Adaptation triggers: Use more criteria rows when the decision is practical. Use more evidence modules when the comparison is based on real benchmarks, experiments, or quantitative analyses.

Minimum module count: 4.
