# [SOURCE] Agent Skills — Specification
# URL: https://agentskills.io/specification
# Retrieved: 2026-08-26 via webfetch (markdown)
# Purpose: chaesajang-style 스킬 개선 근거 자료

# Specification

> The complete format specification for Agent Skills.

## Directory structure

A skill is a directory containing, at minimum, a `SKILL.md` file:

```
skill-name/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation
├── assets/           # Optional: templates, resources
└── ...               # Any additional files or directories
```

## `SKILL.md` format

The `SKILL.md` file must contain YAML frontmatter followed by Markdown content.

### Frontmatter

| Field           | Required | Constraints |
| --------------- | -------- | ----------- |
| `name`          | Yes      | Max 64 characters. Lowercase letters, numbers, and hyphens only. Must not start or end with a hyphen. |
| `description`   | Yes      | Max 1024 characters. Non-empty. Describes what the skill does and when to use it. |
| `license`       | No       | License name or reference to a bundled license file. |
| `compatibility` | No       | Max 500 characters. Indicates environment requirements. |
| `metadata`      | No       | Arbitrary key-value mapping for additional metadata. |
| `allowed-tools` | No       | Space-separated string of pre-approved tools the skill may use. (Experimental) |

#### `name` field

* Must be 1-64 characters
* May only contain unicode lowercase alphanumeric characters (`a-z`, `0-9`) and hyphens (`-`)
* Must not start or end with a hyphen (`-`)
* Must not contain consecutive hyphens (`--`)
* Must match the parent directory name

#### `description` field

* Must be 1-1024 characters
* Should describe both what the skill does and when to use it
* Should include specific keywords that help agents identify relevant tasks

Good example:

```yaml
description: Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.
```

Poor example:

```yaml
description: Helps with PDFs.
```

### Body content

The Markdown body after the frontmatter contains the skill instructions. There are no format restrictions. Write whatever helps agents perform the task effectively.

Recommended sections:

* Step-by-step instructions
* Examples of inputs and outputs
* Common edge cases

Note that the agent will load this entire file once it's decided to activate a skill. Consider splitting longer `SKILL.md` content into referenced files.

## Optional directories

### `scripts/`

Contains executable code that agents can run. Scripts should:

* Be self-contained or clearly document dependencies
* Include helpful error messages
* Handle edge cases gracefully

### `references/`

Contains additional documentation that agents can read when needed. Keep individual reference files focused. Agents load these on demand, so smaller files mean less use of context.

### `assets/`

Contains static resources: Templates, Images, Data files.

## Progressive disclosure

Agents load skills *progressively*, pulling in more detail only as a task calls for it. Skills should be structured to take advantage of this:

1. **Metadata** (~100 tokens): The `name` and `description` fields are loaded at startup for all skills
2. **Instructions** (< 5000 tokens recommended): The full `SKILL.md` body is loaded when the skill is activated
3. **Resources** (as needed): Files (e.g. those in `scripts/`, `references/`, or `assets/`) are loaded only when required

Keep your main `SKILL.md` under 500 lines. Move detailed reference material to separate files.

## File references

When referencing other files in your skill, use relative paths from the skill root:

```markdown
See [the reference guide](references/REFERENCE.md) for details.

Run the extraction script:
scripts/extract.py
```

Keep file references one level deep from `SKILL.md`. Avoid deeply nested reference chains.

## Validation

Use the `skills-ref` reference library (github.com/agentskills/agentskills/tree/main/skills-ref) to validate your skills:

```bash
skills-ref validate ./my-skill
```
