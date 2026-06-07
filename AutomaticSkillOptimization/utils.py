import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from html import escape
from typing import Any

from AutomaticSkillOptimization.args import FAILED_DIR, HALF_STOPPED_DIR, OUTPUT_DIR

def safe_segment(value: Any) -> str:
    text = str(value or "thread").replace(os.sep, "_").replace("\0", "_").strip()
    return text or "thread"


def parse_result_dir_name(name, dataset_categories):
    base_name = name
    match = re.match(r"^agent:[^:]+:(.+)$", base_name)
    if match:
        base_name = match.group(1)

    for category in sorted(dataset_categories, key=len, reverse=True):
        prefix = category + "_"
        if base_name.startswith(prefix):
            remaining = base_name[len(prefix):]
            case_id = remaining.split("_")[0]
            return category, case_id, base_name
    return None, None, base_name


def terminate_processes(procs, grace_seconds: int = 2):
    """SIGTERM 一组子进程及其进程组; 等 grace_seconds 秒后 SIGKILL 未退出者。"""
    if not procs:
        return
    for proc in procs:
        try:
            if proc.returncode is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass
    time.sleep(grace_seconds)
    for proc in procs:
        try:
            if proc.returncode is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass


def _move_items_to_dir(src_dir, dst_dir):
    """把 src_dir 下所有条目 move 到 dst_dir；目标存在时先 rmtree。保留 src_dir。"""
    if not os.path.isdir(src_dir):
        return
    os.makedirs(dst_dir, exist_ok=True)
    for item in os.listdir(src_dir):
        src = os.path.join(src_dir, item)
        dst = os.path.join(dst_dir, item)
        try:
            if os.path.exists(dst):
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                else:
                    os.remove(dst)
            shutil.move(src, dst)
        except Exception as e:
            print(f"Failed to move {src} -> {dst}: {e}")


def archive_pipeline_dirs(exp_dir, time_prefix, pipeline_label,
                           failed_dir, new_failed_path,
                           half_stopped_dir, new_half_stopped_path,
                           running_dir):
    """通用 pipeline 收尾：搬 FAILED_DIR / HALF_STOPPED_DIR / RUNNING_DIR 到 exp_dir。"""
    _move_items_to_dir(failed_dir, new_failed_path)
    _move_items_to_dir(half_stopped_dir, new_half_stopped_path)

    new_running_dir = f"{time_prefix}_{pipeline_label}_{os.path.basename(running_dir)}"
    new_running_path = os.path.join(exp_dir, new_running_dir)
    if os.path.isdir(running_dir):
        if os.path.exists(new_running_path):
            shutil.rmtree(new_running_path)
        shutil.move(running_dir, new_running_path)
        print(f"Moved running dir to {new_running_path}")


def cleanup_skill_dir(skill_dir, skill_names):
    """从 active skill 目录中移除已处理的 skill。"""
    if not skill_dir:
        return
    for skill_name in skill_names:
        p = os.path.join(skill_dir, skill_name)
        if os.path.isdir(p):
            shutil.rmtree(p)


VISION_GEN_COST = {
    "image_cost_per_image": 0,
    "video_cost_per_million_no_video_input": 0,
    "video_cost_per_million_video_input": 0,
    "unit": "N/A",
}


class Logger(object):
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "a", encoding="utf-8")

    def write(self, message):
        if message.strip():
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"[{timestamp}] {message}"
            if not message.endswith("\n"):
                message += "\n"
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()


def find_final_video_paths(output_dir):
    """Find final video candidates in priority order."""
    video_files = []
    for root, dirs, files in os.walk(output_dir):
        dirs.sort()
        for file_name in sorted(files):
            if file_name.endswith(".mp4"):
                video_files.append(os.path.join(root, file_name))

    exact_final_paths = [
        path for path in video_files
        if os.path.basename(path) == "final.mp4"
    ]
    if exact_final_paths:
        return exact_final_paths

    final_prefix_paths = [
        path for path in video_files
        if os.path.basename(path).startswith("final")
    ]
    if final_prefix_paths:
        return final_prefix_paths

    return [
        path for path in video_files
        if os.path.basename(path).startswith("merged")
    ]


