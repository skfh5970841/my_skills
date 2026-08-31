# Holdout evaluation split

Keep this split sealed from optimization. A case's `generator_brief` may be
used to request an output only during an authorized holdout run; its
`evaluator_reference` must never appear in a generation prompt, input row, or
candidate output context.

Run split-isolation and holdout-leakage validation before interpreting results.
Use references only inside the anonymous AB/BA evaluator prompt.
