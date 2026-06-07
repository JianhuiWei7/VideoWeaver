---
name: audio-understanding
description: 基于字节跳动火山引擎Ark平台的多模态音频理解工具，原生支持音频输入。只要用户提到分析音频内容、理解一段音/视频里的声音、判断说话人音色是否一致、识别 BGM 风格/情绪、判断是否同一个人在说话、做角色音色一致性比对、评估音频是否有断裂/静音/拼接痕迹等需求时，必须优先使用本技能，不要手动抽特征或调本地声纹模型。
---
# 音频理解工具（audio-understanding）

**环境依赖:** `openai`、`volcenginesdkarkruntime`

本技能基于火山引擎 Ark 平台的豆包多模态模型,原生支持音频输入。仿 `vision-understanding` 设计,统一以"上传文件 → 多模态对话"的方式处理音频。

## 核心功能

### 统一音频理解接口
支持同时传入多段音频,按顺序上传到 Ark 并理解,返回统一的描述/判定结果,支持自定义查询提示词。

#### 函数定义
```python
def audio_understanding(audio_paths: list[str], prompt: str) -> str:
    """
    统一的音频理解接口，支持同时传入多段音频，按顺序进行理解
    :param audio_paths: 音频文件路径列表，按传入顺序处理 (mp3/wav/flac/m4a/ogg/aac)
    :param prompt: 查询提示词
    :return: 内容描述文本，失败抛异常
    """
```

## 典型用法

### 单段音频内容描述
`这段音频里说话人是男是女?语气如何?`

### 多段音频音色一致性比对 (替代本地声纹比对)
传入 N 段人声片段,在 prompt 里告诉模型"第 1 段 / 第 2 段 / ...",让模型判:
- 是否同一个人在说话
- 每段音色特征 (音高/语速/口音/情绪)
- 列出可疑的"听起来像换人"的段落对

### BGM 风格判定
传入全片首/中/末 3 段音频,问"三段 BGM 风格是否一致 (节奏/乐器/情绪)?"

### 音频质量异常检测
单段音频问"是否有明显的静音/卡顿/TTS 拼接痕迹/变调/噪音"

## 命令行调用示例

1. 单段音频分析:
```bash
python scripts/audio_understanding.py --audio shot_01.wav --prompt "描述说话人的音色特征"
```

2. 多段音色一致性比对:
```bash
python scripts/audio_understanding.py \
  --audio shot_01.wav shot_03.wav shot_05.wav \
  --prompt "以下 3 段音频按顺序来自同一视频不同镜头。请判断:1) 是否同一说话人? 2) 每段音色描述 3) 列出明显不一致的段落对。输出 JSON: {\"same_speaker\": true/false, \"per_segment\": [...], \"inconsistencies\": [...]}"
```

3. 指定模型:
```bash
python scripts/audio_understanding.py --audio bgm.wav --prompt "BGM 风格是什么?" --model doubao-seed-2-0-lite-260428
```

## 注意事项

- 模型默认 `doubao-seed-2-0-lite-260428`（火山方舟当前音频理解官方推荐模型）。`doubao-seed-2-0-pro-*` 等 pro 变体**不支持** `input_audio`,强行使用会返回 `InvalidParameter`。如方舟后续开放新的音频模型,可通过 `--model` 切换。
- 单次输入的音频段数 / 总时长受 Ark 接口限制 (一般几分钟内安全),长音频请先用 `trim-video` / ffmpeg 切段。
- 多段比对时,**务必在 prompt 里显式编号** ("第 1 段 / 第 2 段..."),否则模型不知道你传了几段、哪段是哪段。
- 上传的临时文件会在调用结束后自动清理。