def calculate_rgt(session_dir, duration_seconds):
    """用 ffprobe 读取 final.mp4 时长，返回 Relative Generation Time。"""
    if not session_dir or not os.path.isdir(session_dir) or not duration_seconds:
        return None
    final_video_paths = find_final_video_paths(session_dir)
    final_video_path = final_video_paths[0] if final_video_paths else None
    if not final_video_path:
        return None
    try:
        duration_output = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", final_video_path],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        video_duration_seconds = float(duration_output)
        if video_duration_seconds > 0:
            return round(duration_seconds / video_duration_seconds, 6)
    except Exception:
        pass
    return None


def parse_vision_gen_logs(session_dir):
    """解析 session_dir 下所有 run.log 的视觉生成统计（interval-based merging）。

    Returns dict:
        image_count, image_tokens, image_gen_dur,
        video_tokens_no_input, video_tokens_with_input, video_gen_dur, video_tokens
    """
    image_count = 0
    image_tokens = 0
    video_tokens_no_input = 0
    video_tokens_with_input = 0

    generation_duration_pattern = re.compile(r'(?:所用时间|消耗时间):\s*(\d+)min,\s*(\d+)sec')
    generation_interval_pattern = re.compile(
        r'(?:开始时间|对应启动时间):\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}).*?结束时间:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'
    )
    image_generation_intervals = []
    video_generation_intervals = []

    def _parse_interval(line):
        m = generation_interval_pattern.search(line)
        if not m:
            return None
        try:
            s = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
            e = datetime.strptime(m.group(2), "%Y-%m-%d %H:%M:%S").timestamp()
            return (s, e) if e >= s else None
        except ValueError:
            return None

    def _merged_duration(intervals):
        if not intervals:
            return 0.0
        dur = 0.0
        cs, ce = sorted(intervals)[0]
        for s, e in sorted(intervals)[1:]:
            if s <= ce:
                ce = max(ce, e)
            else:
                dur += ce - cs
                cs, ce = s, e
        return dur + ce - cs

    img_fb = 0.0
    vid_fb = 0.0
    pending_img = None
    pending_vid = None

    for root, _, files in os.walk(session_dir):
        if "run.log" not in files:
            continue
        log_path = os.path.join(root, "run.log")
        try:
            parts = log_path.split(os.sep)
            with open(log_path, "r", encoding="utf-8") as lf:
                for line in lf:
                    if "Successfully saved image:" in line and "images" in parts:
                        image_count += 1
                    elif "Token Used:" in line:
                        tm = re.search(r'Token Used:\s*([\d,]+)', line)
                        if tm:
                            tokens = int(tm.group(1).replace(',', ''))
                            if "images" in parts:
                                image_tokens += tokens
                            elif "videos" in parts:
                                if "Video Input: True" in line:
                                    video_tokens_with_input += tokens
                                elif "Video Input: False" in line:
                                    video_tokens_no_input += tokens
                    elif "任务启动时间:" in line:
                        if "images" in parts and pending_img is not None:
                            img_fb += pending_img; pending_img = None
                        if "videos" in parts and pending_vid is not None:
                            vid_fb += pending_vid; pending_vid = None
                    elif "任务结束" in line:
                        iv = _parse_interval(line)
                        if iv:
                            if "images" in parts:
                                image_generation_intervals.append(iv); pending_img = None
                            elif "videos" in parts:
                                video_generation_intervals.append(iv); pending_vid = None
                    elif ("任务生成完成" in line or "任务失败" in line) and ("所用时间:" in line or "消耗时间:" in line):
                        iv = _parse_interval(line)
                        if iv:
                            if "images" in parts:
                                image_generation_intervals.append(iv)
                            elif "videos" in parts:
                                video_generation_intervals.append(iv)
                        else:
                            dm = generation_duration_pattern.search(line)
                            if dm:
                                secs = int(dm.group(1)) * 60 + int(dm.group(2))
                                if "images" in parts:
                                    pending_img = secs
                                elif "videos" in parts:
                                    pending_vid = secs
            if "images" in parts and pending_img is not None:
                img_fb += pending_img
            if "videos" in parts and pending_vid is not None:
                vid_fb += pending_vid
        except Exception:
            pass

    image_gen_dur = _merged_duration(image_generation_intervals) + img_fb
    video_gen_dur = _merged_duration(video_generation_intervals) + vid_fb

    return {
        "image_count": image_count,
        "image_tokens": image_tokens,
        "image_gen_dur": round(image_gen_dur, 2),
        "video_tokens_no_input": video_tokens_no_input,
        "video_tokens_with_input": video_tokens_with_input,
        "video_gen_dur": round(video_gen_dur, 2),
        "video_tokens": video_tokens_no_input + video_tokens_with_input,
    }


