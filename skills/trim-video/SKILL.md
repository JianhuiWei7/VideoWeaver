---
name: trim-video
description: "【视频剪辑工具】支持指定开始时间和结束时间对视频进行精确裁剪。当用户需要截取视频片段、去除视频首尾或保留特定时间段时，必须立即调用此技能。"
---

## 前置依赖
1. 安装依赖包：`pip install moviepy`
2. 本地环境建议已配置好 `ffmpeg`（虽然 moviepy 会尝试自动处理，但系统级 ffmpeg 会提升稳定性）。


## 典型使用案例

### 基础视频剪辑
剪辑指定时间段的视频，并自动在基于 session 生成的特定输出目录下生成带有 `_trimmed_{start_time}_{end_time}` 后缀的输出文件。
```bash
python trim-video/scripts/trim_video.py \
  --input_path "/path/to/video.mp4" \
  --start_time 10 \
  --end_time 60 \
  --session-key "agent:{agent_id}:{session_id}"
``````

## 运行模式与日志监控
**默认行为**：
该脚本为前台同步执行（Blocking），在执行过程中会在终端直接输出处理日志。

**任务监控流程**：
1. **提交任务**：通过命令行执行脚本。
2. **监控进度**：剪辑过程通常较快，但对于大文件可能需要几秒到几分钟。
3. **完成状态**：
   - **成功**：日志末尾会输出 `✅ Video trimmed successfully: [输出路径]`，并返回状态码 0。
   - **失败**：日志末尾会输出 `❌ An error occurred during video trimming: [错误信息]`。

## 参数说明
| 参数名 | 说明 |
|--------|------|
| `--input_path` | （**必填**）需要剪辑的视频文件路径。 |
| `--start_time` | （**必填**）剪辑起始时间（秒），例如 10.5。 |
| `--end_time` | （**必填**）剪辑结束时间（秒），例如 60.0。 |
| `--session-key` | **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |

## 执行规范
- **执行前检查**：在执行剪辑前，确保传入的 `--input_path` 对应的文件在本地确实存在。
- **时间检查**：`start_time` 必须小于 `end_time`，且 `start_time` 必须大于等于 0。
- **结果反馈**：命令执行结束后，你需要检查输出日志。
  - 若成功，向用户汇报："✅ 视频剪辑成功！已保存至：[输出路径]"。
  - 若失败，向用户汇报失败原因（如路径无效、时间参数错误等），并提供可能的修复建议。
