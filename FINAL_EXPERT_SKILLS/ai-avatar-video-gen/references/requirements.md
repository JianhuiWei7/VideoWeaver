`requirements` 用于从 `input.json` 提取硬性指标，并生成 `requirements.json`。

这里只放可执行、可校验的要求，不放大段剧情，不负责具体分段。

## 提取内容

- `target_duration`
- `duration_tolerance`
- `resolution`
- `aspect_ratio`
- `fps`
- `avatar_rules`
- `scene`
- `narration`
- `subtitle`
- `bgm`
- `output_filename`

## 提取规则

- 优先读取 `input.json` 中已经整理好的需求和素材理解
- 用户没有明确提出的字段写 `没有`
- 文视数字人口播任务中，若需求提到“底部同步白色中文字幕”，`subtitle.required` 必须为 `true`
- `output_filename` 固定为 `final_video.mp4`

## requirements.json 示例

```json
{
  "target_duration": 60,
  "duration_tolerance": 5,
  "resolution": "1080P",
  "aspect_ratio": "9:16",
  "fps": "没有",
  "avatar_rules": {
    "source": "参考视频1",
    "position": "正面居中",
    "posture": "自然端正，平视镜头",
    "lip_sync": true,
    "extra_motion": "无夸张多余动作"
  },
  "scene": {
    "description": "",
    "lighting": "",
    "style": ""
  },
  "narration": {
    "language": "普通话",
    "speed_wpm": 190,
    "tone": "",
    "no_stutter_or_misread": true
  },
  "subtitle": {
    "required": true,
    "position": "底部",
    "color": "白色",
    "sync": "与口播精准同步"
  },
  "bgm": {
    "required": true,
    "style": "",
    "volume_ratio": "人声的20%"
  },
  "output_filename": "final_video.mp4"
}
```
