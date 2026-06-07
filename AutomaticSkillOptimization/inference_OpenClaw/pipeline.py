import json
import asyncio
import argparse
import os
import random
import time
import shutil
import sys
import re
from tqdm import tqdm
from datetime import datetime

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from AutomaticSkillOptimization.inference_OpenClaw.openclaw_sdk_tools import delete_session, get_available_agent_ids
from AutomaticSkillOptimization.prompts import (
    append_task_cases_prompt,
    build_eval_prompt,
    expert_skill_creator_prefix,
    vanilla_skill_creator_prefix,
    VIDEO_GENERATION_TASK_PREFIX,
    VIDEO_GENERATION_TASK_PREFIX_WO_TASK_TRACKER,
)
from AutomaticSkillOptimization.evaluation_PRM.generate_summary import generate_eval_summary
from AutomaticSkillOptimization.evaluation_PRM.evaluation_utils import (
    check_eval_done,
    copy_human_rubrics,
    ensure_execution_error_eval,
    load_and_prepare_rubric,
    load_execution_error_rubric_template,
)
from AutomaticSkillOptimization.args import DATASET_DIR, EXTRA_SKILL_LOADING_DIR, FAILED_DIR, HALF_STOPPED_DIR, OPENCLAW_WORKSPACE, OUTPUT_DIR, RUNNING_DIR, setup_openclaw_workspace
from AutomaticSkillOptimization.args import (
    BACKUP_ORIGINAL_CREATOR_PATH_EXPERT,
    BACKUP_ORIGINAL_CREATOR_PATH_VANILLA,
    ORIGINAL_CREATOR_PATH_EXPERT,
    ORIGINAL_CREATOR_PATH_VANILLA,
)
from AutomaticSkillOptimization.utils import (
    Logger,
    archive_pipeline_dirs,
    cleanup_skill_dir,
    find_final_video_paths,
    find_session_dir,
    generate_basic_results_summary,
    move_to_failed_output,
    print_success_rate_summary,
    process_input,
    restore_skill_creator_backup,
    save_basic_result,
)
from AutomaticSkillOptimization.inference_OpenClaw.running_utils import (
    run_single_task,
    create_skill_task,
    running_sessions,
    done_gen_sessions,
    failed_gen_sessions,
    done_eval_sessions,
    failed_eval_sessions,
    check_gen_done,
)

from AutomaticSkillOptimization.summary_txt import summarize_react_process_txt

