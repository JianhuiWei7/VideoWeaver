import json
import re
from typing import Dict
import os
import sys
import subprocess
import argparse

class TaskStep:
    """
    基础任务模组，不支持嵌套子步骤细节，但支持将外部调用的其他 skill（任务栈）
    作为字典嵌套到动态的 `task_name` 键中。
    包含 status 属性，支持状态流转：PENDING -> PROCESSING -> SUCCESS / FAIL
    """
    def __init__(self, task: str = "", task_details: list = None, output: str = "", output_file: list = None, status: str = "PENDING", notes: str = "", subtasks: Dict[str, dict] = None):
        self.task = task
        self.task_details = task_details if task_details is not None else []
        self.output = output
        self.output_file = output_file if output_file is not None else []
        self.status = status
        self.notes = notes
        # subtasks 字典，存储格式如 {"vision-understanding": {...}}
        self.subtasks = subtasks if subtasks is not None else {}

    def to_dict(self) -> dict:
        d = {
            "task": self.task,
            "task_details": self.task_details,
            "status": self.status
        }
        
        d.update({
            "output": self.output,
            "output_file": self.output_file,
            "notes": self.notes
        })
        
        # 统一规范：将所有的技能挂载放在专门的 "subtasks" 字段中
        if self.subtasks:
            d["subtasks"] = self.subtasks
            
        return d
    
    @classmethod
    def from_dict(cls, data: dict) -> 'TaskStep':
        output_file = data.get("output_file", [])
        if isinstance(output_file, str):
            output_file = [output_file] if output_file else []
            
        task_details = data.get("task_details", [])
        if isinstance(task_details, str):
            task_details = [task_details] if task_details else []
            
        subtasks = data.get("subtasks", {})
        
        # 兼容旧版本平铺结构
        for key, val in data.items():
            if key.startswith("task:") and key.replace("task:", "") not in subtasks:
                subtasks[key.replace("task:", "")] = val
                
        return cls(
            task=data.get("task", ""),
            task_details=task_details,
            output=data.get("output", ""),
            output_file=output_file,
            status=data.get("status", "PENDING"),
            notes=data.get("notes", ""),
            subtasks=subtasks
        )

