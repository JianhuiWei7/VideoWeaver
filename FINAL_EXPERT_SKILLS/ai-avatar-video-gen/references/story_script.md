`story_script` 用于确定最终口播主线，建议产出 `story_script.json`。

即使原文已经足够，也必须生成 `story_script.json`，此时 `rewrite_policy` 写 `normalized_only`。

通用文视口播的默认动作是“规范化文案”，不是无条件扩写。

## 生成规则

- 以 `input.json.script_source_decision.selected_text` 为主线
- 默认做规范化：清理重复、补标点、统一口语节奏、按语义分段、提取覆盖点
- 若原文已足够，保持原意，做轻微规范化即可
- 扩写触发强度较弱；只有文本自然朗读时长明显短于目标时长、缺少必要承接，或无法支撑每个 shot 的 `lines` 时才轻量扩写
- 扩写只补充解释、过渡、例子和收束，不改变主题和观点
- 每个后续 shot 都必须有对应 `lines`
- 不要把未选为主线的冲突文本混入最终口播

## 时长估算

按 `requirements.json.narration.speed_wpm` 估算：

```text
估算秒数 = 字数 / 语速(字/分钟) * 60
```

若目标为 `60±5` 秒，最终脚本自然朗读应尽量落在 `55-65` 秒附近；但不得为了凑时长大幅偏离选定口播主线。

## story_script.json 示例

```json
{
  "script_source": "参考文本",
  "rewrite_policy": "normalized_only",
  "target_duration_sec": 60,
  "estimated_duration_sec": 60,
  "final_script": "",
  "coverage_points": [
    {
      "id": "C1",
      "summary": "",
      "source_quote_or_paraphrase": ""
    }
  ],
  "normalization_notes": [
    ""
  ],
  "expansion_notes": [
    ""
  ]
}
```
