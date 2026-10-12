`asset` 用于生成正式视频前的稳定资产，建议产出 `asset.json`。

当前只重点处理：
- `人物资产`
- `背景资产`

## 必须使用的技能

- 先调用 `get-output-dir`
- 从参考视频提取 `3-5` 帧代表性人物帧
- 使用 `image-gen` 生成人物三视图锚图
- 必要时使用 `image-gen` 生成背景锚图

## 人物资产

若存在参考视频，必须先从参考视频提取代表性人物帧：
- 正面清晰帧
- 轻微侧向帧
- 说话状态帧
- 全身或半身构图帧

固定产物：
- `output_dir/images/avatar_primary.png`
- `output_dir/images/avatar.png`

`avatar.png` 是单张三视图合成图，包含同一数字人的正面、左侧、右侧三个视角。

固定 `image-gen` prompt：

```text
参考输入的3-5张数字人人物帧，生成同一人物的三视图参考图。画面为一张干净的三视图设定图，包含正面、左侧、右侧三个半身视角，三者保持同一人物身份、发型、五官、服装、比例和画风一致。白色背景，无字幕，无水印，无额外人物，不改变人物年龄、气质和服装。
```

## 背景资产

若需求指定虚拟演播背景，建议生成：
- `output_dir/images/background_main.png`

背景应符合需求中的场景描述，并服务于数字人口播，不要喧宾夺主。

## asset.json 示例

```json
{
  "人物资产": {
    "参考视频": "",
    "参考帧": [
      "output_dir/images/avatar_frame_1.png",
      "output_dir/images/avatar_frame_2.png",
      "output_dir/images/avatar_frame_3.png"
    ],
    "主锚图": "output_dir/images/avatar_primary.png",
    "三视图": "output_dir/images/avatar.png",
    "安全锚图": "没有",
    "人物role描述": "参考图中的人物形象作为数字人口播讲解人"
  },
  "背景资产": {
    "主背景图": "output_dir/images/background_main.png",
    "背景描述": ""
  }
}
```
