import argparse
import asyncio
import json
import os
import shutil
import signal
import sys
import time
from datetime import datetime

from tqdm import tqdm

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from AutomaticSkillOptimization.prompts import build_optimize_prompt, PAIRWISE_CREATOR_MERGE_PROMPT
from AutomaticSkillOptimization.args import CODEX_BIN, CODEX_WORKSPACE, DATASET_DIR, FOUNDATION_SKILLS_DIR, OUTPUT_DIR, RUNNING_DIR, setup_codex_workspace
from AutomaticSkillOptimization.utils import Logger, safe_segment
from AutomaticSkillOptimization.inference_CodeX.codex_cli_tool import (
    calculate_cost_from_jsonl,
    find_latest_rollout_after,
    find_rollout_by_session_id,
    jsonl_to_react_process,
    load_jsonl_file,
    load_jsonl_text,
    summarize_codex_records,
    write_jsonl_records,
)
from AutomaticSkillOptimization.utils import save_basic_result, terminate_processes
from AutomaticSkillOptimization.optimize.optimization_utils import (
    EXCLUDED_OBJECTIVE_CRITERIA,
    archive_dir_if_exists,
    generate_optimization_diffs,
    has_low_score,
    iter_rubric_items,
    load_eval_data,
    load_allowed_cases,
    parse_result_dir_name,
    prepare_eval_data,
)
active_processes = set()
done_sessions = set()
failed_sessions = set()
dataset_work_dirs = []
creator_merge_work_dirs = []
OPTIMIZE_RUNNING_DIR = f"{RUNNING_DIR}_optimize"


def ensure_shared_codex_cwd(args):
    setup_codex_workspace()
    print(f"[Codex cwd] Skill load path: {os.path.join(CODEX_WORKSPACE, '.agents', 'skills')}")


def read_skill_name(dataset_dir, category):
    skill_query_path = os.path.join(dataset_dir, category, "skill_query.json")
    if not os.path.isfile(skill_query_path):
        return None
    try:
        with open(skill_query_path, "r", encoding="utf-8") as f:
            return json.load(f).get("skill_name")
    except Exception:
        return None


def check_output_done(output_dir):
    react_file = os.path.join(output_dir, "ReAct_process.json")
    if not os.path.isfile(react_file):
        return False
    try:
        with open(react_file, "r", encoding="utf-8") as f:
            return len(json.load(f)) > 3
    except Exception:
        return False


def copy_skill_children_to_archive(source_skill_dir, archive_skill_dir, category):
    copied_skill_names = []
    if not os.path.isdir(source_skill_dir):
        return copied_skill_names

    os.makedirs(archive_skill_dir, exist_ok=True)
    for skill_name in sorted(os.listdir(source_skill_dir)):
        source_path = os.path.join(source_skill_dir, skill_name)
        if not os.path.isdir(source_path):
            continue
        target_path = os.path.join(archive_skill_dir, skill_name)
        if os.path.exists(target_path):
            raise FileExistsError(
                f"Duplicate optimized skill folder '{skill_name}' while archiving dataset {category}: {target_path}"
            )
        shutil.copytree(source_path, target_path)
        copied_skill_names.append(skill_name)
    return copied_skill_names


def case_sort_key(item):
    case_id = str(item["case_id"])
    if case_id.isdigit():
        return (0, int(case_id), item["name_without_prefix"])
    return (1, case_id, item["name_without_prefix"])


def find_successful_case_output(output_root, session_name):
    prefix = f"{safe_segment(session_name)}_"
    if not os.path.isdir(output_root):
        return None, None

    candidates = []
    for item in os.listdir(output_root):
        output_dir = os.path.join(output_root, item)
        if not item.startswith(prefix) or not os.path.isdir(output_dir):
            continue
        basic_result_path = os.path.join(output_dir, "basic_results.json")
        if os.path.isfile(basic_result_path):
            try:
                with open(basic_result_path, "r", encoding="utf-8") as f:
                    if not json.load(f).get("success"):
                        continue
            except Exception:
                continue
        elif not check_output_done(output_dir):
            continue

        session_id = item[len(prefix):]
        candidates.append((os.path.getmtime(output_dir), output_dir, session_id))

    if not candidates:
        return None, None
    _, output_dir, session_id = max(candidates, key=lambda item: item[0])
    return output_dir, session_id


def has_dataset_work_dirs(grouped_cases, args):
    for category in grouped_cases:
        work_dir = os.path.join(args.exp_dir, f"work_{safe_segment(category)}")
        if os.path.isdir(work_dir):
            return True
    return False


def find_latest_v2_manifest(exp_dir):
    if not os.path.isdir(exp_dir):
        return None, None
    suffix = "_codex_gpt_v2_opt_manifest.json"
    candidates = []
    for item in os.listdir(exp_dir):
        path = os.path.join(exp_dir, item)
        if os.path.isfile(path) and item.endswith(suffix):
            time_prefix = item[:-len(suffix)]
            candidates.append((os.path.getmtime(path), path, time_prefix))
    if not candidates:
        return None, None
    _, manifest_path, time_prefix = max(candidates, key=lambda item: item[0])
    return manifest_path, time_prefix


def load_archived_creator_results_for_merge(args, original_creator_skill_name):
    manifest_path, time_prefix = find_latest_v2_manifest(args.exp_dir)
    if not manifest_path:
        return None, None, []

    final_creator_dir = os.path.join(
        args.exp_dir,
        f"{time_prefix}_codex_gpt_v2_opt_{original_creator_skill_name}",
    )
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_records = json.load(f)

    if os.path.isdir(final_creator_dir):
        if not any(record.get("category") == "__creator_merge__" for record in manifest_records):
            update_manifest_with_creator_merge(manifest_path, final_creator_dir, [])
        return manifest_path, time_prefix, []

    creator_results = []
    for record in manifest_records:
        if record.get("category") == "__creator_merge__":
            continue
        creator_dir = record.get("creator_dir")
        if not creator_dir or not os.path.isdir(creator_dir):
            continue
        creator_results.append({
            "category": record.get("category"),
            "creator_dir": creator_dir,
            "session_id": record.get("session_id"),
        })
    return manifest_path, time_prefix, creator_results


def update_manifest_with_creator_merge(manifest_path, final_creator_dir, creator_merge_records):
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_records = json.load(f)

    manifest_records = [
        record for record in manifest_records
        if record.get("category") != "__creator_merge__"
    ]
    manifest_records.append({
        "category": "__creator_merge__",
        "cases": len(creator_merge_records),
        "session_id": creator_merge_records[-1]["session_id"] if creator_merge_records else None,
        "skill_dir": None,
        "skill_names": [],
        "creator_dir": final_creator_dir,
        "diff_index": None,
        "merge_records": creator_merge_records,
    })

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_records, f, ensure_ascii=False, indent=2)