async def process_and_run_gen_task(agent_id, session_name, sub_dir_path, thinking, timeout_seconds, logs_dir, max_retries=3, task_max_retries=3, retry_delay=60, add_task_tracker=True):
    global running_sessions, done_gen_sessions, failed_gen_sessions
    attempt_errors = []
    for attempt in range(task_max_retries):
        running_sessions.add((agent_id, session_name))
        try:
            log_file = os.path.join(logs_dir, f"{session_name}.log")
            # 只有在第一次尝试时才需要overwrite_log, 后面的task_max_retries*max_retries次尝试都不需要overwrite_log
            result = await run_single_task(agent_id, session_name, "/new", thinking, timeout_seconds, log_file, overwrite_log=True if attempt==0 else False, max_retries=max_retries, retry_delay=retry_delay)
            if not result.get("success", False):
                error_msg = result.get("stderr", "Unknown error")
                print(f"Failed to /new {session_name}. Error: {error_msg}")
                attempt_errors.append({"attempt": attempt + 1, "error": error_msg})
                if attempt < task_max_retries - 1:
                    move_to_failed_output(session_name, agent_id=agent_id)
                    await delete_session(agent_id, session_name)
                    print(f"[{session_name}] Task failed on /new, retrying ({attempt + 1}/{task_max_retries})...")
                    continue
                running_sessions.discard((agent_id, session_name))
                failed_gen_sessions.add(session_name)
                save_basic_result(session_name, agent_id=agent_id, success=False, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors)
                move_to_failed_output(session_name, agent_id=agent_id)
                await delete_session(agent_id, session_name)
                return False

            input_context = process_input(sub_dir_path, VIDEO_GENERATION_TASK_PREFIX, VIDEO_GENERATION_TASK_PREFIX_WO_TASK_TRACKER, add_task_tracker=add_task_tracker)

            if not input_context:
                error_msg = "No valid input context files"
                print(f"Warning: {session_name} has no valid input context files")
                attempt_errors.append({"attempt": attempt + 1, "error": error_msg})
                if attempt < task_max_retries - 1:
                    move_to_failed_output(session_name, agent_id=agent_id)
                    await delete_session(agent_id, session_name)
                    print(f"[{session_name}] Task failed due to no valid input context, retrying ({attempt + 1}/{task_max_retries})...")
                    continue
                running_sessions.discard((agent_id, session_name))
                failed_gen_sessions.add(session_name)
                save_basic_result(session_name, agent_id=agent_id, success=False, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors)
                move_to_failed_output(session_name, agent_id=agent_id)
                await delete_session(agent_id, session_name)
                return False

            print(f"[{session_name}] Starting Gen...")

            task_start_time = time.time()
            result = await run_single_task(agent_id, session_name, input_context, thinking, timeout_seconds, log_file, max_retries=max_retries, retry_delay=retry_delay)
            task_duration = time.time() - task_start_time

            if result.get("success", False):
                if check_gen_done(agent_id, session_name):
                    running_sessions.discard((agent_id, session_name))
                    done_gen_sessions.add(session_name)
                    print(f"[{session_name}] Succeeded Gen on attempt {attempt + 1}/{task_max_retries}")
                    
                    cost = result.get("response_data", {}).get("cost")
                    tool_call_count = result.get("response_data", {}).get("tool_call_count", 0)
                    
                    save_basic_result(session_name, agent_id=agent_id, success=True, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors, duration_seconds=task_duration, backbone_cost=cost, tool_call_count=tool_call_count)
                    await delete_session(agent_id, session_name)
                    return True
                else:
                    error_msg = result.get("stderr", "Task executed but not fully done (missing files/videos)")
                    print(f"[{session_name}] {error_msg}.")
                    attempt_errors.append({"attempt": attempt + 1, "error": error_msg})
                    if attempt < task_max_retries - 1:
                        move_to_failed_output(session_name, agent_id=agent_id)
                        await delete_session(agent_id, session_name)
                        print(f"[{session_name}] Task incomplete, retrying ({attempt + 1}/{task_max_retries})...")
                        continue
                    running_sessions.discard((agent_id, session_name))
                    failed_gen_sessions.add(session_name)
                    
                    cost = result.get("response_data", {}).get("cost")
                    tool_call_count = result.get("response_data", {}).get("tool_call_count", 0)
                    save_basic_result(session_name, agent_id=agent_id, success=False, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors, duration_seconds=task_duration, backbone_cost=cost, tool_call_count=tool_call_count)
                    # 感觉不能直接移动到FAILED_DIR, 因为需要评估结果
                    move_to_failed_output(session_name, agent_id=agent_id)
                    await delete_session(agent_id, session_name)
                    return False
            else:
                error_msg = result.get("stderr", "Unknown error")
                attempt_errors.append({"attempt": attempt + 1, "error": error_msg})
                if attempt < task_max_retries - 1:
                    move_to_failed_output(session_name, agent_id=agent_id)
                    await delete_session(agent_id, session_name)
                    print(f"[{session_name}] Task failed, error message: {error_msg}, retrying ({attempt + 1}/{task_max_retries})...")
                    continue
                running_sessions.discard((agent_id, session_name))
                failed_gen_sessions.add(session_name)
                
                cost = result.get("response_data", {}).get("cost") if isinstance(result.get("response_data"), dict) else None
                tool_call_count = result.get("response_data", {}).get("tool_call_count", 0) if isinstance(result.get("response_data"), dict) else 0
                save_basic_result(session_name, agent_id=agent_id, success=False, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors, duration_seconds=task_duration, backbone_cost=cost, tool_call_count=tool_call_count)
                move_to_failed_output(session_name, agent_id=agent_id)
                await delete_session(agent_id, session_name)
                return False
        except asyncio.CancelledError:
            print(f"[{session_name}] Cancelled (Ctrl+C). Marking as half_stopped...")
            raise
        except Exception as e:
            error_msg = str(e)
            print(f"[{session_name}] Exception occurred: {error_msg}")
            attempt_errors.append({"attempt": attempt + 1, "error": error_msg})
            if attempt < task_max_retries - 1:
                move_to_failed_output(session_name, agent_id=agent_id)
                await delete_session(agent_id, session_name)
                print(f"[{session_name}] Exception occurred, retrying ({attempt + 1}/{task_max_retries})...")
                continue
            running_sessions.discard((agent_id, session_name))
            failed_gen_sessions.add(session_name)
            save_basic_result(session_name, agent_id=agent_id, success=False, attempts=attempt + 1, max_retries=task_max_retries, attempt_errors=attempt_errors)
            move_to_failed_output(session_name, agent_id=agent_id)
            await delete_session(agent_id, session_name)
            return False

