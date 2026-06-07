import argparse
import asyncio
import os
import random
import shutil
import sys

from tqdm import tqdm

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from AutomaticSkillOptimization.prompts import build_eval_prompt
from AutomaticSkillOptimization.args import OUTPUT_DIR, RUNNING_DIR, setup_openclaw_workspace
from AutomaticSkillOptimization.utils import (
    Logger,
    find_final_video_paths,
    find_session_dir,
    move_to_half_stopped_output,
    move_to_failed_output,
    parse_result_dir_name,
)
from AutomaticSkillOptimization.evaluation_PRM.generate_summary import generate_eval_summary
from AutomaticSkillOptimization.inference_OpenClaw.openclaw_sdk_tools import delete_session, get_available_agent_ids
from AutomaticSkillOptimization.inference_OpenClaw.pipeline import (
    process_and_run_eval_task,
)
from AutomaticSkillOptimization.evaluation_PRM.evaluation_utils import (
    check_eval_done,
    copy_human_rubrics,
    ensure_execution_error_eval,
    load_and_prepare_rubric,
    load_execution_error_rubric_template,
)

SKIPPED_LLM_RUBRIC_IDS = {"fixed_P2", "fixed_P5"}
RUNNING_DIR_PM_FR = f"{RUNNING_DIR}_evaluate_PM+FR"
running_eval_sessions = set()


def parse_args():
    parser = argparse.ArgumentParser(description="Run eval only for existing generation results.")
    parser.add_argument("--agent_id", type=str, default="main")
    parser.add_argument("--dataset", type=str, default="dataset")
    parser.add_argument(
        "--result_dir",
        type=str,
        default="CC_Seed_basic_skill_creator",
        help="Existing result directory with generated cases to evaluate.",
    )
    parser.add_argument("--target_task", type=str, nargs="+", default=["all"])
    parser.add_argument("--max_concurrency", type=int, default=20)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--timeout_seconds", type=int, default=10800)
    parser.add_argument("--max_retries", type=int, default=6)
    parser.add_argument("--eval_max_retries", type=int, default=9)
    parser.add_argument("--retry_delay", type=int, default=10)
    parser.add_argument("--limit", type=int, default=10, help="最多评估的有效 case 数; 默认 10,设为 0 表示不限制")
    parser.add_argument("--overwrite", type=lambda x: str(x).lower() in ["true", "1", "yes"], default=False)
    parser.add_argument("--dry_run", type=lambda x: str(x).lower() in ["true", "1", "yes"], default=False)
    parser.add_argument("--random_seed", type=int, default=42)
    return parser.parse_args()


def dataset_categories(dataset_dir):
    return sorted(
        [
            item
            for item in os.listdir(dataset_dir)
            if os.path.isdir(os.path.join(dataset_dir, item))
        ],
        key=len,
        reverse=True,
    )


def build_existing_result_eval_prompt(rubric_content, item_path):
    react_file = os.path.join(item_path, "ReAct_process.json")
    final_video_paths = find_final_video_paths(item_path)
    return build_eval_prompt(rubric_content, react_file, item_path, final_video_paths=final_video_paths)


def collect_tasks(args, mutate=False):
    categories = dataset_categories(args.dataset)
    tasks = []
    skipped = 0
    for case_name in sorted(os.listdir(args.result_dir)):
        item_path = os.path.join(args.result_dir, case_name)
        if not os.path.isdir(item_path):
            continue
        category, case_id, session_name = parse_result_dir_name(case_name, categories)
        if session_name.startswith("eval_"):
            skipped += 1
            continue
        if not category or not case_id:
            skipped += 1
            continue
        if "all" not in args.target_task and category not in args.target_task:
            continue
        if not args.overwrite and check_eval_done(
            None,
            f"eval_{session_name}",
            gen_session_name=session_name,
            search_dirs=[args.result_dir],
        ):
            if mutate:
                ensure_execution_error_eval(
                    item_path,
                    load_execution_error_rubric_template(
                        os.path.join(args.dataset, category, case_id, "rubric_deterministic.json")
                    ),
                )
            continue
        react_file = os.path.join(item_path, "ReAct_process.json")
        if not os.path.isfile(react_file):
            print(f"⚠️ ReAct_process.json not found: {item_path}")
            continue
        if not find_final_video_paths(item_path):
            print(f"⚠️ final video not found, skip: {item_path}")
            continue
        rubric_path = os.path.join(args.dataset, category, case_id, "rubric_deterministic.json")
        rubric_content, execution_error_template = load_and_prepare_rubric(rubric_path, skip_rubric_ids=SKIPPED_LLM_RUBRIC_IDS)
        if rubric_content is None:
            print(f"⚠️ rubric file not found: {rubric_path}")
            continue
        if mutate:
            copy_human_rubrics(args.dataset, category, case_id, item_path)
        tasks.append(
            {
                "category": category,
                "case_id": case_id,
                "session_name": session_name,
                "eval_session_name": f"eval_{session_name}",
                "item_path": item_path,
                "prompt": build_existing_result_eval_prompt(rubric_content, item_path),
                "execution_error_template": execution_error_template,
            }
        )
    if args.limit and args.limit > 0:
        tasks = tasks[:args.limit]
    return tasks, skipped


