---
name: image-gen
description: AI图片生成工具，基于豆包Seedream系列和gpt-image-2模型，支持传入提示词、参考图、分辨率、比例、模型、种子等参数生成图片，支持文生图、图生图两种模式。集成了提示词优化重写与多轮迭代创作（自动记录全量日志）。只要用户提到生成图片、AI画图、seedream/gpt生成图片、根据提示词/参考图绘图、自定义分辨率/比例生成海报/插画/头像/设计图等需求时，必须优先使用本技能。在使用生成功能之前，确保prompt已经过本技能内置的提示词优化规则处理。
---

# 图片生成与提示词优化统一技能（image-gen）

**环境依赖:** `Pillow`、`httpx`、`volcenginesdkarkruntime`、`openai`
**⚠️警告: **: 不可使用image_generate这个内置方法，来代替这个技能的调用，否则会导致图片生成失败。任何生成图片的需求，都必须使用本技能。

## 核心功能与工作流程
本技能整合了**提示词重写**、**图片生成**和**多轮日志记录**三大核心功能。处理所有图片生成需求时（无论单轮还是多轮），必须严格按照以下四大步骤依次执行，不得跳过日志记录：

---

### 第一步：分析需求与提示词优化重写 (Prompt Rewriting)

#### 1. 分析用户需求与生成模式
首先分析用户当前的生成需求，判断生成模式：
- **图生图模式**：如果用户prompt中明确提到“参考某张图”、“基于这张图修改”、“用这张图生成”，或用户当前轮次主动传入了图片路径/文件。
- **文生图模式**：否则默认优先使用文生图模式，结合历史生成记录判断是否需要参考历史图片。
- **强制规则**：多轮生成（第n轮，n≥2）时，**除非用户在当前轮次的prompt中明确说明“不需要参考历史图片”、“不要用之前的图”等类似表述，否则必须从1到n-1轮的历史图片中选择 0-3 张合适的图片作为参考输入, 你可以使用 `vision-understanding` 技能分析参考图片的内容来帮助你选择有用的参考图来生成新的图片**。

**⚠️ 图片传入限制（参考图/历史图）：**
1. **图片格式**：支持 jpeg、png、webp、bmp、tiff、gif
2. **宽高比限制**：宽/高的范围需在 [1/16, 16] 之间
3. **最小尺寸**：宽和高均必须大于 14 像素
4. **文件大小**：单张图片不超过 10 MB
5. **最大像素**：单张图片总像素（宽 × 高）不超过 36,000,000 px（相当于 6000x6000 像素）
6. **数量限制**：每次请求最多支持传入 14 张参考图

#### 2. 检查输入内容与辅助分析
- 如果用户提供了参考图片，先调用 `vision-understanding` 技能分析参考图片的内容、风格、色调、构图等信息，作为重写提示词的参考。

#### 3. 提示词质量判断规则
当用户提供的prompt满足以下**所有**条件时，判定为合格，无需重写，直接返回原prompt：
- 明确描述了画面的核心主体（是什么物品/人物/场景）
- 明确描述了主体所处的场景/背景
- 明确描述了整体风格、色调、光线效果
- 明确描述了构图、视角要求
- 包含了需要避免的负面元素（可选）
- 如果用户有提供参考图或者你选择了历史参考图，那么参考图在prompt中要有占位符（比如 `[图1]`、`[图2]` 等）。并且显示地描述参考了参考图中的哪些内容。
*缺少任意一项以上的内容时，判定为需要重写。*

#### 4. 提示词重写规则
重写后的提示词需要包含以下结构，确保生成效果稳定：
```text
[核心主体描述]，放置在[场景/背景描述]中，[光线效果描述]，[色彩/色调描述]，[风格/质感描述]，[构图/视角/分辨率要求]，[需要排除的负面元素]
```
**重写注意事项**：
- 保留用户原prompt中的所有核心需求，不添加用户没有提到的无关内容。
- 补充缺失的必要信息，优先选择符合用户需求场景的通用优质参数（比如电商产品图默认补充"产品突出，光影自然，无多余杂物，高清2k分辨率"）。
- 如果是图生图模式，需要明确说明"参考图主体保持不变，仅调整[修改的内容]"。
- 避免使用模糊的形容词，尽可能具体（比如用"日系清新胶片感，柔和侧光，暖白调"代替"好看的风格"）。

