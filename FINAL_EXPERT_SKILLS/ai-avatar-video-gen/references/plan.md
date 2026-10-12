`plan` 用于生成整体演播规划，建议产出 `plan.json`。

`plan.json` 不写最终 video-gen prompt，不替代 `asset.json` 或 `shot.json`。

## 输入来源

生成前必须读取：
- `input.json`
- `requirements.json`
- `story_script.json`

## 规划重点

`plan.json` 必须明确：
- 口播内容如何覆盖 `story_script.json.coverage_points`
- 音频如何分段
- 字幕如何生成
- BGM 如何混入
- 数字人如何保持一致
- 背景如何保持一致
- 哪些段落是 `连续镜头`
- 哪些段落是 `回锚镜头`

## 分段规则

- 每段建议 `4-10` 秒
- 单段不得超过 video-gen 能力上限，通常不超过 `15` 秒
- 首段通常为 `回锚镜头`
- 连续演播可以使用 `连续镜头`
- 每 `2-3` 段安排一次 `回锚镜头`
- 不要把所有历史片段作为参考传给当前段

## plan.json 示例

```json
{
  "target_duration_sec": 60,
  "total_segments": 8,
  "audio_params": {
    "voice_type": "",
    "speed": 1.0,
    "pitch": 1.0,
    "volume": 1.0
  },
  "subtitle_strategy": {
    "required": true,
    "source": "narration_segment_N_timestamp.json",
    "output": "output_dir/subtitles.srt"
  },
  "bgm_strategy": {
    "required": true,
    "style": "",
    "volume_ratio": "人声的20%"
  },
  "visual_continuity_strategy": {
    "global_avatar_anchor": "output_dir/images/avatar.png",
    "primary_avatar_anchor": "output_dir/images/avatar_primary.png",
    "background_anchor": "output_dir/images/background_main.png",
    "previous_reference_policy": "仅连续镜头可使用最近一段尾帧；禁止传全部历史视频",
    "reanchor_policy": "每2-3段回到原始人物锚图和背景锚图"
  },
  "segments": [
    {
      "id": 1,
      "coverage_points": [
        "C1"
      ],
      "text": "",
      "audio_file": "output_dir/audio/narration_segment_1.mp3",
      "timestamp_file": "output_dir/audio/narration_segment_1_timestamp.json",
      "video_file": "output_dir/videos/segment_1.mp4",
      "audio_duration_sec": 0,
      "video_target_duration_sec": 0,
      "shot_type": "回锚镜头"
    }
  ]
}
```
