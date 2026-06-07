import json


expert_skill_creator_prefix = """
使用video-skill-creator技能, [读取这个技能下面的所有资料, 包括references/下面的.md文件和SKILL.md]参考现在与视觉生成/理解/处理相关的skills来创建新的skill工作流。skill叫做{skill_name}; 生成好的skill要放在~/.openclaw/workspace/composition_skills_expert目录下; 不要调用subagent或session_spawn来创建skill; 生成的skill是用来完成一系列视频生成任务的, 所以skill description需要和任务的输入内容和要求匹配, 来达到任务与技能的匹配; 整体要求: 生成的视频需要跟随用户指令与需求; 视频的剧情和逻辑需要保持连贯; 准确地使用用户提供的参考资料, 如果有的话, 比如图片，音频，视频，文本等; 多次出现的人物, 场景, 物体等, 要在整个视频中视觉上保持一致; 同一个说话的音色, 背景音乐也需要在整个视频中保持一致。
"""

vanilla_skill_creator_prefix = """
使用skill-creator技能, 参考现在与视觉生成/理解/处理相关的skills来创建新的skill工作流。skill叫做{skill_name}; 生成好的skill要放在~/.openclaw/workspace/composition_skills_vanilla目录下; 不要调用subagent或session_spawn来创建skill。 生成的skill是用来完成一系列视频生成任务的, 所以skill description需要和任务的输入内容和要求匹配, 来达到任务与技能的匹配; 整体要求: 生成的视频需要跟随用户指令与需求; 视频的剧情和逻辑需要保持连贯; 准确地使用用户提供的参考资料, 如果有的话, 比如图片，音频，视频，文本等; 多次出现的人物, 场景, 物体等, 要在整个视频中视觉上保持一致; 同一个说话的音色, 背景音乐也需要在整个视频中保持一致。
"""


EVAL_TASK_PREFIX = "使用skill: process-eval来对你以下接收到的内容进行评估。在评估时: 1. 不要调用subagent或session_spawn; 2. 当最终结果完全生成好的时候再回答我，不要再生成的中途回答我. 所有审批都通过,不需要问用户来获取审批; 3. 你输出的评估内容，需要先通过session_status来获取session_key. 然后调用scripts/write_to_json.py来写入。"


VIDEO_GENERATION_TASK_PREFIX = "按照要求生成视频。在执行任务时: 1. 不要调用subagent或session_spawn; 2. 先读取'task-tracker'这个skill, 在执行任务时配合'task-tracker'这个技能来持续进行你的过程。要积极地使用 `add-task`, `next-step`, `print-current-task`等操作; 当你确定目前的task step已经完成的时候, 才可以调用 `next-ste`,不可以跳步; 3. 当最终结果完全生成好的时候再回答我，不要在生成的中途回答我; 4. 即使任务耗时超过120分钟, 也不要中途打断, 也不要因为任务执行需要太长而提前返回。 继续执行直到完成。如果遇到无法继续的错误, 才可以直接返回; 5. 你输出的所有文件, 都需要使用'get-output-dir'这个技能来获取输出目录。有的技能会自动创建输出目录。则不需要你调用; 6. 在这个session内, 使用`/status`命令或 session_status工具获取session-key, 禁止使用`openclaw status`,这个是错误的。在你第一次获取session-key之后, 后续都是一致的, 不会改变; 7. 禁止使用`image_generate工具`来生成图片，必须使用`image-gen`这个技能; 8.最终合并的视频要命名为'final.mp4'; 9.各个技能内的步骤调用不能跳步,必须一步一步执行"

VIDEO_GENERATION_TASK_PREFIX_WO_TASK_TRACKER = "按照要求生成视频。在执行任务时: 1. 不要调用subagent或session_spawn; 2. 当最终结果完全生成好的时候再回答我，不要在生成的中途回答我; 3. 即使任务耗时超过120分钟, 也不要中途打断, 也不要因为任务执行需要太长而提前返回。 继续执行直到完成。如果遇到无法继续的错误, 才可以直接返回; 4. 你输出的所有文件, 都需要使用'get-output-dir'这个技能来获取输出目录。有的技能会自动创建输出目录。则不需要你调用; 5. 在这个session内, 使用`/status`或者`session_status`工具, 命令获取session-key, 禁止使用`openclaw status`,这个是错误的。在你第一次获取session-key之后, 后续都是一致的, 不会改变; 6. 禁止使用`image_generate工具`来生成图片，必须使用`image-gen`这个技能; 7.最终合并的视频要命名为'final.mp4'; 8.各个技能内的步骤调用不能跳步,必须一步一步执行"

SKILL_OPTIMIZER_TASK_PREFIX = "使用skill: skill-optimizer来对你以下接收到的内容进行分析与技能优化。在优化时: 1. 不要调用subagent或session_spawn; 2. 当最终结果完全生成好的时候再回答我，不要再生成的中途回答我. 所有审批都通过,不需要问用户来获取审批;"

