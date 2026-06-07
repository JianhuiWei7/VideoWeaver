import argparse
import asyncio
import json
import os
import random
import re
import shutil
import signal
import sys
import time
from datetime import datetime

from tqdm import tqdm

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from AutomaticSkillOptimization.args import (
    CODEX_ORIGINAL_CREATOR_PATH_EXPERT,
    CODEX_ORIGINAL_CREATOR_PATH_VANILLA,
    CODEX_WORKSPACE,
    DATASET_DIR,
    FAILED_DIR,
    HALF_STOPPED_DIR,
    OUTPUT_DIR,
    RUNNING_DIR,
    setup_codex_workspace,
)
from AutomaticSkillOptimization.codex_claude_pipeline_utils import (
    check_gen_artifacts_done,
    check_gen_done,
    clean_composition_skills_from_fixed_dir,
    formalize_gen_output,
    skill_exists_for_run,
    skill_names_in_dir,
    sync_composition_skills_to_fixed_dir,
)
from AutomaticSkillOptimization.inference_CodeX.codex_cli_tool import (
    active_processes,
    calculate_cost_from_jsonl,
    jsonl_to_react_process,
)
from AutomaticSkillOptimization.inference_CodeX.running_utils import (
    create_skill_task,
    done_gen_sessions,
    failed_gen_sessions,
    running_sessions,
    run_single_task,
)
from AutomaticSkillOptimization.prompts import (
    CODEX_EXPERT_SKILL_CREATOR_PREFIX,
    CODEX_TASK_PREFIX,
    CODEX_TASK_PREFIX_WO_TASK_TRACKER,
    CODEX_VANILLA_SKILL_CREATOR_PREFIX,
    append_task_cases_prompt,
)
from AutomaticSkillOptimization.summary_txt import summarize_react_process_txt
from AutomaticSkillOptimization.utils import (
    Logger,
    archive_pipeline_dirs,
    find_session_dir,
    generate_basic_results_summary,
    move_to_failed_output,
    move_to_half_stopped_output,
    print_success_rate_summary,
    process_input,
    save_basic_result,
    terminate_processes,
)

latest_gen_session_ids = {}


