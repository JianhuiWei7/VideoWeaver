---
name: trim-audio
description: "【音频剪辑工具】支持指定开始时间和结束时间对音频文件进行精确裁剪。当用户需要截取音频片段、去除音频首尾或保留特定时间段时，必须立即调用此技能。"
---

## 前置依赖
1. 本地环境必须已配置好 `ffmpeg`。

## 支持模式
指定开始时间和结束时间，截取音频的特定片段。输出文件将自动保存在基于 session 生成的特定输出目录下，并在文件名后加上 `_trimmed` 后缀。

## 典型使用案例

### 基础音频剪辑
剪辑指定时间段的音频，并自动生成输出文件。
```bash
python trim-audio/scripts/trim_audio.py \
  --input_path "/path/to/audio.mp3" \
  --start_time 10 \
  --end_time 60 \
  --session-key "agent:{agent_id}:{session_id}"
```

## 运行模式与日志监控
**默认行为**：
该脚本为前台同步执行（Blocking），在执行过程中会在终端直接输出处理日志。

**任务监控流程**：
1. **提交任务**：通过命令行执行脚本。
2. **监控进度**：剪辑过程通常较快，但对于大文件可能需要几秒到几分钟。
3. **完成状态**：
   - **成功**：日志末尾会输出 `✅ Audio trimmed successfully: [输出路径]`，并返回状态码 0。
   - **失败**：日志末尾会输出 `❌ An error occurred during audio trimming: [错误信息]`。

## 参数说明
| 参数名 | 说明 |
|--------|------|
| `--input_path` | （**必填**）需要剪辑的音频文件路径。 |
| `--start_time` | （**必填**）剪辑起始时间（秒），例如 10.5。 |
| `--end_time` | （**必填**）剪辑结束时间（秒），例如 60.0。 |
| `--session-key` | **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |

## 执行规范
- **执行前检查**：在执行剪辑前，确保传入的 `--input_path` 对应的文件在本地确实存在。
- **时间检查**：`start_time` 必须小于 `end_time`，且 `start_time` 必须大于等于 0。
- **结果反馈**：命令执行结束后，你需要检查输出日志。
  - 若成功，向用户汇报："✅ 音频剪辑成功！已保存至：[输出路径]"。
  - 若失败，向用户汇报失败原因（如路径无效、时间参数错误等），并提供可能的修复建议。