def normalize_history_entries(history_entries):
    normalized = []
    for entry in history_entries or []:
        if len(entry) != 3:
            raise ValueError(
                "--history_task_result_composition_skill_creator_skill_dir expects repeated triples: "
                "TASK_RESULT_DIR COMPOSITION_SKILL_DIR CREATOR_SKILL_DIR"
            )
        task_result_dir, composition_skill_dir, creator_skill_dir = entry
        creator_skill_dir = str(creator_skill_dir).strip()
        if creator_skill_dir.lower() in {"", "none", "null"}:
            creator_skill_dir = None
        else:
            creator_skill_dir = os.path.abspath(os.path.expanduser(creator_skill_dir))
        normalized.append((
            os.path.abspath(os.path.expanduser(task_result_dir)),
            os.path.abspath(os.path.expanduser(composition_skill_dir)),
            creator_skill_dir,
        ))
    return normalized


def find_history_case_item(history_task_result_dir, current_info, dataset_categories):
    if not os.path.isdir(history_task_result_dir):
        return None

    matches = []
    for item in sorted(os.listdir(history_task_result_dir)):
        item_path = os.path.join(history_task_result_dir, item)
        if not os.path.isdir(item_path):
            continue
        if item.startswith(("eval_", "opt_", "failed_", "half_stopped_")):
            continue

        category, case_id, name_without_prefix = parse_result_dir_name(item, dataset_categories)
        if category != current_info["category"] or str(case_id) != str(current_info["case_id"]):
            continue

        react_file_path = os.path.join(item_path, "ReAct_process.json")
        has_react = os.path.isfile(react_file_path)
        exact_name = name_without_prefix == current_info["name_without_prefix"]
        matches.append((0 if exact_name else 1, 0 if has_react else 1, item_path, react_file_path, name_without_prefix))

    if not matches:
        return None

    _, _, item_path, react_file_path, name_without_prefix = sorted(matches)[0]
    return {
        "item_path": item_path,
        "react_file_path": react_file_path if os.path.isfile(react_file_path) else None,
        "name_without_prefix": name_without_prefix,
    }


def collect_history_cases(current_info, history_entries, dataset_categories):
    history_cases = []
    for history_index, (task_result_dir, composition_skill_dir, creator_skill_dir) in enumerate(history_entries or [], start=1):
        history_item = find_history_case_item(task_result_dir, current_info, dataset_categories)
        if not history_item:
            continue

        specific_skill_dir = os.path.join(composition_skill_dir, current_info["skill_name"])
        history_cases.append({
            "history_index": history_index,
            "task_result_dir": history_item["item_path"],
            "react_file_path": history_item["react_file_path"],
            "composition_skill_dir": specific_skill_dir if os.path.isdir(specific_skill_dir) else composition_skill_dir,
            "creator_skill_dir": creator_skill_dir,
            "matched_case_name": history_item["name_without_prefix"],
        })
    return history_cases


def append_history_context(optimize_prompt, history_cases):
    if not history_cases:
        return optimize_prompt

    lines = [
        "",
        "",
        "【同一个 case 的历史优化材料】:",
        "下面每一组历史材料都对应当前 case 的历史 task result、历史 skill result、历史 creator skill。",
        "请把它们和当前 case 的 task result、当前 skill、当前 creator skill 一起分析，用于判断哪些修改已经有效、哪些问题反复出现、哪些历史经验应该保留或修正。",
        "不要只照抄历史版本；最终仍然要基于当前 case 和当前工作目录做必要优化。",
    ]
    for history_case in history_cases:
        lines.extend([
            "",
            f"【History {history_case['history_index']} - matched case】:\n{history_case['matched_case_name']}",
            f"【History {history_case['history_index']} - task result folder】:\n{history_case['task_result_dir']}",
        ])
        if history_case["react_file_path"]:
            lines.append(f"【History {history_case['history_index']} - task trace file】:\n{history_case['react_file_path']}")
        lines.extend([
            f"【History {history_case['history_index']} - composition skill folder】:\n{history_case['composition_skill_dir']}",
        ])
        if history_case["creator_skill_dir"]:
            lines.append(f"【History {history_case['history_index']} - creator skill folder】:\n{history_case['creator_skill_dir']}")

    return optimize_prompt + "\n".join(lines)


def extract_dataset_objective_criteria(dataset_dir, category, case_id):
    objectives = []
    seen = set()
    case_dir = os.path.join(dataset_dir, category, str(case_id))
    for filename in ("rubric_deterministic.json", "rubric.json"):
        rubric_path = os.path.join(case_dir, filename)
        if not os.path.isfile(rubric_path):
            continue
        try:
            rubric_data = load_eval_data(rubric_path)
        except Exception:
            continue

        for item in iter_rubric_items(rubric_data):
            criterion = item.get("criterion")
            if not criterion:
                continue

            criterion = " ".join(str(criterion).split())
            if not criterion or criterion in seen:
                continue
            if criterion in EXCLUDED_OBJECTIVE_CRITERIA:
                continue

            natural_language_question = item.get("natural_language_question", "")
            if natural_language_question:
                natural_language_question = " ".join(str(natural_language_question).split())

            evaluation_guide = item.get("evaluation_guide", "")
            if evaluation_guide:
                evaluation_guide = " ".join(str(evaluation_guide).split())

            seen.add(criterion)
            objective = {"criterion": criterion}
            if evaluation_guide:
                objective["evaluation_guide"] = evaluation_guide
            if natural_language_question:
                objective["natural_language_question"] = natural_language_question
            objectives.append(objective)

    return objectives


def prepare_case_eval_data(item_path, args, category, case_id):
    if args.eval_source == "none":
        return {
            "objective_criteria": extract_dataset_objective_criteria(
                args.dataset_dir,
                category,
                case_id,
            )
        }

    return prepare_eval_data(item_path, args)




def creator_merge_snapshot_path(progressive_dir, step_index, category, original_creator_skill_name):
    step_name = f"{step_index:03d}_{safe_segment(category)}_{original_creator_skill_name}"
    return os.path.join(progressive_dir, step_name)


def snapshot_creator_merge_progress(
    progressive_dir,
    step_index,
    category,
    source_dir,
    original_creator_skill_name,
    overwrite=True,
):
    if not os.path.isdir(source_dir):
        return None

    os.makedirs(progressive_dir, exist_ok=True)
    snapshot_dir = creator_merge_snapshot_path(
        progressive_dir,
        step_index,
        category,
        original_creator_skill_name,
    )
    if os.path.exists(snapshot_dir):
        if not overwrite:
            return snapshot_dir
        shutil.rmtree(snapshot_dir)
    shutil.copytree(source_dir, snapshot_dir)
    return snapshot_dir


def restore_creator_merge_progress(snapshot_dir, target_dir):
    if not os.path.isdir(snapshot_dir):
        raise FileNotFoundError(f"Creator merge progress snapshot not found: {snapshot_dir}")
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    shutil.copytree(snapshot_dir, target_dir)


def previous_creator_merge_snapshot(progressive_dir, sorted_results, step_index, original_creator_skill_name):
    previous_index = step_index - 1
    previous_category = (
        f"base_{sorted_results[0]['category']}"
        if previous_index == 0
        else sorted_results[previous_index]["category"]
    )
    return creator_merge_snapshot_path(
        progressive_dir,
        previous_index,
        previous_category,
        original_creator_skill_name,
    )