def build_vision_gen_cost(parsed):
    """从 parse_vision_gen_logs 的返回值构建 vision_gen_cost 字段。"""
    image_gen_cost = parsed["image_count"] * VISION_GEN_COST.get("image_cost_per_image", 0)
    video_gen_cost = (
        (parsed["video_tokens_no_input"] / 1_000_000) * VISION_GEN_COST.get("video_cost_per_million_no_video_input", 0)
        + (parsed["video_tokens_with_input"] / 1_000_000) * VISION_GEN_COST.get("video_cost_per_million_video_input", 0)
    )
    return {
        "image_count": parsed["image_count"],
        "image_tokens": parsed["image_tokens"],
        "image_generation_duration": parsed["image_gen_dur"],
        "video_tokens_no_input": parsed["video_tokens_no_input"],
        "video_tokens_with_input": parsed["video_tokens_with_input"],
        "video_tokens": parsed["video_tokens"],
        "video_generation_duration": parsed["video_gen_dur"],
        "cost": {
            "image": round(image_gen_cost, 6),
            "video": round(video_gen_cost, 6),
            "total": round(image_gen_cost + video_gen_cost, 6),
            "unit": VISION_GEN_COST.get("unit", "RMB"),
        },
    }


def calculate_vision_content_rgt(parsed_vision, duration_seconds):
    """计算 Vision Content Relative Generation Time。

    parsed_vision 需含 image_generation_duration 和 video_generation_duration。
    """
    if not duration_seconds or duration_seconds <= 0:
        return None
    total = parsed_vision.get("image_generation_duration", 0) + parsed_vision.get("video_generation_duration", 0)
    if total > 0:
        return round(total / duration_seconds, 6)
    return None


def print_success_rate_summary(max_retries, search_dirs=None, save_dir=None):
    """Scan all session folders for basic_results.json and print success rate @1, @2, ..., @max_retries."""
    if search_dirs is None:
        search_dirs = [OUTPUT_DIR, FAILED_DIR, HALF_STOPPED_DIR]
    task_results = []
    for folder in search_dirs:
        if not os.path.isdir(folder):
            continue
        for item in os.listdir(folder):
            result_file = os.path.join(folder, item, "basic_results.json")
            if os.path.isfile(result_file):
                try:
                    with open(result_file, "r", encoding="utf-8") as f:
                        task_results.append(json.load(f))
                except (json.JSONDecodeError, IOError):
                    pass

    if not task_results:
        print("No task results found.")
        return

    total = len(task_results)
    print(f"\n{'='*60}")
    print(f"Success Rate Summary (total tasks: {total})")
    print(f"{'='*60}")

    summary_data = {
        "total_tasks": total,
        "success_rates": {},
        "per_task_details": [],
    }

    for k in range(1, max_retries + 1):
        success_at_k = sum(1 for r in task_results if r["success"] and r["attempts"] <= k)
        rate = success_at_k / total * 100 if total > 0 else 0
        print(f"  success@{k}: {success_at_k}/{total} ({rate:.1f}%)")
        summary_data["success_rates"][f"success@{k}"] = {
            "success_count": success_at_k,
            "total": total,
            "rate_percent": rate,
        }

    print("\nPer-task details:")
    for r in task_results:
        status = "SUCCESS" if r["success"] else "FAILED"
        duration = r.get("duration_seconds", 0)
        attempt_errors = r.get("attempt_errors", [])
        print(f"  [{r['session_name']}] {status} after {r['attempts']} attempt(s), duration: {duration:.1f}s")
        for err in attempt_errors:
            print(f"    attempt {err['attempt']}: {err['error']}")

        summary_data["per_task_details"].append({
            "session_name": r["session_name"],
            "status": status,
            "attempts": r["attempts"],
            "duration_seconds": duration,
            "attempt_errors": attempt_errors,
        })
    print(f"{'='*60}\n")

    if save_dir and os.path.isdir(save_dir):
        summary_path = os.path.join(save_dir, "success_rate_summary.json")
        try:
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary_data, f, ensure_ascii=False, indent=4)
            print(f"Success rate summary successfully written to {summary_path}")
        except Exception as e:
            print(f"Failed to write success rate summary: {e}")


