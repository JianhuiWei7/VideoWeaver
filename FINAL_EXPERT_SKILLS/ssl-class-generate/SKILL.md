---
name: ssl-class-generate
description: 儿童 SSL 教学视频生成工具。必须由调用方传入 session_dir（绝对路径）作为输入；该目录包含参考需求.txt、参考文本.txt、image/（老师与儿童真实锚图）。按表格逐行生成讲解和回答片段，群体反应行只记录不生成，最终拼接为完整教学视频。严禁调用 image-gen 生成人物锚图。
---

# SSL Class Generate

## Overview
本技能用于生成儿童教学 / SSL 课堂 session 视频。输入数据已结构化完整，无需扩写。

## 输入参数
- `session_dir`（**必填，绝对路径**）：会话输入目录。该目录下必须包含：
  - `参考需求.txt`：整体规格（默认 9:16、720p、整 session 视频）
  - `参考文本.txt`：逐行表格（场景 / 角色 / 神态动作 / 台词），主交付蓝本
  - `image/teacher_anchor_plain.png`：老师锚图
  - `image/child_a.png` ~ `image/child_e.png`：孩子锚图
  - `audio`：文件夹下面有对应的老师和儿童的音色参考音频

## 红线（全流程生效，违反任意一条立即中止）
1. **锚图来源唯一**：所有人物锚图必须来自 `{session_dir}/image/`，禁止从 `{output_dir}/images/`、技能目录或任何其他位置读取。
2. **严禁 `image-gen` 造人物**：本技能在任何阶段都禁止调用 `image-gen` 生成老师/孩子的锚图。`{session_dir}/image/` 中真实缺失的锚图，只能在 `rows.json` 中标记 `missing_asset` 并跳过该角色对应的 shot，**禁止用任何生成图替代真实锚图**。
3. **不写回源目录**：所有产物写入 `output_dir`，禁止回写 `session_dir`。
4. **台词原文照抄**：禁止改写、概括或用"同上"替代。

**核心原则**：
- 台词照抄，不改写、不扩写、不概括
- 角色严格对应锚图，不重新设计
- 每个保留行（`include = true`）对应一个 `line_xxx.mp4`
- `孩子们（反应）` 等群体反应行只记录、不单独生成
- 真人锚图必须先用 `split-image` 切为 2x2 四宫格，prompt 中以 `[图1][图2][图3][图4]` 引用 4 张子图作为人物参考，规避版权审核
- 最终交付物：`videos/final.mp4`

## 工作流（严格按顺序执行，禁止跳步）
**【极其重要】必须严格按 1-6 步顺序执行；前置步骤未完成并输出结果前，禁止开始下一步。**

### 步骤1：读取 session 输入并锁定输出目录
#### 不要跳步,这里必须先在 `{session_dir}` 下完整盘点输入，再调用 `get-output-dir` 锁定输出目录
#### 所有中间产物与最终视频统一写入 `get-output-dir` 锁定的目录
1. **read `{session_dir}/参考需求.txt`**：确认整体规格（默认 9:16、720p；用户自定义优先）。
2. **read `{session_dir}/参考文本.txt`**：解析逐行表格（场景 / 角色 / 神态动作 / 台词），台词字段原文保留，禁止改写。
3. **校验角色 ↔ 锚图 / 音频覆盖**：对 `参考文本.txt` 中出现的每个 `role_key`（除 `孩子们（反应）`），建立 `anchor_paths` 映射并核对 `{session_dir}/image/` 是否有对应锚图；同时建立 `audio_paths` 映射，扫描 `{session_dir}/audio/` 下与该角色对应的音色参考文件。**锚图缺失项记录到 `missing_assets`、音频缺失项记录到 `missing_audio`（步骤3写入 `rows.json`），并跳过该 shot；严禁调用 `image-gen` 或用其他角色锚图/音频替代。**
4. 调用 `get-output-dir` 锁定 `output_dir`。后续全部产物（`rows.json` / `shot.json` / 切分子图 / `line_xxx.mp4` / `final.mp4`）统一写入此目录，**禁止回写 `session_dir`**。

