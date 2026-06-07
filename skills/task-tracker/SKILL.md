---
name: task-tracker
description: 用于追踪和管理任务执行的技能。它可以读取并解析其他技能的 SKILL.md 文件，将其中的执行步骤和子步骤初始化为一个可以无限嵌套的 JSON 任务结构（Task）。支持通过脚本直接生成指定技能的执行状态结构。
---
# 任务追踪器 (task-tracker)

`task-tracker` 技能用于帮助 Agent 将复杂的任务分解为可追踪的结构，并进行进度管理，来防止跳步执行。


## 使用方法

> ⚠️ **【最高优先级规则】**
>
> ```text
> IF (决定执行某个技能) {
>     // 无论是因为刚读完 SKILL.md，还是凭记忆多次调用
>     
>     IF (当前 session 下还没有 task_tracker.json) {
>         必须调用 `init` 来初始化全局的主任务栈
>     } ELSE {
>         // 当前已有主任务在运行，调用新技能属于嵌套任务
>         必须调用 `add-task` 将该技能的任务栈挂载到当前步骤下
>     }
>     
>     // 在执行完技能中的每个步骤后
>     必须使用 `next-step` 推进状态并检查 `print-current-task` 确认进度
> 
> } ELSE IF (仅仅是读取 SKILL.md 查看文档，不打算执行) {
>     不需要更新 task-tracker, 不需要做任何步骤操作
> }
> ```

## 核心功能

1. **结构初始化**：通过解析目标技能的 `SKILL.md`，自动提取所有主步骤。最外层的 key 会自动带有 `main:` 前缀（例如 `main:video-gen`），表明这是主控任务。
2. **状态流转**：每个任务节点都包含一个 `status`，支持 `PENDING` -> `PROCESSING` -> `SUCCESS` 或 `FAIL` 的状态流转。
3. **扁平化结构**：所有的子步骤都会被提取为简单的文本列表，存入主步骤的 `task_details` 字段中，生成简洁易懂的单层任务流。
4. **动态技能嵌套 (Tasks)**：当在执行某一步（处于 `PROCESSING`）时，如果需要调用其他的 skill（例如 `vision-understanding`），你可以动态将该技能的任务流嵌套进当前的步骤中。它会以 `subtasks` 下对应的技能名称为 key 挂载。
5. **输出结构化**：生成标准化的 JSON 对象，支持记录每个步骤的：
   - `task`：主任务名称。
   - `task_details`：(列表 `[]`) 该主任务下包含的所有任务（或步骤细节）列表。
   - `status`：当前执行状态 (`PENDING`, `PROCESSING`, `SUCCESS`, `FAIL`)。
   - `subtasks`：（动态生成的对象）挂载的技能任务栈集合。
   - `output`：简单记录该步生成或处理了什么内容。
   - `output_file`：(列表 `[]`) 记录该步生成的所有文件路径（包含任何图片、视频、音频、文本文件、日志等）。
   - `notes`：记录该步执行过程中其他需要补充或备忘的内容。

## 文件结构

```text
task-tracker/
├── SKILL.md (本文件)
└── scripts/
    └── tracker_utils.py (核心工具类与解析脚本)
```

## 支持参数

| 参数名 | 说明 | 可选值 | 默认值 |
|--------|------|--------|--------|
| `action` | **(Required)** 需要执行的操作 | `init`, `print-current-task`, `print-whole-task-stack`, `next-step`, `add-task`, `delete-task` | - |
| `--session-key` | **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。脚本会把追踪器保存为统一名称 `task_tracker.json`。 | 字符串 | - |
| `--skill-md-path` | 目标技能的 `SKILL.md` 绝对路径（仅在 `init` 或 `add-task` 阶段必填） | 字符串 | - |
| `--task-path` | 目标技能栈的完整依赖路径，用于删除特定的任务（仅在 `delete-task` 阶段必填）。格式必须包含层级前缀（最外层主任务使用 `main:`，挂载的子任务使用 `subtask:`）。例如：`main:video-gen->step1->subtask:get-output-dir` | 字符串 | - |
| `--status` | 更新当前任务的状态（仅在 `next-step` 阶段可用）。无论传入 `SUCCESS` 还是 `FAIL`，都会自动将下一个任务推进到 `PROCESSING`（如因前置失败导致后续无法执行，请继续用 FAIL 推进）。 | `SUCCESS`, `FAIL` | `SUCCESS` |
| `--output` | 用于记录当前执行完的任务输出了什么内容（仅在 `next-step` 阶段可选） | 字符串 | - |
| `--output-file` | 记录当前任务生成的文件路径列表。可传入多个路径，以空格分隔（仅在 `next-step` 阶段可选） | 字符串列表 | - |
| `--notes` | 记录当前任务执行过程中的其他补充说明或备忘（仅在 `next-step` 阶段可选） | 字符串 | - |



### 1. 命令行调用

支持六种操作模式（action）：

**初始化追踪器 (init)**：
解析目标 `SKILL.md` 并生成任务追踪器，默认将第一个任务状态置为 `PROCESSING`，其余为 `PENDING`。
```bash
python task-tracker/scripts/tracker_utils.py init --session-key "agent:test:test" --skill-md-path image-gen/SKILL.md
```

**打印当前状态 (print-current-task)**：
输出当前正在执行的任务层级链路。

```bash
python task-tracker/scripts/tracker_utils.py print-current-task --session-key "agent:test:test"
```

**打印完整任务栈 (print-whole-task-stack)**：
输出当前的 `task_tracker.json` 完整状态。
```bash
python task-tracker/scripts/tracker_utils.py print-whole-task-stack --session-key "agent:test:test"
```

**推进任务状态 (next-step)**：
将当前处于 `PROCESSING` 的任务标记为 `SUCCESS`（或通过 `--status` 标记为 `FAIL`），并将传入的 `output`, `output-file`, `notes` 数据记录到该任务节点。无论状态标记为什么，都会将下一个 `PENDING` 的任务推进为 `PROCESSING`，确保流程不中断。

**示例（标记成功并流转到下一步）：**
```bash
python task-tracker/scripts/tracker_utils.py next-step \
  --session-key "agent:test:test" \
  --status "SUCCESS" \
  --output "生成了两张教师节海报" \
  --output-file "/path/to/poster1.jpg" "/path/to/poster2.jpg" "/path/to/generation.log" \
  --notes "第二张图由于分辨率问题自动降级为2K处理"
```

**示例（标记失败，并自动流转到下一步）：**
```bash
python task-tracker/scripts/tracker_utils.py next-step \
  --session-key "agent:test:test" \
  --status "FAIL" \
  --notes "API调用超时，请稍后重试"
```

**添加技能任务栈 (add-task)**：
在执行某一步时（即该步骤为 `PROCESSING` 状态），如果需要调用其他的 skill，你可以将该技能的任务栈作为嵌套字段附加到当前的主步骤中。
```bash
python task-tracker/scripts/tracker_utils.py add-task \
  --session-key "agent:test:test" \
  --skill-md-path vision-understanding/SKILL.md
```

**删除技能任务栈 (delete-task)**：
如果你需要根据依赖路径（例如发生了取消、回退，或者动态执行不需要该任务栈时），将特定的技能栈从当前的 tracker 栈中剔除，你可以使用这个操作：
```bash
python task-tracker/scripts/tracker_utils.py delete-task \
  --session-key "agent:test:test" \
  --task-path "main:video-gen->step1->subtask:vision-understanding"
```

通过在执行过程中更新每个步骤的 `output` 和 `output_file`，并灵活挂载/删除 `subtasks`，Agent 可以完美记录和追踪极度复杂的任务栈状态。
