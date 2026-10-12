---
name: brand-promo-video-gen
description: 品牌宣传视频生成工具。输入可以包含需求、参考文本、参考图片、参考视频、参考音频；先整理为 input.json，再提取 requirement.json，再生成 plan.json、asset.json 和 shot.json，最后生成符合品牌调性、叙事连贯、音画统一的品牌宣传片。适用于需要生成品牌宣传片、产品品牌广告、品牌形象短片，并要求品牌元素、产品、场景、风格和音频保持高度一致的任务。
---

# Brand Promo Video Gen

## Overview
本技能适用于生成品牌宣传片。

1. `input.json`
2. `requirement.json`
3. `plan.json`
4. `asset.json`
5. `shot.json`
6. 视频生成与复核
7. 合成导出

这版技能的核心原则是：
- `input.json` 负责详细整理输入
- `requirement.json` 只负责硬性指标
- `plan.json` 先做完整叙事和整体结构
- `asset.json` 先补齐品牌片真正需要反复引用的稳定资产
- `shot.json` 再拆成逐镜头执行表
- 视频生成阶段动态构造 prompt，不在前面的 JSON 中写死完整生成提示词

## 前置阅读
开始前先按顺序阅读以下 reference：
- `references/input.md`
- `references/requirment.md`
- `references/plan.md`
- `references/asset.md`
- `references/shot.md`
- `references/brand-promo-shot-planning.md`

主 `SKILL.md` 只负责定义总流程；具体字段、提取规则和简化示例以这些 reference 为准。

## Core Dependencies
- **get-output-dir**：获取输出目录，所有文件必须写在这里
- **vision-understanding / video-understanding**：理解参考图片、参考视频和最终生成结果
- **image-gen**：补齐品牌标准资产、产品标准资产、风格参考资产
- **video-gen**：逐段生成有声视频
- **split-audio**：必要时从上一段视频中分离音频，作为后续段落音频连续性参考
- **merge-video**：合并最终视频
- **change-fps / resize-video-resolution**：按需调整输出规格
- **automatic-speech-recognition**：必要时为有人声视频补字幕或校对台词

## Output Layout
在开始写任何文件前，先调用 `get-output-dir`，并在输出目录下固定这些产物：
- `output_dir/input.json`
- `output_dir/requirement.json`
- `output_dir/plan.json`
- `output_dir/asset.json`
- `output_dir/shot.json`
- `output_dir/videos/final.mp4`

所有中间文件也必须放在 `output_dir` 下。

## Workflow

### Step 0: 获取输出目录
1. 调用 `get-output-dir`
2. 锁定输出目录
3. 后续所有 JSON、图片、视频、音频、日志都写到该目录下

### Step 1: 生成 input.json
1. 严格参考 `references/input.md`
2. 先整理原始输入，常见输入包括：
3. 对不同输入做对应处理：
4. 品牌宣传片输入阶段不要急于把卖点直接映射成镜头，而要先整理：
5. `input.json` 负责详细整理输入，不负责下硬性执行结论

### Step 2: 生成 requirement.json
1. 严格参考 `references/requirment.md`
2. `requirement.json` 只提取硬性指标，不放大段原始剧情
3. 常见硬性指标包括：
4. 若用户或输入里没有明确给出，对应字段直接写 `没有`
5. 不得把文学化主题、抽象情绪、长段剧情直接写进 `requirement.json`

### Step 3: 生成 plan.json
1. 严格参考 `references/plan.md`
2. `plan.json` 必须先满足 `requirement.json`，再参考 `input.json`
3. 优先级固定为：
   - `requirement.json`
   - `input.json`
4. `plan.json` 主要负责整体规划
5. 品牌宣传片默认应按连续视频规划，而不是按多个独立短广告规划
6. 默认避免按总时长机械均分段落，应优先根据叙事推进自然分配时长
7. 品牌宣传片默认采用全程旁白方案。除非用户明确要求无旁白、纯视觉表达、仅保留字幕或仅使用背景音乐，否则 `plan.json` 中应默认规划完整音频主线和分段旁白推进
8. 不得在 `plan.json` 里擅自修改 `requirement.json` 里的硬指标

### Step 4: 生成 asset.json
1. 严格参考 `references/asset.md`
2. `asset.json` 负责评估资产覆盖度并补齐品牌片真正需要复用的标准资产
3. 必须先判断：
   - 现有素材能覆盖哪些叙事段落
   - 哪些品牌元素和产品状态是缺失的
   - 哪些资产需要全片复用
   - 哪些资产只在局部段落使用