class TaskTracker:
    """
    任务追踪器，管理特定 skill 下的所有步骤。
    """
    def __init__(self, skill_name: str, is_main: bool = True):
        self.skill_name = skill_name
        self.is_main = is_main
        self.steps: Dict[str, TaskStep] = {}
        # 为了支持同级平铺多个 main skill，增加一个额外的主任务字典。
        # 如果 additional_mains 不为空，说明有其他 main 被并列添加进来了
        self.additional_mains: Dict[str, 'TaskTracker'] = {}

    def add_step(self, step_id: str, step: TaskStep):
        self.steps[step_id] = step

    def to_dict(self) -> dict:
        result = {
            self.skill_name: {
                step_id: step.to_dict() for step_id, step in self.steps.items()
            }
        }
        
        if self.is_main:
            for am_key, am_tracker in self.additional_mains.items():
                result.update(am_tracker.to_dict_inner())
            return {"main": result}
        else:
            return result

    def to_dict_inner(self) -> dict:
        result = {
            self.skill_name: {
                step_id: step.to_dict() for step_id, step in self.steps.items()
            }
        }
        for am_key, am_tracker in self.additional_mains.items():
            result.update(am_tracker.to_dict_inner())
        return result
        
    def save_to_json(self, file_path: str):
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=4, ensure_ascii=False)

    @classmethod
    def load_from_json(cls, file_path: str) -> 'TaskTracker':
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        main_data = data.get("main", data)
        keys = list(main_data.keys())
        if not keys:
            return cls("unknown")
            
        first_key = keys[0]
        
        actual_name = first_key
        tracker = cls(actual_name, is_main=True)
        
        for step_id, step_data in main_data[first_key].items():
            tracker.add_step(step_id, TaskStep.from_dict(step_data))
            
        # 处理额外并列的 main
        for other_key in keys[1:]:
            other_actual_name = other_key
            other_tracker = cls(other_actual_name, is_main=False)
            for step_id, step_data in main_data[other_key].items():
                other_tracker.add_step(step_id, TaskStep.from_dict(step_data))
            tracker.additional_mains[other_key] = other_tracker
            
        return tracker

    def get_all_nodes(self) -> list:
        """平铺获取所有任务节点，保持执行顺序（深度优先遍历以支持嵌套的 task）"""
        nodes = []
        # 重新实现一个更严谨的遍历，确保能把嵌套的字典全部转成 TaskStep 并加入节点链
        def deep_traverse(step_obj):
            nodes.append(step_obj)
            for task_key, task_dict in step_obj.subtasks.items():
                for nested_step_id, nested_step_data in task_dict.items():
                    # 递归遍历所有挂载的技能步骤
                    deep_traverse(TaskStep.from_dict(nested_step_data))

        # 遍历当前 main 的 steps
        for key, step in self.steps.items():
            deep_traverse(step)
            
        # 遍历追加的其他并列 main 的 steps
        for am_key, am_tracker in self.additional_mains.items():
            for key, step in am_tracker.steps.items():
                deep_traverse(step)
            
        return nodes

    def print_whole_task_stack(self):
        """打印当前所有任务的状态"""
        print(json.dumps(self.to_dict(), indent=4, ensure_ascii=False))

    def print_current_task(self):
        """打印当前正在执行的任务层级链路"""
        level_name, chain_str = self.get_current_level_chain()
        print("\n" + "="*40)
        if chain_str:
            print(f"当前层级任务为: {level_name}")
            print(f"执行链路为: {chain_str}")
        else:
            print("当前没有正在执行 (PROCESSING) 的任务。")
        # print("="*40)
        self.print_processing_status()

    def get_current_level_chain(self) -> tuple[str, str]:
        """
        获取当前正在执行的最深层任务层级和链路
        返回 (level_name, chain_str)
        """
        stack = self._build_execution_stack()
        if not stack:
            return "", ""
            
        # 栈顶即为最深层正在执行的任务所在的层级上下文
        parent_dict, current_key, current_node, current_path = stack[-1]
        
        # 提取 level_name
        # 我们可以通过 current_path 来推断 level_name
        segments = current_path.split("->")
        level_name = ""
        # The last segment is the task step (e.g. step1:xxx), the one before is the skill name.
        if len(segments) > 1:
            # We don't have task: prefix anymore, so we take the segment before the last one as level_name
            level_name = segments[-2]
        else:
            root_seg = segments[0]
            level_name = root_seg
            
        # 提取同层级的所有步骤并格式化为 chain_str
        valid_keys = [k for k in parent_dict.keys() if k != "subtasks"]
        parts = []
        for k in valid_keys:
            v = parent_dict[k]
            if isinstance(v, dict):
                t_name = v.get("task", "")
                t_status = v.get("status", "")
                parts.append(f"{k}: {t_name} [{t_status}]")
            elif isinstance(v, TaskStep):
                parts.append(f"{k}: {v.task} [{v.status}]")
                
        chain_str = " -> ".join(parts) if parts else ""
        
        return level_name, chain_str

    def _build_execution_stack(self):
        """
        将树状结构解析为显式的执行栈 (Call Stack)。
        返回列表: [(parent_dict, step_key, step_node_obj, full_path_string), ...]
        栈底是主任务，栈顶是当前正在执行的最深层任务步骤。
        """
        stack = []
        def dfs(step_dict, prefix=""):
            for k, v in step_dict.items():
                if k == "subtasks": continue
                
                status = v.get("status") if isinstance(v, dict) else v.status
                task_name = v.get("task", "") if isinstance(v, dict) else v.task
                path_segment = f"{k}:{task_name}" if task_name else k
                
                if status == "PROCESSING":
                    stack.append((step_dict, k, v, prefix + path_segment))
                    
                    subtasks = v.get("subtasks", {}) if isinstance(v, dict) else v.subtasks
                    # 如果有挂载的技能，遍历它们看有没有处于 PROCESSING 的
                    for task_key, task_val in subtasks.items():
                        if dfs(task_val, prefix + path_segment + "->subtask:" + task_key + "->"):
                            break
                    # 不管有没有更深层的 PROCESSING，当前节点处于 PROCESSING，整条路径就是有效的
                    return True
            # 如果当前层级的所有节点都不是 PROCESSING，才返回 False
            return False

        root_key = f"main:{self.skill_name}"
        if not dfs(self.steps, root_key + "->"):
            for am_key, am_tracker in self.additional_mains.items():
                am_root = f"main:{am_tracker.skill_name}"
                if dfs(am_tracker.steps, am_root + "->"):
                    break
        return stack

    def get_current_processing_path(self) -> str:
        """
        获取当前正在执行的最深层任务路径 (通过任务栈实现)
        格式示例：main:video-gen->step1:提示词优化重写->task:get-output-dir->step2:调用脚本
        """
        stack = self._build_execution_stack()
        if stack:
            # stack[-1] 保存的是栈顶元素，[3] 是完整路径字符串
            return stack[-1][3]
        return "当前没有正在执行 (PROCESSING) 的任务。"

    def print_processing_status(self):
        """打印出格式化的当前处理路径"""
        print("\n" + "="*40)
        current_path = self.get_current_processing_path()
        if current_path == "当前没有正在执行 (PROCESSING) 的任务。":
            print("⚠️ 提示：所有现在的任务栈都已经完成，请检查用户需求/任务是否已经被满足。如果没有，请通过 `add-task` 继续执行，否则返回。")
        else:
            print(f"📍 正在执行：{current_path}")
            # 获取当前节点的 task_details 并打印
            current_node_obj = self._get_node_by_path(current_path)
            if current_node_obj:
                task_details = current_node_obj.get("task_details", []) if isinstance(current_node_obj, dict) else current_node_obj.task_details
                if task_details:
                    print(f"📍 任务细节与注意事项: ")
                    for detail in task_details:
                        print(f"  - {detail}")
                        
            print("💡 提示：如需查看完整任务栈完整状态，请调用 print-whole-task-stack 操作。如果想查看当前层级, 请调用 print-current-task 操作。")
            print("💡 提示：当使用 read 来读取新的 SKILL.md 并且准备执行里面的指令时; 或者要重新执行一遍某个 SKILL 的 workflow 时，你需要调用 add-task。")
            
        # print("="*40 + "\n")

    def _update_node_in_tree(self, steps_dict: dict, target_task_name: str, modifier_func) -> bool:
        """
        递归在树中查找目标任务节点并对其执行修改。
        由于树中可能存在同名节点（例如多个旧的 image-gen 任务），
        为确保准确命中，我们要求被修改的节点不仅任务名匹配，还必须当前处于 PROCESSING 或 PENDING 状态，
        以此过滤掉那些已经处于 SUCCESS/FAIL 状态的旧任务节点。
        """
        for key, val in steps_dict.items():
            if isinstance(val, dict):
                # 这是一个嵌套字典（如 subtasks 里的 step）
                status = val.get("status")
                if val.get("task") == target_task_name and status in ["PROCESSING", "PENDING"]:
                    modifier_func(val)
                    return True
                # 继续深挖这个字典里面可能挂载的其它 subtasks
                subtasks = val.get("subtasks", {})
                for task_key, task_val in subtasks.items():
                    if self._update_node_in_tree(task_val, target_task_name, modifier_func):
                        return True
            elif isinstance(val, TaskStep):
                if val.task == target_task_name and val.status in ["PROCESSING", "PENDING"]:
                    modifier_func(val)
                    return True
                # 继续深挖
                if val.subtasks:
                    for task_key, task_dict in val.subtasks.items():
                        if self._update_node_in_tree(task_dict, target_task_name, modifier_func):
                            return True
        return False

    def _get_node_by_path(self, path_str: str):
        """
        根据精确的绝对路径（如 main:video-gen->step1->subtask:image-gen->step2）
        返回对应的字典或 TaskStep 对象的引用，方便直接修改。
        如果找不到，返回 None。
        """
        if not path_str or path_str == "当前没有正在执行 (PROCESSING) 的任务。":
            return None
            
        stack = self._build_execution_stack()
        if stack:
            # 既然我们已经有了执行栈，而且 path_str 通常就是栈顶任务的路径
            # 我们可以直接比满路径，如果匹配，直接返回栈帧中的节点对象！
            for _, _, node_obj, full_path in stack:
                # 因为 full_path 包含了 task_name (如 step1:xxx)，而传入的 path_str 可能也包含
                # 我们这里做个简单的判断，如果是当前正在执行的路径，直接返回
                if full_path == path_str:
                    return node_obj
                    
        # 回退逻辑：如果栈里没找到（比如要找一个非 PROCESSING 的历史节点），还是用老方法去树里挖
        segments = path_str.split("->")
        
        # 判断是从哪个 root tracker 开始找
        root_seg = segments[0]
        if root_seg.startswith("main:"):
            root_seg = root_seg.replace("main:", "")
            
        if root_seg != self.skill_name:
            active_tracker = self.additional_mains.get(root_seg)
            if not active_tracker:
                return None
        else:
            active_tracker = self
            
        curr_dict = active_tracker.steps
        # 去掉 root_key
        if len(segments) > 0 and (segments[0] == active_tracker.skill_name or segments[0] == f"main:{active_tracker.skill_name}"):
            segments = segments[1:]
            
        curr_obj = None
        for i, seg in enumerate(segments):
            # seg 可能是 "step1:提示词优化" 或者仅仅是 "step1"
            # 如果是 step 节点，提取冒号前的 key，即 "step1"
            if seg.startswith("step"):
                step_key = seg.split(":")[0]
                if isinstance(curr_dict, dict) and step_key in curr_dict:
                    curr_obj = curr_dict[step_key]
                    # 如果不是最后一段，准备进入下一层的 subtasks
                    if i < len(segments) - 1:
                        if isinstance(curr_obj, dict):
                            curr_dict = curr_obj.get("subtasks", {})
                        elif isinstance(curr_obj, TaskStep):
                            curr_dict = curr_obj.subtasks
                else:
                    return None
            # seg 可能是 "subtask:image-gen"
            else:
                task_key = seg.replace("subtask:", "") if seg.startswith("subtask:") else seg
                if isinstance(curr_dict, dict) and task_key in curr_dict:
                    curr_obj = curr_dict[task_key]
                    # task 节点本身就是一个字典，包含了它下面的 steps
                    # 如果不是最后一段，准备进入它的内部
                    if i < len(segments) - 1:
                        curr_dict = curr_obj
                else:
                    return None
                    
        return curr_obj

    def add_task(self, task_name: str, task_tracker: 'TaskTracker'):
        """
        向当前 processing 状态的最深层任务添加或更新技能的 tracker 栈。
        如果当前没有 processing 任务（所有任务已完成），则将新任务追加到 root 级别，作为新的主技能执行。
        """
        nodes = self.get_all_nodes()
        target_node = None
        # 因为是深度优先遍历，最后一个 PROCESSING 节点即为当前最深层正在执行的任务
        for node in nodes:
            if node.status == "PROCESSING":
                target_node = node
                
        if not target_node:
            # 如果没有 PROCESSING 任务，说明主任务已全部完成，直接将新技能作为并列的 main
            # 计算新的 main key 名称，避免重复覆盖
            new_main_key = f"{task_name}"
            
            # 为了支持多个相同 main 技能追加（例如连续两个 video-gen）
            existing_keys = [self.skill_name] + list(self.additional_mains.keys())
            if new_main_key in existing_keys:
                counter = 2
                while f"{new_main_key}_{counter}" in existing_keys:
                    counter += 1
                new_main_key = f"{new_main_key}_{counter}"
            
            # 我们将新传入的 task_tracker 设置为新的并列主追踪器，并把它挂载到 additional_mains 中
            # 但我们需要更新它的名称使其和计算出的 new_main_key 一致
            task_tracker.skill_name = new_main_key
            task_tracker.is_main = False
            
            self.additional_mains[new_main_key] = task_tracker
            
            # 提取技能中的所有主步骤名称，用于打印提示
            task_steps_info = [f"[{step_id}] {step_obj.task}" for step_id, step_obj in task_tracker.steps.items()]
            steps_str = " -> ".join(task_steps_info)
            
            print("\n" + "="*40)
            print(f"所有任务已完成，已将任务 '{task_name}' 追加为新的并列主任务 (节点: {new_main_key})")
            print(f"包含的执行步骤: {steps_str}")
            self.print_processing_status()
            return
            
        def attach_task(node_obj):
            # 获取当前节点已经存在的技能 keys
            existing_keys = []
            if isinstance(node_obj, dict):
                # 检查专属挂载区 subtasks
                if "subtasks" in node_obj:
                    existing_keys = [k for k in node_obj["subtasks"].keys() if k.startswith(task_name)]
                else:
                    # 兼容老数据结构
                    existing_keys = [k for k in node_obj.keys() if k.startswith(task_name)]
            else:
                existing_keys = [k for k in node_obj.subtasks.keys() if k.startswith(task_name)]
                
            # 计算新的 key 名称，避免重复覆盖
            new_task_key = f"{task_name}"
            if new_task_key in existing_keys:
                counter = 2
                while f"{new_task_key}_{counter}" in existing_keys:
                    counter += 1
                new_task_key = f"{new_task_key}_{counter}"
                
            if isinstance(node_obj, dict):
                # 确保当前字典包含 "subtasks" 字段，如果不作为专属字典管理可能会有冲突
                if "subtasks" not in node_obj:
                    node_obj["subtasks"] = {}
                node_obj["subtasks"][new_task_key] = task_tracker.to_dict_inner()[task_name]
            else:
                node_obj.subtasks[new_task_key] = task_tracker.to_dict_inner()[task_name]
                
        # 我们现在可以通过执行栈精确找到栈顶的任务对象并对其进行修改
        # 从而避免 _update_node_in_tree 在有重名任务时发生匹配错误
        stack = self._build_execution_stack()
        if stack:
            _, _, current_node, _ = stack[-1]
            attach_task(current_node)
            target_task_name = current_node.get("task") if isinstance(current_node, dict) else current_node.task
        else:
            # 回退逻辑
            self._update_node_in_tree(self.steps, target_node.task, attach_task)
            target_task_name = target_node.task
        
        # 提取技能中的所有主步骤名称，用于打印提示
        task_steps_info = [f"[{step_id}] {step_obj.task}" for step_id, step_obj in task_tracker.steps.items()]
        steps_str = " -> ".join(task_steps_info)
        
        print("\n" + "="*40)
        print(f"成功将任务 '{task_name}' 挂载到任务节点: {target_task_name}")
        print(f"包含的执行步骤: {steps_str}")
        self.print_processing_status()

    def delete_task(self, task_path: str):
        """
        根据传入的完整路径字符串删除对应的 task 节点。
        传入的格式必须为精确到 task 的路径，例如：
        main:video-gen->step1:提示词优化重写->subtask:get-output-dir
        或者简化版路径（仅包含 key）：
        main:video-gen->step1->subtask:get-output-dir
        """
        segments = task_path.split("->")
        target_task_key = segments[-1].replace("subtask:", "") if segments[-1].startswith("subtask:") else segments[-1]
        
        # 提取目标 task 挂载在哪个父步骤节点下（倒数第二个 segment）
        if len(segments) < 2:
            print("\n" + "="*40)
            print(f"⚠️ 错误：不合法的 task 路径。路径过短，无法找到父节点层级。接收到的路径: {task_path}")
            print("="*40 + "\n")
            return
        
        # parent segment 可能是 "step1" 或 "step1:任务名称"
        parent_segment = segments[-2]
        parent_step_key = parent_segment.split(":")[0]
        
        # 直接使用我们强大且稳健的 _get_node_by_path 方法获取父节点！
        # 父节点的路径就是去掉最后一个 task segment 的路径
        parent_path = "->".join(segments[:-1])
        parent_node = self._get_node_by_path(parent_path)
        
        if not parent_node:
            print("\n" + "="*40)
            print(f"⚠️ 错误：找不到要删除的任务的父节点层级：{parent_path}")
            # print("="*40 + "\n")
            return
            
        # 现在我们拿到了父节点的字典引用或 TaskStep 对象
        deleted = False
        if isinstance(parent_node, dict):
            # 兼容新老结构：优先从 subtasks 里删
            if "subtasks" in parent_node and target_task_key in parent_node["subtasks"]:
                del parent_node["subtasks"][target_task_key]
                deleted = True
            elif target_task_key in parent_node:
                del parent_node[target_task_key]
                deleted = True
        elif isinstance(parent_node, TaskStep):
            if target_task_key in parent_node.subtasks:
                del parent_node.subtasks[target_task_key]
                deleted = True
                
        if deleted:
            print("\n" + "="*40)
            print(f"🗑️ 成功删除挂载的技能节点: {target_task_key}")
            # print("="*40 + "\n")
            self.print_processing_status()
        else:
            print("\n" + "="*40)
            print(f"⚠️ 错误：在父节点下找不到指定的任务键: {target_task_key}")
            # print("="*40 + "\n")

    def move_to_next(self, status: str = "SUCCESS", output: str = "", output_file: list = None, notes: str = ""):
        """
        将当前 processing 状态的最深层任务标记为指定的 status (默认 SUCCESS，也可传 FAIL)，并存入相关执行结果。
        通过任务栈机制 (Call Stack) 自动寻找下一个 PENDING 任务。
        如果当前任务已全部完成，将自动出栈 (Pop)，返回父级任务上下文。
        """
        if output_file is None:
            output_file = []
            
        stack = self._build_execution_stack()
        if not stack:
            self.print_processing_status()
            return
            
        # 获取栈顶任务 (当前正在执行的最深层任务)
        parent_dict, current_key, current_node, current_path = stack[-1]
        
        current_task_name = current_node.get("task") if isinstance(current_node, dict) else current_node.task
        
        # 1. 标记当前任务完成
        if isinstance(current_node, dict):
            current_node["status"] = status
            current_node["output"] = output
            current_node["output_file"] = output_file
            current_node["notes"] = notes
        else:
            current_node.status = status
            current_node.output = output
            current_node.output_file = output_file
            current_node.notes = notes
            
        # 2. 寻找当前层级的下一个任务
        valid_keys = [k for k in parent_dict.keys() if k != "subtasks"]
        current_idx = valid_keys.index(current_key)
        
        next_task_name = None
        next_key = None
        
        # 在同层级找下一个 PENDING 任务
        for i in range(current_idx + 1, len(valid_keys)):
            k = valid_keys[i]
            v = parent_dict[k]
            v_status = v.get("status") if isinstance(v, dict) else v.status
            if v_status == "PENDING":
                next_key = k
                next_node = v
                next_task_name = v.get("task") if isinstance(v, dict) else v.task
                
                # 标记为 PROCESSING
                if isinstance(next_node, dict):
                    next_node["status"] = "PROCESSING"
                else:
                    next_node.status = "PROCESSING"
                break
                
        # 3. 如果当前层级没有下一个任务了，触发多米诺骨牌式出栈
        if not next_task_name:
            # 当前节点刚才已经被标记为 SUCCESS 了，现在把它的栈帧弹出
            stack.pop()
            
            # 由于用户的强制要求：任务全部完成时，绝对不能自动将父节点标记为 SUCCESS，
            # 而是必须停留在父节点的 PROCESSING 状态，等待用户后续手动执行一次 next-step 来确认完成父级任务。
            # 因此，如果发生出栈，我们只需要弹出当前已完成的任务层级即可。
            if stack:
                # 获取新的栈顶（父节点），它依然保持着原有的 PROCESSING 状态
                parent_layer_node = stack[-1][2]
                parent_layer_name = parent_layer_node.get("task") if isinstance(parent_layer_node, dict) else parent_layer_node.task
                print(f"⬆️ 当前任务已全部完成，任务栈出栈，返回父级任务: '{parent_layer_name}'")
                    
        level_name, chain_str = self.get_current_level_chain()
        
        print("\n" + "="*40)
        if current_task_name:
            print(f"✅ 成功将任务 '{current_task_name}' 标记为 {status}。")
            
        if next_task_name:
            print(f"➡️ 下一个执行任务已更新为: '{next_task_name}'")
        elif not stack:
            print("🎉 所有任务栈已全部执行完毕！")
                
        if chain_str:
            print(f"当前层级任务为: {level_name}")
            print(f"执行链路为: {chain_str}")
        # print("="*40)
            
        self.print_processing_status()

