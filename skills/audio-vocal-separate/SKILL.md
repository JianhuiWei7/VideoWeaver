---
name: audio-vocal-separate
description: "【人声与背景音分离工具】基于 Demucs (htdemucs) 把一段音频/视频里的人声轨从 BGM/伴奏中分离出来,产出 vocals.wav (干净人声) + bgm.wav (无人声背景)。当用户要求分离人声/伴奏、去 BGM、提取干净人声、做声纹比对前的预处理、或要单独评估 BGM 风格时,必须立即调用此技能。"
---

# 人声/BGM 分离 (audio-vocal-separate)

基于 Meta 开源 **Demucs (htdemucs)** 模型,把音频/视频文件中的人声轨从背景音乐 + 伴奏中分离开。

## 前置依赖
本 skill **必须在项目 uv venv 中执行**:
```bash
```
调用时统一用 `.venv/bin/python`:
```bash
/Users/tanjie/project/claude_baseline/.venv/bin/python scripts/separate.py ...
```
首次运行会下载 Demucs 模型 (~80 MB) 到 `~/.cache/torch/hub/`,之后离线可用。

## 输入
- 任意 `wav` / `mp3` / `flac` / `m4a` / `mp4`,有视频也行(只取音轨)。
- Demucs 内部统一重采样到 44.1kHz stereo,无需提前处理。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--audio_path` | 必填 | 输入音/视频路径 |
| `--model` | `htdemucs` | `htdemucs` (默认,平衡) / `htdemucs_ft` (更准但慢 4x) / `mdx_extra` |
| `--two_stems` | `vocals` | `vocals` (默认: 只出人声/BGM 两轨,最快) / `all` (出 4 轨: vocals/drums/bass/other) |
| `--device` | `auto` | `auto` (macOS 自动 mps, 否则 cpu) / `cpu` / `mps` / `cuda` |
| `--format` | `wav` | 输出格式: `wav` (无损) / `mp3` (--mp3-bitrate 192) |
| `--mp3_bitrate` | `192` | 仅当 `--format mp3` 生效 |
| `--session-key` | 可选 | 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入session-key；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |

## 输出

`--two_stems vocals` 模式(默认):
```
{output_dir}/
├── vocals.wav            # 干净人声 (做声纹比对 / 词级 ASR 用)
├── bgm.wav               # 无人声背景 (评估 BGM 风格 / 音乐相似度用)
└── separate_info.json    # {model, two_stems, device, durations, paths}
```

`--two_stems all` 模式:
```
{output_dir}/
├── vocals.wav
├── drums.wav
├── bass.wav
├── other.wav
└── separate_info.json
```

## 使用示例

### 分离人声 (最常用,O5.b 预处理)
```bash
python scripts/separate.py --audio_path /path/to/audio.mp3
# 产物: <session_out>/audios/audio_separated/vocals.wav + bgm.wav
```

OpenClaw 环境需要传入 session-key:
```bash
python scripts/separate.py \
  --audio_path /path/to/audio.mp3 \
  --session-key "agent:{agent_id}:{session_id}"
```

### 直接处理 video
```bash
python scripts/separate.py \
  --audio_path /path/to/final.mp4
```

### Mac M 系芯片 MPS 加速
```bash
python scripts/separate.py --audio_path audio.mp3 --device mps
# 默认 auto 已会选 mps; 如要强制走 CPU 用 --device cpu
```

### 4 轨完整分离 (做音乐分析)
```bash
python scripts/separate.py --audio_path audio.mp3 --two_stems all
```

## 性能参考 (macOS M-series, CPU)

| 输入时长 | htdemucs 单声道 | htdemucs MPS 加速 |
|---|---|---|
| 30s | ~25s | ~10s |
| 60s | ~50s | ~20s |

## 在 output-eval 里的典型链路

```
final.mp4
  → split-audio → audio.mp3
  → audio-vocal-separate (本 skill) → vocals.wav + bgm.wav
  → voiceprint-compare 比对 vocals.wav 跨 shot 一致性
  → vision-understanding / CLAP 评估 bgm.wav 风格
```

## 设计原则
- **幂等**: 若 `output_dir/vocals.wav` 已存在且未传 `--overwrite`,跳过分离直接读 sidecar
- **失败回退**: Demucs 加载/推理出错时,在 `separate_info.json` 标记 `success=false`,下游能感知