4. 品牌宣传片资产阶段优先补齐：
   - 品牌核心资产
   - 产品标准资产
   - 场景基础资产
   - 续写锚点资产
   - 过渡桥接资产
5. 不要为每个镜头都单独补一份资产，应优先建立少量但稳定的 canonical assets
6. 根据 `asset.json` 中识别出的缺口与资产规划，补充生成对应的资产文件，并统一保存到输出目录下的 `images/` 文件夹中，供后续 `shot.json` 和视频生成阶段引用。

### Step 5: 生成 shot.json
1. 严格参考 `references/shot.md`
2. `shot.json` 必须同时满足：
   - `requirement.json`
   - `plan.json`
   - `asset.json`（若存在）
   - `input.json`
3. `shot.json` 采用 `shots` 数组结构，每个镜头至少应包含：
   - `shot_id`
   - `description`
   - `duration`
   - `lines`
   - `subtitle`
   - `shot_type`
   - `require_assets`
   - `is_completed`
4. 每个镜头都必须明确对应一个卖点、品牌信息、体验节点或叙事任务
5. 品牌宣传片中的镜头拆解应体现承接、递进、桥接和收束关系，避免把每个卖点拆成独立广告镜头
6. 若任务采用默认全程旁白方案，应尽量让 `lines` 与镜头一一对应推进
7. 若 `shot_type = 连续镜头`，后续正式生成时默认应参考上一镜或上一段视频继续生成

### Step 6: 逐镜头 / 逐段视频生成
1. 视频生成前，必须重新读取：
   - `requirement.json`
   - `plan.json`
   - `asset.json`
   - `shot.json`
2. 视频生成必须先服从叙事结构，再根据模型能力组织技术分段；不得让单次生成时长限制反过来决定故事结构
3. 逐镜头生成时，必须引入：
   - 全局品牌 / 产品 / 风格参考资产
   - 必要时的上一镜尾帧或上一段视频
   - 必要时的上一段音频参考
4. 若当前镜头或当前段不是首段，且存在连续性要求：
   - 视觉上应优先参考前一段视频
   - 音频上应优先参考前一段约 `5-10s` 的音乐或环境音氛围
   - 必要时使用 `split-audio` 从前段视频中提取音频参考
5. 若包含台词 / 旁白，必须在视频提示词中明确写出：
   - 说话人属性
   - 音色
   - 语言
   - 台词内容
6. 若要求展示文案 / 字幕，必须在视频提示词中明确写出内容与展现方式
7. 每段生成后都要用 `vision-understanding` 做基础一致性检查，至少检查：
   - 品牌元素是否准确
   - 画面风格是否统一
   - 是否满足与上一段的连续性
   - 是否存在素材拼接感过强、动作重复、构图重复的问题
8. 若检查不通过，应优先根据当前段的连续性要求和参考输入重生成，而不是直接跳到下一段
9. 每个镜头或每个技术段完成后，应及时更新 `shot.json` 中的完成状态

### Step 7: 合成与导出
1. 读取 `shot.json` 检查所有镜头是否已完成
2. 逐条检查：
   - `requirement.json` 的硬指标是否满足
   - `plan.json` 的叙事主线是否完成
   - `shot.json` 中的卖点和镜头是否全部覆盖
3. 按要求拼接并导出最终视频：
   - `output_dir/videos/final.mp4`
4. 对最终视频使用 `vision-understanding` 做最终理解检查；若不合格，则定位到对应段落返工

## Important Rules
1. 所有输出都必须放在 `get-output-dir` 返回的输出目录下
2. 必须先生成 `input.json`
3. 必须在 `input.json` 之后生成 `requirement.json`
4. 必须先有 `requirement.json`，再生成 `plan.json`
5. 必须先有 `plan.json`，再生成 `asset.json`
6. 必须先有 `asset.json`，再生成 `shot.json`
8. `plan.json` 不得违反 `requirement.json`
9. `asset.json` 只负责资产诊断与补齐，不代替 `plan.json` 或 `shot.json`
10. `shot.json` 不得违反 `requirement.json`、`plan.json` 和 `asset.json`
11. 若没有对应输入、没有对应参考、没有明确要求，就直接写 `没有`
12. 不得为了补齐字段而擅自脑补不存在的输入或参考
