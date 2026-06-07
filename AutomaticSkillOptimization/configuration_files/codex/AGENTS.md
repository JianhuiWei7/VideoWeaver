# Agent Reading Instructions

When working in this repository, agents should not read or inspect files under the following paths unless the user explicitly asks for one of them:

- `<repo_root>/cc_deepseek/`
- `<repo_root>/cc_opus4.7/`
- `<repo_root>/cc_seed_result/`
- `<repo_root>/codex_gpt55/`
- `<repo_root>/output_eval/`
- `<repo_root>/VideoSkill/`
- `./<EXP_ID>/`                  (previous experiment archives)
- `./codex/`                      (this runner's runtime output dir)
- `./videos_failed/`
- `./videos_half_stopped/`

Treat these paths as out of scope for routine context gathering, searching, and documentation review.

## Output dir convention (codex)

- 所有产物必须落到 `get-output-dir` 返回的目录下：`./codex/output/{thread_name}_{thread_id}/[<subdir>]`
- 与 Claude Code 的差异：codex 使用 `CODEX_THREAD_NAME` / `CODEX_THREAD_ID` env，而不是 `CLAUDE_CODE_SESSION_NAME` / `CLAUDE_CODE_SESSION_ID`
- 详细见 `.agents/skills/get-output-dir/SKILL.md`
