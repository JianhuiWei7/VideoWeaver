---
name: video-shot-split
description: 视频镜头切割与统计工具，支持统计视频镜头数量、切割视频为单独的镜头片段文件。当用户提及处理视频镜头、查询视频镜头数量、拆分视频镜头时使用本技能。
---

# Video Shot Split Skill
基于PySceneDetect实现的视频镜头分割工具，可以统计视频中的镜头数量，也可以将视频按镜头切割为单独的片段文件。


## 使用方法
### 参数说明
- `video_path`: 本地视频文件的绝对路径
- `split` (可选): 是否切割视频为单独文件，默认`True`；如果用户仅查询镜头数量，设为`False`
- `--session-key` (可选；OpenClaw 必填): 可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。

### 调用方式
#### 仅统计镜头数量（不切割）
```bash
python video-shot-split/scripts/split.py --video_path <视频路径> --split False --session-key "agent:{agent_id}:{session_id}"
```

#### 统计并切割视频为镜头片段
```bash
python video-shot-split/scripts/split.py --video_path <视频路径> --split True --session-key "agent:{agent_id}:{session_id}"
```

## 示例
用户提问：`/tmp/test.mp4这个视频有多少个镜头？`
调用命令：
```bash
python video-shot-split/scripts/split.py --video_path /tmp/test.mp4 --split False --session-key "agent:{agent_id}:{session_id}"
```

用户提问：`把/tmp/test.mp4按镜头拆分`
调用命令：
```bash
python video-shot-split/scripts/split.py --video_path /tmp/test.mp4 --split True --session-key "agent:{agent_id}:{session_id}"
```
