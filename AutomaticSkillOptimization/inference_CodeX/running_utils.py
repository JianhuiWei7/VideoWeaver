import asyncio
import os
from AutomaticSkillOptimization.inference_CodeX.codex_cli_tool import codex_chat
from AutomaticSkillOptimization.utils import move_to_failed_output

running_sessions = set()
done_sessions = set()
failed_sessions = set()
done_gen_sessions = set()
failed_gen_sessions = set()


async def run_single_task(session_name, message, cwd, *,
                          timeout_seconds=10800, log_file=None,
                          overwrite_log=False, max_retries=3, retry_delay=60):
    """异步跑一个 Codex session。"""
    retry_errors = [
        "API rate limit reached",
        "TPM (Tokens Per Minute) limit",
        "rate_limit_error",
        "overloaded_error",
        "Agent returned empty content",
        "Timed out connecting to",
        "Timed out waiting for",
    ]

    for attempt in range(max_retries):
        try:
            result = await codex_chat(
                session_name, message,
                cwd,
                timeout_seconds=timeout_seconds,
                max_retries=1,
                retry_delay=0,
                log_file=log_file,
                overwrite_log=(overwrite_log and attempt == 0),
            )

            err = result.get("error") or ""
            if any(e in str(err) for e in retry_errors):
                if attempt < max_retries - 1:
                    print(f"[{session_name}] Retry-able error: {err}. "
                          f"Retrying {attempt+1}/{max_retries}...")
                    await asyncio.sleep(retry_delay)
                    continue

            return {
                "success": result.get("success", False),
                "session_id": result.get("session_id"),
                "content": result.get("content", ""),
                "stderr": result.get("stderr", ""),
                "error": result.get("error"),
            }
        except Exception as e:
            err = str(e)
            if any(e in err for e in retry_errors):
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
            return {"success": False, "session_id": None, "error": err}

    return {"success": False, "session_id": None, "error": "Max retries exceeded"}


async def create_skill_task(skill_name, final_query, cwd, timeout_seconds, logs_dir, max_retries, retry_delay):
    """用 skill-creator 创建一个 skill。"""
    create_skill_session_name = f"create_{skill_name}"
    log_file = os.path.join(logs_dir, f"create_{skill_name}.log")
    running_sessions.add(create_skill_session_name)
    result = None
    try:
        result = await run_single_task(create_skill_session_name, final_query, cwd, timeout_seconds=timeout_seconds, log_file=log_file, overwrite_log=True, max_retries=max_retries, retry_delay=retry_delay)
        if result.get("success", False):
            running_sessions.discard(create_skill_session_name)
            done_sessions.add(create_skill_session_name)
        else:
            move_to_failed_output(create_skill_session_name, session_id=result.get("session_id"))
            running_sessions.discard(create_skill_session_name)
            failed_sessions.add(create_skill_session_name)
        return skill_name, result
    except asyncio.CancelledError:
        print(f"[{create_skill_session_name}] Cancelled (Ctrl+C). Marking as half_stopped...")
        raise
    except Exception as e:
        move_to_failed_output(create_skill_session_name, session_id=result.get("session_id") if result else None)
        running_sessions.discard(create_skill_session_name)
        failed_sessions.add(create_skill_session_name)
        return skill_name, {"success": False, "error": str(e)}