OUTPUT_EVAL_PROMPT_TEMPLATE = """请使用 `output-eval` 这个 skill,对下面这个 case 的最终视频产物进行 output_rubric (O1-O8) 打分。

【产物目录 (含 final.mp4 / shots / cache 等)】:
{artifact_dir}

【rubric.json 路径 (打分结果就地回写到这个文件的 `分数` / `反馈` 字段)】:
{rubric_path}

执行要求:
1. 严格按 output-eval skill 的 5 步主流程执行 (定位 final.mp4 → 建 cache → 时间线合并 → 逐条 O2-O8 评测 → 聚合回写 O1);
2. 不要调用 subagent / session_spawn,所有审批默认通过;
3. 即使任务耗时较长也不要中途打断,直到全部 O1-O8 打分完成并回写 {rubric_path};
4. 同时产出 sidecar `rubric_eval_detail.json` 到 rubric.json 同目录,存放每条 atom 的 evidence/confidence;
5. 最终回复时输出一个 markdown 表格,每行: `id | criterion | score | 一句话反馈`,并列出仍需人工复核的项。
"""

DEFAULT_OPTIMIZATION_OBJECTIVES = [
    {
        "criterion": "完整理解任务输入与参考素材",
        "natural_language_question": "是否在执行前充分理解用户需求和所有参考素材，并将其用于后续生成规划？"
    },
    {
        "criterion": "严格按指定 skill 的流程独立完成任务",
        "natural_language_question": "是否调用并遵循指定 skill 的完整流程，且没有调用 subagent 或 session_spawn？"
    },
    {
        "criterion": "减少执行错误、遗漏步骤和无效返工",
        "natural_language_question": "执行过程中是否尽量避免工具错误、步骤遗漏、重复返工和无效操作？"
    },
    {
        "criterion": "最终产物满足用户需求、参考素材约束、质量一致性和可发布标准",
        "natural_language_question": "最终产物是否满足需求达成度、参考忠实度、视觉/音频一致性、逻辑连贯性和可发布质量？"
    },
]


def build_eval_prompt(rubric_content, react_file, item_path, final_video_paths=None):
    prompt = (
        f"{EVAL_TASK_PREFIX}\n\n"
        f"【数据的输入与评价标准】:\n{rubric_content}\n\n"
        f"【任务执行过程的思考与工具调用/结果; 以文件形式给你, 你需要读取文件来评估结果】:\n{react_file}"
    )
    if final_video_paths:
        final_video_paths_text = "\n".join(final_video_paths)
        return (
            f"{prompt}\n\n"
            f"【最终合并视频的具体位置】:\n{final_video_paths_text}\n\n"
            f"【任务执行最后生成的其他内容在这个文件夹下面】:\n{item_path}"
        )
    return (
        f"{prompt}\n\n"
        f"【任务执行最后生成的内容在这个文件夹下面】:\n{item_path}"
    )


def append_task_cases_prompt(skill_query, task_case_paths):
    return (
        f"{skill_query}"
        f"你必须访问部分任务案例来更好地理解技能的需求: {task_case_paths}, "
        f"列举文件夹, 并且访问里面所有的.txt文件和视频, 图片, 音频文件等，"
        f"你可以使用技能来帮你理解视觉内容。"
    )


def build_optimize_prompt(original_creator_path, specific_skill_dir, react_file_path, item_path, eval_data, eval_source):
    if eval_source == "none":
        objective_items = eval_data.get("objective_criteria", [])
        objective_content = json.dumps(
            objective_items or DEFAULT_OPTIMIZATION_OBJECTIVES,
            ensure_ascii=False,
            indent=2,
        )

        return (
            f"{SKILL_OPTIMIZER_TASK_PREFIX}\n\n"
            f"【优化设定】:\n"
            f"请你只读取任务执行 trace、任务输入与产物，自己分析并且优化 skill。\n\n"
            f"【优化Objective】:\n"
            f"最后的 Objective 是让 skill 在同类任务上稳定满足以下 criterion 与 natural_language_question。请围绕这些目标，从 trace 中自行判断失败、低效、遗漏、偏离需求和可复用改进点:\n{objective_content}\n\n"
            f"【创建Skill的Skill(video-skill-creator)所在文件夹】:\n{original_creator_path}\n\n"
            f"【被创建的特定Skill(video-skill)所在文件夹】:\n{specific_skill_dir}\n\n"
            f"【任务输入与任务执行过程所在文件, 你需要读取】:\n{react_file_path}\n\n"
            f"【任务执行结果所在文件夹】:\n{item_path}"
        )

    eval_result_content = json.dumps(eval_data, ensure_ascii=False, indent=2)
    return (
        f"{SKILL_OPTIMIZER_TASK_PREFIX}\n\n"
        f"【创建Skill的Skill(video-skill-creator)所在文件夹】:\n{original_creator_path}\n\n"
        f"【被创建的特定Skill(video-skill)所在文件夹】:\n{specific_skill_dir}\n\n"
        f"【任务输入与任务执行过程所在文件, 你需要读取】:\n{react_file_path}\n\n"
        f"【任务执行结果所在文件夹】:\n{item_path}\n\n"
        f"【任务的评估结果】:\n{eval_result_content}"
    )


