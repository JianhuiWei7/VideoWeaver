---
name: output-eval
description: "用于评估视频生成任务的最终产物 (final.mp4) 是否符合 rubric.json 中 output_rubric 列出的指标 (O2-O8 需求达成度/参考忠实度/视觉一致性/音频一致性/物理异常/剧情连贯/音画同步)。当用户要求对一个 case 目录、产物目录、生成结果做 output rubric 打分、给视频质量评分、跑 LLM-as-judge 评测,或者提到 `output_rubric` / `rubric.json` 的最终视频打分时,必须立即调用此技能。这个 skill 不评估执行过程 (process_rubric),只评估最终视频质量。这里不需要对 O1(通过率) 打分。"
---

# 视频产物评测技能 (output-eval)

## 🎯 目标
对一个 case 的产物目录 + `rubric.json`,逐项给 O2-O8 打分,写回 `rubric.json` 的 `分数` / `反馈` 字段。

## 📥 输入
1. **case 目录**: 含 `rubric.json` (`input_materials` + `output_rubric`)
2. **产物目录**: 含 Agent 生成的 mp4/jpg/json/log
3. **参考素材**: `input_materials.参考图片 / 参考音频` 中的文件

## 📏 统一评分标准
所有指标只有三档:

| 分数 | 含义 |
|------|------|
| `1`   | 无任何问题 |
| `0.5` | 有瑕疵但不影响主要观感 |
| `0`   | 有明显问题 |


## 🛠️ 依赖技能
- 预处理: `get-video-metadata` / `automatic-speech-recognition` / `video-shot-split` / `extract-video-frame` / `grid-generate`
- 判定: `vision-understanding` (图像/视频,O2-O4/O6/O8 用) / `audio-understanding` (音频,O5 用)

> 网格图统一走 `grid-generate`,不要自己拼图。

## 🔁 主流程 (4 步)

### Step 1 · 定位 final.mp4
扫描产物目录所有 `*.mp4`:
- 优先文件名含 `final` / `merged` / `output`
- 次选时长最长且接近需求时长 (±10%)
- 拿不准时列候选让上层确认

可用 `scripts/locate_final.py`。

### Step 2 · 建立 cache (一次预处理,所有指标复用)

使用`get-output-dir`技能,在并且加上 subdir: `cache`后, 产出:

```
cache/
├── meta.json           # get-video-metadata: duration / w / h / fps / total_frames
├── audio.mp3           # ffmpeg 从 final.mp4 抽出的原音轨 (-vn -acodec libmp3lame)
├── transcript.srt      # automatic-speech-recognition (输入 audio.mp3),带时间戳
├── transcript.txt      # 纯文本
├── shots.json          # video-shot-split: [{shot_id,start,end,frame_path}]
├── grid_overview.jpg   # grid-generate --mode by-time --interval 2 --cols 6   (O2/O3/O6 用)
├── shot_grid.jpg       # grid-generate --mode by-shot --frame first --cols 6  (O4 人物路 用)
├── bg_grid.jpg         # grid-generate --mode by-shot --frame first --max_cells 6 --cols 3  (O3/O4 背景路 / O6 复用)
└── overview.json       # 故事卡片 (见下)
```

**overview.json**:
```json
{
  "synopsis": "一句话剧情",
  "timeline": [{"t":"00:00-00:05","desc":"画面","narration":"旁白"}],
  "characters": ["主角描述"],
  "scenes": ["场景列表"],
  "visual_style": "风格关键词",
  "audio_observation": {"bgm":"BGM 风格","sfx":["主要音效"]}
}
```

生成方式: `grid_overview.jpg` + `transcript.txt` 一起喂 `vision-understanding`,按 schema 输出 JSON。

### Step 3 · 逐条 output_rubric 打分

读 `rubric.json.output_rubric`,逐项按 `references/rubric_methods.md` 的方法判定。**每条 atom 默认 1 次模型调用**,优先复用 cache,不要让模型重看视频。

| ID | 名称 | 主要数据源 | 主调用 |
|----|------|-----------|--------|
| O1 | 通过率 | 不打分,不填写 | — |
| O2 | 需求达成度 | meta + overview + transcript | 1× vision-understanding(可选) |
| O3 | 参考忠实度 | 参考图 + grid_overview / bg_grid | 1× vision-understanding |
| O4 | 视觉一致性 | shot_grid (人物) + bg_grid (背景) | 2× vision-understanding |
| O5 | 音频一致性 | audio.mp3 整段 + ffprobe 兜底 | 1× audio-understanding |
| O6 | 物理异常 | grid_overview + bg_grid | 1× vision-understanding |
| O7 | 剧情连贯 | overview.json (纯文本) | 1× LLM 纯文本 |
| O8 | 音画同步 | final.mp4 + ffprobe 兜底 | 1× vision-understanding |

### Step 4 · 回写 rubric.json
- O1 通过率不填(留空)
- 每项填 `分数` (`"0"` / `"0.5"` / `"1"`) + `反馈` (**只写负面反馈**,即哪里没达成;满分项 `反馈` 留空)
- 写回原路径

## ⚠️ 原则
- **确定性数值走 ffprobe** (时长/分辨率/帧率/音轨),不交给 LLM
- **反馈只写负面**: 满分留空,扣分必须指出具体问题
- **粗看 → 精看 (异常区间细化抽帧)**: 默认全片走 `grid_overview.jpg` (6 列,每 2s 一格,行数自动) 粗扫;若某条 atom 在某区间发现可疑/异常,**对该区间二次抽帧**(例如 10s 区间抽 20 帧, `grid-generate --time_range "Ts-Te" --interval 0.5 --cols 5`),再喂 `vision-understanding` 确认。避免漏判,也避免一开始就密集抽帧导致 token 爆炸。