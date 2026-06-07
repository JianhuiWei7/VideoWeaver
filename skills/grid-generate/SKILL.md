---
name: grid-generate
description: "【视频网格图生成工具】把一个视频按时间间隔或按镜头边界抽帧,拼成一张带序号+时间戳标注的网格总览图 (grid_overview.jpg),便于一次性喂给多模态模型做全片理解、视觉一致性、物理异常等评测。当用户要求生成视频全片概览图/总览拼图/shot 网格图/grid overview/拼帧图,或要给 LLM 一张代表整段视频的图片时,必须立即调用此技能。"
---

# 视频网格图生成 (grid-generate)

把一段视频抽帧拼成 `cols × rows` 网格图,每格左上角标 **[序号]**、左下角标 **mm:ss 时间戳**,同时输出 sidecar JSON 索引,下游(O3/O4/O6/overview)直接读 JSON 而不用反查时间戳。

## 前置依赖
```bash
pip install opencv-python pillow scenedetect
```

## 两种模式

### 1. by-time (默认) — 等间隔抽帧
按固定时间间隔 (默认 2s) 抽帧,适合做全片概览 (`cache/grid_overview.jpg`)。

### 2. by-shot — 按镜头边界抽帧
内部调 PySceneDetect 切镜头,每镜头取一帧 (first/middle/last),适合做跨镜头视觉一致性 (`cache/shot_grid.jpg`)。也可以传入已经算好的 `--shots-json` 跳过检测。

## 标注

每个格子:
- 左上角 `[1]` `[2]` …（黑底白字,LLM 引用"第 7 格"时不会错位）
- 左下角 `00:08` 或 `shot_03 00:08`（by-shot 模式带 shot_id）

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--video_path` | 必填 | 输入视频绝对路径 |
| `--mode` | `by-time` | `by-time` 或 `by-shot` |
| `--interval` | `2.0` | (by-time) 抽帧间隔 (秒) |
| `--frame` | `first` | (by-shot) 每 shot 取哪一帧: `first` / `middle` / `last` |
| `--shots_json` | 无 | (by-shot) 跳过检测,直接读 `[{shot_id,start,end},...]` |
| `--cols` | `6` | 列数 (行数自动算) |
| `--cell_width` | `384` | 每格像素宽 (高度按视频宽高比自动算) |
| `--padding` | `4` | 格子间距像素 |
| `--max_cells` | `60` | 总格数上限; 超过后均匀降采样 |
| `--time_range` | 无 | 限定区间 `"00:10-00:50"` 或 `"10-50"` 秒 |
| `--no_label` | flag | 关闭标注 |
| `--quality` | `92` | JPEG 质量 |
| `--session-key` | 可选 | 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入session-key；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |

## 输出

```
<session_out>/images/{video_name}_grid_overview.jpg      # by-time 网格 JPG
<session_out>/images/{video_name}_shot_grid.jpg          # by-shot 网格 JPG
同名 `.jpg.json` 文件                                      # sidecar 索引
```

sidecar schema:
```json
{
  "video_path": "...",
  "mode": "by-time",
  "cols": 6,
  "rows": 5,
  "cell_width": 384,
  "cell_height": 216,
  "total_cells": 30,
  "cells": [
    {"idx": 1, "t_sec": 0.0,  "t_label": "00:00", "shot_id": null, "frame_idx": 0},
    {"idx": 2, "t_sec": 2.0,  "t_label": "00:02", "shot_id": null, "frame_idx": 48},
    ...
  ]
}
```

## 使用示例

### 全片概览图 (Step 2 用)
```bash
python scripts/grid_generate.py \
  --video_path /path/to/final.mp4 \
  --mode by-time --interval 2 --cols 6
```

### 镜头网格图 (O4 用)
```bash
python scripts/grid_generate.py \
  --video_path /path/to/final.mp4 \
  --mode by-shot --frame first --cols 6
```

### 已有 shots.json 时跳过检测
```bash
python scripts/grid_generate.py \
  --video_path /path/to/final.mp4 \
  --mode by-shot --shots_json /path/to/cache/shots.json --frame middle
```

### OpenClaw 环境
```bash
python scripts/grid_generate.py \
  --video_path /path/to/final.mp4 \
  --mode by-time --interval 2 \
  --session-key "agent:{agent_id}:{session_id}"
```

### 只看片段
```bash
python scripts/grid_generate.py \
  --video_path /path/to/final.mp4 \
  --mode by-time --interval 1 --time_range "00:20-00:40"
```

## 设计原则

- **序号 + 时间戳双标注**: LLM 引用某格时,既能说"第 7 格"也能说"00:08 那一段",降低指代歧义。
- **sidecar JSON 必出**: 下游不用再从图片里 OCR 时间戳。
- **格数封顶**: `--max_cells` 防超长视频拼出几百格的图,LLM 喂不下。
- **幂等**: 给定相同输入 + 输出路径,产物可重复。
