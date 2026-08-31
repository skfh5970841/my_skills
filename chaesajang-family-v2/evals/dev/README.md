# Development evaluation split

Use this split for iterative prompt and implementation work. Cases in this
directory must have unique `case_id`, `source_group`, and normalized
`generator_brief` content relative to the golden and holdout splits.

Only `generator_brief` may enter generation prompts. Any
`evaluator_reference` is evaluator-only material and must remain outside model
generation rows.
