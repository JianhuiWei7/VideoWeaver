---
name: resize-video-resolution
description: "调整视频分辨率的技能。当用户要求改变视频分辨率、缩放视频画面尺寸（如转换为1920x1080）时调用此技能。"
---

# Resize Video Resolution (修改视频分辨率)

这是一个用于修改视频画面分辨率（Resolution）的技能。它接收一个输入视频路径和目标分辨率，然后调用提供的 Python 脚本生成一个带有新分辨率后缀的新视频文件。

## 使用说明 (When to Use)

当用户请求：
- 改变某个视频的分辨率或尺寸
- 将视频缩放/转换为特定的分辨率（例如 1920x1080, 1280x720, 1080p等）
- 使用 `resize-video-resolution` 技能处理视频时

请**立即调用此技能**并按照以下步骤操作。

## 技能参数

1. **输入视频 (`input_video`)**: 原始视频的绝对路径或相对路径。
2. **目标分辨率 (`target_resolution`)**: 用户期望转换的分辨率格式，标准格式为 `宽x高`（例如：`1920x1080`, `1280x720`）。如果用户说 1080p，请转换为 `1920x1080`；如果是 720p，转换为 `1280x720` 等。
3. **session-key (`--session-key`)**: **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。

## 执行步骤 (How to Execute)

当此技能被调用时，请执行工作区提供的 Python 脚本完成操作：

1. **确认参数**：
   - 提取输入路径和目标分辨率（确保格式为 `宽x高`，例如 `1920x1080`）。
   
2. **执行脚本**：
   - 向终端发送以下命令（基于当前工作区根目录）：
     ```bash
     python resize-video-resolution/scripts/resize_video_resolution.py "<input_video>" "<target_resolution>" --session-key "agent:{agent_id}:{session_id}"
     ```
   
3. **验证并返回结果**：
   - Python脚本会自动将新视频保存在基于 session 生成的特定输出目录下，并命名为 `[原文件名]_[目标分辨率][扩展名]`。
   - 检查命令是否执行成功（Exit Code 为 0）。
   - 向用户返回成功的消息，并提供新生成的视频路径。

## 示例 (Example)

**用户输入**: "帮我把 /path/to/my_video.mp4 的分辨率改成 1920x1080"

**你的处理逻辑**:
1. 输入视频: `/path/to/my_video.mp4`
2. 目标分辨率: `1920x1080`
3. 运行命令: `python resize-video-resolution/scripts/resize_video_resolution.py "/path/to/my_video.mp4" "1920x1080" --session-key "agent:{agent_id}:{session_id}"`
4. 回复用户: "视频分辨率已成功修改为 1920x1080，文件保存在: /基于session生成的输出目录/my_video_1920x1080.mp4"
