---
name: extract-video-frame
description: "【视频抽帧工具】从指定的视频中提取特定位置的单帧画面并保存为图片。支持提取首帧(first)、中间帧(middle)、尾帧(last)、指定帧号(如 100)或指定秒数(如 2.5)。当用户要求从视频中截取画面、保存视频截图、提取某一帧图片时，必须立即调用此技能。"
---

## 前置依赖
1. 安装依赖包：`pip install opencv-python`

## 支持模式
1. 相对位置抽帧
支持通过关键词快速提取视频的关键节点画面：
- `first`: 第一帧
- `middle`: 中间帧
- `last`: 最后一帧（默认行为）

2. 精确位置抽帧
支持精准定位提取：
- **按帧号**：传入整数（例如 `150` 代表第 150 帧）
- **按时间（秒）**：传入浮点数（例如 `3.5` 代表第 3.5 秒处的帧）

## 典型使用案例

1. 提取视频的最后一帧（自动生成路径）
如果用户只要求从视频提取一帧或明确要求最后一帧，不用指定输出路径，会自动在基于 session 生成的特定输出目录下生成 `{视频文件名}_last.jpeg`：
```bash
python extract-video-frame/scripts/extract_frame.py \
  --video_path "/path/to/video.mp4" \
  --session-key "agent:{agent_id}:{session_id}"
```

2. 提取视频的第一帧或中间帧（自动生成路径）
通过 `--position` 参数指定相对位置，会自动生成如 `{视频文件名}_first.jpeg`：
```bash
python extract-video-frame/scripts/extract_frame.py \
  --video_path "/path/to/video.mp4" \
  --position "first" \
  --session-key "agent:{agent_id}:{session_id}"
```

3. 按指定时间（秒）或帧号提取并指定输出路径
通过 `--position` 参数指定数字（小数代表秒，整数代表帧号），可自主决定输出路径：
```bash
# 提取第 2.5 秒的画面

**环境依赖:** `opencv-python`

python extract-video-frame/scripts/extract_frame.py \
  --video_path "/path/to/video.mp4" \
  --output_path "/path/to/output_2_5s.jpg" \
  --position "2.5" \
  --session-key "agent:{agent_id}:{session_id}"
```

4. 指定输出的 JPEG 图片质量
默认质量为 95，可通过 `--quality` 参数调节（0-100）：
```bash
python extract-video-frame/scripts/extract_frame.py \
  --video_path "/path/to/video.mp4" \
  --output_path "/path/to/output_high_res.jpg" \
  --position "middle" \
  --quality 100 \
  --session-key "agent:{agent_id}:{session_id}"
```

## 运行模式与日志监控
**默认行为**：
该脚本为前台同步执行（Blocking），直接在终端输出执行结果。

**完成状态**：
- **成功**：日志末尾会输出 `✅ 帧已保存至: [输出路径] (目标帧位置: X / 总帧数: Y)`。
- **失败**：日志会输出 `读取帧失败` 或 `无法打开视频文件`，并且脚本会以非零状态码退出。

## 参数说明
| 参数名 | 说明 |
|--------|------|
| `--video_path` | （**必填**）需要提取帧的输入视频文件绝对路径。 |
| `--output_path` | （**选填**）提取出图片的保存绝对路径（通常为 `.jpg` 或 `.png`）。如果不填，默认在基于 session 生成的特定输出目录下自动生成形如 `{视频名}_last.jpeg`，`{视频名}_frame_100.jpeg` 的文件。 |
| `--position` | （**选填**）要提取的帧位置。支持字符串 `"first"`, `"middle"`, `"last"`，也支持传入整数（代表帧号）或浮点数（代表秒数）。默认为 `"last"`。 |
| `--quality` | （**选填**）当输出为 JPEG 格式时，指定图片保存质量（0-100），默认为 `95`。 |
| `--session-key` | **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |

## 执行规范
- **路径检查**：确保传入的 `--video_path` 在本地确实存在。
- **参数类型处理**：脚本会自动处理 `--position` 参数的类型判断，Agent 只需要将用户的意图（如“第5秒”转化为 `5.0`，或“第100帧”转化为 `100`）以字符串形式传入即可。
- **结果反馈**：提取成功后，向用户汇报："✅ 视频帧提取成功！已保存至：[输出路径]"。如果用户需要在聊天窗口查看，可以引导用户打开该文件。
