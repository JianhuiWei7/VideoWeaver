import asyncio
import json
import os
import signal
from datetime import datetime

from AutomaticSkillOptimization.inference_OpenClaw.openclaw_sdk_tools import delete_session, open_claw_chat
from AutomaticSkillOptimization.args import OUTPUT_DIR, RUNNING_DIR
from AutomaticSkillOptimization.utils import (
    find_final_video_paths,
    find_session_dir,
    move_to_failed_output,
    move_to_half_stopped_output,
    restore_skill_creator_backup,
)

running_sessions = set()
done_sessions = set()
failed_sessions = set()
done_gen_sessions = set()
failed_gen_sessions = set()
done_eval_sessions = set()
failed_eval_sessions = set()


async def run_single_task(agent_id, session_name, message, thinking=True, timeout_seconds=10800, log_file=None, overwrite_log=False, max_retries=6, retry_delay=60):
    retry_errors = [
        "API rate limit reached",
        "TPM (Tokens Per Minute) limit of the model",
        "Agent returned empty content",
        "Timed out connecting to",
        "Timed out waiting for connect handshake with gateway",
    ]
    for attempt in range(max_retries):
        try:
            response_data = await open_claw_chat(
                agent_id, session_name, message,
                thinking_enabled=thinking,
                timeout_seconds=timeout_seconds,
                log_file=log_file,
                overwrite_log=overwrite_log if attempt == 0 else False,
            )
            success = response_data["error"] is None
            error_msg = response_data["error"] or ""
            if any(err in error_msg for err in retry_errors):
                if attempt < max_retries - 1:
                    print(f"[{session_name}] with error: {error_msg}. Retrying {attempt + 1}/{max_retries} after {retry_delay} seconds...")
                    if "Timed out" not in error_msg:
                        message = "继续"
                    await asyncio.sleep(retry_delay)
                    continue
            return {
                "success": success,
                "stdout": response_data["content"],
                "stderr": error_msg,
                "response_data": response_data,
            }
        except Exception as e:
            error_msg = str(e)
            if any(err in error_msg for err in retry_errors):
                if attempt < max_retries - 1:
                    print(f"[{session_name}] with error: {error_msg}. Retrying {attempt + 1}/{max_retries} after {retry_delay} seconds...")
                    if "Timed out" not in error_msg:
                        message = "继续"
                    await asyncio.sleep(retry_delay)
                    continue
            return {"success": False, "error": error_msg}



async def create_skill_task(agent_id, skill_name, final_query, thinking, timeout_seconds, logs_dir, max_retries, retry_delay):
    create_skill_session_name = f"create_{skill_name}"
    log_file = os.path.join(logs_dir, f"create_{skill_name}.log")
    running_sessions.add((agent_id, create_skill_session_name))
    try:
        result = await run_single_task(agent_id, create_skill_session_name, final_query, thinking, timeout_seconds, log_file, overwrite_log=True, max_retries=max_retries, retry_delay=retry_delay)
        result["agent_id"] = agent_id
        if result.get("success", False):
            running_sessions.discard((agent_id, create_skill_session_name))
            done_sessions.add(create_skill_session_name)
        else:
            move_to_failed_output(create_skill_session_name, agent_id=agent_id)
            running_sessions.discard((agent_id, create_skill_session_name))
            failed_sessions.add(create_skill_session_name)
        await delete_session(agent_id, create_skill_session_name)
        return skill_name, result
    except asyncio.CancelledError:
        print(f"[{create_skill_session_name}] Cancelled (Ctrl+C). Marking as half_stopped...")
        raise
    except Exception as e:
        move_to_failed_output(create_skill_session_name, agent_id=agent_id)
        running_sessions.discard((agent_id, create_skill_session_name))
        failed_sessions.add(create_skill_session_name)
        await delete_session(agent_id, create_skill_session_name)
        return skill_name, {"success": False, "error": str(e), "agent_id": agent_id}


def check_gen_done(agent_id, session_name, search_dirs=None):
    if search_dirs is None:
        search_dirs = [OUTPUT_DIR]

    session_path = find_session_dir(session_name, agent_id=agent_id, search_dirs=search_dirs)
    if session_path and os.path.isdir(session_path):
        react_file = os.path.join(session_path, "ReAct_process.json")
        if os.path.isfile(react_file):
            with open(react_file, "r") as f:
                try:
                    data = json.load(f)
                    if len(data) > 3 and find_final_video_paths(session_path):
                        return True
                except json.JSONDecodeError:
                    pass
    return False


def cleanup(args, target_running_sessions=None):
    if target_running_sessions is None:
        target_running_sessions = running_sessions

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    print("\nCaught KeyboardInterrupt, sending /stop to all running tasks...")
    if not target_running_sessions:
        print("No running sessions to stop.")
    else:
        async def stop_all_sessions():
            stop_tasks = []
            os.makedirs(RUNNING_DIR, exist_ok=True)

            for agent_id_run, session_name in target_running_sessions.copy():
                print(f"[{session_name}] Sending /stop to agent {agent_id_run}...")
                log_file = os.path.join(RUNNING_DIR, f"{session_name}.log")
                stop_tasks.append(run_single_task(agent_id_run, session_name, "/stop", thinking=False, timeout_seconds=60, log_file=log_file, overwrite_log=False, max_retries=1))

            if stop_tasks:
                await asyncio.gather(*stop_tasks, return_exceptions=True)
            print("All running sessions have been sent /stop commands.")

            if target_running_sessions:
                print(f"Deleting {len(target_running_sessions)} sessions...")
                delete_tasks = []
                for agent_id_run, session_name in target_running_sessions:
                    delete_tasks.append(delete_session(agent_id_run, session_name))
                await asyncio.gather(*delete_tasks, return_exceptions=True)
                print("All running sessions have been deleted.")

            if target_running_sessions:
                print(f"Moving {len(target_running_sessions)} unfinished session folders to half_stopped...")
                for agent_id_run, session_name in target_running_sessions:
                    move_to_half_stopped_output(session_name, agent_id=agent_id_run)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(stop_all_sessions())
        loop.close()

        if args.use_existing_skill_creator and args.existing_skill_creator_dir != "":
            if hasattr(args, '_original_creator_path') and hasattr(args, '_backup_creator_path'):
                restore_skill_creator_backup(args._original_creator_path, args._backup_creator_path)
                args._skill_creator_was_replaced = False
