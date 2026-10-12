---
name: ai-avatar-tech-content-video-gen
description: AI数字人科技数码讲解视频生成工具。输入可包含需求、参考文本、参考图片、参考视频和参考音频；先规范化/必要扩写讲解文案，再建立数字人、产品、背景和参考音频锚点，最后逐段生成并合成为科技讲解成片。
---

# AI Avatar Tech Content Video Gen

## Overview
本技能用于生成 AI 数字人科技 / 数码类讲解视频。
输入通常包括：
- 用户需求
- 参考文本 / 口播文本
- 参考视频：一段数字人说话视频，用于提取人物、背景和音频锚点
- 参考图片：通常是产品图，用于生成产品锚图
核心原则：
- 人物、产品、背景、音频都先建立稳定锚点
- 逐段生成时只使用当前段相关资产和必要的最近尾帧
- 最终主交付物固定为 `videos/final.mp4`

## Workflow
严格按步骤执行，前置步骤未完成时禁止跳到后续步骤。

### 步骤1：需求与输入理解
#### 不要跳步
1. 读取用户需求、参考文本、参考图片、参考视频。
2. 调用视觉理解能力分析参考图片和参考视频：
   - 参考视频：提取数字人人物形象、服装、说话状态、背景环境、风格
   - 参考图片：默认按产品参考理解，提取产品主体、外观、结构、颜色、材质、文字信息
3. 只整理输入，不拆分镜头，不直接写视频生成 prompt。
   生成一个`input.json`

### 步骤2：硬性要求与文案主线
#### 不要跳步
前置检查：确认 `input.json` 已保存。

1. 生成 `requirement.json`，只提取硬性要求：
   - 时长
   - 分辨率
   - 宽高比
   - fps
   - 是否有配音
   - 是否需要音频连续性
   - 输出文件名：固定 `final.mp4`
   - 字幕：默认不生成，除非用户明确要求
2. 生成 `story_script.json`，必须保存。
3. `story_script.json` 默认做规范化文案：
   - 去重
   - 补标点
   - 统一术语
   - 整理口语节奏
   - 拆出覆盖点
   - 保留参考文本核心信息、顺序和结论
4. 根据参考文本和用户需求，对讲解文案进行规范化与必要扩写。扩写应服务于数字人口播场景，保持原有主题、事实和结论不变；语速按需求控制在约 180-220 字/分钟，并结合目标时长生成总量合适的口播文案。若无明确目标时长，默认生成约 180-220 字的完整讲解文案。

5. 规划 shot 时，应保证每个 shot 承担相对独立的讲解任务。每段应围绕一个明确的信息点、卖点或过渡目标展开，避免多个 shot 重复讲同一内容，也避免单个 shot 同时塞入过多无关信息。shot 之间需要有清晰的承接关系，整体形成连贯的讲解逻辑。


`story_script.json` 至少包含：
- `script_source`
- `rewrite_policy`
- `final_script`
- `coverage_points`
- `estimated_duration_sec`
- `normalization_notes`
- `expansion_notes`

### 步骤3：整体计划 plan.json
#### 不要跳步
前置检查：确认 `requirement.json` 和 `story_script.json` 已保存。

1. 根据 `story_script.json.final_script` 和 `coverage_points` 生成 `plan.json`。
2. `plan.json` 必须完整覆盖参考文本和规范化后的讲解主线。
3. 拆分为多个生成段，每段建议 `4-10` 秒。
4. 每段必须明确：
   - `segment_id`
   - `segment_goal`
   - `duration`
   - `narration_summary`
   - `coverage_points`
   - `shot_type`
   - `required_assets`
5. `shot_type` 只能是：
   - `连续镜头`：允许使用最近一段尾帧或短视频
   - `切分镜头`：不使用上一段视频，只使用当前段资产和内容
   - `回锚镜头`：回到原始人物、背景和当前段内容
6. 不依赖用户提供参考分镜。

### 步骤4：一致性资产 asset.json
#### 不要跳步
#### 前置检查：确认 `plan.json` 已保存。
#### 这里提取资产, 调用‘image-gen'生成资产,模型固定为‘gpt-image-2‘ 以及提取音频
1. 从参考视频提取 `1` 帧最清晰、最能代表数字人形象的人物参考帧。
   - 保存为 `output_dir/images/avatar_source_frame.png`
   - 后续视频生成必须优先传入这张原始人物帧作为人物细节参考
2. 调用 `image-gen` 的 `gpt-image-2` 模式生成 `output_dir/images/avatar.png`：
 例如: 基于[图1]参考帧生成单张白底人物锚图，只替换为纯白背景，不改变人物身份、发型、五官、服装、比例和视觉风格。
   - 数字人讲解默认不需要人物三视图
3. 若存在产品参考图，生成或整理 `output_dir/images/product.png` 调用 `image-gen` 的 `gpt-image-2` 模式生成 
 例如: 基于[图1]生成产品三视图，保留为纯白背景
4. 根据需求调用 `image-gen` 的 `gpt-image-2` 模式生成 `output_dir/images/background.png`
 例如: 生成xx的背景图。

### 步骤5：shot.json 生成
#### 不要跳步
前置检查：确认 `asset.json` 已保存。