def parse_skill_md(file_path: str) -> TaskTracker:
    """
    解析 SKILL.md 文件，提取任务步骤，并初始化为一个 TaskTracker 对象。
    默认会将第一个任务的状态初始化为 PROCESSING。
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 尝试提取 skill 名称
    skill_name = "unknown-skill"
    name_match = re.search(r'name:\s*([^\n]+)', content)
    if name_match:
        skill_name = name_match.group(1).strip()
    else:
        # 降级：从一级标题提取
        name_match = re.search(r'#\s*(.*?)\s*\((.*?)\)', content)
        if name_match:
            skill_name = name_match.group(2).strip()
        else:
            # 降级：使用目录名
            skill_name = os.path.basename(os.path.dirname(file_path))

    tracker = TaskTracker(skill_name)
    
    lines = content.split('\n')
    
    # --- 预处理：寻找 dominant pattern ---
    # 我们不仅要记录每个层级（井号数量）出现的次数，还要记录在该层级下出现的 "index" (比如步骤1, 步骤2)。
    # dominant 的判断标准：该层级下的所有步骤 index 必须是没有重复的（如果重复，说明可能是 step 的 sub title）。
    # 如果有多个符合条件的层级，优先选择步骤数量最多的层级。
    explicit_level_indexes = {}
    fallback_level_indexes = {}
    
    for line in lines:
        line_stripped = line.strip()
        
        # 提取显式的 "第X步" 或 "步骤X"
        # 尝试匹配数字或中文数字，作为 index
        step_match = re.match(r'^(#{2,})\s+(?:第([一二三四五六七八九十百]+)步|步骤\s*(\d+)|Step\s*(\d+))(?:[:：]\s*|\s+)(.*)', line_stripped)
        if step_match:
            level = len(step_match.group(1))
            # 提取具体的 index (由于中文数字转阿拉伯数字较复杂，为了去重，直接存原始字符串即可)
            index_str = step_match.group(2) or step_match.group(3) or step_match.group(4)
            if level not in explicit_level_indexes:
                explicit_level_indexes[level] = []
            explicit_level_indexes[level].append(index_str)
        else:
            temp_match = re.match(r'^(#{2,})\s+(\d+)[\.\、](?:\s+)(.*)', line_stripped)
            if temp_match:
                level = len(temp_match.group(1))
                index_str = temp_match.group(2)
                if level not in fallback_level_indexes:
                    fallback_level_indexes[level] = []
                fallback_level_indexes[level].append(index_str)
                
    dominant_level = 0
    
    def find_dominant(level_indexes_dict):
        best_level = 0
        max_unique_count = 0
        for lvl, indexes in level_indexes_dict.items():
            # 判断是否有重复: 列表长度等于集合长度，说明没有重复
            if len(indexes) == len(set(indexes)):
                if len(indexes) > max_unique_count:
                    max_unique_count = len(indexes)
                    best_level = lvl
        return best_level

    dominant_level = find_dominant(explicit_level_indexes)
    if dominant_level == 0:
        dominant_level = find_dominant(fallback_level_indexes)
        
    current_step_id = None
    current_step = None
    step_counter = 1
    
    for line in lines:
        line = line.strip()
        
        # 匹配主步骤：
        step_match = re.match(r'^(#{2,})\s+(?:第[一二三四五六七八九十百]+步|步骤\s*\d+|Step\s*\d+)(?:[:：]\s*|\s+)(.*)', line)
        if not step_match:
            # 如果没有明确的步骤标记，且使用了 fallback 规则作为主步骤
            if not explicit_level_indexes:
                temp_match = re.match(r'^(#{2,})\s+(\d+)[\.\、](?:\s+)(.*)', line)
                if temp_match:
                    step_match = temp_match
        
        # 只有当匹配到的层级等于 dominant_level 时，才真正将其视为一个主步骤
        if step_match:
            matched_level = len(step_match.group(1))
            if dominant_level > 0 and matched_level != dominant_level:
                step_match = None
            
        if step_match:
            if current_step_id and current_step:
                tracker.add_step(current_step_id, current_step)
            
            # 根据正则分组，取最后一个非空的 group 字符串作为任务名
            task_name = step_match.groups()[-1].strip()
            current_step_id = f"step{step_counter}"
            step_counter += 1
            
            current_step = TaskStep(task=task_name)
            continue
            
        # 匹配子步骤：将子步骤的标题内容扁平化提取到 task_details 中
        # 注意：子步骤必须带有井号（#）且层级大于 dominant_level
        sub_step_match = re.match(r'^(#{2,})\s+(.*)', line)
        if sub_step_match and current_step:
            sub_level = len(sub_step_match.group(1))
            if dominant_level > 0 and sub_level > dominant_level:
                sub_task_name = sub_step_match.group(2).strip()
                current_step.task_details.append(sub_task_name)
                
    # 循环结束后加入最后一步
    if current_step_id and current_step:
        tracker.add_step(current_step_id, current_step)
        
    # 兜底逻辑：如果完全没有匹配到任何主步骤，则创建一个默认的全局任务
    if not tracker.steps:
        default_step = TaskStep(task=f"执行 {skill_name} 任务")
        tracker.add_step("step1", default_step)
        
    # 初始化时将第一个任务设置为 PROCESSING
    nodes = tracker.get_all_nodes()
    if nodes:
        nodes[0].status = "PROCESSING"
        
    return tracker

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse SKILL.md and generate/manage task_tracker.json")
    parser.add_argument("action", choices=["init", "print-current-task", "print-whole-task-stack", "next-step", "add-task", "delete-task"], help="Action to perform: init | print-current-task | print-whole-task-stack | next-step | add-task | delete-task")
    parser.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    parser.add_argument("--skill-md-path", help="Path to the SKILL.md file (required for init or add-task action)")
    
    # next-step 专属参数
    parser.add_argument("--status", choices=["SUCCESS", "FAIL"], default="SUCCESS", help="Status to mark the current task (used with next-step)")
    parser.add_argument("--output", default="", help="Output description for the current task (used with next-step)")
    parser.add_argument("--output-file", nargs='*', default=[], help="List of output files generated (used with next-step)")
    parser.add_argument("--notes", default="", help="Additional notes for the current task (used with next-step)")
    
    # delete-task 专属参数
    parser.add_argument("--task-path", help="Path to the task to delete (required for delete-task action)")
    
    args = parser.parse_args()
    
    try:
        # 获取 session 对应的输出目录
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "task-tracker"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        folder = result.stdout.strip()
        
        if result.returncode != 0 or not folder or "Error" in folder or "Warning" in folder:
            detail = result.stderr.strip() or folder
            raise ValueError(f"Could not resolve output directory: {detail}")
            
        # 确保目录存在
        os.makedirs(folder, exist_ok=True)
        output_file = os.path.join(folder, "task_tracker.json")
        
        if args.action == "init":
            if not args.skill_md_path:
                raise ValueError("--skill-md-path is required for 'init' action")
            tracker = parse_skill_md(args.skill_md_path)
            tracker.save_to_json(output_file)
            print(f"Successfully generated and initialized task tracker to: {output_file}")
            tracker.print_processing_status()
            
        elif args.action == "print-current-task":
            if not os.path.exists(output_file):
                raise FileNotFoundError(f"Task tracker not found at {output_file}. Please run 'init' first.")
            tracker = TaskTracker.load_from_json(output_file)
            tracker.print_current_task()

        elif args.action == "print-whole-task-stack":
            if not os.path.exists(output_file):
                raise FileNotFoundError(f"Task tracker not found at {output_file}. Please run 'init' first.")
            tracker = TaskTracker.load_from_json(output_file)
            tracker.print_whole_task_stack()
            
        elif args.action == "next-step":
            if not os.path.exists(output_file):
                raise FileNotFoundError(f"Task tracker not found at {output_file}. Please run 'init' first.")
            tracker = TaskTracker.load_from_json(output_file)
            tracker.move_to_next(status=args.status, output=args.output, output_file=args.output_file, notes=args.notes)
            tracker.save_to_json(output_file)
            
        elif args.action == "add-task":
            if not os.path.exists(output_file):
                raise FileNotFoundError(f"Task tracker not found at {output_file}. Please run 'init' first.")
            if not args.skill_md_path:
                raise ValueError("--skill-md-path is required for 'add-task' action")
            
            # 解析技能的 md，如果不作为技能而是新主技能，我们会在 add_task 中处理
            task_tracker = parse_skill_md(args.skill_md_path)
            
            # 加载现有的 tracker
            main_tracker = TaskTracker.load_from_json(output_file)
            
            # 如果主任务队列已经全空了，那么新加入的技能应该作为一个全新的 main:xxx
            nodes = main_tracker.get_all_nodes()
            has_processing = any(node.status == "PROCESSING" for node in nodes)
            
            if not has_processing:
                # 保留其主技能前缀
                task_tracker.is_main = True
            else:
                # 正常作为技能挂载
                task_tracker.is_main = False 
                
            main_tracker.add_task(task_tracker.skill_name, task_tracker)
            main_tracker.save_to_json(output_file)
            
        elif args.action == "delete-task":
            if not os.path.exists(output_file):
                raise FileNotFoundError(f"Task tracker not found at {output_file}. Please run 'init' first.")
            if not args.task_path:
                raise ValueError("--task-path is required for 'delete-task' action")
            
            tracker = TaskTracker.load_from_json(output_file)
            tracker.delete_task(args.task_path)
            tracker.save_to_json(output_file)
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
