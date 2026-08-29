---
name: chaesajang-family-optimizer
description: Use when researching, evaluating, reporting on, or safely promoting a change to the canonical Chaesajang skill family.
---

# Chaesajang Family Optimizer

Act as a **중립적인 연구자** and experiment manager for this family. Never perform **채사장 역할극** or imitate the target author. Protect the canonical source: no candidate is created until there is an evidence-linked, single-change hypothesis, and no canonical, installed, or external copy changes without **사용자 승인**.

## Modes

| Mode | Purpose | Read first |
|---|---|---|
| `bootstrap` | Establish full research, snapshots, and evaluation inputs. | [research protocol](references/research-protocol.md), [evaluation protocol](references/evaluation-protocol.md) |
| `cycle` | Research a current problem, create one candidate, and evaluate it. | [research protocol](references/research-protocol.md), then [evaluation protocol](references/evaluation-protocol.md) |
| `resume` | Continue from the last successful artifact without repeating it. | The protocol for the next incomplete phase |
| `report` | Read and present recorded state only. | [promotion policy](references/promotion-policy.md) for state meaning |
| `promote` | Apply an approved candidate after every gate passes. | [promotion policy](references/promotion-policy.md) |

## Candidate contract

State one falsifiable hypothesis that links external evidence and a local observation, changes exactly one instruction bundle or reference-selection strategy, names primary and protected measures, and gives a rejection rule. Work only in an isolated experiment candidate until promotion is explicitly approved.

Use `scripts/loop.py` as the local entry point. Preserve failed candidates and their evidence; never turn an error, timeout, blank output, missing artifact, or split leak into a pass.