### 步骤2：切分真人锚图
#### 这里严禁使用 `image-gen` 创造新的人物图像，`split-image` 的输入必须是 `{session_dir}/image/` 下的真实锚图
#### 不要跳步,对每张真人锚图调用 `split-image` 进行 2x2 分割
**【前置检查】：步骤1已完成，`output_dir` 已锁定，`anchor_paths` 映射已建立且全部指向 `{session_dir}/image/` 下真实文件。**
1. 遍历步骤1.3 建立的 `anchor_paths` 映射，对每个角色对应的真实锚图调用 `split-image`：
   - 输入路径：`anchor_paths[role_key]`（即 `{session_dir}/image/{filename}`，**禁止使用任何其他路径**）
   - 输出至 `output_dir/images/`：
     - `{锚图名}_grid_1.png`（左上）
     - `{锚图名}_grid_2.png`（右上）
     - `{锚图名}_grid_3.png`（左下）
     - `{锚图名}_grid_4.png`（右下）
2. 在内存中维护"角色 → 4 张子图绝对路径"的映射，供步骤4 prompt 组装使用。
3. **若步骤1标记的 `missing_assets` 中含某角色**，跳过该角色的 `split-image`，**严禁调用 `image-gen` 临时生成"补位锚图"**。

### 步骤3：生成 `rows.json`
#### 不要跳步,按 `参考文本.txt` 逐行建立行元数据；台词必须原文照抄
**【前置检查】：步骤2已完成，每个出现角色均有 4 张切分子图。**
1. 按 `参考文本.txt` 逐行解析，每行一条记录写入 `output_dir/rows.json`，至少包含：
   - `row_id`：`line_001` / `line_002` / ...（按行序递增）
   - `scene_id`：所在场景编号
   - `role_key`：`老师` / `孩子A` ~ `孩子E` / `孩子们（反应）`
   - `row_type`：`speaking`（有台词）/ `silent_reaction`（无台词、单角色反应）/ `group_reaction`（群体反应）
   - `dialogue`：原始台词，**禁止改写、概括或用"同上"替代**
   - `action_hint`：原始神态动作描述
   - `include`：
     - `speaking` → `true`
     - `silent_reaction` → 默认 `true`
     - `group_reaction` → `false`，并填写 `skip_reason`（如 "群体反应行默认不单独生成"）
   - `missing_asset`（可选）：该行角色锚图缺失时填写说明
2. **`rows.json` 必须覆盖 `参考文本.txt` 全部行**，包括 `include = false` 的群体反应行（不生成视频但必须留底）。

### 步骤4：生成 `shot.json`（详细 prompt）
#### 不要跳步,为每个 `include = true` 的行写出完整 prompt，必须使用 `[图1][图2][图3][图4]` 句式
#### prompt 末尾必须显式提及该角色在 `{session_dir}/audio/` 下对应的音色参考音频文件
**【前置检查】：步骤3的 `rows.json` 已生成且覆盖全部行。**
1. 按 `rows.json` 中 `include = true` 的行，依次写入一条 shot 至 `output_dir/shot.json`，每条至少包含：
   - `shot_id`：`shot_001` / `shot_002` / ...（与 `row_id` 一一对应）
   - `row_id`：对应 `rows.json`
   - `role_key`：该行角色
   - `reference_images`：该角色 4 张 `_grid_1/2/3/4` 子图绝对路径（取自步骤2映射）
   - `prompt`：完整 prompt（要素见下）
   - `duration_sec`：5-15 秒
   - `aspect_ratio`：`9:16`
   - `resolution`：`720p`
   - `output_video`：`videos/line_xxx.mp4`（与 `row_id` 一一对应）

2. **prompt 强制包含 6 要素**：
   1. **规避版权核心句式**：`[图1][图2][图3][图4]分别为{角色身份}的左上 / 右上 / 左下 / 右下四部分，参考这个人物形象`
   2. **场景**：纯色背景（默认浅米色或浅灰，避免复杂场景增加生成失败率）
   3. **神态动作语气**：直接复用 `参考文本.txt` 的 `action_hint`，不二次加工
   4. **台词**：
      - `speaking` 行：`角色用{语气}说："{完整原始台词}"`
      - `silent_reaction` 行：`无台词，仅做{action_hint 描述的}表情和肢体反应`
   5. **视频规格**：`画面 9:16 竖屏，720p，写实风格，禁止出现字幕文字和多余人物`
   6. **音色参考**：在 prompt 末尾追加一句 `请参考[音频1]作为该角色音色参考，保持与该角色既有音色一致`。

3. **prompt 禁止**：
   - 改写、概括或省略台词
   - 用"同上""保持一致"代替具体内容
   - 角色与锚图错配（如孩子 A 的行用孩子 B 的锚图）
   - 为 `group_reaction` 行写 prompt（这些行不进入 `shot.json`）

