---
name: pair-wise-skill-merge
description: Progressively merge one incoming version of the same skill or skill creator into an accumulator skill directory in place. Use when given an accumulator skill directory plus the next incoming skill directory in a gradual merge sequence, consolidating optimized copies by repeated pair-wise absorption across calls, preserving useful differences, deduplicating similar rules, resolving conflicts, and producing a dense non-redundant accumulator. Never modify the incoming skill directory.
---

# Pair-wise Skill Merge

## Goal

Merge one incoming skill directory into one accumulator skill directory. Treat the merge as knowledge distillation: preserve genuinely useful differences, combine overlapping guidance into stronger unified rules, and remove redundancy.

This skill is meant to be called repeatedly with progressively revealed incoming skills. Each call receives the current accumulator and only the next incoming skill, not the full set of future incoming skills. Compare this pair, then rewrite only the accumulator to absorb useful material from the incoming skill.

## Required Inputs

Collect these before editing:

1. Accumulator skill directory. This is the only directory that may be modified.
2. Incoming skill directory. This is a read-only source for the current merge step.

Do not create a new output directory unless the user explicitly asks for one. Do not edit, delete, rename, reformat, or normalize the incoming skill directory.

## Workflow

1. Read the accumulator and incoming skill contents thoroughly.
   - Read both `SKILL.md` files in full.
   - Read as many relevant files as possible under `references/` and other text/config/source files in the skill directories.
   - Inspect custom folders when they may affect behavior. Summarize binary assets instead of loading raw binary content.

2. Decide what to absorb.
   - Merge similar rules into one stronger rule.
   - Keep genuinely new, useful, or more precise guidance from the incoming skill.
   - Drop repeated, vague, stale, or lower-signal wording.
   - If two rules conflict, rewrite the accumulator with the clearer conditional rule or the safer general rule.

3. Rewrite the accumulator only.
   - Preserve valid YAML frontmatter with `name` and `description`.
   - Edit `SKILL.md`, `references/`, scripts, assets, or custom folders only inside the accumulator.
   - Organize content by topic, not by source variant.
   - Keep the final wording dense and non-redundant.

4. Validate the accumulator.
   - Check that the merged skill has no TODO placeholders, repeated sections, or contradictory instructions.
   - Run the skill validator when available.
   - Summarize what was absorbed, merged, dropped, and still uncertain.

## Pair-wise Merge Principle

Keep the main `SKILL.md` concise, mobile, non-redundant, and information-rich. Merge overlapping ideas into compact stronger rules, and move detailed examples, long checklists, domain notes, or bulky supporting material into appropriate accumulator subfolders such as `references/` instead of bloating the main skill body.

## Output Expectations

The final response after a merge should include:

1. Accumulator skill directory that was updated.
2. Files changed.
3. High-value additions absorbed from the incoming skill.
4. Duplicate or lower-signal material removed.
5. Validation performed and any remaining risks.