def restore_skill_creator_backup(original_creator_path, backup_creator_path):
    """Restore original skill creator directory from backup, deleting the temp one."""
    if os.path.exists(original_creator_path):
        shutil.rmtree(original_creator_path)
        print(f"Deleted temp skill creator {original_creator_path}")

    if backup_creator_path and os.path.exists(backup_creator_path):
        shutil.copytree(backup_creator_path, original_creator_path)
        print(f"Restored original video-skill-creator from {backup_creator_path} to {original_creator_path}")


def find_session_dir(session_name, *, agent_id=None, session_id=None, search_dirs=None):
    """在 search_dirs 下定位 session 输出文件夹。

    支持两种命名约定:
      - OpenClaw: agent:{agent_id}:{session_name}_{timestamp}
      - CodeX:    {session_name}_{session_id}
    agent_id/session_id 为 None 时通配。
    """
    if search_dirs is None:
        search_dirs = [OUTPUT_DIR, FAILED_DIR, HALF_STOPPED_DIR]

    for folder in search_dirs:
        if not folder or not os.path.isdir(folder):
            continue
        try:
            items = sorted(
                os.listdir(folder),
                key=lambda name: os.path.getmtime(os.path.join(folder, name)),
                reverse=True,
            )
        except OSError:
            continue
        for item in items:
            item_path = os.path.join(folder, item)
            if not os.path.isdir(item_path):
                continue
            clean = item
            for tag in ("failed_", "half_stopped_"):
                if clean.startswith(tag):
                    clean = clean[len(tag):]
                    break

            # OpenClaw: agent:{agent_id}:{session_name}_
            if agent_id is not None:
                if re.match(rf"^agent:{re.escape(agent_id)}:{re.escape(session_name)}_", clean):
                    return item_path
            elif re.match(rf"^agent:[^:]+:{re.escape(session_name)}_", clean):
                return item_path

            # CodeX: {session_name}_{session_id}
            if clean.startswith(f"{session_name}_"):
                if session_id is None or clean.endswith(f"_{session_id}") or str(session_id) in clean:
                    return item_path

    return None


def move_to_failed_output(session_name, *, agent_id=None, session_id=None):
    src_path = find_session_dir(session_name, agent_id=agent_id, session_id=session_id, search_dirs=[OUTPUT_DIR])
    if not src_path:
        return
    dst = os.path.join(FAILED_DIR, "failed_" + os.path.basename(src_path))
    os.makedirs(FAILED_DIR, exist_ok=True)
    if os.path.exists(dst):
        shutil.rmtree(dst) if os.path.isdir(dst) else os.remove(dst)
    shutil.move(src_path, dst)


def move_to_half_stopped_output(session_name, *, agent_id=None, session_id=None):
    src_path = find_session_dir(session_name, agent_id=agent_id, session_id=session_id, search_dirs=[OUTPUT_DIR])
    if not src_path:
        return
    dst = os.path.join(HALF_STOPPED_DIR, "half_stopped_" + os.path.basename(src_path))
    os.makedirs(HALF_STOPPED_DIR, exist_ok=True)
    if os.path.exists(dst):
        shutil.rmtree(dst) if os.path.isdir(dst) else os.remove(dst)
    shutil.move(src_path, dst)