#### 5. 提示词重写示例
**示例1：模糊prompt重写**
- 用户输入：`帮我生成一张咖啡杯的图`
- 重写后输出：白色陶瓷咖啡杯，放置在原木色桌面的棉麻餐垫上，旁边搭配一小盘曲奇饼干和一本摊开的书，窗边的柔和晨光照进来，整体日系清新风格，暖白调，中心构图，产品突出，光影自然，高清2k分辨率，无多余杂物

**示例2：合格prompt无需重写**
- 用户输入：`生成一张黑色运动鞋放在健身房瑜伽垫上的图片，工业风，冷灰色调，硬光，俯拍角度，2k分辨率，不要出现其他健身器材`
- 直接返回原prompt。

**示例3：图生图模式，参考图占位符**
- 用户输入：`根据这张图, 帮我生成一张运动鞋的图片，工业风，冷灰色调，硬光，俯拍角度，2k分辨率，不要出现其他健身器材`
- 重写后输出：白色运动鞋，放置在[图1]的运动垫上，旁边搭配一小盘曲奇饼干和一本摊开的书，窗边的柔和晨光照进来，整体日系清新风格，暖白调，中心构图，产品突出，光影自然，高清2k分辨率，无多余杂物

---

### 第二步：生成图片 (Seedream / GPT-Image-2 API)
根据判定的生成模式和优化后的prompt调用核心生成脚本 `scripts/generate.py`。

#### 1. 技能结构
```
image-gen/
├── SKILL.md (本文件)
├── scripts/
│   └── generate.py (核心生成脚本，所有生成调用都通过此脚本执行)
├── evals/ (测试用例目录，包含不同场景的生成测试prompt)
└── requirements.txt (依赖包列表)
```

#### 2. 支持参数
| 参数名 | 说明 | 可选值 | 默认值 |
|--------|------|--------|--------|
| `--session-key` | **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 | 字符串 | - |
| prompt | 生成图片的提示词（必填） | 任意文本 | - |
| output_file_name | 生成图片的文件名（必填），**仅需填写文件名**（如`20260313_xxx.jpg`），不需要传入完整路径，脚本会自动保存到默认输出目录 | 文件名 | - |
| img_path | 参考图路径（图生图模式使用）。**支持传入多张图片**，多次使用 `--img_path` 参数即可（如 `--img_path path1.jpg --img_path path2.jpg`）。 | 本地图片路径 | None |
| model | 使用的模型 | doubao-seedream-5-0-260128 / gpt-image-2 | doubao-seedream-5-0-260128 |
| resolution | 生成图片分辨率 | 1k/2k/4k 或自定义(如 1920x1080)。gpt-image-2 会自动根据 ratio 映射为满足官方约束条件的合法尺寸（长边<=3840px，16的倍数等） | 2k |
| ratio | 生成图片比例 | 1:1 / 4:3 / 3:4 / 21:9 / 16:9 / 9:16 / 3:2 / 2:3 / None | 16:9 |
| quality | 生成图片质量（仅 gpt-image-2 支持） | low / medium / high / auto | auto |
| max_images | 序列生成最大图片数 | 1-10 | 1 |
| watermark | 是否添加水印(action="store_true") | true / false | false |
| seed | 随机种子（固定可复现生成结果） | 整数 | -1（随机） |
| web_search | 是否启用联网搜索功能(action="store_true") | true / false | false |

**支持的分辨率对应尺寸（像素，长边）**：
- 1k -> 1920
- 2k -> 2560
- 4k -> 3840
- WidthxHeight -> 自定义分辨率（如 2560x1440，**必须使用小写x分隔**）

#### 3. 重要注意事项
- ⚠️ **生成等待与查询**：图片生成可能会占用一段时间。执行命令后，你需要反复查询session（终端输出）来检查结果。如果暂时没有内容返回，请耐心等待，**绝对不要**因为短暂无响应就直接kill掉进程重新执行。
- ⚠️ **多图生成要求（仅 Seedream 系列模型支持，gpt-image-2 每次仅生成 1 张）**：如果需要生成多张图片，必须同时满足两个条件：① 在 `prompt` 参数中显式写明"生成x张图片"；② 设置 `max_images` 参数为对应的数量。二者缺一不可。
- ⚠️ **自定义分辨率格式警告**：自定义分辨率必须严格遵循 `WidthxHeight` 格式，中间的分隔符必须是小写字母 `x`，严禁使用 `*`、`,`、空格或大写 `X`。并将 `--ratio` 设置为 `None`。
- ⚠️ **联网搜索功能增强实效性（仅 doubao-seedream-5-0-260128 支持）**：可以使用联网搜索功能（传入 `--web_search`）来大幅提高生成图片的实效性。当用户的 prompt 里面出现需要一定实时知识或最新资讯的时候，**必须同时满足两个条件**：① 传入 `--web_search` 参数；② 在 `prompt` 中显式地写上“使用联网搜索功能”。只要是涉及一些新的知识，你不认识的一些角色，都需要打开联网搜索功能。例如：**“使用联网搜索功能制作一张上海未来5日的天气预报图”**、**“使用联网搜索功能生成一张最新的苹果手机平面图”**。二者缺一不可。

