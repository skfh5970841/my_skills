# Golden evaluation split

Use this curated split for stable regression comparisons. Do not copy cases,
source groups, normalized prompt content, or evaluator references between this
directory and either the development or holdout split.

Judge results are supporting evidence only. They do not constitute human
approval and must not be converted into a release gate or overall score.

Aggregation requires one source-stable `baseline` and `candidate`
`row_type: deterministic` row for every case/repeat, with identical parity
signatures. Axis counts stay separate by condition. Candidate failures on
`request_fulfillment` or `meaning_and_facts` are listed in
`hard_gate_failures`; failed candidate axes in this split are also listed in
`golden_failures`, with separate boolean summaries.

Optional `row_type: judge` rows must contain exactly one anonymous AB and one
BA result per stable `pair_id`. Their model/runtime/command provenance and
prompt hash are retained under the nested `judge` aggregate, whose role is
always `supporting_only`. Evaluator references remain evaluator-only in both
typed row flows.
