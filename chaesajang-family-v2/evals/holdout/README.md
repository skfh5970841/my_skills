# Holdout evaluation split

Keep this split sealed from optimization. A case's `generator_brief` may be
used to request an output only during an authorized holdout run; its
`evaluator_reference` must never appear in a generation prompt, input, or
loaded reference/research context. Generated output is evaluation evidence,
not generator-visible input, and is therefore not scanned as prompt leakage.

Run split-isolation and holdout-leakage validation before interpreting results.
Use references only inside the anonymous AB/BA evaluator prompt.

Leakage comparison applies NFKC normalization and case folding, then removes
all whitespace and Unicode punctuation. It detects full normalized references,
near-full normalized character 8-gram Jaccard similarity of at least `0.85`,
and contiguous partial excerpts of at least `16` normalized characters. Text
without usable 8-grams uses deterministic edit similarity of at least `0.85`
for split isolation. Tiny common phrases below the 16-character partial
threshold do not trigger the partial-excerpt rule.

Only these explicitly generator-visible fields are scanned recursively:
`prompt`, `input`, `loaded_references`, `loaded_reference_paths`,
`loaded_reference_content`, `reference_material`, `reference_materials`,
`reference_text`, `references`, `research_card`, and `research_cards`.
Generated `output` and runner `stderr` are never treated as prompt leakage.
