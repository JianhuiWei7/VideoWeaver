---
name: change-fps
description: "修改视频帧率(FPS)的技能。当用户要求改变视频的FPS、转换帧率或生成指定FPS的新视频时调用此技能。"
---

# Change FPS (视频帧率转换)

这是一个用于修改视频帧率（FPS）的技能。它接收一个输入视频路径和目标帧率，然后调用提供的 Python 脚本生成一个包含新帧率信息后缀的新视频文件。

## 使用说明 (When to Use)

当用户请求：
- 改变某个视频的帧率（FPS）
- 将视频转换为特定的FPS（如 30, 60 等）
- 使用 `change-fps` 技能处理视频时

请**立即调用此技能**并按照以下步骤操作。

## 技能参数

1. **输入视频 (`input_video`)**: 原始视频的绝对路径或相对路径。
2. **目标帧率 (`target_fps`)**: 用户期望转换的FPS数值（例如：`30`, `60`, `24`）。
3. **session-key (`--session-key`)**: **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。

## 执行步骤 (How to Execute)

当此技能被调用时，请执行工作区提供的 Python 脚本完成操作：

1. **确认参数**：
   - 提取输入路径和目标帧率。
   
2. **执行脚本**：
   - 向终端发送以下命令（基于当前工作区根目录）：
     ```bash
     python change-fps/scripts/change_fps.py "<input_video>" <target_fps> --session-key "agent:{agent_id}:{session_id}"
     ```
   
3. **验证并返回结果**：
   - Python脚本会自动将新视频保存在基于 session 生成的特定输出目录下，并命名为 `[原文件名]_fps_[target_fps][扩展名]`。
   - 检查命令是否执行成功（Exit Code 为 0）。
   - 向用户返回成功的消息，并提供新生成的视频路径。

## 示例 (Example)

**用户输入**: "帮我把 /path/to/my_video.mp4 的帧率改成 60"

**你的处理逻辑**:
1. 输入视频: `/path/to/my_video.mp4`
2. 目标 FPS: `60`
3. 运行命令: `python change-fps/scripts/change_fps.py "/path/to/my_video.mp4" 60 --session-key "agent:{agent_id}:{session_id}"`
4. 回复用户: "视频帧率已成功修改为 60 FPS，文件保存在: /基于session生成的输出目录/my_video_fps_60.mp4"
