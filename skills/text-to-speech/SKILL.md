---
name: text-to-speech
description: OpenSpeech（字节跳动/火山）TTS V3 语音合成工具：只支持文本输入，并选择已有音色/音频 ID 将文本合成为语音文件；不能随意传入音频文件、音频 URL 或参考音频。支持参数化音色/语速/音量/音高，可选返回字级时间戳。当需要生成台词、旁白或 speech 时可以使用该技能。
---

# 文本转语音统一技能（text-to-speech 火山TTS V3接口版本）

**环境依赖:** `requests`

## 核心功能与工作流程
本技能用于把用户提供的文本通过 OpenSpeech TTS V3 单向流接口（`/api/v3/tts/unidirectional`）合成为音频文件。该接口为HTTP流式接口，支持长文本合成，稳定高效，支持连接复用。

⚠️ 输入限制：本技能只支持文本输入。音色必须通过已有的 `--voice-type` 音色/音频 ID 选择，不能传入任意音频文件、音频 URL、参考音频或用户上传的声音来生成/复刻音色。

## 环境配置
支持两种鉴权方式（二选一即可）：

```bash
# 方式1：API Key鉴权（推荐）
export AUDIO_GEN_API_KEY="your-volcengine-api-key"

# 方式2：AppID + Token鉴权
export AUDIO_GEN_APPID="your-app-id"
export AUDIO_GEN_TOKEN="your-access-token"
```
密钥可在火山引擎控制台获取。

## 核心参数说明
| 参数名 | 说明 |
|--------|------|
| `--session-key` | **(可选；OpenClaw 必填)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |
| `--text` | **(Required)** 需要合成的文本；这是唯一支持的内容输入形式 |
| `--voice-type` | **(Required)** 已有音色/发音人/音频 ID（[音色列表](可以访问text-to-speech/references/voice_type_list.md; 或者是url: https://www.volcengine.com/docs/6561/1257544?lang=zh)）。只能选择已有 ID，不能传入音频文件或音频 URL |
| `--output` | 输出音频文件名（例如 `out.mp3` / `out.wav`）。默认 `out.mp3`。将自动保存在当前会话的输出目录下 |
| `--encoding` | 输出编码：`mp3` / `wav` / `pcm` / `opus`。默认从 `--output` 扩展名推断；若无扩展名则默认 `mp3` |
| `--speed` | 语速倍率，默认 `1.0`，范围 [0.5, 2.0] |
| `--volume` | 音量倍率，默认 `1.0`，范围 [0.5, 2.0] |
| `--pitch` | 音高倍率，默认 `1.0`，范围 [0.5, 2.0] |
| `--sample-rate` | 采样率，默认 24000，可选 8000/16000/24000/48000 |
| `--resource-id` | 资源ID，默认 `seed-tts-2.0`，用于选择模型版本和计费方式 |
| `--output-timestamp` | 可选，时间戳输出JSON文件名，如提供则返回字级时间戳。将自动保存在当前会话的输出目录下 |
| `--format` | 兼容参数：等价于 `--encoding`（若同时传入，以 `--encoding` 为准） |
| `--verbose` | 是否打印调试信息 |

### Resource ID 说明
| Resource ID | 说明 | 对应计费商品 |
|-------------|------|--------------|
| `seed-tts-2.0` | 豆包语音合成模型2.0（推荐） | 语音合成2.0字符版 |
| `seed-tts-1.0` | 豆包语音合成模型1.0 | 语音合成1.0字符版 |
| `seed-tts-1.0-concurr` | 豆包语音合成模型1.0并发版 | 语音合成1.0并发版 |
| `seed-icl-2.0` | 声音复刻2.0版本 | 声音复刻2.0字符版 |
| `seed-icl-1.0` | 声音复刻1.0版本 | 声音复刻1.0字符版 |
| `seed-icl-1.0-concurr` | 声音复刻1.0并发版 | 声音复刻1.0并发版 |

## 典型使用案例

### 案例1：基础用法
```bash
python text-to-speech/scripts/generate.py \
  --session-key "agent:test:test" \
  --text "你好，我是你的语音助手。" \
  --voice-type "zh_female_vv_uranus_bigtts" \
  --output "hello.mp3"
```

### 案例2：生成音频并返回时间戳
```bash
python text-to-speech/scripts/generate.py \
  --session-key "agent:test:test" \
  --text "这是一段带有时间戳的测试语音，每个字都会有对应的时间信息。" \
  --voice-type "zh_female_xiaohe_uranus_bigtts" \
  --output "narration.wav" \
  --output-timestamp "narration_timestamp.json"
```

时间戳输出格式示例：
```json
{
  "sentences": [
    {
      "text": "这是一段测试语音。",
      "words": [
        {"word": "这", "startTime": 0.1, "endTime": 0.2, "confidence": 0.98},
        {"word": "是", "startTime": 0.2, "endTime": 0.3, "confidence": 0.99},
        ...
      ]
    }
  ]
}
```

### 案例3：自定义参数 + 使用1.0模型
```bash
python text-to-speech/scripts/generate.py \
  --session-key "agent:test:test" \
  --text "这是调整语速、音量、音高后的语音，使用1.0版本模型。" \
  --voice-type "zh_male_m191_uranus_bigtts" \
  --output "custom.mp3" \
  --speed 1.2 \
  --volume 1.3 \
  --pitch 1.05 \
  --resource-id "seed-tts-1.0" \
  --verbose
```

### 案例4：生成16k采样率的pcm文件
```bash
python text-to-speech/scripts/generate.py \
  --session-key "agent:test:test" \
  --text "测试pcm输出" \
  --voice-type "zh_male_m191_uranus_bigtts" \
  --output "test.pcm" \
  --sample-rate 16000
```

### 案例5：使用已有女声音色 ID 生成指定文案
生成内容为“这是一段语音示例。”的音频，使用已有通用女声 ID（Vivi 2.0）。通常语速下该文案时长约在 1-2 秒左右。更多声音请参考[音色列表](可以访问text-to-speech/references/voice_type_list.md; 或者是url: https://www.volcengine.com/docs/6561/1257544?lang=zh)。
```bash
python text-to-speech/scripts/generate.py \
  --session-key "agent:test:test" \
  --text "这是一段语音示例。" \
  --voice-type "zh_female_vv_uranus_bigtts" \
  --output "ref_female.mp3"
```

### 案例6：使用已有男声音色 ID 生成指定文案
生成相同文案的音频，使用已有通用男声 ID（云舟 2.0）。
```bash
python text-to-speech/scripts/generate.py \
  --session-key "agent:test:test" \
  --text "这是一段语音示例。" \
  --voice-type "zh_male_m191_uranus_bigtts" \
  --output "ref_male.mp3"
```

## 执行规范
- **输入边界**：只接受 `--text` 文本输入和已有 `--voice-type` ID；不要尝试上传、传入或引用任意音频文件作为音色/参考音频。
- **鉴权与密钥管理**：任何时候不得把 `AUDIO_GEN_API_KEY` 写入代码、日志或对外输出。
- **成功判定**：脚本退出码为 0 且输出文件存在、大小 > 0，才算生成成功。
- **失败处理**：若服务端返回错误消息，会返回错误码和logid，方便定位问题。
- **连接复用**：默认使用requests.Session复用TCP连接，服务端keep-alive时间为1分钟，适合批量合成场景。
