---
name: split-audio
description: 将视频文件中的音频和视频画面分离。输入一个视频路径，提取出的音频和无声视频会保存到基于 session 生成的特定输出目录下，无声视频会加上 _no_audio 后缀。当用户要求“抽离视频音频”、“提取视频声音”或“分离音视频”时必须调用本技能。
---

# 视频音频分离工具 (split-audio)

本技能用于将视频文件分离为“纯音频文件”和“无声视频文件”。

## 核心功能与工作流程

当用户需要从一个视频中抽离出音频，或者需要去掉视频的原声时，使用本技能。

### 调用脚本分离音视频

使用本技能自带的 `scripts/split_audio.py` 脚本来处理视频。

#### 参数说明
| 参数名 | 说明 |
|--------|------|
| `video_path` | **(Required)** 需要分离音频的源视频的绝对路径。 |
| `--session-key` | **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |

#### 执行逻辑与输出
执行脚本后，它会自动在目标位置生成两个文件：
1. **音频文件**: 保存为 `[基于session生成的输出目录]/[原文件名]_audio.mp3`
2. **无声视频**: 保存为 `[基于session生成的输出目录]/[原文件名]_no_audio.[原后缀]`

#### 调用示例

```bash
python split-audio/scripts/split_audio.py "/path/to/your/video.mp4" --session-key "agent:{agent_id}:{session_id}"
```
