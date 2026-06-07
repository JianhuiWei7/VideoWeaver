---
name: automatic-speech-recognition
description: 字节跳动火山引擎ASR自动语音识别工具：基于HTTP API将音视频文件转换为文本，支持本地文件/URL输入，输出识别结果JSON/纯文本/SRT字幕。当用户要求从音频或视频识别文本时，必须立即调用此技能。本技能用于把用户提供的音视频文件通过火山引擎ASR API合成为文本内容，支持两种输入方式：本地音视频文件、在线音视频URL。
---

### 第一步：执行语音识别
调用脚本执行ASR识别并输出结果。

1. 参数说明
| 参数名 | 说明 |
|--------|------|
| `--session-key` | **(可选；OpenClaw 必填)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |
| `--file-path` | **(二选一)** 本地音视频文件路径，支持mp3/wav/mp4等常见格式 |
| `--file-url` | **(二选一)** 在线音视频文件URL |
| `--output` | 输出识别结果文件名，可选。将自动保存在当前会话的输出目录下，支持`.json`（完整结果）/`.txt`（仅识别文本）/`.srt`（字幕文件） |
| `--enable-itn` | 是否启用文本规范化，默认true |
| `--enable-punc` | 是否启用标点符号，默认true |
| `--enable-ddc` | 是否启用语气词识别，默认true |
| `--enable-speaker-info` | 是否启用说话人分离，默认false |
| `--show-timestamps` | 是否在控制台和纯文本输出中展示每一句的时间戳，默认false |
| `--verbose` | 是否打印调试信息，默认false |

2. 典型使用案例

**案例1：识别本地音频，输出到控制台**
```bash
python automatic-speech-recognition/scripts/recognize.py --session-key "agent:{agent_id}:{session_id}" --file-path "luise.mp3"
```

**案例2：识别本地视频中的音频，保存字幕结果**
```bash
python automatic-speech-recognition/scripts/recognize.py --session-key "agent:{agent_id}:{session_id}" --file-path "video.mp4" --output "result.srt"
```

**案例3：识别在线音视频URL**
```bash
python automatic-speech-recognition/scripts/recognize.py --session-key "agent:{agent_id}:{session_id}" --file-url "https://example.com/audio.mp3"
```

**案例4：识别音频，并在控制台及文本输出中附带时间戳**
```bash
python automatic-speech-recognition/scripts/recognize.py --session-key "agent:{agent_id}:{session_id}" --file-path "luise.mp3" --show-timestamps --output "result.txt"
```

3. 执行规范（必须遵守）
- **鉴权与密钥管理**：任何时候不得把 `ASR_TOKEN` 写入代码、日志或对外输出。
- **成功判定**：脚本退出码为0且返回识别结果，才算识别成功。
- **失败处理**：若服务端返回错误消息，必须把错误信息原样返回给用户，并提示检查输入参数是否有效。

---

### 第二步（可选, 如果没有此需求, 可以直接跳过）：将字幕硬编码到视频中
如果用户需要生成带有硬字幕的视频，调用 `embed_subtitles.py` 脚本，将生成的 `.srt` 文件烧录回原视频中。

1. 参数说明
| 参数名 | 说明 |
|--------|------|
| `--session-key` | **(可选；OpenClaw 必填)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |
| `--video` | **(必填)** 输入的原视频文件路径（如 `.mp4`） |
| `--srt` | **(必填)** 生成的 `.srt` 字幕文件路径 |
| `--output` | **(可选)** 输出的视频文件名（不含路径）。生成的新视频将固定保存在当前会话的输出目录下。如果不指定，默认生成 `原视频名_with_subtitles.mp4` |

2. 使用案例
```bash
python automatic-speech-recognition/scripts/embed_subtitles.py --session-key "agent:{agent_id}:{session_id}" --video "video.mp4" --srt "result.srt" --output "video_带字幕.mp4"
```

---