1. 生成 `shot.json`，每个 shot 至少包含：
   - `shot_id`
   - `segment_id`
   - `description`
   - `duration`
   - `lines`
   - `coverage_points`
   - `shot_type`
   - `require_assets`
   - `actual_asset_paths`
   - `audio_reference_source`
   - `output_video`
   - `is_completed`
2. 每个 shot 默认必须有明确旁白 `lines`。
3. 每个 shot 应介绍相对独立的内容，围绕一个明确的信息点、卖点或过渡目标展开。
4. `shot.json` 必须先完整保存并校验通过，才能进入视频生成步骤。
5. 校验重点：
   - 所有 coverage point 均被覆盖
   - 每个 shot 都有明确台词
   - 总时长与 `requirement.json` 基本一致
   - `shot_type` 已明确标注为 `连续镜头`、`切分镜头` 或 `回锚镜头`
   - `is_completed` 初始值为 `false`

### 步骤6：逐段视频生成
#### 不要跳步
**【前置检查】：请确认步骤5中 `shot.json` 已生成并校验通过。如果未完成，请立刻停止当前步骤，返回步骤5。**

1. 按照 `shot.json` 分段计划，逐段生成视频：
   - 使用 `video-gen` 技能生成每个片段，**传入当前片段台词 / 音频、当前片段相关的一致性资产图、`reference_audio_15s.wav`，以及上一段 split 出的音频参考**，来保证人物、场景、音色、BGM 和环境音统一。
   - 生成具体片段前，确保 prompt 已经被重写，不能直接使用原始需求或原始分镜描述。Prompt 应该是：参考[图1]的人物以及风格，参考[图2]的背景，[图3]的xx [图4]的xx，[图3]，[图4]这里是对应的资产。
   - 每个片段生成超时设置为 `30` 分钟，避免生成失败。
   - 禁止默认写 `现实风格`，这里必须参考[图1]的人物以及风格
   - 这里在prompt里面需要传入这一段的口播文案
**2. 在生成每个片段的时候，需要传入当前片段相关的一致性资产图和当前 `shot` 内容**

**3. 在生成第 `n+1` 个片段的时候，必须使用第 `n` 个片段的音频作为参考[使用 `split-audio` 技能来分割音频]，和第 `n+1` 个片段相关的一致性资产图、当前 `shot` 内容一起传入，来保持角色、场景、音色、背景音乐和环境音等元素高度一致，避免不协调的情况。并且需要在 prompt 里写明：参考[音频1]的音色、背景音乐和环境音氛围，禁止重复音频里说话的内容和背景音乐。**

4. 补充约束：
   - 首段使用 `reference_audio_15s.wav` 作为全局音频参考。
   - 从第二段开始，必须额外传入上一段提取音频；不要传入全部历史音频。
   - 若 `shot_type = 连续镜头`，可额外传入上一段尾帧或短视频；否则不传上一段视频。

5. 每段输出：
   - `output_dir/videos/segment_001.mp4`
   - `output_dir/videos/segment_002.mp4`
   - 以此类推

### 步骤7：合成与导出
#### 不要跳步
前置检查：确认 `shot.json` 中所有需要生成的段落已完成。

1. 按 `shot.json` 顺序合并所有 `segment_*.mp4`。
2. 统一分辨率、宽高比和 fps。
3. 默认不生成字幕；用户明确要求字幕时才生成。
4. 导出最终成片：
   - `output_dir/videos/final.mp4`
5. 最终检查：
   - 成片路径真实存在
   - 时长符合 `requirement.json`
   - 人物一致
   - 产品一致
   - 参考文本覆盖完整
   - 音频连续自然

## Important Rules
1. 只保留 `SKILL.md` 作为技能说明，不依赖额外 reference
2. 所有输出都必须写入 `get-output-dir` 返回的目录
3. `story_script.json` 必须生成并保存
4. 默认规范化文案，只有不足时才轻量扩写
5. 人物原始帧固定为 `images/avatar_source_frame.png`
6. 人物白底锚图固定为 `images/avatar.png`，默认不生成三视图
7. 产品锚图仅有产品参考图时生成，固定为 `images/product.png`
8. 参考视频必须提取 `audio/reference_audio_15s.wav`
9. `shot.json` 保存并校验完成后，才能开始逐段视频生成
10. 生成 prompt 必须强调参考图视觉风格，不得默认写现实风格
11. 不得把全部历史视频传给当前段
12. 第 `n+1` 段必须使用第 `n` 段 split 出的音频作为参考，但不得传入全部历史音频
13. 最终主交付物固定为 `videos/final.mp4`
## Core Dependencies
- `get-output-dir`：获取输出目录，所有产物写入该目录
- `vision-understanding`：理解参考视频和生成结果
- `extract-video-frame`：从参考视频提取人物帧，从分段视频提取尾帧
- `image-gen`：使用 `gpt-image-2` 生成人物白底锚图、产品锚图和背景锚图
- `split-audio`：从参考视频提取 15s 参考音频锚点，并从上一段生成视频提取连续音频参考
- `video-gen`：逐段生成视频
- `merge-video`：合并最终视频
- `resize-video-resolution / change-fps`：按需统一规格
所有中间文件必须写入 `output_dir`。
