# Development evaluation split

Use this split for iterative prompt and implementation work. `case_id` and
exact normalized generator/evaluator content must be unique across the complete
dataset. Near-duplicate and short-text similarity checks apply between splits,
so intentional variants may share one split and source group. A `source_group`
may repeat inside this split, but it must not occur in the golden or holdout
split.

Only `generator_brief` may enter generation prompts. Any
`evaluator_reference` is evaluator-only material and must remain outside model
generation rows.

`deterministic_checks` accepts exactly these keys:

- `output_present` (when present, it must be `true`), `required_terms`,
  `forbidden_terms`, and `checklist_items` map to `request_fulfillment`.
- `exact_facts` maps to `meaning_and_facts`.
- `min_characters` and `max_characters` map to
  `structure_and_information`.
- `max_source_overlap_characters` maps to `over_imitation` and requires an
  evaluator-only reference longer than the threshold.

Sequence checks must be non-empty. Required and forbidden normalized literals
must not contain one another. A `max_characters` limit must accommodate the
exact shortest common superstring of all required literals, including overlap.
Thresholds must be positive and possible, and every configured check requires
its mapped axis. Deterministic rows use
`row_type: deterministic` and carry case, split, condition, repeat, `pair_id`,
`parity_signature`, and six separate axis results; unmeasured axes remain
`passed: null` with `status: not_scored`.
