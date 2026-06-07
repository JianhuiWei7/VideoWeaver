---
name: get-output-dir
description: "获取当前任务的标准化输出目录路径。支持 OpenClaw、Codex、Claude Code 三种运行环境；保存任何输出产物前必须调用此技能。"
---

# 统一输出目录获取技能 (get-output-dir)

## 用途

返回当前 agent/session/thread 的标准化输出目录。所有任务产物，包括文本、日志、图片、音频、视频、任务状态等，都必须保存到该目录下，方便按 session 管理、回溯和评估。

脚本会自动创建目录，并且 stdout 只输出最终路径。

## 目录规则

### OpenClaw

```text
${OUTPUT_DIR}/<session_key>_<session_id>[/<subdir>]
```

- 先运行 `session_status` 工具判断当前会话信息。
- OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`；脚本会查询对应 `session_id` 后拼出目录。

### Codex

```text
${OUTPUT_DIR}/<CODEX_THREAD_NAME>_<CODEX_THREAD_ID>[/<subdir>]
```
- `CODEX_THREAD_ID`：Codex 自动注入的真实 thread id。
- `CODEX_THREAD_NAME`：父进程注入的业务 thread 名。
- 如果缺失，会分别 fallback 为 `unknown_thread` 和 `unknown_thread_id`。

### Claude Code

```text
${OUTPUT_DIR}/<session_name>_<session_id>[/<subdir>]
```
- `session_id` 来自 `CLAUDE_CODE_SESSION_ID`，缺失时，会 fallback 为 `unknown_session_id`。
- `session_name` 来自 `CLAUDE_CODE_SESSION_NAME_USER`，缺失时 fallback 为 `unknown_session`。

## 使用方法

### 自动识别环境

自动识别规则：

1. 传入 `--session-key` 时使用 OpenClaw。
2. 存在 `CODEX_THREAD_ID` 时使用 CodeX；CodeX/Claude Code 环境会自动识别，不需要传入内容。
3. 存在 `CLAUDE_CODE_SESSION_ID` 时使用 Claude Code；CodeX/Claude Code 环境会自动识别，不需要传入内容。
4. 以上都不满足时按 OpenClaw 处理；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`，否则报错。

### OpenClaw

```bash
python scripts/get_output_dir.py --session-key "agent:{agent_id}:{session_id}"
python scripts/get_output_dir.py --session-key "agent:{agent_id}:{session_id}" --subdir images
```

### Codex

```bash
python scripts/get_output_dir.py --subdir videos
python scripts/get_output_dir.py --subdir images
```

### Claude Code

```bash
python scripts/get_output_dir.py --subdir videos
python scripts/get_output_dir.py --subdir images
```

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `--session-key` | 可选的 OpenClaw session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |
| `--subdir` | 可选子目录，例如 `images`、`videos`、`logs`。 |

## 返回值

- 成功：stdout 打印一个完整目录路径，并自动创建目录。
- 失败：stderr 输出错误信息，进程以非零状态码退出。
