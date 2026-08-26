# [SOURCE] Agent Skills — Optimizing skill descriptions
# URL: https://agentskills.io/skill-creation/optimizing-descriptions
# Retrieved: 2026-08-26 via webfetch (markdown)
# Purpose: chaesajang-style 스킬 개선 근거 자료

# Optimizing skill descriptions

> How to improve your skill's description so it triggers reliably on relevant prompts.

A skill only helps if it gets activated. The `description` field in your `SKILL.md` frontmatter is the primary mechanism agents use to decide whether to load a skill for a given task. An under-specified description means the skill won't trigger when it should; an over-broad description means it triggers when it shouldn't.

## How skill triggering works

Agents use progressive disclosure to manage context. At startup, they load only the `name` and `description` of each available skill — just enough to decide when a skill might be relevant. When a user's task matches a description, the agent reads the full `SKILL.md` into context and follows its instructions.

This means the description carries the entire burden of triggering. If the description doesn't convey when the skill is useful, the agent won't know to reach for it.

One important nuance: agents typically only consult skills for tasks that require knowledge or capabilities beyond what they can handle alone. A simple, one-step request like "read this PDF" may not trigger a PDF skill even if the description matches perfectly, because the agent can handle it with basic tools. Tasks that involve specialized knowledge — an unfamiliar API, a domain-specific workflow, or an uncommon format — are where a well-written description can make the difference.

## Writing effective descriptions

* **Use imperative phrasing.** Frame the description as an instruction to the agent: "Use this skill when..." rather than "This skill does..." The agent is deciding whether to act, so tell it when to act.
* **Focus on user intent, not implementation.** Describe what the user is trying to achieve, not the skill's internal mechanics. The agent matches against what the user asked for.
* **Err on the side of being pushy.** Explicitly list contexts where the skill applies, including cases where the user doesn't name the domain directly: "even if they don't explicitly mention 'CSV' or 'analysis.'"
* **Keep it concise.** A few sentences to a short paragraph is usually right — long enough to cover the skill's scope, short enough that it doesn't bloat the agent's context across many skills. The specification enforces a hard limit of 1024 characters.

## Designing trigger eval queries

To test triggering, you need a set of eval queries — realistic user prompts labeled with whether they should or shouldn't trigger your skill.

```json eval_queries.json
[
  { "query": "...", "should_trigger": true },
  { "query": "...", "should_trigger": false }
]
```

Aim for about 20 queries: 8-10 that should trigger and 8-10 that shouldn't.

### Should-trigger queries

Vary them along several axes:

* **Phrasing**: some formal, some casual, some with typos or abbreviations.
* **Explicitness**: some name the skill's domain directly ("analyze this CSV"), others describe the need without naming it ("my boss wants a chart from this data file").
* **Detail**: mix terse prompts with context-heavy ones.
* **Complexity**: vary the number of steps and decision points. Include single-step tasks alongside multi-step workflows.

The most useful should-trigger queries are ones where the skill would help but the connection isn't obvious from the query alone.

### Should-not-trigger queries

The most valuable negative test cases are **near-misses** — queries that share keywords or concepts with your skill but actually need something different. These test whether the description is precise, not just broad.

Weak negative examples: obviously irrelevant queries ("What's the weather today?").

Strong negative examples: share surface keywords but need different capabilities ("can you write a python script that reads a csv and uploads each row to our postgres database" — involves CSV, but the task is database ETL, not analysis).

### Tips for realism

Real user prompts contain context that generic test queries lack. Include:

* File paths
* Personal context ("my manager asked me to...")
* Specific details
* Casual language, abbreviations, and occasional typos

## Testing whether a description triggers

Run each query through your agent with the skill installed and observe whether the agent invokes it. Check observability (execution logs, tool call histories) to see which skills were consulted.

Model behavior is nondeterministic — run each query multiple times (3 is a reasonable starting point) and compute a **trigger rate**: the fraction of runs where the skill was invoked.

A should-trigger query passes if its trigger rate is above a threshold (0.5 is reasonable). A should-not-trigger query passes if its trigger rate is below that threshold.

## Avoiding overfitting with train/validation splits

Split your query set:

* **Train set (~60%)**: the queries you use to identify failures and guide improvements.
* **Validation set (~40%)**: queries you set aside and only use to check whether improvements generalize.

Shuffle randomly and keep the split fixed across iterations.

## The optimization loop

1. **Evaluate** the current description on both train and validation sets.
2. **Identify failures** in the train set only.
   * Only use train set failures to guide your changes — keep validation set results out of the process.
3. **Revise the description.** Focus on generalizing:
   * If should-trigger queries are failing, broaden scope or add context about when the skill is useful.
   * If should-not-trigger queries are false-triggering, add specificity about what the skill does *not* do, or clarify the boundary between this skill and adjacent capabilities.
   * Avoid adding specific keywords from failed queries — that's overfitting. Find the general category or concept and address that.
   * If stuck after several iterations, try a structurally different approach rather than incremental tweaks.
   * Keep under the 1024-character limit.
4. **Repeat** until all train set queries pass or improvement stalls.
5. **Select the best iteration by validation pass rate.**

Five iterations is usually enough.

## Applying the result

1. Update the `description` field.
2. Verify under 1024 characters.
3. Verify triggers with fresh queries never used in optimization — honest check on generalization.

Before:

```yaml
description: Process CSV files.
```

After:

```yaml
description: >
  Analyze CSV and tabular data files — compute summary statistics,
  add derived columns, generate charts, and clean messy data. Use this
  skill when the user has a CSV, TSV, or Excel file and wants to
  explore, transform, or visualize the data, even if they don't
  explicitly mention "CSV" or "analysis."
```