async def main(args):
    random.seed(args.random_seed)
    args.dataset = os.path.abspath(os.path.expanduser(args.dataset))
    args.result_dir = os.path.abspath(os.path.expanduser(args.result_dir))

    for label, path in [
        ("Dataset directory", args.dataset),
        ("Result directory", args.result_dir),
    ]:
        if not os.path.isdir(path):
            raise FileNotFoundError(f"{label} not found: {path}")

    os.makedirs(RUNNING_DIR_PM_FR, exist_ok=True)
    logger = Logger(os.path.join(RUNNING_DIR_PM_FR, "000_eval_existing_results.log"))
    sys.stdout = logger
    sys.stderr = logger

    tasks, skipped = collect_tasks(args, mutate=not args.dry_run)
    print(f"Collected {len(tasks)} eval tasks from {args.result_dir}; skipped {skipped} non-case dirs.")
    if args.dry_run:
        for task in tasks[:50]:
            print(f"  - {task['eval_session_name']} -> {task['item_path']}")
        if len(tasks) > 50:
            print(f"  ... {len(tasks) - 50} more")
        return
    if not tasks:
        print("No eval tasks to run.")
        generate_eval_summary(args, set(), set(), args.result_dir)
        return

    setup_openclaw_workspace()

    available_agents = await get_available_agent_ids(args.agent_id)
    print(f"Available agents for eval: {available_agents}")
    if not available_agents:
        raise RuntimeError(f"No available OpenClaw agents found for agent_id={args.agent_id}")
    if args.max_concurrency <= 0:
        raise ValueError(f"--max_concurrency must be positive, got {args.max_concurrency}")

    done = set()
    failed = set()
    semaphore = asyncio.Semaphore(args.max_concurrency)
    pbar = tqdm(total=len(tasks), desc="Eval existing results")

    async def run_one(task):
        async with semaphore:
            agent_id = random.choice(available_agents)
            eval_session_name = task["eval_session_name"]
            try:
                if not args.overwrite and check_eval_done(
                    None,
                    eval_session_name,
                    gen_session_name=task["session_name"],
                    search_dirs=[args.result_dir],
                ):
                    ensure_execution_error_eval(task["item_path"], task["execution_error_template"])
                    done.add(eval_session_name)
                    return

                running_eval_sessions.add((agent_id, eval_session_name))
                success = await process_and_run_eval_task(
                    agent_id,
                    eval_session_name,
                    task["prompt"],
                    args.thinking,
                    args.timeout_seconds,
                    RUNNING_DIR_PM_FR,
                    args.max_retries,
                    args.eval_max_retries,
                    args.retry_delay,
                )
                if success:
                    eval_dir = find_session_dir(eval_session_name, agent_id=agent_id, search_dirs=[OUTPUT_DIR])
                    if eval_dir:
                        dst = os.path.join(task["item_path"], "evals")
                        if os.path.exists(dst):
                            shutil.rmtree(dst)
                        shutil.move(eval_dir, dst)
                        ensure_execution_error_eval(task["item_path"], task["execution_error_template"])
                        done.add(eval_session_name)
                    else:
                        print(f"⚠️ eval output dir not found after success: {eval_session_name}")
                        failed.add(eval_session_name)
                else:
                    move_to_failed_output(eval_session_name, agent_id=agent_id)
                    failed.add(eval_session_name)
            except asyncio.CancelledError:
                print(f"[{eval_session_name}] Cancelled. Moving unfinished eval output to half_stopped.")
                move_to_half_stopped_output(eval_session_name, agent_id=agent_id)
                raise
            except Exception as e:
                print(f"⚠️ eval task failed with exception: {eval_session_name}: {e}")
                move_to_failed_output(eval_session_name, agent_id=agent_id)
                failed.add(eval_session_name)
            finally:
                running_eval_sessions.discard((agent_id, eval_session_name))
                for a_id in available_agents:
                    try:
                        await delete_session(a_id, eval_session_name)
                    except Exception as e:
                        print(f"⚠️ failed to delete OpenClaw session {eval_session_name} on {a_id}: {e}")
                pbar.update(1)
                await asyncio.sleep(1)

    try:
        await asyncio.gather(*(run_one(task) for task in tasks))
    finally:
        pbar.close()
    print("\n--- Eval Existing Results Summary ---")
    print(f"Done: {len(done)}")
    print(f"Failed: {len(failed)}")
    if failed:
        print("Failed sessions:")
        for session_name in sorted(failed):
            print(f"  - {session_name}")

    print("\n--- Generating Eval Summary ---")
    generate_eval_summary(args, done, failed, args.result_dir)


if __name__ == "__main__":
    # evaluate existing Process Metrics and Format Requirements with OpenClaw + Seed2.0
    main_args = parse_args()
    try:
        asyncio.run(main(main_args))
    except KeyboardInterrupt:
        print("\nCaught KeyboardInterrupt. Moving unfinished eval outputs to half_stopped...")
        for agent_id, eval_session_name in list(running_eval_sessions):
            move_to_half_stopped_output(eval_session_name, agent_id=agent_id)
        raise