async def process_and_run_gen_task(session_name, sub_dir_path, timeout_seconds, logs_dir,
                                   max_retries=3, task_max_retries=3, retry_delay=60,
                                   add_task_tracker=True, skill_name=None):
    global running_sessions, done_gen_sessions, failed_gen_sessions, latest_gen_session_ids
    attempt_errors = []
    for attempt in range(task_max_retries):
        running_sessions.add(session_name)
        sid = None
        try:
            log_file = os.path.join(logs_dir, f"{session_name}.log")

            input_context = process_input(
                sub_dir_path,
                CODEX_TASK_PREFIX,
                CODEX_TASK_PREFIX_WO_TASK_TRACKER,
                add_task_tracker=add_task_tracker,
            )

            if not input_context:
                error_msg = "No valid input context files"
                print(f"Warning: {session_name} has no valid input context files")
                attempt_errors.append({"attempt": attempt + 1, "error": error_msg})
                if attempt < task_max_retries - 1:
                    print(f"[{session_name}] Task failed due to no valid input context, retrying ({attempt + 1}/{task_max_retries})...")
                    continue
                running_sessions.discard(session_name)
                failed_gen_sessions.add(session_name)
                save_basic_result(session_name, success=False, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors)
                return False

            print(f"[{session_name}] Starting Gen (attempt {attempt + 1}/{task_max_retries})...")
            task_start_time = time.time()
            result = await run_single_task(
                session_name,
                input_context,
                CODEX_WORKSPACE,
                timeout_seconds=timeout_seconds,
                log_file=log_file,
                overwrite_log=(attempt == 0),
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
            task_duration = time.time() - task_start_time

            sid = result.get("session_id")
            if sid:
                latest_gen_session_ids[session_name] = sid

            if result.get("success", False):
                session_dir = os.path.join(OUTPUT_DIR, f"{session_name}_{sid}" if sid else f"{session_name}_unknown")
                if sid:
                    try:
                        jsonl_to_react_process(sid, session_dir)
                        summarize_react_process_txt(os.path.join(session_dir, "ReAct_process.json"), session_name)
                    except Exception:
                        pass

                final_mp4 = check_gen_done(session_name, sid, after_timestamp=task_start_time)
                if final_mp4:
                    running_sessions.discard(session_name)
                    done_gen_sessions.add(session_name)
                    print(f"[{session_name}] Succeeded Gen on attempt {attempt + 1}/{task_max_retries}")
                    cost_data = calculate_cost_from_jsonl(sid)
                    save_basic_result(
                        session_name,
                        session_id=sid,
                        backbone_cost=cost_data,
                        tool_call_count=cost_data.get("tool_call_count", 0),
                        success=True,
                        attempts=attempt + 1,
                        max_retries=task_max_retries,
                        attempt_errors=attempt_errors,
                        duration_seconds=task_duration,
                    )
                    return True

                error_msg = f"Task executed but output not found (checking {session_name}_{sid})"
                print(f"[{session_name}] {error_msg}.")
                attempt_errors.append({"attempt": attempt + 1, "error": error_msg})
                if attempt < task_max_retries - 1:
                    move_to_failed_output(session_name, session_id=sid)
                    print(f"[{session_name}] Task incomplete, retrying ({attempt + 1}/{task_max_retries})...")
                    continue
                running_sessions.discard(session_name)
                failed_gen_sessions.add(session_name)
                cost_data = calculate_cost_from_jsonl(sid)
                save_basic_result(session_name, session_id=sid, backbone_cost=cost_data, tool_call_count=cost_data.get("tool_call_count", 0), success=False, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors, duration_seconds=task_duration)
                move_to_failed_output(session_name, session_id=sid)
                return False

            error_msg = result.get("error") or result.get("stderr", "Unknown error")
            print(f"[{session_name}] Gen failed: {error_msg}")
            attempt_errors.append({"attempt": attempt + 1, "error": str(error_msg)})
            if attempt < task_max_retries - 1:
                move_to_failed_output(session_name, session_id=sid)
                print(f"[{session_name}] Retrying ({attempt + 1}/{task_max_retries})...")
                await asyncio.sleep(retry_delay)
                continue
            running_sessions.discard(session_name)
            failed_gen_sessions.add(session_name)
            cost_data = calculate_cost_from_jsonl(sid)
            save_basic_result(session_name, session_id=sid, backbone_cost=cost_data, tool_call_count=cost_data.get("tool_call_count", 0), success=False, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors, duration_seconds=task_duration)
            move_to_failed_output(session_name, session_id=sid)
            return False
        except asyncio.CancelledError:
            print(f"[{session_name}] Cancelled (Ctrl+C). Marking as half_stopped...")
            raise
        except Exception as e:
            error_msg = str(e)
            print(f"[{session_name}] Exception: {error_msg}")
            attempt_errors.append({"attempt": attempt + 1, "error": error_msg})
            if attempt < task_max_retries - 1:
                move_to_failed_output(session_name, session_id=sid)
                print(f"[{session_name}] Retrying ({attempt + 1}/{task_max_retries})...")
                continue
            running_sessions.discard(session_name)
            failed_gen_sessions.add(session_name)
            cost_data = calculate_cost_from_jsonl(sid)
            save_basic_result(session_name, session_id=sid, backbone_cost=cost_data, tool_call_count=cost_data.get("tool_call_count", 0), success=False, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors)
            move_to_failed_output(session_name, session_id=sid)
            return False

async def run_case_pipeline(session_name, task_name, sub_dir_name, sub_dir_path, args, pbar, skill_name=None):
    complete_dir = check_gen_artifacts_done(session_name, search_dirs=[OUTPUT_DIR, args.new_generate_materials_path])
    if complete_dir and not args.overwrite:
        print(f"[{session_name}] Gen artifacts already done. Skipping generation.")
        await formalize_gen_output(session_name, args, latest_gen_session_ids)
        done_gen_sessions.add(session_name)
        pbar.update(1)
        return

    gen_done = check_gen_done(session_name, None, search_dirs=[OUTPUT_DIR, args.new_generate_materials_path])
    if gen_done:
        print(f"[{session_name}] Gen already done. Skipping generation.")
        gen_success = True
    else:
        gen_success = await process_and_run_gen_task(
            session_name,
            sub_dir_path,
            args.timeout_seconds,
            RUNNING_DIR,
            args.max_retries,
            args.task_max_retries,
            args.retry_delay,
            add_task_tracker=args.add_task_tracker,
            skill_name=skill_name,
        )

    if not gen_success:
        if not hasattr(run_case_pipeline, "copy_lock"):
            run_case_pipeline.copy_lock = asyncio.Lock()
        async with run_case_pipeline.copy_lock:
            failed_dir = find_session_dir(session_name, session_id=latest_gen_session_ids.get(session_name), search_dirs=[FAILED_DIR])
            if failed_dir and os.path.exists(failed_dir) and os.path.dirname(os.path.abspath(failed_dir)) != os.path.abspath(args.new_failed_path):
                final_dst = os.path.join(args.new_failed_path, os.path.basename(failed_dir))
                try:
                    if os.path.exists(final_dst):
                        shutil.rmtree(final_dst)
                    shutil.move(failed_dir, final_dst)
                    print(f"[{session_name}] Moved failed output to {final_dst}")
                except Exception as e:
                    print(f"[{session_name}] Failed to move failed_dir to final dest: {e}")
        pbar.update(1)
        return

    # 2. summarize ReAct_process.json
    item_path = find_session_dir(
        session_name,
        session_id=latest_gen_session_ids.get(session_name),
        search_dirs=[OUTPUT_DIR, args.new_generate_materials_path],
    )
    if not item_path:
        print(f"⚠️ item_path not found for {session_name}")
        pbar.update(1)
        return

    react_file_path = os.path.join(item_path, "ReAct_process.json")
    try:
        print(f"[{session_name}] Summarizing ReAct_process.json with Step3...")
        summarize_react_process_txt(react_file_path, session_name)
    except Exception as e:
        print(f"⚠️ Error summarizing {session_name}: {e}")

    await formalize_gen_output(session_name, args, latest_gen_session_ids)
    pbar.update(1)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Pipeline Run Codex Video Gen (inference only)")
    # --agent_id removed (Codex exec doesn't need an agent pool)
    parser.add_argument("--dataset", type=str, default=DATASET_DIR, help="Path to the dataset directory")
    parser.add_argument("--max_concurrency", type=int, default=5, help="Maximum number of concurrent tasks")
    parser.add_argument("--timeout_seconds", type=int, default=10800, help="Execution timeout in seconds")
    parser.add_argument("--max_retries", type=int, default=6, help="Maximum number of retries for rate limit errors and timed out errors, this is not skills' error but the system's unavoidable glitches")
    parser.add_argument("--task_max_retries", type=int, default=3, help="Maximum number of retries for gen task")
    parser.add_argument("--retry_delay", type=int, default=30, help="Delay in seconds before retrying")

    parser.add_argument("--target_task", type=str, nargs="+", default=["all"], help="Target tasks to run, or 'all' for all tasks")
    parser.add_argument("--but", type=str, nargs="+", default=[""], help="Skip specific tasks when target_task is 'all'")

    parser.add_argument("--test_sample", type=int, default=9999, help="Run only a sample of cases for each task for testing")
    parser.add_argument("--skill_type", type=str, choices=["expert", "vanilla"], default="expert", help="Skill type to run; baseline is selected by --no_composition_skills")
    parser.add_argument("--create_skill_only", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Only create skills, do not run tasks")
    
    parser.add_argument("--use_existing_skill_dir", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Whether to copy from an existing skill directory")
    parser.add_argument("--existing_skill_dir", type=str, default="", help="Path to the existing skill directory")
    
    parser.add_argument("--use_existing_skill_creator", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Whether to use an existing skill creator directory")
    parser.add_argument("--existing_skill_creator_dir", type=str, default="", help="Path to the existing skill creator directory")
    
    parser.add_argument("--no_composition_skills", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Run baseline without creating or using skills")
    
    parser.add_argument("--add_task_cases_in_creating_skills", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=True, help="Add task cases when creating skills")
    parser.add_argument("--exp_id", type=str, default="codex_gpt55_inference", help="Experiment ID to group results")
    parser.add_argument("--random_seed", type=int, default=42, help="Random seed for reproducibility")

    parser.add_argument("--skip_copy", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Skip moving gen output to archive dir")
    parser.add_argument("--overwrite", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Overwrite existing results")
    parser.add_argument("--dry_run", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Dry run: print info and exit before execution")
    parser.add_argument("--add_task_tracker", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Add task tracker to prompt")
    return parser.parse_args()

async def main(args):
    random.seed(args.random_seed)
    setup_codex_workspace()

    # CodeX has only one skill load path. The logical skill_type branches mirror
    # OpenClaw, but both expert and vanilla sync into this fixed directory.
    fixed_skill_dir = os.path.join(CODEX_WORKSPACE, ".agents", "skills")

    if args.no_composition_skills:
        assert not args.use_existing_skill_creator, "Cannot use existing skill creator when --no_composition_skills is True."
        assert not args.use_existing_skill_dir, "Cannot use existing skill dir when --no_composition_skills is True."
        assert not args.create_skill_only, "Cannot create skill only when --no_composition_skills is True."
    os.makedirs(RUNNING_DIR, exist_ok=True)
    logger = Logger(os.path.join(RUNNING_DIR, "000_overall.log"))
    sys.stdout = logger
    sys.stderr = logger

    args.dataset = os.path.abspath(os.path.expanduser(args.dataset))
    if args.max_concurrency <= 0:
        print(f"Error: --max_concurrency must be positive, got {args.max_concurrency}.")
        return

    exp_dir = os.path.join(os.path.dirname(OUTPUT_DIR), args.exp_id)
    os.makedirs(exp_dir, exist_ok=True)
    print(f"Created experiment directory: {exp_dir}")

    if args.no_composition_skills:
        args.skill_type = "baseline"
        skill_dir = None
        skill_creator_prefix = None
        original_creator_path = None
    elif args.skill_type == "vanilla":
        skill_dir = fixed_skill_dir
        skill_creator_prefix = CODEX_VANILLA_SKILL_CREATOR_PREFIX
        original_creator_path = CODEX_ORIGINAL_CREATOR_PATH_VANILLA
    elif args.skill_type == "expert":
        skill_dir = fixed_skill_dir
        skill_creator_prefix = CODEX_EXPERT_SKILL_CREATOR_PREFIX
        original_creator_path = CODEX_ORIGINAL_CREATOR_PATH_EXPERT
    else:
        raise ValueError(f"Unknown skill_type: {args.skill_type}")

    if args.no_composition_skills:
        creator_suffix = "no_composition_skills"
    elif args.use_existing_skill_dir and args.existing_skill_dir:
        creator_suffix = "copy_existing"
    elif args.use_existing_skill_creator and args.existing_skill_creator_dir:
        creator_suffix = f"created_by_{os.path.basename(os.path.normpath(args.existing_skill_creator_dir))}"
    else:
        creator_suffix = "created_by_defaults"

    skill_dir_name = "codex_fixed_skills" if skill_dir else "none"
    expected_skill_dir_suffix = f"_{args.skill_type}_{skill_dir_name}_{creator_suffix}"
    expected_generate_materials_suffix = f"_{args.skill_type}_res"
    is_dynamic_suffix = False
    if args.use_existing_skill_dir and args.existing_skill_dir:
        expected_generate_materials_suffix += f"_on_skills_{os.path.basename(os.path.normpath(args.existing_skill_dir))}"
    else:
        is_dynamic_suffix = True

    existing_prefixes = set()
    if os.path.isdir(exp_dir):
        for item in os.listdir(exp_dir):
            match = re.match(r"^(\d{4}_\d{4})(.*)", item)
            if not match:
                continue
            run_prefix = match.group(1)
            suffix = match.group(2)
            valid_suffixes = [expected_skill_dir_suffix]
            if is_dynamic_suffix:
                valid_suffixes.append(f"{expected_generate_materials_suffix}_on_skills_{run_prefix}{expected_skill_dir_suffix}")
            else:
                valid_suffixes.append(expected_generate_materials_suffix)
            if suffix in valid_suffixes:
                existing_prefixes.add(run_prefix)

    if existing_prefixes:
        assert len(existing_prefixes) == 1, f"Expected exactly 1 matching time_prefix, but found multiple: {existing_prefixes}"
        time_prefix = existing_prefixes.pop()
        print(f"Found existing experiment run matching current config, reusing time_prefix: {time_prefix}")
    else:
        time_prefix = datetime.now().strftime("%m%d_%H%M")
        print(f"Starting new experiment run with time_prefix: {time_prefix}")

    args.time_prefix = time_prefix
    args.new_skill_dir = f"{time_prefix}{expected_skill_dir_suffix}"
    args.new_skill_path = os.path.join(exp_dir, args.new_skill_dir)
    new_generate_materials_dir = f"{time_prefix}{expected_generate_materials_suffix}"
    if not (args.use_existing_skill_dir and args.existing_skill_dir):
        new_generate_materials_dir += f"_on_skills_{args.new_skill_dir}"
    args.new_generate_materials_path = os.path.join(exp_dir, new_generate_materials_dir)
    args.new_failed_path = os.path.join(exp_dir, f"{time_prefix}_{args.skill_type}_failed")
    args.new_half_stopped_path = os.path.join(exp_dir, f"{time_prefix}_{args.skill_type}_half_stopped")
    if not args.dry_run:
        os.makedirs(args.new_generate_materials_path, exist_ok=True)
        os.makedirs(args.new_failed_path, exist_ok=True)
        os.makedirs(args.new_half_stopped_path, exist_ok=True)

    args.search_dirs = [OUTPUT_DIR, args.new_generate_materials_path]

    if args.use_existing_skill_dir and args.use_existing_skill_creator:
        print("Error: --use_existing_skill_dir and --use_existing_skill_creator cannot both be True.")
        return

    print("=" * 50)
    print("Experiment Parameters:")
    print(json.dumps(vars(args), indent=4))
    print("=" * 50)

    if args.use_existing_skill_creator and args.existing_skill_creator_dir:
        if os.path.exists(args.existing_skill_creator_dir):
            if args.dry_run:
                print(f"Dry run: would copy existing skill creator from {args.existing_skill_creator_dir} to {original_creator_path}")
            else:
                if os.path.exists(original_creator_path):
                    shutil.rmtree(original_creator_path)
                shutil.copytree(args.existing_skill_creator_dir, original_creator_path)
                print(f"Copied existing skill creator from {args.existing_skill_creator_dir} to {original_creator_path}")
        else:
            print(f"Error: Existing skill creator directory {args.existing_skill_creator_dir} not found.")
            return

    if args.use_existing_skill_dir and args.existing_skill_dir:
        if os.path.exists(args.existing_skill_dir):
            if args.dry_run:
                print(f"Dry run: would sync composition skills from {args.existing_skill_dir} into fixed Codex skill dir {fixed_skill_dir}")
            else:
                sync_composition_skills_to_fixed_dir(
                    args.existing_skill_dir,
                    fixed_skill_dir,
                    dry_run=args.dry_run,
                    label="fixed Codex skill dir",
                )
                print(f"Synced composition skills from {args.existing_skill_dir} into fixed Codex skill dir {fixed_skill_dir}")
        else:
            print(f"Error: Existing skill directory {args.existing_skill_dir} not found.")
            return
    elif not args.no_composition_skills and skill_dir and os.path.isdir(args.new_skill_path):
        if args.dry_run:
            print(f"Dry run: would restore archived composition skills from {args.new_skill_path} into fixed Codex skill dir {fixed_skill_dir}")
        else:
            sync_composition_skills_to_fixed_dir(
                args.new_skill_path,
                fixed_skill_dir,
                dry_run=args.dry_run,
                label="fixed Codex skill dir",
            )
            print(f"Restored archived composition skills from {args.new_skill_path} into fixed Codex skill dir {fixed_skill_dir}")
    elif args.no_composition_skills:
        clean_composition_skills_from_fixed_dir(fixed_skill_dir, dry_run=args.dry_run, label="fixed Codex skill dir")

    if skill_dir and not args.dry_run:
        os.makedirs(skill_dir, exist_ok=True)
    if not os.path.isdir(args.dataset):
        print(f"Dataset directory not found: {args.dataset}")
        return

    if args.use_existing_skill_dir and args.existing_skill_dir and "all" in args.target_task:
        existing_skills = skill_names_in_dir(args.existing_skill_dir)
        matched_tasks = []
        for task_name in os.listdir(args.dataset):
            task_dir = os.path.join(args.dataset, task_name)
            skill_query_path = os.path.join(task_dir, "skill_query.json")
            if not os.path.isfile(skill_query_path):
                continue
            try:
                with open(skill_query_path, "r", encoding="utf-8") as f:
                    if json.load(f).get("skill_name", "") in existing_skills:
                        matched_tasks.append(task_name)
            except Exception:
                continue
        if matched_tasks:
            args.target_task = matched_tasks
            print(f"Automatically set target_task to {len(matched_tasks)} tasks based on existing skills in {args.existing_skill_dir}")
        else:
            print(f"Warning: No matching tasks found for skills in {args.existing_skill_dir}. Keeping original target_task.")

    all_tasks_to_run = []
    for task_name in os.listdir(args.dataset):
        if "all" not in args.target_task and task_name not in args.target_task:
            continue
        if "all" in args.target_task and task_name in args.but:
            continue
        task_dir = os.path.join(args.dataset, task_name)
        skill_query_path = os.path.join(task_dir, "skill_query.json")
        if not os.path.isdir(task_dir) or not os.path.isfile(skill_query_path):
            continue
        with open(skill_query_path, "r", encoding="utf-8") as f:
            try:
                skill_data = json.load(f)
            except json.JSONDecodeError:
                continue
        if args.no_composition_skills:
            skill_data["skill_name"] = "no_composition_skills"
        skill_name = skill_data.get("skill_name", "")
        sub_dirs = sorted([d for d in os.listdir(task_dir) if os.path.isdir(os.path.join(task_dir, d))])
        for sub_dir_name in sub_dirs[:args.test_sample]:
            sub_dir_path = os.path.join(task_dir, sub_dir_name)
            if not os.path.isdir(sub_dir_path):
                continue
            session_name = f"{task_name}_{sub_dir_name}_{skill_name}"
            if check_gen_artifacts_done(session_name, search_dirs=[args.new_generate_materials_path]) and not args.overwrite:
                tqdm.write(f"Session {session_name} gen artifacts already done. Skipping.")
                continue
            if not check_gen_done(session_name, None):
                move_to_failed_output(session_name)
            all_tasks_to_run.append({
                "task_name": task_name,
                "task_dir": task_dir,
                "sub_dir_path": sub_dir_path,
                "session_name": session_name,
                "skill_data": skill_data,
            })

    total_to_run = len(all_tasks_to_run)
    if total_to_run == 0:
        print("All tasks are complete.")

    processed_skills = set()
    failed_to_create_skills = set()
    skills_to_create = {}
    for task_info in all_tasks_to_run:
        if args.no_composition_skills:
            break
        task_name = task_info["task_name"]
        skill_data = task_info["skill_data"]
        skill_name = skill_data.get("skill_name", "")
        skill_query = skill_data.get("skill_query", "")
        if args.add_task_cases_in_creating_skills:
            sub_dirs = [os.path.join(task_info["task_dir"], d) for d in os.listdir(task_info["task_dir"]) if os.path.isdir(os.path.join(task_info["task_dir"], d))]
            skill_query = append_task_cases_prompt(skill_query, random.sample(sub_dirs, min(2, len(sub_dirs))))
        if skill_name in skills_to_create or skill_name in processed_skills:
            continue
        if skill_exists_for_run(skill_name, skill_dir, args):
            tqdm.write(f"Skill {skill_name} already exists. Skipping create_skill.")
            processed_skills.add(skill_name)
        elif args.use_existing_skill_dir and args.existing_skill_dir:
            print(
                f"Error: Required skill '{skill_name}' for task '{task_name}' is missing from "
                f"existing skill directory {args.existing_skill_dir}. "
                "--use_existing_skill_dir does not create new skills."
            )
            return None
        else:
            skills_to_create[skill_name] = {
                "task_name": task_name,
                "final_query": skill_creator_prefix.format(skill_name=skill_name, skill_dir=skill_dir) + skill_query,
            }

    if args.dry_run:
        print("\n" + "=" * 50)
        print("DRY RUN SUMMARY")
        print("=" * 50)
        print(f"Experiment ID: {args.exp_id}")
        print(f"Time Prefix: {args.time_prefix}")
        if args.no_composition_skills:
            print("Skill Strategy: Running BASELINE (no composition skills).")
        else:
            print(f"Skill Strategy: Using {args.skill_type.upper()} skills via fixed Codex skill dir '{fixed_skill_dir}'.")
        print(f"Skills to create: {len(skills_to_create)}")
        for skill_name, info in skills_to_create.items():
            print(f"  - {skill_name} (Task: {info['task_name']})")
        print(f"Tasks to run: {total_to_run}")
        for task_info in all_tasks_to_run:
            print(f"  - {task_info['session_name']}")
        print("=" * 50 + "\n")
        return

    pbar = tqdm(total=len(skills_to_create) + (0 if args.create_skill_only else total_to_run), desc="Pipeline Progress")

    if skills_to_create:
        tqdm.write(f"Creating {len(skills_to_create)} skills concurrently...")
        active_create_tasks = set()

        def skill_done_callback(t):
            try:
                res_skill_name, result = t.result()
                create_session_name = f"create_{res_skill_name}"
                if not result["success"]:
                    tqdm.write(f"Failed to create skill {res_skill_name}. Error: {result.get('error', 'Unknown')}")
                    failed_to_create_skills.add(res_skill_name)
                    failed_dir = find_session_dir(create_session_name, session_id=result.get("session_id"), search_dirs=[FAILED_DIR, OUTPUT_DIR])
                    if failed_dir and os.path.exists(failed_dir):
                        final_dst = os.path.join(args.new_failed_path, os.path.basename(failed_dir))
                        try:
                            if os.path.exists(final_dst):
                                shutil.rmtree(final_dst)
                            shutil.move(failed_dir, final_dst)
                        except Exception:
                            pass
                else:
                    tqdm.write(f"Successfully created skill {res_skill_name}.")
                    processed_skills.add(res_skill_name)
                    os.makedirs(args.new_skill_path, exist_ok=True)
                    skill_src = os.path.join(skill_dir, res_skill_name)
                    skill_dst = os.path.join(args.new_skill_path, res_skill_name)
                    if os.path.isdir(skill_src):
                        try:
                            if os.path.exists(skill_dst):
                                shutil.rmtree(skill_dst)
                            shutil.copytree(skill_src, skill_dst)
                        except Exception:
                            pass
                    success_dir = find_session_dir(create_session_name, session_id=result.get("session_id"), search_dirs=[OUTPUT_DIR])
                    if success_dir and os.path.exists(success_dir):
                        creation_logs_dir = os.path.join(args.new_skill_path, "_creation_logs")
                        os.makedirs(creation_logs_dir, exist_ok=True)
                        final_dst = os.path.join(creation_logs_dir, os.path.basename(success_dir))
                        try:
                            if os.path.exists(final_dst):
                                shutil.rmtree(final_dst)
                            shutil.move(success_dir, final_dst)
                        except Exception:
                            pass
            except Exception as e:
                tqdm.write(f"Task failed with exception: {e}")
            finally:
                pbar.update(1)

        for skill_name, info in skills_to_create.items():
            tqdm.write(f"Queueing skill creation: {skill_name} for task {info['task_name']}...")
            while len(active_create_tasks) >= args.max_concurrency:
                _, active_create_tasks = await asyncio.wait(active_create_tasks, return_when=asyncio.FIRST_COMPLETED)
            task = asyncio.create_task(create_skill_task(
                skill_name,
                info["final_query"],
                CODEX_WORKSPACE,
                args.timeout_seconds,
                RUNNING_DIR,
                args.max_retries,
                args.retry_delay,
            ))
            task.add_done_callback(skill_done_callback)
            active_create_tasks.add(task)
        if active_create_tasks:
            await asyncio.wait(active_create_tasks)

    if args.create_skill_only:
        pbar.close()
        print("Skill creation phase completed. Exiting as --create_skill_only is set.")
        archive_pipeline_dirs(exp_dir, args.time_prefix, args.skill_type, FAILED_DIR, args.new_failed_path, HALF_STOPPED_DIR, args.new_half_stopped_path, RUNNING_DIR)
        print(f"All tasks have been completed. Outputs archived to {exp_dir}.")
        return None

    semaphore = asyncio.Semaphore(args.max_concurrency)

    async def sem_pipeline_task(task_info):
        async with semaphore:
            skill_name = task_info["skill_data"].get("skill_name", "")
            if skill_name in failed_to_create_skills:
                failed_gen_sessions.add(task_info["session_name"])
                pbar.update(1)
                return
            await run_case_pipeline(
                task_info["session_name"],
                task_info["task_name"],
                os.path.basename(task_info["sub_dir_path"]),
                task_info["sub_dir_path"],
                args,
                pbar,
                skill_name=skill_name,
            )

    tasks = []
    for task_info in all_tasks_to_run:
        tasks.append(asyncio.create_task(sem_pipeline_task(task_info)))
        await asyncio.sleep(5)
    if tasks:
        await asyncio.wait(tasks)
    pbar.close()

    print("\n--- Pipeline Summary ---")
    print(f"Total tasks processed(skills creating task not included): {total_to_run}")
    print(f"Skills created: {len(processed_skills)} (Failed: {len(failed_to_create_skills)})")
    print(f"Done Generation: {len(done_gen_sessions)}")
    print(f"Failed Generation: {len(failed_gen_sessions)}")
    print_success_rate_summary(args.task_max_retries, search_dirs=args.search_dirs + [FAILED_DIR, args.new_failed_path], save_dir=args.new_generate_materials_path)
    generate_basic_results_summary(args.new_generate_materials_path)

    archive_pipeline_dirs(exp_dir, args.time_prefix, args.skill_type, FAILED_DIR, args.new_failed_path, HALF_STOPPED_DIR, args.new_half_stopped_path, RUNNING_DIR)
    print(f"All tasks have been completed. Outputs archived to {exp_dir}.")


def cleanup(args):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    print("\nCaught KeyboardInterrupt. Stopping active Codex processes...")
    terminate_processes(list(active_processes))

    print("Moving unfinished sessions to half_stopped...")
    for session_name in list(running_sessions):
        try:
            move_to_half_stopped_output(session_name, session_id=latest_gen_session_ids.get(session_name))
        except Exception:
            pass

if __name__ == "__main__":
    args = parse_arguments()
    print(f"CodeX cwd: {CODEX_WORKSPACE}")
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        cleanup(args)