async def merge_creator_skills_pairwise(results, args, time_prefix, original_creator_skill_name):
    global creator_merge_work_dirs

    sorted_results = sorted(results, key=lambda item: safe_segment(item["category"]))
    final_creator_dir = os.path.join(
        args.exp_dir,
        f"{time_prefix}_codex_gpt_v2_opt_{original_creator_skill_name}",
    )
    default_temp_creator_dir = os.path.join(
        args.exp_dir,
        f"temp_{time_prefix}_codex_gpt_v2_opt_{original_creator_skill_name}",
    )
    progressive_dir = os.path.join(
        args.exp_dir,
        f"{time_prefix}_progressive_merge_result",
    )
    restored_temp_creator_dir = find_latest_creator_merge_temp(
        args.exp_dir,
        original_creator_skill_name,
        time_prefix,
    ) if args.resume else None
    temp_creator_dir = restored_temp_creator_dir or default_temp_creator_dir
    if os.path.exists(final_creator_dir):
        shutil.rmtree(final_creator_dir)
    if not restored_temp_creator_dir and os.path.exists(temp_creator_dir):
        shutil.rmtree(temp_creator_dir)

    if not sorted_results:
        return final_creator_dir, []

    first_result = sorted_results[0]
    if not os.path.isdir(first_result["creator_dir"]):
        raise FileNotFoundError(f"Accumulator creator directory not found: {first_result['creator_dir']}")
    if restored_temp_creator_dir:
        print(f"[Resume] Reusing creator merge accumulator: {temp_creator_dir}")
    else:
        shutil.copytree(first_result["creator_dir"], temp_creator_dir)
    if temp_creator_dir not in creator_merge_work_dirs:
        creator_merge_work_dirs.append(temp_creator_dir)

    base_snapshot_was_existing = os.path.isdir(creator_merge_snapshot_path(
        progressive_dir,
        0,
        f"base_{first_result['category']}",
        original_creator_skill_name,
    ))
    base_snapshot_dir = snapshot_creator_merge_progress(
        progressive_dir,
        0,
        f"base_{first_result['category']}",
        temp_creator_dir,
        original_creator_skill_name,
        overwrite=not bool(restored_temp_creator_dir),
    )

    merge_records = [{
        "category": first_result["category"],
        "role": "initial_accumulator_base_copy",
        "accumulator_dir": temp_creator_dir,
        "final_creator_dir": final_creator_dir,
        "incoming_dir": first_result["creator_dir"],
        "progressive_snapshot_dir": base_snapshot_dir,
        "progressive_snapshot_reused": bool(restored_temp_creator_dir and base_snapshot_was_existing),
        "progressive_snapshot_reconstructed": bool(restored_temp_creator_dir and not base_snapshot_was_existing),
        "session_id": None,
        "output_dir": None,
        "success": True,
    }]

    session_id = None
    thread_name = f"v2_creator_merge_{time_prefix}"
    merge_output_root = os.path.join(args.output_root, "creator_merge")
    log_file = os.path.join(OPTIMIZE_RUNNING_DIR, f"v2_creator_merge_{time_prefix}.log")
    os.makedirs(merge_output_root, exist_ok=True)

    for step_index, incoming_result in enumerate(sorted_results[1:], start=1):
        incoming_creator_dir = incoming_result["creator_dir"]
        if not os.path.isdir(incoming_creator_dir):
            raise FileNotFoundError(f"Incoming creator directory not found: {incoming_creator_dir}")

        category_key = safe_segment(incoming_result["category"])
        session_name = f"v2_creator_merge_{category_key}_{original_creator_skill_name}"
        merge_prompt = PAIRWISE_CREATOR_MERGE_PROMPT.format(
            accumulator_creator_dir=os.path.abspath(temp_creator_dir),
            incoming_creator_dir=os.path.abspath(incoming_creator_dir),
        )

        if restored_temp_creator_dir:
            completed_output_dir, completed_session_id = find_successful_case_output(merge_output_root, session_name)
            if completed_output_dir and completed_session_id:
                snapshot_path = creator_merge_snapshot_path(
                    progressive_dir,
                    step_index,
                    incoming_result["category"],
                    original_creator_skill_name,
                )
                snapshot_was_existing = os.path.isdir(snapshot_path)
                if snapshot_was_existing:
                    restore_creator_merge_progress(snapshot_path, temp_creator_dir)
                    session_id = completed_session_id
                    merge_records.append({
                        "category": incoming_result["category"],
                        "role": "incoming_merged_resume_skip",
                        "accumulator_dir": temp_creator_dir,
                        "final_creator_dir": final_creator_dir,
                        "incoming_dir": incoming_creator_dir,
                        "progressive_snapshot_dir": snapshot_path,
                        "progressive_snapshot_reused": True,
                        "progressive_snapshot_reconstructed": False,
                        "session_id": session_id,
                        "output_dir": completed_output_dir,
                        "success": True,
                        "errors": [],
                    })
                    print(f"[Resume Skip] creator merge category={incoming_result['category']} output={completed_output_dir}")
                    continue
                print(
                    f"[Resume] Successful creator merge output exists for {incoming_result['category']} "
                    f"but snapshot is missing. Re-running this merge step from previous accumulator."
                )

            previous_snapshot = previous_creator_merge_snapshot(
                progressive_dir,
                sorted_results,
                step_index,
                original_creator_skill_name,
            )
            if os.path.isdir(previous_snapshot):
                restore_creator_merge_progress(previous_snapshot, temp_creator_dir)
                print(f"[Resume] Restored creator accumulator before {incoming_result['category']}: {previous_snapshot}")
            elif step_index == 1:
                if os.path.exists(temp_creator_dir):
                    shutil.rmtree(temp_creator_dir)
                shutil.copytree(first_result["creator_dir"], temp_creator_dir)
                print(f"[Resume] Rebuilt base creator accumulator before {incoming_result['category']}")
            else:
                raise RuntimeError(
                    f"Cannot resume creator merge for {incoming_result['category']}: "
                    f"previous progress snapshot missing: {previous_snapshot}"
                )

        success = False
        attempt_errors = []
        last_result = {}
        for attempt in range(args.max_retries):
            start_time = time.time()
            last_result = await run_codex_turn(
                thread_name,
                session_name,
                merge_prompt,
                args,
                CODEX_WORKSPACE,
                merge_output_root,
                log_file,
                resume_session_id=session_id,
            )
            if last_result.get("session_id"):
                session_id = last_result["session_id"]
            duration = time.time() - start_time

            if last_result.get("output_dir"):
                is_done = last_result.get("success") and check_output_done(last_result["output_dir"])
                error_msg = last_result.get("error") or last_result.get("stderr") or "Creator merge executed but ReAct_process.json missing/too short"
                current_attempt_errors = attempt_errors if is_done else attempt_errors + [{"attempt": attempt + 1, "error": str(error_msg)}]
                cost_data = calculate_cost_from_jsonl(session_id)
                save_basic_result(
                    session_name,
                    session_id=session_id,
                    output_dir=last_result["output_dir"],
                    backbone_cost=cost_data,
                    tool_call_count=cost_data.get("tool_call_count", 0),
                    success=bool(is_done),
                    attempts=attempt + 1,
                    max_retries=args.max_retries,
                    duration_seconds=duration,
                    attempt_errors=current_attempt_errors,
                )
                if is_done:
                    success = True
                    break

            error_msg = last_result.get("error") or last_result.get("stderr") or "Creator merge executed but ReAct_process.json missing/too short"
            attempt_errors.append({"attempt": attempt + 1, "error": str(error_msg)})
            if attempt < args.max_retries - 1:
                await asyncio.sleep(args.retry_delay)

        snapshot_dir = snapshot_creator_merge_progress(
            progressive_dir,
            step_index,
            incoming_result["category"],
            temp_creator_dir,
            original_creator_skill_name,
        ) if success else None

        merge_records.append({
            "category": incoming_result["category"],
            "role": "incoming_merged",
            "accumulator_dir": temp_creator_dir,
            "final_creator_dir": final_creator_dir,
            "incoming_dir": incoming_creator_dir,
            "progressive_snapshot_dir": snapshot_dir,
            "session_id": session_id,
            "output_dir": last_result.get("output_dir"),
            "success": success,
            "errors": attempt_errors,
        })
        if not success:
            failed_sessions.add(session_name)
            raise RuntimeError(f"Creator merge failed for category {incoming_result['category']}: {attempt_errors}")

    shutil.move(temp_creator_dir, final_creator_dir)
    if temp_creator_dir in creator_merge_work_dirs:
        creator_merge_work_dirs.remove(temp_creator_dir)
    for record in merge_records:
        record["accumulator_dir"] = final_creator_dir

    return final_creator_dir, merge_records


