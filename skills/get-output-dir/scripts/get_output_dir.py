import argparse
import asyncio
import os
import sys


def safe_segment(value):
    text = str(value or "thread").replace(os.sep, "_").replace("\0", "_").strip()
    return text or "thread"


def resolve_output_root():
    output_root = os.path.expanduser(os.environ.get("OUTPUT_DIR", ""))
    if not os.path.isabs(output_root):
        output_root = os.path.abspath(output_root)
    return output_root


def append_subdir(output_dir, subdir):
    if subdir:
        output_dir = os.path.join(output_dir, safe_segment(subdir))
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def get_session_id(agent_id, session_name, max_retries=3, verbose=True):
    async def _get():
        try:
            from openclaw_sdk import OpenClawClient
        except ImportError as exc:
            print(f"Error importing OpenClaw SDK: {exc}", file=sys.stderr)
            return None

        target_key = f"agent:{agent_id}:{session_name}"
        for attempt in range(max_retries):
            try:
                async with await OpenClawClient.connect() as client:
                    sessions_list = await client.gateway.sessions_list()

                    for sess in sessions_list:
                        if sess.get("key", "").lower() == target_key.lower():
                            session_id = sess.get("sessionId")
                            if verbose:
                                print(f">>> Found Session ID for {target_key}: {session_id}")
                            return session_id

                    print(f">>> Warning: No active session found for key {target_key} via SDK.")
                    return None
            except Exception as exc:
                print(f">>> Failed to fetch session ID via SDK: {exc}")

            if attempt < max_retries - 1:
                print(f">>> Retrying get_session_id ({attempt + 1}/{max_retries})...")
                await asyncio.sleep(2)

        print(f">>> Error: Exhausted all {max_retries} retries for get_session_id.")
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import threading

        result = []

        def run_in_thread():
            result.append(asyncio.run(_get()))

        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()
        return result[0] if result else None

    return asyncio.run(_get())


def get_openclaw_output_dir(session_key=None, subdir=None):
    if not session_key:
        print(
            "Error: OpenClaw 环境必须运行 session_status 获取session-key并且传入, "
            "格式通常为 agent:{agent_id}:{session_id}.",
            file=sys.stderr,
        )
        return None

    parts = session_key.split(":")
    if len(parts) < 3:
        print(
            f"Error: invalid session_key '{session_key}'. Expected 'agent:<agent_id>:<session_id>'.",
            file=sys.stderr,
        )
        return None

    agent_id = parts[1]
    session_name = parts[2]
    session_id = get_session_id(agent_id, session_name, verbose=False)
    if not session_id:
        print(f"Error: could not retrieve session id for '{session_key}'.", file=sys.stderr)
        return None

    output_dir = os.path.join(
        resolve_output_root(),
        f"{session_key}_{session_id}",
    )
    return append_subdir(output_dir, subdir)


def get_codex_output_dir(subdir=None):
    thread_name = os.environ.get("CODEX_THREAD_NAME") or "unknown_thread_name"
    thread_id = os.environ.get("CODEX_THREAD_ID") or "unknown_thread_id"

    output_dir = os.path.join(
        resolve_output_root(),
        f"{safe_segment(thread_name)}_{safe_segment(thread_id)}",
    )
    return append_subdir(output_dir, subdir)


def get_claude_output_dir(subdir=None):
    resolved_name = os.environ.get("CLAUDE_CODE_SESSION_NAME_USER") or "unknown_session_name"
    resolved_id = os.environ.get("CLAUDE_CODE_SESSION_ID") or "unknown_session_id"
    output_dir = os.path.join(
        resolve_output_root(),
        f"{safe_segment(resolved_name)}_{safe_segment(resolved_id)}",
    )
    return append_subdir(output_dir, subdir)


def infer_mode(args):
    if args.session_key:
        return "openclaw"
    if os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude"
    return "openclaw"


def validate_session_key(args):
    if args.session_key and os.environ.get("CODEX_THREAD_ID"):
        print(
            "Error: CODEX_THREAD_ID is set, so --session-key must be empty. "
            "CodeX/Claude Code 环境会自动识别，不需要传入session-key。",
            file=sys.stderr,
        )
        return False
    if args.session_key and os.environ.get("CLAUDE_CODE_SESSION_ID"):
        print(
            "Error: CLAUDE_CODE_SESSION_ID is set, so --session-key must be empty. "
            "CodeX/Claude Code 环境会自动识别，不需要传入session-key。",
            file=sys.stderr,
        )
        return False
    if (
        not args.session_key
        and not os.environ.get("CODEX_THREAD_ID")
        and not os.environ.get("CLAUDE_CODE_SESSION_ID")
    ):
        print(
            "Error: 自动识别到是 OpenClaw 环境，但是没有传入 session-key。"
            "OpenClaw 环境必须运行 session_status 获取session-key并且传入, "
            "格式通常为 agent:{agent_id}:{session_id}.",
            file=sys.stderr,
        )
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Get the standard output directory for the current agent session.")
    parser.add_argument("--session-key", help="OpenClaw session-key，格式通常为 agent:{agent_id}:{session_id}。")
    parser.add_argument("--subdir", help="Optional subdirectory to append, e.g. images or videos.")
    args = parser.parse_args()

    if not validate_session_key(args):
        sys.exit(1)

    mode = infer_mode(args)
    if mode == "openclaw":
        output_dir = get_openclaw_output_dir(args.session_key, args.subdir)
    elif mode == "codex":
        output_dir = get_codex_output_dir(args.subdir)
    elif mode == "claude":
        output_dir = get_claude_output_dir(args.subdir)
    else:
        print(f"Error: unsupported mode '{mode}'.", file=sys.stderr)
        sys.exit(1)

    if output_dir:
        print(output_dir)
    else:
        sys.exit(1)
if __name__ == "__main__":
    main()
