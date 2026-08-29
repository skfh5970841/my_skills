# Promotion policy

## Terminal and error states

Valid progress is `researching` → `hypothesis_ready` → `baseline_captured` → `candidate_ready` → `auto_evaluated` → `awaiting_human` or `ready_for_approval` → `promoted`. At any point, use `rejected`, `blocked_external`, or `invalid`.

Non-zero command exits, timeouts, or blank outputs are `blocked_external`. Missing provenance, outputs, scores, commands, or hashes; model/configuration mismatch; more than one independent candidate change; and holdout leakage are `invalid`. Hard-gate/golden failures or a human blind preference against the candidate are `rejected`.

## Required artifacts

An experiment directory contains, when its completed state requires them: `manifest.json`, `research.jsonl`, `hypothesis.md`, `baseline.jsonl`, `candidate.patch`, `candidate.jsonl`, `scores.json`, `blind_pairs.jsonl`, `human_ratings.jsonl`, and `report.md`. Missing artifacts required by an already-passed phase block `resume` and promotion.

## Approval, rollback, and scope

`ready_for_approval` is not promotion. Require explicit 사용자 승인 before modifying canonical source, adapters, packages, installations, or external copies. Before writes, preserve byte-for-byte backups and hashes for every canonical file to change. Apply only after static, hard, golden, quality, blind, and provenance gates pass; regenerate adapters and packages; then revalidate.

If a replacement or post-write hash verification fails, restore every changed file from its backups, record the rollback, and mark the experiment `invalid`. Failed candidates are retained with their reasons and never alter canonical or installed copies.