#### 4. 生成策略与调用示例
- **首轮生成**：
  - 文生图模式：使用优化后的prompt调用生成脚本。
  - 图生图模式：使用用户传入的参考图和优化后的prompt调用生成脚本。
- **多轮生成（第n轮，n≥2）**：
  - 文生图模式：提取1到n-1轮所有历史生成的图片，调用 `vision-understanding` 挑选最适合作为本轮参考的1-3张图片作为输入，结合优化后的prompt调用生成脚本。
  - 图生图模式：优先使用用户当前传入的参考图，再从历史图片中挑选1-2张补充（总数控制在2-3张），结合优化后的prompt调用生成脚本。

**调用示例：文生图（生成多张）**
```bash
python image-gen/scripts/generate.py \
  --session-key "agent:{agent_id}:{session_id}" \
  --prompt "生成2张复杂的海报，主要体现的是小学生班班有歌声的比赛" \
  --output_file_name 202603101950_班班有歌声海报.jpg \
  --resolution 2k \
  --ratio 16:9 \
  --max_images 2
```

**调用示例：图生图（基于参考图）**
```bash
python image-gen/scripts/generate.py \
  --session-key "agent:{agent_id}:{session_id}" \
  --prompt "教师节海报，卡通风格，小学生给老师献花" \
  --output_file_name 202603101950_教师节海报.jpg \
  --img_path references/reference.jpg
```

**调用示例：图生图（传入多张参考图）**
```bash
python image-gen/scripts/generate.py \
  --session-key "agent:{agent_id}:{session_id}" \
  --prompt "根据提供的两张图融合，生成一辆科技感跑车" \
  --output_file_name 202603101950_科技跑车.jpg \
  --img_path references/reference1.jpg \
  --img_path references/reference2.jpg
```

**调用示例：自定义分辨率**
```bash
python image-gen/scripts/generate.py \
  --session-key "agent:{agent_id}:{session_id}" \
  --prompt "赛博朋克风格的未来城市夜景，高画质，细节丰富" \
  --output_file_name 20260313_未来城市壁纸.jpg \
  --resolution 2560x1440 \
  --ratio None
```

**调用示例：使用 gpt-image-2 模型**
```bash
python image-gen/scripts/generate.py \
  --session-key "agent:{agent_id}:{session_id}" \
  --prompt "一只喝咖啡的赛博朋克小猫" \
  --output_file_name 20260313_cybercat.jpg \
  --model gpt-image-2 \
  --resolution 2k \
  --ratio 1:1 \
  --quality high
```

---

### 第三步：多轮迭代与日志记录 (Logging)
生成图片并拿到保存路径后，无论单轮还是多轮，**必须**调用 `logging_manager.py` 脚本记录本轮信息。日志文件（`multi-turn-log.json`）默认保存到图片输出目录的父目录。
⚠️ **注意：如果手动传入 `--session-key`，调用 `logging_manager.py` 时需要与生成图片时保持一致；CodeX/Claude Code 环境会自动识别，不需要传入内容。**

**1. 记录本轮日志**：
```bash
python image-gen/scripts/logging_manager.py --session-key "agent:{agent_id}:{session_id}" add --data '{
  "original_prompt": "[用户输入的原始prompt]",
  "rewritten_prompt": "[image-prompt-rewriter优化后的prompt，若未优化则和original_prompt一致]",
  "prompt_optimization_notes": "[prompt优化点说明，未优化则为空]",
  "params": "[生成参数：分辨率、模型、种子等]",
  "selected_reference_images": "[本轮选择的参考图片列表，首轮为空]",
  "generated_images": "[本轮生成的图片路径/URL列表]",
  "vision_analysis_result": "[vision-understanding返回的分析结果和选图理由]"
}'
```

**2. 获取历史记录**（在进行多轮生成前使用，用于分析和上下文参考）：
```bash
python image-gen/scripts/logging_manager.py --session-key "agent:{agent_id}:{session_id}" get
```

---