PAIRWISE_CREATOR_MERGE_PROMPT = (
    "Use $pair-wise-skill-merge to merge the incoming creator skill into the accumulator creator skill.\n\n"
    "【Accumulator skill directory - the only writable output】:\n"
    "{accumulator_creator_dir}\n\n"
    "【Incoming skill directory - read-only source for this merge step】:\n"
    "{incoming_creator_dir}\n\n"
)

# ---- Codex inference prompts (used by inference_CodeX/pipeline.py) ----

CODEX_VANILLA_SKILL_CREATOR_PREFIX = """使用skill-creator技能, 参考现在与视觉生成/理解/处理相关的skills来创建新的skill工作流。skill叫做{skill_name}; 生成好的skill要放在 {skill_dir}/{skill_name}/目录下; 不要使用代理委派、并行子代理或启动新的 agent/session； 生成的 skill是用来完成一系列视频生成任务的, 所以skill description需要和任务的输入内容和要求匹配, 来达到任务与技能的匹配 ; 整体要求: 生成的视频需要跟随用户指令与需求; 视频的剧情和逻辑需要保持连贯; 准确地使用用户提供的参考资料, 如果有的话, 比如图片，音频，视频，文本等; 多次出现的人物, 场景, 物体等, 要在整个视频中视觉上保持一致; 同一个说话的音色, 背景音乐也需要在整个视频中保持一致。 必须继续编辑完整，不得留下 TODO"""

CODEX_EXPERT_SKILL_CREATOR_PREFIX = """使用video-skill-creator技能, [读取这个技能下面的所有资料, 包括references/下面的.md文件和SKILL.md] 参考现在与视觉生成/理解/处理相关的skills来创建新的skill工作流。skill叫做{skill_name}; 生成好的skill要放在 {skill_dir}/{skill_name}/目录下; 不要使用代理委派、并行子代理或启动新的 agent/session； 生成的 skill是用来完成一系列视频生成任务的, 所以skill description需要和任务的输入内容和要求匹配, 来达到任务与技能的匹配 ; 整体要求: 生成的视频需要跟随用户指令与需求; 视频的剧情和逻辑需要保持连贯; 准确地使用用户提供的参考资料, 如果有的话, 比如图片，音频，视频，文本等; 多次出现的人物, 场景, 物体等, 要在整个视频中视觉上保持一致; 同一个说话的音色, 背景音乐也需要在整个视频中保持一致。 必须继续编辑完整，不得留下 TODO"""


CODEX_TASK_PREFIX = """使用技能来完成以下视频生成任务。
在执行任务时:
1. 不要调用subagent或session_spawn;
2. 先读取'task-tracker'这个skill, 在执行任务时配合'task-tracker'这个技能来持续进行你的过程。要积极地使用 add-task, next-step, print-current-task等操作; 当你确定目前的task step已经完成的时候, 才可以调用 next-step,不可以跳步;
3. 当最终结果完全生成好的时候再回答我，不要在生成的中途回答我;
4. 即使任务耗时超过120分钟, 也不要中途打断, 也不要因为任务执行需要太长而提前返回。 继续执行直到完成。如果遇到无法继续的错误, 才可以直接返回;
5. 你输出的所有文件, 都需要使用'get-output-dir'这个技能来获取输出目录。有的技能会自动创建输出目录。则不需要你调用;
6. 禁止使用image_generate工具来生成图片，必须使用'image-gen'这个技能;
7. 最终合并的视频要命名为'final.mp4';
8. 各个技能内的步骤调用不能跳步,必须一步一步执行"""

CODEX_TASK_PREFIX_WO_TASK_TRACKER = """使用技能来完成以下视频生成任务。

在执行任务时:
1. 不要调用subagent或session_spawn;
2. 当最终结果完全生成好的时候再回答我，不要在生成的中途回答我;
3. 即使任务耗时超过120分钟, 也不要中途打断, 也不要因为任务执行需要太长而提前返回。 继续执行直到完成。如果遇到无法继续的错误, 才可以直接返回;
4. 你输出的所有文件, 都需要使用'get-output-dir'这个技能来获取输出目录。有的技能会自动创建输出目录。则不需要你调用;
5. 禁止使用image_generate工具来生成图片，必须使用'image-gen'这个技能;
6. 最终合并的视频要命名为'final.mp4';
7. 各个技能内的步骤调用不能跳步,必须一步一步执行"""