async def process_and_run_eval_task(agent_id, session_name, input_context, thinking, timeout_seconds, logs_dir, max_retries=3, eval_max_retries=3, retry_delay=60):
    global running_sessions, done_eval_sessions, failed_eval_sessions
    task_max_retries = eval_max_retries
    for attempt in range(task_max_retries):
        running_sessions.add((agent_id, session_name))
        try:
            log_file = os.path.join(logs_dir, f"{session_name}.log")
            result = await run_single_task(agent_id, session_name, "/new", thinking, timeout_seconds, log_file, overwrite_log=True, max_retries=max_retries, retry_delay=retry_delay)
            if not result.get("success", False):
                error_msg = result.get("stderr", "Unknown error")
                print(f"Failed to /new {session_name}. Error: {error_msg}")
                move_to_failed_output(session_name, agent_id=agent_id)
                await delete_session(agent_id, session_name)
                if attempt < task_max_retries - 1:
                    print(f"[{session_name}] Eval Task failed on /new, retrying ({attempt + 1}/{task_max_retries})...")
                    continue
                running_sessions.discard((agent_id, session_name))
                failed_eval_sessions.add(session_name)
                return False
                
            
            result = await run_single_task(agent_id, session_name, input_context, thinking, timeout_seconds, log_file, max_retries=max_retries, retry_delay=retry_delay)
            if result.get("success", False):
                if check_eval_done(agent_id, session_name):
                    running_sessions.discard((agent_id, session_name))
                    done_eval_sessions.add(session_name)
                    await delete_session(agent_id, session_name)
                    print(f"[{session_name}] Succeeded Eval on attempt {attempt + 1}/{task_max_retries}")
                    return True
                else:
                    error_msg = result.get("stderr", "Eval Task executed but not fully done (missing ReAct/rubrics file).")
                    print(f"[{session_name}] {error_msg}.")
                    move_to_failed_output(session_name, agent_id=agent_id)
                    await delete_session(agent_id, session_name)
                    if attempt < task_max_retries - 1:
                        print(f"[{session_name}] Eval Task incomplete, retrying ({attempt + 1}/{task_max_retries})...")
                        continue
                    running_sessions.discard((agent_id, session_name))
                    failed_eval_sessions.add(session_name)
                    return False
            else:
                error_msg = result.get("stderr", "Unknown error")
                move_to_failed_output(session_name, agent_id=agent_id)
                await delete_session(agent_id, session_name)
                if attempt < task_max_retries - 1:
                    print(f"[{session_name}] Eval Task failed, error message: {error_msg}, retrying ({attempt + 1}/{task_max_retries})...")
                    continue
                running_sessions.discard((agent_id, session_name))
                failed_eval_sessions.add(session_name)
                return False
        except asyncio.CancelledError:
            print(f"[{session_name}] Cancelled (Ctrl+C). Marking as half_stopped...")
            raise
        except Exception as e:
            print(f"Exception in {session_name}: {e}")
            move_to_failed_output(session_name, agent_id=agent_id)
            await delete_session(agent_id, session_name)
            if attempt < task_max_retries - 1:
                print(f"[{session_name}] Exception occurred, retrying ({attempt + 1}/{task_max_retries})...")
                continue
            running_sessions.discard((agent_id, session_name))
            failed_eval_sessions.add(session_name)
            return False