### 步骤5：逐行生成 `line_xxx.mp4`
#### 不要跳步,按 `shot.json` 顺序调用 `video-gen`，每次必须传入 4 张子图
#### 视频生成支持的长度是5-15s
**【前置检查】：步骤4的 `shot.json` 已生成且覆盖全部 `include = true` 的行。**
1. 按 `shot.json` 顺序逐条调用 `video-gen`：
   - `reference_images`：严格使用 shot 中的 4 张 `_grid_*` 子图路径
   - `prompt`：严格使用 shot 中的 `prompt` 字段（含 `[图1][图2][图3][图4]` 句式 + 台词 + 场景 + 规格）
   - `aspect_ratio` / `resolution` / `duration_sec`：按 shot 参数设置
   - **单条超时 ≥ 30 分钟**，避免中途失败
2. **同角色连续 shot 的连续性增强**：
   - 用 `extract-video-frame` 抽取上一条同角色 `line_xxx.mp4` 的尾帧，保存至 `output_dir/frames/line_xxx_tail.png`
   - 作为补充参考图传入下一条，prompt 末尾追加 `延续上一镜头的服装、发型、表情方向`
3. 单条生成完成后自检：
   - 角色形象与锚图一致（无 A/B 错配）
   - 台词与当前 row 精准对应（无误用邻行）
   - 神态动作匹配 `action_hint`
   - 无字幕、旁白文字、多余角色
   - 分辨率与画面比例符合步骤1规格
4. 自检不通过则重生该条 shot，**禁止跳过继续推进**。

### 步骤6：拼接 `final.mp4` 与最终交付检查
#### 不要跳步,使用 `merge-video` 按 `rows.json` 顺序拼接，并完成交付前自检
**【前置检查】：步骤5全部 `include = true` 的行均已生成 `line_xxx.mp4`。**
1. 拼接前校验：
   - 全部 `include = true` 片段文件存在
   - 分辨率统一（不一致则用 `resize-video-resolution` 归一）
   - fps 基本一致（不一致则用 `change-fps` 归一）
   - 无漏行；`group_reaction` 已在 `rows.json` 中标记 `skip_reason`
2. 调用 `merge-video`，按 `rows.json` 中 `include = true` 的顺序拼接为 `output_dir/videos/final.mp4`。
3. 交付前最终自检（用 `get-video-metadata` 取实测参数）：
   - `videos/final.mp4` 存在
   - 画面比例 9:16（或用户指定值）
   - 分辨率 720p（或用户指定值）
   - 片段顺序与 `参考文本.txt` 行序一致
   - 角色形象全程稳定，无人设崩坏
   - 抽查台词与 `rows.json` 的 `dialogue` 字段一致，无改写
4. 回复用户时只引用真实存在的最终路径和实测参数，**禁止编造**。

## 依赖子技能
- `get-output-dir`：锁定输出目录
- `split-image`：切分真人锚图为 2x2 四宫格（必须在 `video-gen` 之前调用）
- `video-gen`：逐行生成教学视频片段
- `extract-video-frame`：抽取同角色尾帧用于连续性续接
- `merge-video`：按行序拼接最终视频
- `get-video-metadata`：获取实测时长 / 分辨率 / 比例 / fps
- `resize-video-resolution`：必要时统一分辨率
- `change-fps`：必要时统一 fps
- `vision-understanding`：必要时辅助理解锚图、检查生成结果

## 注意事项
1. 真人锚图必须先 `split-image` 切分；`video-gen` 调用时传 4 张子图，prompt 中用 `[图1][图2][图3][图4]` 引用，否则触发版权审核失败。**这是与普通视频生成最关键的差异，不可省略。**
2. 台词严格照抄 `参考文本.txt`，禁止改写、概括或用"同上"替代。
3. 每个 `include = true` 的行对应一个 `line_xxx.mp4`；`group_reaction` 跳过但必须在 `rows.json` 留 `skip_reason`，禁止静默丢弃。
4. 角色锚图是强锚点：禁止跨角色复用（孩子 A 不可生成成孩子 B），尾帧续接也仅限同角色内。
5. 全部产物写入 `get-output-dir` 锁定的目录，禁止回写源 session 文件夹。
6. 单条 `video-gen` 超时 ≥ 30 分钟；失败时定位是 prompt 还是参考图问题，重生该条而不是跳过。
