# Evaluation protocol

## Split isolation

Use `evals/dev` to form and tune hypotheses, `evals/golden` to protect known failures and behavior, and `evals/holdout` only for final candidate judgment. Keep a book, chapter, serial, or revision family in one split. Run exact-hash and near-duplicate checks before splitting. Give the generator only a neutral `generator_brief`; actual source text and evaluator-only checklists stay with evaluation. Holdout leakage into a prompt, reference, or research card makes the experiment `invalid`.

## Six axes

| Axis | Role |
|---|---|
| `request_fulfillment` | hard gate |
| `meaning_and_facts` | hard gate |
| `structure_and_information` | comparison |
| `style_behavior` | comparison |
| `over_imitation` | comparison |
| `resource_use` | supporting signal |

Baseline and candidate use the same Codex model, reasoning configuration, input, and allowed references. Any mismatch is `invalid`.

## Generation ladder and human blind

Run deterministic static checks and smoke checks first. Then generate each affected and protected case once. Only a candidate that can pass is expanded adaptively to three total fresh generations per case. Hard-gate and golden failures reject it.

For risky changes, prepare one-person blind material: hide baseline/candidate identity, balance A/B and B/A order, ask the user about usefulness/completeness, thought/style fidelity, over-imitation, meaning distortion, and supporting passages. A single user's preference is a decision input, never statistical superiority.

## Persona layering

- `chaesajang-advisor` and `chaesajang-dialogue`: perspective and thinking persona.
- `chaesajang-style` and `chaesajang-style-youtube-scripter`: thinking, structure, and style techniques without biographical role-play.
- `chaesajang-write-teacher`: teaches principles without role-play.
- `chaesajang-family-optimizer`: neutral researcher and evaluator.
