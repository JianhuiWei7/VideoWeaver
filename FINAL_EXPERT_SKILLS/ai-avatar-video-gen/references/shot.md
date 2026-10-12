`shot` 用于把 `plan.json` 拆成可执行的视频生成段，建议产出 `shot.json`。

`shot.json` 是内部执行表，不要求用户提前提供参考分镜。

## 输入来源

生成前必须读取：
- `requirements.json`
- `story_script.json`
- `plan.json`
- `asset.json`
- `input.json`

## 字段结构

```json
{
  "shots": [
    {
      "shot_id": 1,
      "segment_id": 1,
      "description": "",
      "duration": 6,
      "lines": "",
      "coverage_points": [
        "C1"
      ],
      "shot_type": "回锚镜头",
      "require_assets": [
        "人物三视图",
        "人物主锚图",
        "主背景图"
      ],
      "actual_asset_paths": [
        "output_dir/images/avatar.png",
        "output_dir/images/avatar_primary.png",
        "output_dir/images/background_main.png"
      ],
      "audio_file": "output_dir/audio/narration_segment_1.mp3",
      "timestamp_file": "output_dir/audio/narration_segment_1_timestamp.json",
      "video_file": "output_dir/videos/segment_1.mp4",
      "subtitle_required": true,
      "previous_visual_reference": "无",
      "is_completed": false
    }
  ]
}
```

## 字段要求

- `shot_id`：从 `1` 开始递增
- `segment_id`：对应 `plan.json.segments[].id`
- `description`：说明当前段讲什么、画面怎么呈现
- `duration`：以当前段实际音频时长为准
- `lines`：当前段旁白，默认必填
- `coverage_points`：对应 `story_script.json.coverage_points`
- `shot_type`：只能是 `连续镜头` 或 `回锚镜头`
- `require_assets`：写资产名称
- `actual_asset_paths`：写真实路径，必须来自 `asset.json`
- `audio_file`：当前段口播音频
- `timestamp_file`：当前段时间戳
- `video_file`：当前段视频，固定为 `output_dir/videos/segment_N.mp4`
- `subtitle_required`：与 `requirements.json.subtitle.required` 一致
- `previous_visual_reference`：连续镜头可写最近一段尾帧；回锚镜头写 `无`
- `is_completed`：初始化为 `false`

## 执行规则

- 默认每个 shot 都必须有 `lines`
- 默认每个 shot 都必须有 `audio_file` 和 `timestamp_file`
- 默认每个 shot 都必须有 `video_file`
- `连续镜头` 才允许带最近一段尾帧
- `回锚镜头` 不带上一段视频，回到原始人物和背景锚点
- 不要把前面所有已生成视频一起传给当前 shot
- 字幕若被要求，必须跟随每段时间戳生成
