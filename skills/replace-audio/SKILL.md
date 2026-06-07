---
name: replace-audio
description: "将视频文件中的原始音频替换为输入的音频文件。当用户需要“将视频的音频替换为指定音频”、“删除原视频音轨并换成新音频”、“替换视频声音”时，必须立即调用此技能。"
---

# 音频替换工具 (replace-audio)

本技能用于将视频文件中的原始音频替换为指定音频文件，生成一个音轨已被完全替换的新视频。

⚠️ 注意：本技能会删除原视频的音轨，并用输入音频完全替换；不会保留、混合、叠加或智能配上新的音频。

## 核心功能与工作流程

当用户要求替换视频中的音频、删除原视频音轨并换成指定音频，或合并视频画面和独立音频时，使用本技能。

### 调用脚本替换音视频

使用本技能自带的 `scripts/replace_audio.py` 脚本来处理视频。

#### 参数说明
| 参数名 | 说明 |
|--------|------|
| `video_path` | **(必填)** 原始视频文件的绝对路径。 |
| `audio_path` | **(必填)** 要替换进视频的新音频文件的绝对路径。 |
| `--session-key` | **(可选；OpenClaw 必填)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |

#### 执行逻辑与输出
执行脚本后，它会自动调用 FFmpeg 删除原视频音轨，并把输入音频作为唯一音轨写入新视频（视频不重新编码，音频编码为 aac），并保留最短的媒体时长（防止画面定格或声音空播）。
目标文件将保存在基于 session 生成的特定输出目录下：
- **输出视频**: 保存为 `[基于session生成的输出目录]/[原视频文件名无后缀]_replace_audio.mp4`

#### 调用示例

```bash
python replace-audio/scripts/replace_audio.py "/path/to/your/video.mp4" "/path/to/your/audio.mp3" --session-key "agent:{agent_id}:{session_id}"
```
