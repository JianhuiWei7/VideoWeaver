---
name: ai-avatar-video-gen
description: AI数字人口播短视频生成工具。输入通常包含需求、参考文本和参考视频；适用于知识科普、生活干货、商业讲解、产品思维等文案驱动的数字人演播视频。
---

# AI Avatar Video Gen

## Overview
生成“参考视频人物 + 参考文本/口播文案”的数字人口播短视频，默认包含口播音频、同步字幕、BGM、虚拟演播背景和最终合成视频。

核心链路：
1. `input.json`
2. `requirements.json`
3. `story_script.json`
4. `plan.json`
5. `asset.json`
6. `shot.json`
7. 分段音频、分段视频、字幕、BGM、最终合成

## References
开始前按需读取：
- `references/input.md`
- `references/requirements.md`
- `references/story_script.md`
- `references/plan.md`
- `references/asset.md`
- `references/shot.md`
- `references/case_examples.md`（仅作风格参考）

## Core Dependencies
- **get-output-dir**：获取并锁定输出目录
- **vision-understanding / video-understanding**：理解参考视频人物、背景和生成结果
- **extract-video-frame**：提取人物帧和分段尾帧
- **image-gen**：生成人物三视图、安全锚图和背景锚图
- **audio-gen**：生成分段口播音频和时间戳
- **video-gen**：逐段生成数字人口播视频
- **merge-video / split-audio / trim-audio**：合成视频、口播和 BGM
- **resize-video-resolution / change-fps**：统一规格

## Output Layout
所有产物必须写入 `get-output-dir` 返回的 `output_dir`：
- `output_dir/input.json`
- `output_dir/requirements.json`
- `output_dir/story_script.json`
- `output_dir/plan.json`
- `output_dir/asset.json`
- `output_dir/shot.json`
- `output_dir/images/`
- `output_dir/audio/`
- `output_dir/videos/segment_N.mp4`
- `output_dir/full_narration.mp3`
- `output_dir/subtitles.srt`（若要求字幕）
- `output_dir/videos/final_video.mp4`

## Workflow

### Step 0: 输出目录
调用 `get-output-dir`，后续所有文件都写入该目录。

### Step 1: input.json
按 `references/input.md` 整理需求、参考文本、参考视频和参考音频。若有参考视频，必须先做视觉理解并记录人物、服装、姿态、背景和说话状态。

口播主线选择：
- 用户明确说“以参考文本为准”或“参考文本就可以”时，使用 `参考文本`
- 否则若需求中有完整 `口播文案`，优先使用需求口播
- 两者冲突时不要混写，在 `input.json` 记录冲突和选择理由

### Step 2: requirements.json
按 `references/requirements.md` 提取硬指标：时长、分辨率、比例、fps、数字人出镜、演播背景、语速语气、字幕、BGM 和输出文件名。不要在这里写剧情或分段。

### Step 3: story_script.json
按 `references/story_script.md` 必须生成 `story_script.json`。默认只做规范化文案：清理重复、补标点、统一口语节奏、按语义分段、提取覆盖点。

只有文本明显不足以支撑目标时长、缺少必要承接，或无法支撑每个 shot 的 `lines` 时，才做轻量扩写。扩写不得改变主题、立场和核心结论。

### Step 4: plan.json
按 `references/plan.md` 生成整体计划。必须包含 `total_segments` 和 `segments`，并规划音频分段、字幕、BGM、人物连续性、背景一致性、`连续镜头` / `回锚镜头`。

### Step 5: asset.json
按 `references/asset.md` 建立稳定资产：
- 从参考视频提取 `3-5` 帧人物帧
- 生成 `output_dir/images/avatar_primary.png`
- 生成单张三视图 `output_dir/images/avatar.png`
- 必要时生成 `output_dir/images/background_main.png`

### Step 6: shot.json
按 `references/shot.md` 拆成逐段执行表。每个 shot 默认必须有 `lines`、`coverage_points`、`audio_file`、`timestamp_file`、`video_file`、`shot_type`、`is_completed`。

### Step 7: 音频与时间戳
视频生成前必须完成全部分段口播音频：
- `output_dir/audio/narration_segment_N.mp3`
- `output_dir/audio/narration_segment_N_timestamp.json`

全片锁定同一套 `voice_type`、`speed`、`pitch`、`volume`。拼接完整口播为 `output_dir/full_narration.mp3`。字幕只能基于时间戳生成，禁止手写估时字幕。

### Step 8: 逐段视频
每段生成前重读 `requirements.json`、`story_script.json`、`plan.json`、`asset.json`、`shot.json`。

生成策略：
- 首段使用人物主锚图 / 三视图 + 当前段音频
- `连续镜头` 才允许带最近一段尾帧 + 人物锚图 + 当前段音频
- `回锚镜头` 回到原始人物锚图和背景锚图，不带上一段视频
- 禁止把全部历史视频塞给当前段
- prompt 必须明确“参考图中的人物形象作为数字人口播讲解人”

每段固定输出 `output_dir/videos/segment_N.mp4`，完成后提取 `output_dir/images/tail_frame_N.png` 并更新 `shot.json`。

### Step 9: 合成与验收
按 `shot.json` 顺序拼接视频，合成完整口播和 BGM。若需求要求字幕，生成本任务目录下的 `subtitles.srt` 并烧录或合成到最终视频。

最终主交付物固定为：
- `output_dir/videos/final_video.mp4`

最终回复前必须运行：

```bash
python scripts/validate_delivery.py \
  --output-dir "<输出目录>" \
  --final-path "videos/final_video.mp4"
```

校验失败不得回复“已完成”。

## Important Rules
- `story_script.json` 必产，默认规范化，必要时才轻量扩写
- 未完成整套分段音频，不得进入视频生成
- 音色参数全片一致
- 字幕若被需求要求，必须生成当前输出目录下的 `subtitles.srt`
- 最终输出路径只能是 `videos/final_video.mp4`
- 最终回复里的时长、分辨率、比例和路径必须来自实测，不得引用估算值