async def run_case_pipeline(agent_id, session_name, task_name, sub_dir_name, sub_dir_path, args, pbar):
    # Check if Generation is already done
    gen_done = check_gen_done(None, session_name)
    
    if gen_done:
        print(f"[{session_name}] Gen already done. Skipping generation.")
        gen_success = True
    else:
        # 1. Gen
        gen_success = await process_and_run_gen_task(agent_id, session_name, sub_dir_path, args.thinking, args.timeout_seconds, RUNNING_DIR, args.max_retries, args.task_max_retries, args.retry_delay, add_task_tracker=args.add_task_tracker)
    
    if not gen_success:
        # Move to new_failed_path immediately
        if not hasattr(run_case_pipeline, "copy_lock"):
            run_case_pipeline.copy_lock = asyncio.Lock()
        async with run_case_pipeline.copy_lock:
            failed_dir = find_session_dir(session_name, agent_id=agent_id, search_dirs=[FAILED_DIR])
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

    # 4. Copy eval results (Formalize) per case
    # Removed from here since it's now at the end of run_case_pipeline

    # 2. summarize ReAct_process.json
    item_path = find_session_dir(session_name, agent_id=agent_id, search_dirs=[OUTPUT_DIR])
    if not item_path:
        print(f"⚠️ item_path not found for {session_name}")
        pbar.update(1)
        return
    
    react_file_path = os.path.join(item_path, "ReAct_process.json")
    if os.path.exists(react_file_path):
        summarize_react_process_txt(react_file_path, session_name)

    # 3. Eval
    if "all" not in args.target_task and task_name not in args.target_task:
        print(f"Skipping eval for {session_name} as target_task is {args.target_task}")
        pbar.update(1)
        return

    rubric_path = os.path.join(args.dataset, task_name, sub_dir_name, "rubric_deterministic.json")
    skip_ids = ["fixed_P0", "fixed_P1"] if args.no_composition_skills else None
    rubric_content, execution_error_rubric_template = load_and_prepare_rubric(rubric_path, skip_rubric_ids=skip_ids)
    if rubric_content is None:
        print(f"⚠️ rubric file not found for {task_name}/{sub_dir_name}")
        pbar.update(1)
        return

    copy_human_rubrics(args.dataset, task_name, sub_dir_name, item_path)

    react_file = os.path.join(item_path, "ReAct_process.json")
    final_video_paths = find_final_video_paths(item_path)
    
    eval_prompt = build_eval_prompt(
        rubric_content,
        react_file,
        item_path,
        final_video_paths=final_video_paths,
    )
    
    eval_session_name = f"eval_{session_name}"
    
    # Check if already evaluated (unless overwrite)
    if not args.overwrite and check_eval_done(agent_id, eval_session_name, gen_session_name=session_name):
        tqdm.write(f"Session {eval_session_name} already done. Skipping.")
        for a_id in args.available_agents:
            await delete_session(a_id, eval_session_name)
    else:
        # 3. Eval
        print(f"[{session_name}] Starting Eval...")
        eval_success = await process_and_run_eval_task(agent_id, eval_session_name, eval_prompt, args.thinking, args.timeout_seconds, RUNNING_DIR, args.max_retries, args.eval_max_retries, args.retry_delay)
        if not eval_success:
            # Eval failed. Gen is still in OUTPUT_DIR. Move both to FAILED_DIR or new_failed_path
            if not hasattr(run_case_pipeline, "copy_lock"):
                run_case_pipeline.copy_lock = asyncio.Lock()
            async with run_case_pipeline.copy_lock:
                # Move gen
                gen_dir = find_session_dir(session_name, agent_id=agent_id, search_dirs=[OUTPUT_DIR])
                if gen_dir and os.path.exists(gen_dir) and os.path.dirname(os.path.abspath(gen_dir)) != os.path.abspath(args.new_failed_path):
                    final_dst = os.path.join(args.new_failed_path, os.path.basename(gen_dir))
                    try:
                        if os.path.exists(final_dst):
                            shutil.rmtree(final_dst)
                        shutil.move(gen_dir, final_dst)
                    except Exception as e:
                        pass
                # Move eval (which is probably already in FAILED_DIR by process_and_run_eval_task)
                eval_failed_dir = find_session_dir(eval_session_name, agent_id=agent_id, search_dirs=[FAILED_DIR])
                if eval_failed_dir and os.path.exists(eval_failed_dir) and os.path.dirname(os.path.abspath(eval_failed_dir)) != os.path.abspath(args.new_failed_path):
                    final_eval_dst = os.path.join(args.new_failed_path, os.path.basename(eval_failed_dir))
                    try:
                        if os.path.exists(final_eval_dst):
                            shutil.rmtree(final_eval_dst)
                        shutil.move(eval_failed_dir, final_eval_dst)
                    except Exception as e:
                        pass
            pbar.update(1)
            return

    
    # 4. Copy eval results (Formalize) per case
    if not args.skip_copy:
        # Perform the formalization (move eval folder inside gen folder)
        if not hasattr(run_case_pipeline, "copy_lock"):
            run_case_pipeline.copy_lock = asyncio.Lock()

        async with run_case_pipeline.copy_lock:
            gen_dir = find_session_dir(session_name, agent_id=agent_id, search_dirs=[OUTPUT_DIR])
            eval_dir = find_session_dir(f"eval_{session_name}", agent_id=agent_id, search_dirs=[OUTPUT_DIR])
            if gen_dir and eval_dir and os.path.abspath(gen_dir) != os.path.abspath(eval_dir):
                dst_path = os.path.join(gen_dir, "evals")
                try:
                    if os.path.exists(dst_path):
                        shutil.rmtree(dst_path)
                    shutil.move(eval_dir, dst_path)
                except Exception as e:
                    print(f"[{session_name}] Failed to move eval result: {e}")

            if gen_dir and os.path.exists(gen_dir):
                ensure_execution_error_eval(
                    gen_dir,
                    execution_error_rubric_template,
                )
            
            # Now move the gen_dir to new_generate_materials_path
            if gen_dir and os.path.exists(gen_dir) and os.path.dirname(os.path.abspath(gen_dir)) != os.path.abspath(args.new_generate_materials_path):
                final_dst = os.path.join(args.new_generate_materials_path, os.path.basename(gen_dir))
                try:
                    if os.path.exists(final_dst):
                        shutil.rmtree(final_dst)
                    shutil.move(gen_dir, final_dst)
                    print(f"[{session_name}] Moved output to {final_dst}")
                except Exception as e:
                    print(f"[{session_name}] Failed to move gen_dir to final dest: {e}")
    else:
        ensure_execution_error_eval(
            item_path,
            execution_error_rubric_template,
        )

    pbar.update(1)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Pipeline Run OpenClaw Agent Chat and Eval")
    parser.add_argument("--agent_id", type=str, default="main", help="Agent ID")
    parser.add_argument("--dataset", type=str, default=DATASET_DIR, help="Path to the dataset directory")
    parser.add_argument("--max_concurrency", type=int, default=20, help="Maximum number of concurrent tasks")
    parser.add_argument("--thinking", action="store_true", help="Enable thinking mode")
    parser.add_argument("--timeout_seconds", type=int, default=10800, help="Execution timeout in seconds")
    parser.add_argument("--max_retries", type=int, default=6, help="Maximum number of retries for rate limit errors and timed out errors, this is not skills' error but the system's unavoidable glitches")
    parser.add_argument("--task_max_retries", type=int, default=3, help="Maximum number of retries for gen task")
    parser.add_argument("--eval_max_retries", type=int, default=9, help="Maximum number of retries for eval task")
    parser.add_argument("--retry_delay", type=int, default=10, help="Delay in seconds before retrying")

    parser.add_argument("--target_task", type=str, nargs="+", default=["all"], help="Target tasks to run, or 'all' for all tasks")
    parser.add_argument("--but", type=str, nargs="+", default=["主题视频", "ai数字人科技数码讲解视频", "品牌宣传片"], help="Skip specific tasks when target_task is 'all'")
    # "主题视频", "ai数字人科技数码讲解视频", "品牌宣传片"
    parser.add_argument("--test_sample", type=int, default=40, help="Run only a sample of cases for each task for testing")
    parser.add_argument("--skill_type", type=str, default="expert", help="Skill type to run, 'expert' or 'vanilla' for vanilla skills")
    parser.add_argument("--create_skill_only", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Only create skills, do not run tasks")
    
    parser.add_argument("--use_existing_skill_dir", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=True, help="Whether to use an existing skill directory")
    parser.add_argument("--existing_skill_dir", type=str, default="CodeX_GPT_skill_optimization_v2_no_reward/0521_2019_codex_gpt_v2_opt_0513_1248_expert_composition_skills_expert_created_by_defaults", help="Path to the existing skill directory")
    
    parser.add_argument("--use_existing_skill_creator", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Whether to use an existing skill creator directory")
    parser.add_argument("--existing_skill_creator_dir", type=str, default="", help="Path to the existing skill creator directory")
    
    parser.add_argument("--no_composition_skills", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Run baseline without creating or using skills")
    
    parser.add_argument("--add_task_cases_in_creating_skills", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=True, help="Add task cases when creating skills")
    parser.add_argument("--exp_id", type=str, default="OC_Seed_video_skill_creator_no_reward_optimized_by_CodeX_GPT_iterations_1", help="Experiment ID to group results")
    parser.add_argument("--random_seed", type=int, default=42, help="Random seed for reproducibility")
    # Eval args
    parser.add_argument("--skip_copy", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Skip copying eval results to output_dir")
    parser.add_argument("--overwrite", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Overwrite existing eval results")
    parser.add_argument("--dry_run", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Dry run: print info and exit before execution")
    parser.add_argument("--add_task_tracker", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=False, help="Add task tracker to prompt")
    return parser.parse_args()


def restore_replaced_skill_creator(args):
    if getattr(args, "_skill_creator_was_replaced", False):
        restore_skill_creator_backup(args._original_creator_path, args._backup_creator_path)
        args._skill_creator_was_replaced = False


async def main(args):
    random.seed(args.random_seed)
    if not args.dry_run:
        setup_openclaw_workspace()
    if args.no_composition_skills:
        assert not args.use_existing_skill_creator, "Cannot use existing skill creator when --no_composition_skills is True."
        assert not args.use_existing_skill_dir, "Cannot use existing skill dir when --no_composition_skills is True."
        assert not args.create_skill_only, "Cannot create skill only when --no_composition_skills is True."
    if not args.dry_run:
        os.makedirs(RUNNING_DIR, exist_ok=True)
        overall_log_path = os.path.join(RUNNING_DIR, "000_overall.log")
        logger = Logger(overall_log_path)
        sys.stdout = logger
        sys.stderr = logger

    exp_dir = os.path.join(os.path.dirname(OUTPUT_DIR), args.exp_id)
    if not args.dry_run:
        os.makedirs(exp_dir, exist_ok=True)
        print(f"Created experiment directory: {exp_dir}")
    else:
        print(f"Dry run: would use experiment directory: {exp_dir}")

    if args.no_composition_skills:
        args.skill_type = "baseline"
        skill_dir = None
        skill_creator_prefix = None
        original_creator_path = None
        backup_creator_path = None
    elif args.skill_type == "vanilla":
        skill_dir = os.path.join(OPENCLAW_WORKSPACE, "composition_skills_vanilla")
        skill_creator_prefix = vanilla_skill_creator_prefix
        original_creator_path = ORIGINAL_CREATOR_PATH_VANILLA
        backup_creator_path = BACKUP_ORIGINAL_CREATOR_PATH_VANILLA
    elif args.skill_type == "expert":
        skill_dir = os.path.join(OPENCLAW_WORKSPACE, "composition_skills_expert")
        skill_creator_prefix = expert_skill_creator_prefix
        original_creator_path = ORIGINAL_CREATOR_PATH_EXPERT
        backup_creator_path = BACKUP_ORIGINAL_CREATOR_PATH_EXPERT
    else:
        raise ValueError(f"Unknown skill_type: {args.skill_type}. Must be 'vanilla', 'expert', or use --no_composition_skills.")

    if not args.no_composition_skills and skill_dir and skill_dir not in EXTRA_SKILL_LOADING_DIR:
        print(f"ERROR: skill_dir '{skill_dir}' not in EXTRA_SKILL_LOADING_DIR, aborting.")
        return

    if args.no_composition_skills:
        creator_suffix = "no_composition_skills"
        # baseline 模式不应该保留任何 composition skills，避免后续流程误读旧技能目录。
        for stale_skill_dir in EXTRA_SKILL_LOADING_DIR:
            if os.path.isdir(stale_skill_dir):
                if args.dry_run:
                    print(f"Dry run: would delete stale composition skill directory: {stale_skill_dir}")
                else:
                    shutil.rmtree(stale_skill_dir)
                    print(f"Deleted stale composition skill directory: {stale_skill_dir}")
    elif args.use_existing_skill_dir and args.existing_skill_dir:
        creator_suffix = "copy_existing"
    elif args.use_existing_skill_creator and args.existing_skill_creator_dir:
        creator_name = os.path.basename(os.path.normpath(args.existing_skill_creator_dir))
        creator_suffix = f"created_by_{creator_name}"
    else:
        creator_suffix = "created_by_defaults"

    # Pre-calculate the expected suffixes
    skill_dir_name = os.path.basename(skill_dir) if skill_dir else "none"
    expected_skill_dir_suffix = f"_{args.skill_type}_{skill_dir_name}_{creator_suffix}"
    expected_generate_materials_suffix = f"_{args.skill_type}_res"
    is_dynamic_suffix = False
    if args.use_existing_skill_dir and args.existing_skill_dir:
        existing_skill_dir_name = os.path.basename(os.path.normpath(args.existing_skill_dir))
        expected_generate_materials_suffix += f"_on_skills_{existing_skill_dir_name}"
    else:
        is_dynamic_suffix = True
        

    existing_prefixes = set()
    if os.path.isdir(exp_dir):
        for item in os.listdir(exp_dir):
            match = re.match(r'^(\d{4}_\d{4})(.*)', item)
            if match:
                prefix = match.group(1)
                suffix = match.group(2)

                valid_suffixes = [expected_skill_dir_suffix]

                if is_dynamic_suffix:
                    valid_suffixes.append(f"{expected_generate_materials_suffix}_on_skills_{prefix}{expected_skill_dir_suffix}")
                else:
                    valid_suffixes.append(expected_generate_materials_suffix)

                if suffix in valid_suffixes:
                    existing_prefixes.add(prefix)
            
    if existing_prefixes:
        assert len(existing_prefixes) == 1, f"Expected exactly 1 matching time_prefix, but found multiple: {existing_prefixes}"
        time_prefix = existing_prefixes.pop()
        print(f"Found existing experiment run matching current config, reusing time_prefix: {time_prefix}")
    else:
        time_prefix = datetime.now().strftime('%m%d_%H%M')
        print(f"Starting new experiment run with time_prefix: {time_prefix}")
        
    args.time_prefix = time_prefix

    new_skill_dir = f"{time_prefix}{expected_skill_dir_suffix}"
    args.new_skill_dir = new_skill_dir
    args.new_skill_path = os.path.join(exp_dir, new_skill_dir)

    new_generate_materials_dir = f"{time_prefix}{expected_generate_materials_suffix}"
    if not (args.use_existing_skill_dir and args.existing_skill_dir):
        new_generate_materials_dir += f"_on_skills_{new_skill_dir}"
    args.new_generate_materials_path = os.path.join(exp_dir, new_generate_materials_dir)
    if not args.dry_run:
        os.makedirs(args.new_generate_materials_path, exist_ok=True)
    
    args.new_failed_path = os.path.join(exp_dir, f"{time_prefix}_{args.skill_type}_failed")
    if not args.dry_run:
        os.makedirs(args.new_failed_path, exist_ok=True)
    args.new_half_stopped_path = os.path.join(exp_dir, f"{time_prefix}_{args.skill_type}_half_stopped")
    if not args.dry_run:
        os.makedirs(args.new_half_stopped_path, exist_ok=True)
    
    # Collect specifically the historical folders for the current experiment run
    # Exclude FAILED_DIR and HALF_STOPPED_DIR from done checks so failed tasks can be retried
    args.search_dirs = [OUTPUT_DIR, args.new_generate_materials_path]

    
    available_agents = await get_available_agent_ids(args.agent_id)
    args.available_agents = available_agents
    print(f"Available agents for execution: {available_agents}")

    if args.use_existing_skill_dir and args.use_existing_skill_creator:
        print("Error: --use_existing_skill_dir and --use_existing_skill_creator cannot be both True at the same time.")
        return

    args._original_creator_path = original_creator_path
    args._backup_creator_path = backup_creator_path
    args._skill_creator_was_replaced = False
    
    print("=" * 50)
    print("Experiment Parameters:")
    print(json.dumps(vars(args), indent=4))
    print("=" * 50)
    # if use existing skill creator and its name is 'video-skill-creator', we should set skill-type to 'expert', if its name is 'skill-creator', we should set skill-type to 'vanilla'
    if args.use_existing_skill_creator and args.existing_skill_creator_dir != "":
        # assert args.skill_type in str(args.existing_skill_creator_dir).lower()
        if os.path.exists(args.existing_skill_creator_dir):
            if args.dry_run:
                print(f"Dry run: would copy existing skill creator from {args.existing_skill_creator_dir} to {original_creator_path}")
            else:
                if os.path.exists(original_creator_path):
                    shutil.rmtree(original_creator_path)
                shutil.copytree(args.existing_skill_creator_dir, original_creator_path)
                args._skill_creator_was_replaced = True
                print(f"Copied existing skill creator from {args.existing_skill_creator_dir} to {original_creator_path}")
        else:
            print(f"Error: Existing skill creator directory {args.existing_skill_creator_dir} not found.")
            return
    if args.use_existing_skill_dir and args.existing_skill_dir != "":
        # assert args.skill_type in str(args.existing_skill_dir).lower()

        if os.path.exists(args.existing_skill_dir):
            if args.dry_run:
                print(f"Dry run: would copy existing skill directory from {args.existing_skill_dir} to {skill_dir}")
            else:
                if os.path.exists(skill_dir):
                    shutil.rmtree(skill_dir)
                shutil.copytree(args.existing_skill_dir, skill_dir)
                print(f"Copied existing skill directory from {args.existing_skill_dir} to {skill_dir}")
        else:
            print(f"Error: Existing skill directory {args.existing_skill_dir} not found.")
            return
    elif not args.no_composition_skills and skill_dir and os.path.isdir(args.new_skill_path):
        if args.dry_run:
            print(f"Dry run: would restore skills from archive {args.new_skill_path} to {skill_dir}")
        else:
            if os.path.isdir(skill_dir):
                shutil.rmtree(skill_dir)
            shutil.copytree(args.new_skill_path, skill_dir)
            print(f"Restored skills from archive {args.new_skill_path} to {skill_dir}")
    elif not args.no_composition_skills and skill_dir and os.path.isdir(skill_dir):
        if args.dry_run:
            print(f"Dry run: would remove stale skill directory {skill_dir} for clean start.")
        else:
            shutil.rmtree(skill_dir)
            print(f"Removed stale skill directory {skill_dir} for clean start.")
        
    if skill_dir and not args.dry_run:
        os.makedirs(skill_dir, exist_ok=True)

    if not os.path.isdir(args.dataset):
        print(f"Dataset directory not found: {args.dataset}")
        return

    if args.use_existing_skill_dir and args.existing_skill_dir != "" and "all" in args.target_task:
        if os.path.isdir(args.existing_skill_dir):
            existing_skills = [d for d in os.listdir(args.existing_skill_dir) if os.path.isdir(os.path.join(args.existing_skill_dir, d))]
            matched_tasks = []
            for task_name in os.listdir(args.dataset):
                task_dir = os.path.join(args.dataset, task_name)
                if not os.path.isdir(task_dir):
                    continue
                skill_query_path = os.path.join(task_dir, "skill_query.json")
                if not os.path.isfile(skill_query_path):
                    continue
                try:
                    with open(skill_query_path, "r", encoding="utf-8") as f:
                        skill_data = json.load(f)
                        skill_name = skill_data.get("skill_name", "")
                        if skill_name in existing_skills:
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
        if not os.path.isdir(task_dir):
            continue
        
        skill_query_path = os.path.join(task_dir, "skill_query.json")
        if not os.path.isfile(skill_query_path):
            continue
            
        with open(skill_query_path, "r", encoding="utf-8") as f:
            try:
                skill_data = json.load(f)
            except json.JSONDecodeError:
                continue
        
        if args.no_composition_skills:
            skill_data['skill_name'] = "no_composition_skills"
        skill_name = skill_data.get("skill_name", "")
        for sub_dir_name in sorted(os.listdir(task_dir))[0:args.test_sample]:
            sub_dir_path = os.path.join(task_dir, sub_dir_name)
            if not os.path.isdir(sub_dir_path):
                continue
            session_name = f"{task_name}_{sub_dir_name}_{skill_name}"
            
            # Since pipeline runs eval immediately after gen, we check if gen is done AND eval is done.
            # But to keep it simple, if gen is done but eval is not, we shouldn't re-run gen.
            # We'll just append it to tasks, and inside the task we can skip gen if it's done.
            # Let's check gen status here. We only check if it has reached the final destination.
            gen_done = check_gen_done(None, session_name, search_dirs=[args.new_generate_materials_path])
            eval_done = check_eval_done(None, f"eval_{session_name}", gen_session_name=session_name, search_dirs=[args.new_generate_materials_path])

            if gen_done and eval_done and not args.overwrite:
                tqdm.write(f"Session {session_name} and its eval already done. Skipping.")
                gen_dir = find_session_dir(session_name, search_dirs=[args.new_generate_materials_path])
                rubric_path = os.path.join(args.dataset, task_name, os.path.basename(sub_dir_path), "rubric_deterministic.json")
                ensure_execution_error_eval(
                    gen_dir,
                    load_execution_error_rubric_template(rubric_path),
                )
                continue
            else:
                gen_done_in_output_dir = check_gen_done(None, session_name)
                if not gen_done_in_output_dir:
                    move_to_failed_output(session_name)

                eval_done_in_output_dir = check_eval_done(None, f"eval_{session_name}")
                if not eval_done_in_output_dir:
                    move_to_failed_output(f"eval_{session_name}")
                
                all_tasks_to_run.append({
                    "task_name": task_name,
                    "task_dir": task_dir,
                    "sub_dir_path": sub_dir_path,
                    "session_name": session_name,
                    "skill_data": skill_data
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
        prefix = skill_creator_prefix.format(skill_name=skill_name)
        skill_query = skill_data.get("skill_query", "")
        if args.add_task_cases_in_creating_skills:
            # 增加一些task cases, 让skills创建时可以参考的东西会更多。
            # 在task_info['task_dir']下面的子文件夹中随机选取2个作为task cases
            sub_dirs = [os.path.join(task_info['task_dir'], d) for d in os.listdir(task_info['task_dir']) if os.path.isdir(os.path.join(task_info['task_dir'], d))]
            sub_dir_full_paths = random.sample(sub_dirs, min(2, len(sub_dirs)))
            skill_query = append_task_cases_prompt(skill_query, sub_dir_full_paths)
        
        if skill_name not in skills_to_create and skill_name not in processed_skills:
            skill_path = os.path.join(skill_dir, skill_name)
            if os.path.isdir(skill_path):
                tqdm.write(f"Skill {skill_name} already exists. Skipping create_skill.")
                processed_skills.add(skill_name)
                create_skill_session_name = f"create_{skill_name}"
            elif args.use_existing_skill_dir and args.existing_skill_dir:
                print(
                    f"Error: Required skill '{skill_name}' for task '{task_name}' is missing from "
                    f"existing skill directory {args.existing_skill_dir}. "
                    "--use_existing_skill_dir does not create new skills."
                )
                return None
            else:
                final_query = prefix + skill_query
                skills_to_create[skill_name] = {
                    "task_name": task_name,
                    "final_query": final_query
                }

    if args.create_skill_only:
        pbar = tqdm(total=len(skills_to_create), desc="Creating skills")
    else:
        pbar = tqdm(total=len(skills_to_create) + total_to_run, desc="Pipeline Progress")

    if args.dry_run:
        print("\n" + "="*50)
        print("DRY RUN SUMMARY")
        print("="*50)
        
        # Natural Language Summary of parameters
        print(f"Experiment ID: {args.exp_id}")
        print(f"Time Prefix: {args.time_prefix}")
        if args.no_composition_skills:
            print("Skill Strategy: Running BASELINE (no composition skills).")
        else:
            strategy = f"Skill Strategy: Using {args.skill_type.upper()} skills. "
            if args.use_existing_skill_dir:
                strategy += f"Reusing existing skills from '{args.existing_skill_dir}'. "
            else:
                strategy += "Will create new skills. "
                
            if args.use_existing_skill_creator:
                strategy += f"Using existing skill creator from '{args.existing_skill_creator_dir}'."
            else:
                strategy += "Using default skill creator."
            print(strategy)
            
        print("-" * 50)
        print(f"Skills to create: {len(skills_to_create)}")
        for skill_name, info in skills_to_create.items():
            print(f"  - {skill_name} (Task: {info['task_name']})")
        print(f"Tasks to run: {total_to_run}")
        for task_info in all_tasks_to_run:
            print(f"  - {task_info['session_name']}")
        print("="*50 + "\n")
        return

    
    if skills_to_create:
        tqdm.write(f"Creating {len(skills_to_create)} skills concurrently...")
        
        active_create_tasks = set()
        
        def skill_done_callback(t):
            try:
                res_skill_name, result = t.result()
                create_session_name = f"create_{res_skill_name}"
                create_agent_id = result.get("agent_id")
                if not result["success"]:
                    tqdm.write(f"Failed to create skill {res_skill_name}. Error: {result.get('error', 'Unknown')}")
                    failed_to_create_skills.add(res_skill_name)
                    # Move to failed directory
                    failed_dir = find_session_dir(create_session_name, agent_id=create_agent_id, search_dirs=[FAILED_DIR, OUTPUT_DIR])
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
                    # 立刻复制到 archive，Ctrl+C 后已完成的 skill 不丢失
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
                    # Move session artifacts to generate_materials
                    success_dir = find_session_dir(create_session_name, agent_id=create_agent_id, search_dirs=[OUTPUT_DIR])
                    if success_dir and os.path.exists(success_dir):
                        final_dst = os.path.join(args.new_generate_materials_path, os.path.basename(success_dir))
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
                done, active_create_tasks = await asyncio.wait(active_create_tasks, return_when=asyncio.FIRST_COMPLETED)

            chosen_agent_id = random.choice(available_agents)
            task = asyncio.create_task(create_skill_task(
                chosen_agent_id, skill_name, info['final_query'],
                args.thinking, args.timeout_seconds, RUNNING_DIR, args.max_retries, args.retry_delay
            ))
            task.add_done_callback(skill_done_callback)
            active_create_tasks.add(task)
            
        if active_create_tasks:
            await asyncio.wait(active_create_tasks)

    if args.create_skill_only:
        pbar.close()
        cleanup_skill_dir(skill_dir, processed_skills)
        restore_replaced_skill_creator(args)
        print("Skill creation phase completed. Exiting as --create_skill_only is set.")
        return None

    # Pipeline logic using semaphore
    semaphore = asyncio.Semaphore(args.max_concurrency)
    async def sem_pipeline_task(task_info):
        async with semaphore:
            skill_name = task_info["skill_data"].get("skill_name", "")
            if skill_name in failed_to_create_skills:
                failed_gen_sessions.add(task_info["session_name"])
                pbar.update(1)
                return
            chosen_agent_id = random.choice(available_agents)
            await run_case_pipeline(
                chosen_agent_id, task_info["session_name"], task_info["task_name"], 
                os.path.basename(task_info["sub_dir_path"]), task_info["sub_dir_path"], args, pbar
            )

    tasks = []
    for task_info in all_tasks_to_run:
        tasks.append(asyncio.create_task(sem_pipeline_task(task_info)))
        # prevent large throughput in a short time
        await asyncio.sleep(5)

    if tasks:
        await asyncio.wait(tasks)

    pbar.close()

    
    print("\n--- Pipeline Summary ---")
    print(f"Total tasks processed(skills creating task not included): {total_to_run}")
    print(f"Skills created: {len(processed_skills)} (Failed: {len(failed_to_create_skills)})")
    print(f"Done Generation: {len(done_gen_sessions)}")
    print(f"Failed Generation: {len(failed_gen_sessions)}")
    print(f"Done Eval: {len(done_eval_sessions)}")
    print(f"Failed Eval: {len(failed_eval_sessions)}")

    print_success_rate_summary(args.task_max_retries, search_dirs=args.search_dirs + [FAILED_DIR, args.new_failed_path], save_dir=args.new_generate_materials_path)
    generate_eval_summary(args, done_eval_sessions, failed_eval_sessions, args.new_generate_materials_path)
    generate_basic_results_summary(args.new_generate_materials_path)
    
    if len(skills_to_create) == 0 and total_to_run == 0:
        print("No skills created and no tasks to run. Skipping directory renaming.")
        return None

    archive_pipeline_dirs(exp_dir, args.time_prefix, args.skill_type,
                           FAILED_DIR, args.new_failed_path,
                           HALF_STOPPED_DIR, args.new_half_stopped_path,
                           RUNNING_DIR)

    print(f"All tasks have been completed. Outputs moved to {exp_dir}.")

    cleanup_skill_dir(skill_dir, processed_skills)

    restore_replaced_skill_creator(args)

def cleanup(args):
    from AutomaticSkillOptimization.inference_OpenClaw import running_utils
    running_utils.cleanup(args, running_sessions)

if __name__ == "__main__":
    args = parse_arguments()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        cleanup(args)
    finally:
        restore_replaced_skill_creator(args)