def find_latest_half_stopped_dir(exp_dir, target_basename):
    if not os.path.isdir(exp_dir):
        return None
    suffix = f"_half_stopped_{target_basename}"
    candidates = []
    for item in os.listdir(exp_dir):
        path = os.path.join(exp_dir, item)
        if os.path.isdir(path) and item.endswith(suffix):
            candidates.append((os.path.getmtime(path), path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def restore_half_stopped_dir(exp_dir, target_path):
    if os.path.isdir(target_path):
        return None
    archived_path = find_latest_half_stopped_dir(exp_dir, os.path.basename(target_path))
    if not archived_path:
        return None
    shutil.move(archived_path, target_path)
    return target_path


def find_half_stopped_path_for_target(exp_dir, target_path):
    return find_latest_half_stopped_dir(exp_dir, os.path.basename(target_path))


def find_latest_creator_merge_temp(exp_dir, original_creator_skill_name, time_prefix=None):
    if not os.path.isdir(exp_dir):
        return None
    if time_prefix:
        exact_path = os.path.join(
            exp_dir,
            f"temp_{time_prefix}_codex_gpt_v2_opt_{original_creator_skill_name}",
        )
        return exact_path if os.path.isdir(exact_path) else None

    suffix = f"_codex_gpt_v2_opt_{original_creator_skill_name}"
    candidates = []
    for item in os.listdir(exp_dir):
        path = os.path.join(exp_dir, item)
        if os.path.isdir(path) and item.startswith("temp_") and item.endswith(suffix):
            candidates.append((os.path.getmtime(path), path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def restore_half_stopped_state(args):
    restored = []
    for target_path in [args.output_root, OPTIMIZE_RUNNING_DIR]:
        restored_path = restore_half_stopped_dir(args.exp_dir, target_path)
        if restored_path:
            restored.append(restored_path)

    for item in list(os.listdir(args.exp_dir)) if os.path.isdir(args.exp_dir) else []:
        marker = "_half_stopped_work_"
        if marker not in item:
            continue
        archived_work_dir = os.path.join(args.exp_dir, item)
        if not os.path.isdir(archived_work_dir):
            continue
        target_work_dir = os.path.join(args.exp_dir, f"work_{item.split(marker, 1)[1]}")
        if os.path.isdir(target_work_dir):
            continue
        shutil.move(archived_work_dir, target_work_dir)
        restored.append(target_work_dir)

    for item in list(os.listdir(args.exp_dir)) if os.path.isdir(args.exp_dir) else []:
        marker = "_half_stopped_temp_"
        if marker not in item or "_codex_gpt_v2_opt_" not in item:
            continue
        archived_temp_dir = os.path.join(args.exp_dir, item)
        if not os.path.isdir(archived_temp_dir):
            continue
        target_temp_dir = os.path.join(args.exp_dir, f"temp_{item.split(marker, 1)[1]}")
        if os.path.isdir(target_temp_dir):
            continue
        shutil.move(archived_temp_dir, target_temp_dir)
        creator_merge_work_dirs.append(target_temp_dir)
        restored.append(target_temp_dir)

    if restored:
        print("[Resume] Restored half-stopped state:")
        for path in restored:
            print(f"- {path}")
    return restored


def all_cases_successful(grouped_cases, args):
    missing = []
    for category, cases in sorted(grouped_cases.items()):
        category_key = safe_segment(category)
        dataset_output_root = os.path.join(args.output_root, category_key)
        for info in cases:
            session_name = f"v2_optimization_{category_key}_{info['skill_name']}_{info['name_without_prefix']}"
            output_dir, session_id = find_successful_case_output(dataset_output_root, session_name)
            if not output_dir or not session_id:
                missing.append((category, info["case_id"], session_name))
    return len(missing) == 0, missing


async def run_codex_turn(thread_name, session_name, message, args, codex_cwd, output_root, log_file,
                         resume_session_id=None):
    start_time = time.time()

    if resume_session_id:
        cmd = [
            CODEX_BIN,
            "exec",
            "resume",
            "--skip-git-repo-check",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--model",
            args.model,
            resume_session_id,
            message,
        ]
    else:
        cmd = [
            CODEX_BIN,
            "exec",
            "--skip-git-repo-check",
            "--json",
            "-C",
            codex_cwd,
            "--sandbox",
            "danger-full-access",
            "--dangerously-bypass-approvals-and-sandbox",
            "--model",
            args.model,
            message,
        ]

    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        action = "Resume Codex exec" if resume_session_id else "Start Codex exec"
        f.write(f"[{datetime.now()}] {action}: {session_name}\n")
        f.write(" ".join(cmd[:-1]) + " <prompt>\n")
        f.write("\n=== PROMPT START ===\n")
        f.write(message)
        if not message.endswith("\n"):
            f.write("\n")
        f.write("=== PROMPT END ===\n")

    env = {**os.environ}
    env["CODEX_THREAD_NAME"] = thread_name
    env.pop("CODEX_THREAD_ID", None)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        active_processes.add(proc)
        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=args.timeout_seconds)
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                await asyncio.sleep(1)
                if proc.returncode is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            await proc.wait()
            active_processes.discard(proc)
            return {"success": False, "error": f"Timeout after {args.timeout_seconds}s", "session_id": resume_session_id}
        except asyncio.CancelledError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                await asyncio.sleep(1)
                if proc.returncode is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            active_processes.discard(proc)
            raise
        active_processes.discard(proc)
    except Exception as e:
        return {"success": False, "error": str(e), "session_id": resume_session_id}

    stdout = stdout_data.decode("utf-8", errors="replace")
    stderr = stderr_data.decode("utf-8", errors="replace")
    stdout_records = load_jsonl_text(stdout)
    stdout_summary = summarize_codex_records(stdout_records, returncode=proc.returncode)
    session_id = stdout_summary.get("session_id") or resume_session_id

    rollout_path = find_rollout_by_session_id(session_id) if session_id else None
    if session_id and not rollout_path:
        rollout_path = find_latest_rollout_after(start_time)
    records = load_jsonl_file(rollout_path) if rollout_path else stdout_records
    summary = summarize_codex_records(records, returncode=proc.returncode)
    if not summary.get("session_id"):
        summary["session_id"] = session_id

    storage_id = summary.get("session_id") or session_id or f"unknown_{int(start_time)}"
    output_dir = os.path.join(output_root, f"{safe_segment(session_name)}_{safe_segment(storage_id)}")
    os.makedirs(output_dir, exist_ok=True)
    write_jsonl_records(os.path.join(output_dir, "original_ReAct.jsonl"), records or stdout_records)
    jsonl_to_react_process(None, output_dir, records=records or stdout_records, user_message=message)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] Exit code: {proc.returncode}, session_id={storage_id}\n")
        if stderr.strip():
            f.write("\n=== STDERR ===\n")
            f.write(stderr[:20000])
        f.write("\n=== STDOUT JSONL HEAD ===\n")
        f.write(stdout[:50000])
        f.write("\n")

    return {
        "success": proc.returncode == 0,
        "session_id": storage_id,
        "output_dir": output_dir,
        "summary": summary,
        "stderr": stderr,
        "error": stderr if proc.returncode != 0 else None,
    }


def parse_arguments():
    parser = argparse.ArgumentParser(description="Dataset-level persistent Codex GPT skill optimization")
    parser.add_argument("--dataset_dir", type=str, default=DATASET_DIR, help="Path to the dataset directory")
    parser.add_argument("--split_file", type=str, default=None, help="Path to train/test/OOD split JSON. Defaults to <dataset_dir>/split_train_test_ood.json if it exists")
    parser.add_argument("--split_name", type=str, choices=["train", "test", "ood", "all"], default="train", help="Split to optimize on when split_file exists")
    parser.add_argument("--task_result_dir", type=str, default="OC_Seed_video_skill_creator/0513_1248_expert_res_on_skills_0513_1248_expert_composition_skills_expert_created_by_defaults", help="Path to the directory containing Codex output/eval materials")
    parser.add_argument("--composition_skill_dir", type=str, default="OC_Seed_video_skill_creator/0513_1248_expert_composition_skills_expert_created_by_defaults", help="Path to the initial composition skills directory")
    parser.add_argument("--creator_skill_dir", type=str, default="skills/video-skill-creator", help="Path to the initial video-skill-creator skill directory")
    parser.add_argument(
        "--history_task_result_composition_skill_creator_skill_dir",
        nargs=3,
        action="append",
        default=[],
        metavar=("TASK_RESULT_DIR", "COMPOSITION_SKILL_DIR", "CREATOR_SKILL_DIR"),
        help=(
            "Historical triples to provide per matched case. Repeat this flag for multiple history groups: "
            "--history_task_result_composition_skill_creator_skill_dir TASK_RESULT_DIR COMPOSITION_SKILL_DIR CREATOR_SKILL_DIR. "
            "Use '', none, or null for CREATOR_SKILL_DIR when no historical creator skill is available."
        ),
    )
    
    parser.add_argument("--model", type=str, default="gpt-5.5", help="Codex model to use")
    parser.add_argument("--target_dataset", nargs="+", default=["all"], help="Target dataset/category list to evaluate, or 'all'. Supports space-separated or comma-separated values")
    parser.add_argument("--timeout_seconds", type=int, default=7200, help="Execution timeout per turn")
    parser.add_argument("--max_retries", type=int, default=3, help="Maximum retries per case")
    parser.add_argument("--retry_delay", type=int, default=60, help="Delay in seconds before retrying a failed case")
    parser.add_argument("--exp_id", type=str, default="CodeX_GPT_skill_optimization_v2_eval_both", help="Experiment ID to group results")
    
    # This is the arg for control  Self-Evolution and Evolution with Feedback
    parser.add_argument("--eval_source", type=str.lower, choices=["llm", "human", "both", "none"], default="both", help="llm loads evals/rubrics_eval.json; human loads the matching *_output_eval case's evals_human/rubric_eval_detail.json; none uses objectives only")
    
    
    parser.add_argument("--dry_run", type=lambda value: str(value).lower() in {"1", "true", "yes", "y"}, default=True, help="Only scan and print dataset-level optimization plan; set to false to copy files and start Codex")
    parser.add_argument("--resume", type=lambda value: str(value).lower() in {"1", "true", "yes", "y"}, default=True, help="Resume from existing v2 work/output directories; skip successful cases and continue the dataset Codex thread from the last successful session id")
    return parser.parse_args()


def normalize_target_datasets(target_dataset):
    if isinstance(target_dataset, str):
        values = [target_dataset]
    else:
        values = list(target_dataset or [])

    normalized = []
    for value in values:
        normalized.extend(part.strip() for part in str(value).split(",") if part.strip())
    return normalized or ["all"]


def dataset_selected(category, target_dataset):
    targets = normalize_target_datasets(target_dataset)
    return "all" in targets or category in targets


def prepare_cases(args):
    allowed_cases = load_allowed_cases(args.dataset_dir, args.split_file, args.split_name)
    dataset_categories = [
        item for item in os.listdir(args.dataset_dir)
        if os.path.isdir(os.path.join(args.dataset_dir, item))
    ]
    grouped = {}

    for item in os.listdir(args.task_result_dir):
        item_path = os.path.join(args.task_result_dir, item)
        if not os.path.isdir(item_path):
            continue
        if item.startswith(("eval_", "opt_", "failed_", "half_stopped_")):
            continue

        category, case_id, name_without_prefix = parse_result_dir_name(item, dataset_categories)
        if not category or not case_id:
            continue
        if allowed_cases is not None and (category, case_id) not in allowed_cases:
            continue
        if not dataset_selected(category, args.target_dataset):
            continue

        react_file_path = os.path.join(item_path, "ReAct_process.json")
        if not os.path.isfile(react_file_path):
            continue

        eval_data = prepare_case_eval_data(item_path, args, category, case_id)
        if eval_data is None:
            continue
        if args.eval_source != "none" and not has_low_score(eval_data):
            print(f"Perfect score found for task {name_without_prefix}, skip optimization.")
            continue

        skill_name = read_skill_name(args.dataset_dir, category)
        if not skill_name:
            continue

        current_info = {
            "item_path": item_path,
            "category": category,
            "case_id": case_id,
            "skill_name": skill_name,
            "eval_data": eval_data,
            "name_without_prefix": name_without_prefix,
        }
        current_info["history_cases"] = collect_history_cases(
            current_info,
            args.history_task_result_composition_skill_creator_skill_dir,
            dataset_categories,
        )

        grouped.setdefault(category, []).append(current_info)

    for cases in grouped.values():
        cases.sort(key=case_sort_key)
    return grouped


async def optimize_dataset(category, cases, args):
    global done_sessions, failed_sessions, dataset_work_dirs

    category_key = safe_segment(category)
    work_dir = os.path.join(args.exp_dir, f"work_{category_key}")
    dataset_work_dirs.append(work_dir)
    if os.path.exists(work_dir) and not args.resume:
        shutil.rmtree(work_dir)
    os.makedirs(work_dir, exist_ok=True)

    original_composition_skill_dir_name = os.path.basename(args.composition_skill_dir.rstrip(os.sep))
    original_creator_skill_name = os.path.basename(args.creator_skill_dir.rstrip(os.sep))
    dataset_skill_dir = os.path.join(work_dir, f"temp_{original_composition_skill_dir_name}")
    dataset_creator_dir = os.path.join(work_dir, f"temp_{original_creator_skill_name}")
    os.makedirs(dataset_skill_dir, exist_ok=True)
    dataset_skill_names = sorted({case["skill_name"] for case in cases})
    for skill_name in dataset_skill_names:
        source_skill_dir = os.path.join(args.composition_skill_dir, skill_name)
        target_skill_dir = os.path.join(dataset_skill_dir, skill_name)
        if not os.path.isdir(source_skill_dir):
            raise FileNotFoundError(f"Skill directory not found for dataset {category}: {source_skill_dir}")
        if os.path.exists(target_skill_dir):
            if not args.resume:
                shutil.rmtree(target_skill_dir)
                shutil.copytree(source_skill_dir, target_skill_dir)
        else:
            shutil.copytree(source_skill_dir, target_skill_dir)
    if os.path.exists(dataset_creator_dir):
        if not args.resume:
            shutil.rmtree(dataset_creator_dir)
            shutil.copytree(args.creator_skill_dir, dataset_creator_dir)
    else:
        shutil.copytree(args.creator_skill_dir, dataset_creator_dir)

    dataset_output_root = os.path.join(args.output_root, category_key)
    os.makedirs(dataset_output_root, exist_ok=True)

    session_id = None
    thread_name = f"v2_optimization_{category_key}"
    log_file = os.path.join(OPTIMIZE_RUNNING_DIR, f"v2_{category_key}.log")

    for index, info in enumerate(tqdm(cases, desc=f"{category} Cases", leave=False)):
        skill_name = info["skill_name"]
        session_name = f"v2_optimization_{category_key}_{skill_name}_{info['name_without_prefix']}"
        if args.resume:
            completed_output_dir, completed_session_id = find_successful_case_output(dataset_output_root, session_name)
            if completed_output_dir and completed_session_id:
                session_id = completed_session_id
                done_sessions.add(session_name)
                print(f"[Resume Skip] {category} case_id={info['case_id']} session={session_name} output={completed_output_dir}")
                continue

        specific_skill_dir = os.path.join(dataset_skill_dir, skill_name)
        react_file_path = os.path.join(info["item_path"], "ReAct_process.json")
        optimize_prompt = build_optimize_prompt(
            os.path.abspath(dataset_creator_dir),
            os.path.abspath(specific_skill_dir),
            os.path.abspath(react_file_path),
            os.path.abspath(info["item_path"]),
            info["eval_data"],
            args.eval_source,
        )
        optimize_prompt = append_history_context(optimize_prompt, info.get("history_cases", []))
        if index > 0:
            optimize_prompt = (
                "继续在同一个数据集级优化会话中处理下一个 case。请保留并利用前面 case 对该 skill "
                "和 video-skill-creator 的修改经验，但仍然只根据当前 case 的 trace、输入、产物和 Objective 做本轮必要更新。避免重复问题和错误的过渡优化。关注新的问题和错误。\n\n"
                + optimize_prompt
            )

        success = False
        attempt_errors = []
        for attempt in range(args.max_retries):
            start_time = time.time()
            result = await run_codex_turn(
                thread_name,
                session_name,
                optimize_prompt,
                args,
                CODEX_WORKSPACE,
                dataset_output_root,
                log_file,
                resume_session_id=session_id,
            )
            if result.get("session_id"):
                session_id = result["session_id"]
            duration = time.time() - start_time

            if result.get("output_dir"):
                is_done = result.get("success") and check_output_done(result["output_dir"])
                error_msg = result.get("error") or result.get("stderr") or "Task executed but ReAct_process.json missing/too short"
                current_attempt_errors = attempt_errors if is_done else attempt_errors + [{"attempt": attempt + 1, "error": str(error_msg)}]
                cost_data = calculate_cost_from_jsonl(session_id)
                save_basic_result(
                    session_name,
                    session_id=session_id,
                    output_dir=result["output_dir"],
                    backbone_cost=cost_data,
                    tool_call_count=cost_data.get("tool_call_count", 0),
                    success=bool(is_done),
                    attempts=attempt + 1,
                    max_retries=args.max_retries,
                    duration_seconds=duration,
                    attempt_errors=current_attempt_errors,
                )
                if is_done:
                    done_sessions.add(session_name)
                    success = True
                    break

            error_msg = result.get("error") or result.get("stderr") or "Task executed but ReAct_process.json missing/too short"
            attempt_errors.append({"attempt": attempt + 1, "error": str(error_msg)})
            if attempt < args.max_retries - 1:
                await asyncio.sleep(args.retry_delay)

        if not success:
            failed_sessions.add(session_name)
            print(f"[Dataset Failed] {category} case_id={info['case_id']} session={session_name}. Stop this dataset group and keep work dirs for resume.")
            break

    return {
        "category": category,
        "work_dir": work_dir,
        "skill_dir": dataset_skill_dir,
        "creator_dir": dataset_creator_dir,
        "session_id": session_id,
        "cases": len(cases),
        "failed_sessions": [
            session_name for session_name in sorted(failed_sessions)
            if session_name.startswith(f"v2_optimization_{category_key}_")
        ],
    }


async def main(args):
    args.dataset_dir = os.path.abspath(os.path.expanduser(args.dataset_dir))
    args.task_result_dir = os.path.abspath(os.path.expanduser(args.task_result_dir))
    args.composition_skill_dir = os.path.abspath(os.path.expanduser(args.composition_skill_dir))
    args.creator_skill_dir = os.path.abspath(os.path.expanduser(args.creator_skill_dir))
    args.history_task_result_composition_skill_creator_skill_dir = normalize_history_entries(
        args.history_task_result_composition_skill_creator_skill_dir
    )
    args.exp_dir = os.path.join(os.path.dirname(OUTPUT_DIR), args.exp_id)
    args.output_root = os.path.join(args.exp_dir, "codex_opt_output")
    if args.split_file is not None:
        args.split_file = os.path.abspath(os.path.expanduser(args.split_file))

    if args.resume and not args.dry_run:
        restore_half_stopped_state(args)

    print("\n--- Task Arguments ---")
    print(json.dumps(vars(args), ensure_ascii=False, indent=2, sort_keys=True))

    for label, path in [
        ("Dataset directory", args.dataset_dir),
        ("Task result directory", args.task_result_dir),
        ("Composition skill directory", args.composition_skill_dir),
        ("Creator skill directory", args.creator_skill_dir),
    ]:
        if not os.path.isdir(path):
            print(f"{label} not found: {path}")
            return
    pairwise_merge_skill_dir = os.path.join(FOUNDATION_SKILLS_DIR, "pair-wise-skill-merge")
    if not os.path.isdir(pairwise_merge_skill_dir):
        print(f"Required merge skill not found: {pairwise_merge_skill_dir}")
        return
    for history_index, history_entry in enumerate(args.history_task_result_composition_skill_creator_skill_dir, start=1):
        labels = ("History task result directory", "History composition skill directory", "History creator skill directory")
        for label, path in zip(labels, history_entry):
            if path is None:
                continue
            if not os.path.isdir(path):
                print(f"{label} #{history_index} not found: {path}")
                return

    grouped_cases = prepare_cases(args)
    if not grouped_cases:
        print("No dataset cases need optimization.")
        return

    print(f"Dataset-level parallel groups: {len(grouped_cases)}")
    for category, cases in sorted(grouped_cases.items()):
        print(f"- {category}: {len(cases)} cases")

    original_creator_skill_name = os.path.basename(args.creator_skill_dir.rstrip(os.sep))
    if args.resume:
        all_done, missing_cases = all_cases_successful(grouped_cases, args)
        if args.dry_run and missing_cases and not os.path.isdir(args.output_root):
            archived_output_root = find_half_stopped_path_for_target(args.exp_dir, args.output_root)
            if archived_output_root:
                manifest_path, archive_time_prefix, archived_creator_results = load_archived_creator_results_for_merge(
                    args,
                    original_creator_skill_name,
                )
                if archived_creator_results:
                    print("\nDry run note: active output_root is missing, but a half-stopped output archive exists.")
                    print(f"Half-stopped output archive: {archived_output_root}")
                    print("A real non-dry-run resume will restore it before checking completed cases.")
                    print("Creator merge can restart from archived creator dirs after restore.")
                    print(f"Manifest: {manifest_path}")
                    print(f"Final merged creator dir: {os.path.join(args.exp_dir, f'{archive_time_prefix}_codex_gpt_v2_opt_{original_creator_skill_name}')}")
                    print(f"Progressive merge result dir: {os.path.join(args.exp_dir, f'{archive_time_prefix}_progressive_merge_result')}")
                    print(f"Archived creator inputs: {len(archived_creator_results)}")
                    return
        if all_done:
            manifest_path, archive_time_prefix, archived_creator_results = load_archived_creator_results_for_merge(
                args,
                original_creator_skill_name,
            )
            if archived_creator_results:
                if args.dry_run:
                    print("\nAll dataset optimization cases are complete. Creator merge can resume from archived creator dirs.")
                    print(f"Manifest: {manifest_path}")
                    print(f"Final merged creator dir: {os.path.join(args.exp_dir, f'{archive_time_prefix}_codex_gpt_v2_opt_{original_creator_skill_name}')}")
                    print(f"Progressive merge result dir: {os.path.join(args.exp_dir, f'{archive_time_prefix}_progressive_merge_result')}")
                    print(f"Archived creator inputs: {len(archived_creator_results)}")
                    return

                os.makedirs(OPTIMIZE_RUNNING_DIR, exist_ok=True)
                ensure_shared_codex_cwd(args)
                print("\nAll dataset optimization cases are complete. Resuming creator merge from archived creator dirs.")
                final_creator_dir, creator_merge_records = await merge_creator_skills_pairwise(
                    archived_creator_results,
                    args,
                    archive_time_prefix,
                    original_creator_skill_name,
                )
                update_manifest_with_creator_merge(manifest_path, final_creator_dir, creator_merge_records)
                print(f"[Creator Merge Complete] Final merged creator: {final_creator_dir}")
                print(f"Updated manifest: {manifest_path}")
                if os.path.isdir(OPTIMIZE_RUNNING_DIR):
                    running_archive = os.path.join(args.exp_dir, f"{archive_time_prefix}_codex_gpt_v2_opt_creator_merge_running_logs")
                    if os.path.exists(running_archive):
                        shutil.rmtree(running_archive)
                    shutil.move(OPTIMIZE_RUNNING_DIR, running_archive)
                return

            if has_dataset_work_dirs(grouped_cases, args):
                print("\nAll dataset optimization cases are complete. Continuing final archive and creator merge from restored work dirs.")
            else:
                print("\nAll optimizations are already complete. No Codex sessions need to be started.")
                print("If final archives/manifests already exist, keep them as the completed optimization outputs.")
                return
        else:
            print(f"\n[Resume] Found {len(missing_cases)} unfinished cases. Continuing from existing successful outputs.")
            for category, case_id, session_name in missing_cases[:20]:
                print(f"- pending: {category} case_id={case_id} session={session_name}")
            if len(missing_cases) > 20:
                print(f"- ... {len(missing_cases) - 20} more pending cases")

    if args.dry_run:
        original_composition_skill_dir_name = os.path.basename(args.composition_skill_dir.rstrip(os.sep))
        print("\n--- Dry Run Plan ---")
        print(f"Exp dir: {args.exp_dir}")
        print(f"Shared Codex cwd: {CODEX_WORKSPACE}")
        print(f"Codex skill load path: {os.path.join(CODEX_WORKSPACE, '.agents', 'skills')}")
        print(f"Output root: {args.output_root}")
        print(f"History triples: {len(args.history_task_result_composition_skill_creator_skill_dir)}")
        print(f"Final merged creator dir pattern: <time_prefix>_codex_gpt_v2_opt_{original_creator_skill_name}")
        print("Progressive merge result dir pattern: <time_prefix>_progressive_merge_result")
        for category, cases in sorted(grouped_cases.items()):
            category_key = safe_segment(category)
            skill_names = sorted({case["skill_name"] for case in cases})
            history_case_count = sum(1 for case in cases if case.get("history_cases"))
            work_dir = os.path.join(args.exp_dir, f"work_{category_key}")
            print(f"\n[{category}]")
            print(f"  cases: {len(cases)}")
            print(f"  cases_with_history: {history_case_count}")
            print(f"  skill_names: {', '.join(skill_names)}")
            print(f"  work_dir: {work_dir}")
            print(f"  skill_copy: {os.path.join(work_dir, f'temp_{original_composition_skill_dir_name}')}")
            print(f"  creator_copy: {os.path.join(work_dir, f'temp_{original_creator_skill_name}')}")
            print(f"  output_dir: {os.path.join(args.output_root, category_key)}")
        print("\nDry run complete. No files were copied and no Codex sessions were started.")
        return

    os.makedirs(OPTIMIZE_RUNNING_DIR, exist_ok=True)
    logger = Logger(os.path.join(OPTIMIZE_RUNNING_DIR, "000_codex_gpt_opt_v2_overall.log"))
    sys.stdout = logger
    sys.stderr = logger
    ensure_shared_codex_cwd(args)
    print(f"Dataset-level parallel groups: {len(grouped_cases)}")
    for category, cases in sorted(grouped_cases.items()):
        print(f"- {category}: {len(cases)} cases")

    os.makedirs(args.exp_dir, exist_ok=True)
    os.makedirs(args.output_root, exist_ok=True)

    tasks = []
    pending_categories = set()
    for category, cases in sorted(grouped_cases.items()):
        task = asyncio.create_task(optimize_dataset(category, cases, args))
        tasks.append(task)
        pending_categories.add(category)

    results = []
    for task in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Running Dataset Optimizers"):
        result = await task
        results.append(result)
        completed_category = result["category"]
        pending_categories.discard(completed_category)
        remaining = ", ".join(sorted(pending_categories)) if pending_categories else "None"
        print(f"[Dataset Complete] {completed_category}. Remaining datasets: {remaining}")

    failed_after_optimization = sorted({
        session_name
        for result in results
        for session_name in result.get("failed_sessions", [])
    })
    if failed_after_optimization:
        print("\n[Optimization Failed] Some cases failed after all retries. Final archive and creator merge were skipped.")
        for session_name in failed_after_optimization[:50]:
            print(f"- failed: {session_name}")
        if len(failed_after_optimization) > 50:
            print(f"- ... {len(failed_after_optimization) - 50} more failed cases")
        print("Keep the work/output directories in place and rerun with --resume true after fixing the failures.")
        raise RuntimeError(f"{len(failed_after_optimization)} optimization case(s) failed; skipped final archive and creator merge.")

    time_prefix = datetime.now().strftime("%m%d_%H%M")
    final_records = []
    original_composition_skill_dir_name = os.path.basename(args.composition_skill_dir.rstrip(os.sep))
    original_creator_skill_name = os.path.basename(args.creator_skill_dir.rstrip(os.sep))
    final_skill_archive_dir = os.path.join(
        args.exp_dir,
        f"{time_prefix}_codex_gpt_v2_opt_{original_composition_skill_dir_name}",
    )
    if os.path.exists(final_skill_archive_dir):
        shutil.rmtree(final_skill_archive_dir)
    os.makedirs(final_skill_archive_dir, exist_ok=True)

    archived_creator_results = []
    for result in sorted(results, key=lambda item: safe_segment(item["category"])):
        category_key = safe_segment(result["category"])
        final_category_creator_dir = os.path.join(
            args.exp_dir,
            f"{time_prefix}_codex_gpt_v2_opt_{category_key}_{original_creator_skill_name}",
        )
        if os.path.exists(final_category_creator_dir):
            shutil.rmtree(final_category_creator_dir)
        if os.path.isdir(result["creator_dir"]):
            shutil.copytree(result["creator_dir"], final_category_creator_dir)

        diff_dir = os.path.join(args.exp_dir, f"{time_prefix}_codex_gpt_v2_opt_{category_key}_diff")
        diff_index = generate_optimization_diffs(
            args.composition_skill_dir,
            result["skill_dir"],
            args.creator_skill_dir,
            final_category_creator_dir,
            diff_dir,
        )
        moved_skill_names = copy_skill_children_to_archive(
            result["skill_dir"],
            final_skill_archive_dir,
            result["category"],
        )
        final_records.append({
            "category": result["category"],
            "cases": result["cases"],
            "session_id": result["session_id"],
            "skill_dir": final_skill_archive_dir,
            "skill_names": moved_skill_names,
            "creator_dir": final_category_creator_dir,
            "diff_index": diff_index,
        })
        archived_creator_results.append({
            "category": result["category"],
            "creator_dir": final_category_creator_dir,
            "session_id": result["session_id"],
        })

    manifest_path = os.path.join(args.exp_dir, f"{time_prefix}_codex_gpt_v2_opt_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(final_records, f, ensure_ascii=False, indent=2)
    print(f"[Optimization Archive Complete] Manifest written before creator merge: {manifest_path}")

    for result in results:
        if os.path.isdir(result["work_dir"]):
            shutil.rmtree(result["work_dir"])

    final_creator_dir, creator_merge_records = await merge_creator_skills_pairwise(
        archived_creator_results,
        args,
        time_prefix,
        original_creator_skill_name,
    )
    update_manifest_with_creator_merge(manifest_path, final_creator_dir, creator_merge_records)
    print(f"[Creator Merge Complete] Final merged creator: {final_creator_dir}")

    if os.path.isdir(OPTIMIZE_RUNNING_DIR):
        running_archive = os.path.join(args.exp_dir, f"{time_prefix}_codex_gpt_v2_opt_running_logs")
        if os.path.exists(running_archive):
            shutil.rmtree(running_archive)
        shutil.move(OPTIMIZE_RUNNING_DIR, running_archive)

    print("\n--- Dataset-level Optimization Summary ---")
    print(f"Dataset groups: {len(results)}")
    print(f"Creator merge steps: {max(len(creator_merge_records) - 1, 0)}")
    print(f"Final creator: {final_creator_dir}")
    print(f"Done cases: {len(done_sessions)}")
    print(f"Failed cases: {len(failed_sessions)}")
    print(f"Manifest: {manifest_path}")


def cleanup(args):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    print("\nCaught KeyboardInterrupt. Stopping active Codex processes and archiving partial dataset work...")
    terminate_processes(list(active_processes))

    exp_dir = os.path.join(os.path.dirname(OUTPUT_DIR), getattr(args, "exp_id", "CodeX_GPT_skill_optimization_v2_no_reward_v2"))
    os.makedirs(exp_dir, exist_ok=True)
    time_prefix = datetime.now().strftime("%m%d_%H%M")

    archived_output = archive_dir_if_exists(
        getattr(args, "output_root", os.path.join(exp_dir, "codex_opt_output")),
        exp_dir,
        f"{time_prefix}_half_stopped_codex_opt_v2_output",
    )
    if archived_output:
        print(f"Archived partial outputs to {archived_output}")

    for work_dir in list(dataset_work_dirs):
        if os.path.isdir(work_dir):
            archived_work_dir = os.path.join(exp_dir, f"{time_prefix}_half_stopped_{os.path.basename(work_dir)}")
            if os.path.exists(archived_work_dir):
                shutil.rmtree(archived_work_dir)
            shutil.move(work_dir, archived_work_dir)
            print(f"Archived partial dataset work dir to {archived_work_dir}")

    for work_dir in list(creator_merge_work_dirs):
        if os.path.isdir(work_dir):
            archived_work_dir = os.path.join(exp_dir, f"{time_prefix}_half_stopped_{os.path.basename(work_dir)}")
            if os.path.exists(archived_work_dir):
                shutil.rmtree(archived_work_dir)
            shutil.move(work_dir, archived_work_dir)
            print(f"Archived partial creator merge work dir to {archived_work_dir}")

    archived_running = archive_dir_if_exists(
        OPTIMIZE_RUNNING_DIR,
        exp_dir,
        f"{time_prefix}_half_stopped_{os.path.basename(OPTIMIZE_RUNNING_DIR)}",
    )
    if archived_running:
        print(f"Archived running logs to {archived_running}")

    print("Global video-skill-creator was not modified; v2 uses per-dataset isolated copies, so no restore is required.")


if __name__ == "__main__":
    parsed_args = parse_arguments()
    try:
        asyncio.run(main(parsed_args))
    except KeyboardInterrupt:
        cleanup(parsed_args)