def save_basic_result(session_name, *, agent_id=None, session_id=None, output_dir=None,
                      success=True, attempts=1, max_retries=1, attempt_errors=None,
                      duration_seconds=0, backbone_cost=None, tool_call_count=0):
    if output_dir is None:
        output_dir = find_session_dir(session_name, agent_id=agent_id, session_id=session_id, search_dirs=[OUTPUT_DIR])
        if output_dir is None:
            print(f"[{session_name}] Warning: session output folder not found, skip basic_results.json")
            return None
    os.makedirs(output_dir, exist_ok=True)

    rgt = calculate_rgt(output_dir, duration_seconds)
    parsed = parse_vision_gen_logs(output_dir)
    vision = build_vision_gen_cost(parsed)
    vision_content_rgt = calculate_vision_content_rgt(vision, duration_seconds)

    result = {
        "session_name": session_name,
        "success": success,
        "attempts": attempts,
        "max_retries": max_retries,
        "attempt_errors": attempt_errors or [],
        "duration_seconds": round(duration_seconds, 2),
        "Relative Generation Time (RGT)": rgt,
        "Vision Content Relative Generation Time": vision_content_rgt,
        "tool_call_count": tool_call_count,
        "vision_gen_cost": vision,
        "timestamp": datetime.now().isoformat(),
    }
    if backbone_cost is not None:
        result["backbone_cost"] = backbone_cost

    out = os.path.join(output_dir, "basic_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
    return out


def process_input(sub_dir_path, task_prefix, task_prefix_wo_tracker=None, add_task_tracker=True):
    """将子文件夹下的文件组合成 input context。

    参数:
        sub_dir_path: 子文件夹路径
        task_prefix: 带 task-tracker 的任务前缀
        task_prefix_wo_tracker: 不带 task-tracker 的任务前缀,默认回退到 task_prefix
        add_task_tracker: 是否使用带 task-tracker 的版本
    """
    input_context_parts = []
    if add_task_tracker:
        input_context_parts.append(task_prefix)
    else:
        input_context_parts.append(task_prefix_wo_tracker or task_prefix)

    txt_files = []
    img_files = []
    video_files = []
    audio_files = []

    if not os.path.exists(sub_dir_path):
        return ""

    for filename in os.listdir(sub_dir_path):
        filepath = os.path.abspath(os.path.join(sub_dir_path, filename))
        if not os.path.isfile(filepath):
            continue

        ext = os.path.splitext(filename)[1].lower()
        if ext == '.txt':
            txt_files.append((filename, filepath))
        elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
            img_files.append(filepath)
        elif ext in ['.mp4', '.avi', '.mov', '.mkv', '.webm']:
            video_files.append(filepath)
        elif ext in ['.mp3', '.wav', '.aac', '.flac', '.m4a']:
            audio_files.append(filepath)

    # 处理 txt 文件
    txt_files.sort(key=lambda x: x[0])
    for filename, filepath in txt_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            name_without_ext = os.path.splitext(filename)[0]
            input_context_parts.append(f"{name_without_ext}：\n{content}")
        except Exception as e:
            print(f"Error reading {filepath}: {e}")

    # 处理图片
    if img_files:
        img_files.sort(key=lambda x: os.path.basename(x))
        img_str = "这些是参考图片：\n" + "\n".join(img_files)
        input_context_parts.append(img_str)

    # 处理视频
    if video_files:
        video_files.sort(key=lambda x: os.path.basename(x))
        video_str = "这些是参考视频：\n" + "\n".join(video_files)
        input_context_parts.append(video_str)

    # 处理音频
    if audio_files:
        audio_files.sort(key=lambda x: os.path.basename(x))
        audio_str = "这些是参考音频：\n" + "\n".join(audio_files)
        input_context_parts.append(audio_str)

    return "\n\n".join(input_context_parts)


def generate_basic_results_summary(new_generate_materials_dir):
    """
    遍历生成目录下的 basic_results.json 文件, 统计 duration, RGT, tool call, gen token 和 cost
    按照 category 进行 average 统计，并保存到 basic_results_summary.json 和 basic_results_summary.md
    """
    if not os.path.isdir(new_generate_materials_dir):
        return

    def write_basic_markdown_table(summary_data, output_path):
        excluded_fields = {"rgt_count", "count", "cost", "image_cost", "video_cost", "backbone_cost"}
        average_by_category = summary_data.get("average_by_category", {})
        overall_average = summary_data.get("overall_average", {})

        def normalize_row(row_data):
            normalized = dict(row_data)
            if "rgt_cases" in normalized:
                normalized["rgt_case_count"] = normalized.pop("rgt_cases")
            if "vision_content_rgt_cases" in normalized:
                normalized["vision_content_rgt_case_count"] = normalized.pop("vision_content_rgt_cases")
            if "total_cases" in normalized:
                normalized["case_count"] = normalized.pop("total_cases")
            return normalized

        normalized_by_category = {
            category: normalize_row(category_data)
            for category, category_data in average_by_category.items()
        }
        normalized_overall_average = normalize_row(overall_average) if overall_average else {}
        fields = []

        for row_data in list(normalized_by_category.values()) + ([normalized_overall_average] if normalized_overall_average else []):
            for field in row_data.keys():
                if field not in excluded_fields and field not in fields:
                    fields.append(field)

        def format_cell(field, value):
            if value is None:
                return ""
            if field in {"video_gen_tokens", "backbone_total_tokens"} and isinstance(value, (int, float)):
                return f"{value / 1_000_000:.2f}M"
            if field == "backbone_cacheRead_tokens" and isinstance(value, (int, float)):
                return f"{value / 1_000_000:.2f}M"
            if field in {"image_gen_tokens", "backbone_input_tokens", "backbone_output_tokens"} and isinstance(value, (int, float)):
                return f"{value / 1_000:.2f}K"
            if field == "image_gen_tokens" and isinstance(value, (int, float)):
                return f"{value / 1_000:.2f}K"
            if isinstance(value, float):
                return f"{value:.2f}"
            return str(value)

        lines = []
        lines.append("<table>")
        lines.append("  <thead>")
        lines.append("    <tr>")
        lines.append("      <th>数据集</th>")
        for field in fields:
            lines.append(f"      <th>{escape(field)}</th>")
        lines.append("    </tr>")
        lines.append("  </thead>")
        lines.append("  <tbody>")

        for category, category_data in normalized_by_category.items():
            lines.append("    <tr>")
            lines.append(f"      <td>{escape(category)}</td>")
            for field in fields:
                lines.append(f"      <td>{escape(format_cell(field, category_data.get(field)))}</td>")
            lines.append("    </tr>")

        if normalized_overall_average:
            lines.append("    <tr>")
            lines.append("      <td>All</td>")
            for field in fields:
                lines.append(f"      <td>{escape(format_cell(field, normalized_overall_average.get(field)))}</td>")
            lines.append("    </tr>")

        lines.append("  </tbody>")
        lines.append("</table>")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    category_stats = {}
    total_stats = {
        "duration": 0.0,
        "tool_call": 0.0,
        "video_gen_tokens": 0.0,
        "video_cost": 0.0,
        "image_gen_tokens": 0.0,
        "image_cost": 0.0,
        "backbone_total_tokens": 0.0,
        "backbone_input_tokens": 0.0,
        "backbone_output_tokens": 0.0,
        "backbone_cacheRead_tokens": 0.0,
        "backbone_cost": 0.0,
        "cost": 0.0,
        "relative_generation_time_rgt": 0.0,
        "rgt_count": 0,
        "vision_content_relative_generation_time": 0.0,
        "vision_content_rgt_count": 0,
        "count": 0
    }

    for item in os.listdir(new_generate_materials_dir):
        item_path = os.path.join(new_generate_materials_dir, item)
        if not os.path.isdir(item_path):
            continue

        basic_results_path = os.path.join(item_path, "basic_results.json")
        if not os.path.isfile(basic_results_path):
            continue

        try:
            with open(basic_results_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            session_name = data.get("session_name", "")
            if not session_name:
                continue

            category = session_name.split('_')[0]

            duration = data.get("duration_seconds", 0.0)
            rgt = data.get("Relative Generation Time (RGT)")
            vision_content_rgt = data.get("Vision Content Relative Generation Time")
            tool_call = data.get("tool_call_count", 0)

            vision_gen_cost_data = data.get("vision_gen_cost", {})
            backbone_cost_data = data.get("backbone_cost", {})

            if not isinstance(vision_content_rgt, (int, float)) and isinstance(duration, (int, float)) and duration > 0:
                image_generation_duration = vision_gen_cost_data.get("image_generation_duration")
                video_generation_duration = vision_gen_cost_data.get("video_generation_duration")
                if isinstance(image_generation_duration, (int, float)) and isinstance(video_generation_duration, (int, float)):
                    vision_content_rgt = (image_generation_duration + video_generation_duration) / duration

            video_gen_tokens = vision_gen_cost_data.get("video_tokens", 0)
            video_cost = vision_gen_cost_data.get("cost", {}).get("video", 0.0)

            image_gen_tokens = vision_gen_cost_data.get("image_tokens", 0)
            image_cost = vision_gen_cost_data.get("cost", {}).get("image", 0.0)

            backbone_total_tokens = backbone_cost_data.get("total_tokens", 0)
            backbone_input_tokens = backbone_cost_data.get("input_tokens", 0)
            backbone_output_tokens = backbone_cost_data.get("output_tokens", 0)
            backbone_cache_read_tokens = (
                backbone_cost_data.get("cacheRead_tokens")
                or backbone_cost_data.get("cache_read_input_tokens")
                or 0
            )
            bb_cost = backbone_cost_data.get("cost", {}).get("total", 0.0)

            vision_total_cost = vision_gen_cost_data.get("cost", {}).get("total", 0.0)
            total_cost = vision_total_cost + bb_cost

            if category not in category_stats:
                category_stats[category] = {
                    "duration": 0.0,
                    "tool_call": 0.0,
                    "video_gen_tokens": 0.0,
                    "video_cost": 0.0,
                    "image_gen_tokens": 0.0,
                    "image_cost": 0.0,
                    "backbone_total_tokens": 0.0,
                    "backbone_input_tokens": 0.0,
                    "backbone_output_tokens": 0.0,
                    "backbone_cacheRead_tokens": 0.0,
                    "backbone_cost": 0.0,
                    "cost": 0.0,
                    "relative_generation_time_rgt": 0.0,
                    "rgt_count": 0,
                    "vision_content_relative_generation_time": 0.0,
                    "vision_content_rgt_count": 0,
                    "count": 0
                }

            category_stats[category]["duration"] += duration
            if isinstance(rgt, (int, float)):
                category_stats[category]["relative_generation_time_rgt"] += rgt
                category_stats[category]["rgt_count"] += 1
            if isinstance(vision_content_rgt, (int, float)):
                category_stats[category]["vision_content_relative_generation_time"] += vision_content_rgt
                category_stats[category]["vision_content_rgt_count"] += 1
            category_stats[category]["tool_call"] += tool_call
            category_stats[category]["video_gen_tokens"] += video_gen_tokens
            category_stats[category]["video_cost"] += video_cost
            category_stats[category]["image_gen_tokens"] += image_gen_tokens
            category_stats[category]["image_cost"] += image_cost
            category_stats[category]["backbone_total_tokens"] += backbone_total_tokens
            category_stats[category]["backbone_input_tokens"] += backbone_input_tokens
            category_stats[category]["backbone_output_tokens"] += backbone_output_tokens
            category_stats[category]["backbone_cacheRead_tokens"] += backbone_cache_read_tokens
            category_stats[category]["backbone_cost"] += bb_cost
            category_stats[category]["cost"] += total_cost
            category_stats[category]["count"] += 1

            total_stats["duration"] += duration
            if isinstance(rgt, (int, float)):
                total_stats["relative_generation_time_rgt"] += rgt
                total_stats["rgt_count"] += 1
            if isinstance(vision_content_rgt, (int, float)):
                total_stats["vision_content_relative_generation_time"] += vision_content_rgt
                total_stats["vision_content_rgt_count"] += 1
            total_stats["tool_call"] += tool_call
            total_stats["video_gen_tokens"] += video_gen_tokens
            total_stats["video_cost"] += video_cost
            total_stats["image_gen_tokens"] += image_gen_tokens
            total_stats["image_cost"] += image_cost
            total_stats["backbone_total_tokens"] += backbone_total_tokens
            total_stats["backbone_input_tokens"] += backbone_input_tokens
            total_stats["backbone_output_tokens"] += backbone_output_tokens
            total_stats["backbone_cacheRead_tokens"] += backbone_cache_read_tokens
            total_stats["backbone_cost"] += bb_cost
            total_stats["cost"] += total_cost
            total_stats["count"] += 1

        except Exception as e:
            print(f"Failed to process {basic_results_path}: {e}")

    summary = {
        "average_by_category": {},
        "overall_average": {},
        "overall_total": {}
    }

    for cat, stats in category_stats.items():
        count = stats["count"]
        if count > 0:
            rgt_count = stats["rgt_count"]
            vision_content_rgt_count = stats["vision_content_rgt_count"]
            cache_eligible_tokens = stats["backbone_input_tokens"] + stats["backbone_cacheRead_tokens"]
            summary["average_by_category"][cat] = {
                "duration": stats["duration"] / count,
                "Relative Generation Time (RGT)": stats["relative_generation_time_rgt"] / rgt_count if rgt_count > 0 else None,
                "Vision Content Relative Generation Time": stats["vision_content_relative_generation_time"] / vision_content_rgt_count if vision_content_rgt_count > 0 else None,
                "tool_call": stats["tool_call"] / count,
                "video_gen_tokens": stats["video_gen_tokens"] / count,
                "video_cost": stats["video_cost"] / count,
                "image_gen_tokens": stats["image_gen_tokens"] / count,
                "image_cost": stats["image_cost"] / count,
                "backbone_total_tokens": stats["backbone_total_tokens"] / count,
                "cache_hit_rate": stats["backbone_cacheRead_tokens"] / cache_eligible_tokens if cache_eligible_tokens > 0 else None,
                "backbone_input_tokens": stats["backbone_input_tokens"] / count,
                "backbone_output_tokens": stats["backbone_output_tokens"] / count,
                "backbone_cacheRead_tokens": stats["backbone_cacheRead_tokens"] / count,
                "backbone_cost": stats["backbone_cost"] / count,
                "cost": stats["cost"] / count,
                "rgt_case_count": rgt_count,
                "vision_content_rgt_case_count": vision_content_rgt_count,
                "case_count": count
            }

    if total_stats["count"] > 0:
        count = total_stats["count"]
        rgt_count = total_stats["rgt_count"]
        vision_content_rgt_count = total_stats["vision_content_rgt_count"]
        cache_eligible_tokens = total_stats["backbone_input_tokens"] + total_stats["backbone_cacheRead_tokens"]
        summary["overall_average"] = {
            "duration": total_stats["duration"] / count,
            "Relative Generation Time (RGT)": total_stats["relative_generation_time_rgt"] / rgt_count if rgt_count > 0 else None,
            "Vision Content Relative Generation Time": total_stats["vision_content_relative_generation_time"] / vision_content_rgt_count if vision_content_rgt_count > 0 else None,
            "tool_call": total_stats["tool_call"] / count,
            "video_gen_tokens": total_stats["video_gen_tokens"] / count,
            "video_cost": total_stats["video_cost"] / count,
            "image_gen_tokens": total_stats["image_gen_tokens"] / count,
            "image_cost": total_stats["image_cost"] / count,
            "backbone_total_tokens": total_stats["backbone_total_tokens"] / count,
            "cache_hit_rate": total_stats["backbone_cacheRead_tokens"] / cache_eligible_tokens if cache_eligible_tokens > 0 else None,
            "backbone_input_tokens": total_stats["backbone_input_tokens"] / count,
            "backbone_output_tokens": total_stats["backbone_output_tokens"] / count,
            "backbone_cacheRead_tokens": total_stats["backbone_cacheRead_tokens"] / count,
            "backbone_cost": total_stats["backbone_cost"] / count,
            "cost": total_stats["cost"] / count,
            "rgt_cases": rgt_count,
            "vision_content_rgt_cases": vision_content_rgt_count,
            "total_cases": count
        }

        summary["overall_total"] = {
            "duration": total_stats["duration"],
            "Relative Generation Time (RGT)": total_stats["relative_generation_time_rgt"],
            "Vision Content Relative Generation Time": total_stats["vision_content_relative_generation_time"],
            "tool_call": total_stats["tool_call"],
            "video_gen_tokens": total_stats["video_gen_tokens"],
            "video_cost": total_stats["video_cost"],
            "image_gen_tokens": total_stats["image_gen_tokens"],
            "image_cost": total_stats["image_cost"],
            "backbone_total_tokens": total_stats["backbone_total_tokens"],
            "cache_hit_rate": total_stats["backbone_cacheRead_tokens"] / cache_eligible_tokens if cache_eligible_tokens > 0 else None,
            "backbone_input_tokens": total_stats["backbone_input_tokens"],
            "backbone_output_tokens": total_stats["backbone_output_tokens"],
            "backbone_cacheRead_tokens": total_stats["backbone_cacheRead_tokens"],
            "backbone_cost": total_stats["backbone_cost"],
            "cost": total_stats["cost"],
            "rgt_cases": rgt_count,
            "vision_content_rgt_cases": vision_content_rgt_count,
            "total_cases": count
        }

    summary_path = os.path.join(new_generate_materials_dir, "basic_results_summary.json")
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=4)
        print(f"Basic results summary successfully written to {summary_path}")
    except Exception as e:
        print(f"Failed to write basic results summary: {e}")

    summary_markdown_path = os.path.join(new_generate_materials_dir, "basic_results_summary.md")
    try:
        write_basic_markdown_table(summary, summary_markdown_path)
        print(f"Basic results markdown table successfully written to {summary_markdown_path}")
    except Exception as e:
        print(f"Failed to write basic results markdown table: {e}")
