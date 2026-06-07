"""
Claude Code CLI 工具 —— 替代 openclaw_sdk_tools.py。
用于在 Claude Code 环境下通过 subprocess 批量运行任务。
"""

import asyncio
import glob
import json
import os
import shutil
import signal
from datetime import datetime

from AutomaticSkillOptimization.args import CLAUDE_BIN, CLAUDE_WORKSPACE

active_processes = set()


def configure_claude_backend(backend):
    if backend == "deepseek":
        os.environ.setdefault("USE_DEEPSEEK", "1")
        if not os.environ.get("DEEPSEEK_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            print("WARN: DEEPSEEK_API_KEY/ANTHROPIC_AUTH_TOKEN is not set; DeepSeek calls may fail.")
    elif backend == "seed":
        os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:8082")
        os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", "dummy-token")
        os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-dummy")
    elif backend == "opus":
        if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            print("WARN: ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN is not set; Opus calls may fail.")


def claude_session_jsonl_path(session_id):
    """Return Claude Code's JSONL path for the fixed workspace."""
    project_hash = CLAUDE_WORKSPACE.replace("/", "-").replace(".", "-").replace("_", "-")
    fixed_path = os.path.expanduser(f"~/.claude/projects/{project_hash}/{session_id}.jsonl")
    if os.path.isfile(fixed_path):
        return fixed_path

    matches = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    if matches:
        return max(matches, key=os.path.getmtime)
    return fixed_path

# DeepSeek V4 Pro 定价 (RMB / 百万 token)
BACKBONE_PRICING = {
    "input": 1.0,       # 缓存未命中输入
    "output": 6.0,
    "cacheRead": 0.02,  # 缓存命中输入
    "cacheWrite": 3.0,
    "unit": "RMB",
}

# 豆包视频/图片生成 cost
import sys as _sys
_cur = os.path.dirname(os.path.abspath(__file__))
if _cur not in _sys.path:
    _sys.path.insert(0, _cur)


# ========== JSONL → ReAct_process ==========

def _load_jsonl(session_id):
    path = claude_session_jsonl_path(session_id)
    if not os.path.exists(path):
        return []
    lines = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            try:
                lines.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return lines

# 生成react_process.json和把原始jsonl复制到输出目录，方便后续分析和溯源
def jsonl_to_react_process(session_id, output_dir):
    """从 Claude Code jsonl 提取结构化 ReAct_process.json，并复制原始 jsonl 到同目录。

    输出文件:
    - ReAct_process.json: 清洗后的结构化对话记录
    - ReAct_process.jsonl: 原始 jsonl 副本（便于完整溯源）
    """
    records = _load_jsonl(session_id)
    if not records:
        return None

    # 第一遍：建 tool_use_id → tool_name 映射（CC 里 tool_result 带的是 tool_use_id 而非 name）
    tool_id_to_name = {}
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        for blk in rec.get("message", {}).get("content", []) or []:
            if blk.get("type") == "tool_use":
                tid = blk.get("id") or blk.get("tool_use_id")
                if tid:
                    tool_id_to_name[tid] = blk.get("name", "")

    result = []
    seen_tool_use_ids = set()
    seen_tool_result_ids = set()
    for rec in records:
        typ = rec.get("type")
        if typ == "user":
            msg = rec.get("message", {})
            content = msg.get("content", "")
            # CC 把 tool_result 放在 user-role 的 content list 里。展开为独立条目，每个挂上对应 tool_name
            if isinstance(content, list):
                texts = []
                tool_results = []
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "text":
                        texts.append(b.get("text", ""))
                    elif bt == "tool_result":
                        tid = b.get("tool_use_id", "")
                        if tid:
                            if tid in seen_tool_result_ids:
                                continue
                            seen_tool_result_ids.add(tid)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_name": tool_id_to_name.get(tid, ""),
                            "tool_use_id": tid,
                            "content": _summarize_tool_result(b),
                        })
                if texts:
                    text_joined = "\n".join(texts)
                    if text_joined.strip():
                        result.append({"role": "user", "content": text_joined})
                if tool_results:
                    # tool_result 归到 assistant 上下文里（和原 openclaw 结构对齐）
                    result.append({"role": "assistant", "content": tool_results})
                continue
            if not content or not isinstance(content, str):
                content = "(non-text user message)"
            result.append({"role": "user", "content": content})

        elif typ == "assistant":
            msg = rec.get("message", {})
            blocks = msg.get("content", [])
            entry = {"role": "assistant", "content": []}
            for blk in blocks:
                bt = blk.get("type")
                if bt == "thinking":
                    entry["content"].append({
                        "type": "thinking",
                        "content": blk.get("thinking", ""),
                    })
                elif bt == "tool_use":
                    tid = blk.get("id", "") or blk.get("tool_use_id", "")
                    if tid:
                        if tid in seen_tool_use_ids:
                            continue
                        seen_tool_use_ids.add(tid)
                    entry["content"].append({
                        "type": "tool_call",
                        "name": blk.get("name", ""),
                        "tool_use_id": tid,
                        "arguments": json.dumps(blk.get("input", {}), ensure_ascii=False),
                    })
                elif bt == "text":
                    text = blk.get("text", "")
                    if not text:
                        continue
                    entry["content"].append({
                        "type": "final_return",
                        "content": text,
                    })
            if entry["content"]:
                result.append(entry)

    os.makedirs(output_dir, exist_ok=True)

    # 写结构化 JSON
    out_path = os.path.join(output_dir, "ReAct_process.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 复制原始 jsonl 到同目录（便于完整溯源）
    src_jsonl = claude_session_jsonl_path(session_id)
    if os.path.exists(src_jsonl):
        dst_jsonl = os.path.join(output_dir, "ReAct_process.jsonl")
        try:
            shutil.copy(src_jsonl, dst_jsonl)
        except Exception as e:
            print(f"Failed to copy {src_jsonl} to {dst_jsonl}: {e}")

    return out_path
#这里截断函数，但是这里没有截断
def _summarize_tool_result(blk):
    c = blk.get("content", "")
    if isinstance(c, list):
        c = json.dumps(c, ensure_ascii=False)
    if not isinstance(c, str):
        c = str(c)
    return c

#转换为人类可读的 ReAct_process_raw.txt（无截断的 raw dump，供 debug/grep）
#注意：与 dataset_utils.Step3_summarize_prcess.process_file 输出 ReAct_process.txt（LLM 总结版）
#共存，不要写到同一文件名，否则 summarizer 的 short-circuit 会被触发。
def react_to_text(output_dir):
    """从 ReAct_process.json 生成人类可读的 ReAct_process_raw.txt（无截断 raw dump）。"""
    rp = os.path.join(output_dir, "ReAct_process.json")
    if not os.path.exists(rp):
        return None
    with open(rp, encoding="utf-8") as f:
        data = json.load(f)

    lines = []
    step = 0
    for entry in data:
        if entry["role"] == "user":
            content = entry.get("content", "")
            if isinstance(content, str) and "<system-reminder>" in content:
                continue
            step += 1
            lines.append(f"[{step:02d}] 用户：{content}")
        elif entry["role"] == "assistant":
            for blk in entry.get("content", []):
                step += 1
                bt = blk.get("type")
                if bt == "thinking":
                    lines.append(f"[{step:02d}] 思考：{blk.get('content','')}")
                elif bt == "tool_call":
                    lines.append(
                        f"[{step:02d}] 调用工具 {blk.get('name','')}，"
                        f"参数：{blk.get('arguments','')}"
                    )
                elif bt == "tool_result":
                    name = blk.get("tool_name") or blk.get("tool_use_id", "")
                    lines.append(f"[{step:02d}] 工具结果 ({name})：{blk.get('content','')}")
                elif bt == "final_return":
                    lines.append(f"[{step:02d}] 最终回复：{blk.get('content','')}")

    out_path = os.path.join(output_dir, "ReAct_process_raw.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


# ========== Cost 统计 ==========

def calculate_cost_from_jsonl(session_id):
    """从 jsonl 累积 token 用量并计算 backbone cost。"""
    records = _load_jsonl(session_id)
    inp = out = cr = cw = 0
    tool_calls = 0
    seen_message_ids = set()
    seen_tool_use_ids = set()
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message", {})
        msg_id = msg.get("id")

        # Claude Code may emit the same message id twice: first as an empty text
        # block, then as the actual tool_use block. Deduplicate token usage by
        # message id, but count tool calls independently by tool_use id.
        if not msg_id or msg_id not in seen_message_ids:
            if msg_id:
                seen_message_ids.add(msg_id)
            usage = msg.get("usage", {})
            inp += usage.get("input_tokens", 0)
            out += usage.get("output_tokens", 0)
            cr += usage.get("cache_read_input_tokens", 0)
            cw += usage.get("cache_creation_input_tokens", 0)

        for blk in msg.get("content", []):
            if blk.get("type") == "tool_use":
                tool_use_id = blk.get("id") or blk.get("tool_use_id")
                if tool_use_id:
                    if tool_use_id in seen_tool_use_ids:
                        continue
                    seen_tool_use_ids.add(tool_use_id)
                tool_calls += 1

    total_tokens = inp + out + cr + cw
    return {
        "input_tokens": inp + cw, #
        "output_tokens": out,
        "cacheRead_tokens": cr,
        "cacheWrite_tokens": cw,
        "total_tokens": total_tokens,
        "cost": {
            "input": round(inp / 1_000_000 * BACKBONE_PRICING["input"], 6),
            "output": round(out / 1_000_000 * BACKBONE_PRICING["output"], 6),
            "cacheRead": round(cr / 1_000_000 * BACKBONE_PRICING["cacheRead"], 6),
            "cacheWrite": round(cw / 1_000_000 * BACKBONE_PRICING["cacheWrite"], 6),
            "total": round(
                inp / 1_000_000 * BACKBONE_PRICING["input"]
                + out / 1_000_000 * BACKBONE_PRICING["output"]
                + cr / 1_000_000 * BACKBONE_PRICING["cacheRead"]
                + cw / 1_000_000 * BACKBONE_PRICING["cacheWrite"],
                6,
            ),
            "unit": "RMB",
        },
        "cache_hit_rate": (cr / (inp + cw + cr)) if (inp + cw + cr) > 0 else 0,
        "tool_call_count": tool_calls,
    }


def calculate_tool_calls_from_react(output_dir):
    """从 ReAct_process.json 兜底统计唯一工具调用数。"""
    rp = os.path.join(output_dir, "ReAct_process.json") if output_dir else None
    if not rp or not os.path.isfile(rp):
        return 0

    try:
        with open(rp, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0

    count = 0
    seen = set()
    for entry in data:
        content = entry.get("content", [])
        if not isinstance(content, list):
            continue
        for blk in content:
            if not isinstance(blk, dict) or blk.get("type") != "tool_call":
                continue
            tid = blk.get("tool_use_id")
            if tid:
                if tid in seen:
                    continue
                seen.add(tid)
            count += 1
    return count

# ========== Claude Code CLI 调用 ==========
# 主要函数：claude_chat()，其他函数为辅助 session 管理和结果处理。

#这是重点函数，负责调用 Claude Code CLI，并处理重试逻辑、日志记录、结果解析等。
async def claude_chat(
    session_name, #这个是必传
    message, #这个必传
    session_id=None, # 这个传了也没用，不能传
    timeout_seconds=10800, #默认3小时，视频生成可能很慢
    max_retries=3, #默认重试3次，遇到网络错误或API限流等问题时会重试
    retry_delay=60, #默认重试间隔60秒，等待一段时间后再重试
    log_file=None,
    overwrite_log=False,
    reasoning="high",  # off / low / mid / high —— 通过在 message 前缀关键词触发 CC thinking 预算
    cwd=None,
):
    """异步运行 Claude Code CLI。

    使用 --output-format json 获取 CC 返回的 JSON，直接提取 session_id 和 result。

    reasoning:
        off  -> 不开启 extended thinking（默认）
        low  -> "think"        ~4k thinking tokens
        mid  -> "think hard"   ~10k thinking tokens
        high -> "ultrathink"   ~32k thinking tokens
    """
    _REASONING_PREFIX = {
        "off": "",
        "low": "think\n\n",
        "mid": "think hard\n\n",
        "high": "ultrathink\n\n",
    }
    if reasoning not in _REASONING_PREFIX:
        raise ValueError(f"Invalid reasoning={reasoning!r}, expected one of {list(_REASONING_PREFIX)}")
    message = _REASONING_PREFIX[reasoning] + message
    cwd = os.path.abspath(cwd or CLAUDE_WORKSPACE)

    RETRY_ERRORS = [
        "API rate limit reached",
        "TPM (Tokens Per Minute) limit",
        "rate_limit_error",
        "overloaded_error",
        "Timed out connecting to",
        "Timed out waiting for",
    ]

    def _log(msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # 打印日志时带上时间戳，方便排查问题
        line = f"[{ts}] [{session_name}] {msg}"  # 日志格式：[时间戳] [session_name] 消息内容
        print(line) # 同时输出到控制台
        if log_file:  # 如果指定了 log_file，则将日志写入文件。第一次写入时根据 overwrite_log 决定是覆盖还是追加，之后的写入都使用追加模式。
            mode = "a"  #
            with open(log_file, mode, encoding="utf-8") as lf: # 打开日志文件，写入日志内容
                lf.write(line + "\n")
    if overwrite_log and log_file:
        try:
            open(log_file, "w").close()
        except Exception:
            pass
    for attempt in range(max_retries):
        _log(f"Start (attempt {attempt + 1}/{max_retries}), session_name={session_name}") 

        # ---- backend 路由: 通过外部 env var 切换 Claude / DeepSeek ----
        # 触发条件: 父进程 export USE_DEEPSEEK=1 且提供了 DEEPSEEK_API_KEY/ANTHROPIC_AUTH_TOKEN
        # 其他场景默认走原生 Claude (claude-opus-4-7), 完全兼容旧行为
        deepseek_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        use_deepseek = os.getenv("USE_DEEPSEEK", "").lower() in ("1", "true", "yes") and deepseek_key
        extra_env = {}
        model_arg = os.getenv("CLAUDE_MODEL") or os.getenv("ANTHROPIC_MODEL") or "claude-opus-4-7"

        if use_deepseek:
            extra_env = {
                "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                "ANTHROPIC_AUTH_TOKEN": deepseek_key,
                "ANTHROPIC_API_KEY": "",  # 防止本地原有 ANTHROPIC_API_KEY 被沿用
                "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro[1m]",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro[1m]",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash",
                "CLAUDE_CODE_SUBAGENT_MODEL": "deepseek-v4-flash",
                "CLAUDE_CODE_EFFORT_LEVEL": "max",
            }
            model_arg = "deepseek-v4-pro[1m]"

        cmd = [
            CLAUDE_BIN, "-p", message,
            "--name", session_name,
            "--model", model_arg,
            "--output-format", "json",
            "--permission-mode", "bypassPermissions",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(  # 使用 asyncio 创建子进程执行 Claude Code CLI 命令
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                preexec_fn=os.setsid,
                env={**os.environ,
                     "BASELINE_BASE_DIR": cwd,
                     "CLAUDE_CODE_SESSION_NAME_USER": session_name,
                     **extra_env},  # backend 路由 env (DeepSeek 模式下生效)
            )
            active_processes.add(proc)

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        proc.kill()
                    await proc.wait()
                finally:
                    active_processes.discard(proc)
                err = f"Timeout after {timeout_seconds}s"
                _log(f"Error: {err}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                return {"success": False, "session_id": None, "error": err}
            except asyncio.CancelledError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        proc.kill()
                    await proc.wait()
                finally:
                    active_processes.discard(proc)
                raise
            finally:
                active_processes.discard(proc)

            stderr_str = stderr_data.decode("utf-8", errors="replace")
            stdout_str = stdout_data.decode("utf-8", errors="replace")

            if log_file:
                with open(log_file, "a", encoding="utf-8") as lf:
                    lf.write(f"\n=== STDOUT ===\n{stdout_str[:50000]}\n")
                    if stderr_str.strip():
                        lf.write(f"\n=== STDERR ===\n{stderr_str[:10000]}\n")

            _log(f"Exit code: {proc.returncode}")

            # 解析 --output-format json 返回的 JSON
            result_text = ""
            real_session_id = None
            try:
                data = json.loads(stdout_str)
                real_session_id = data.get("session_id") or session_id
                result_text = data.get("result", "")
            except (json.JSONDecodeError, AttributeError):
                _log("Warning: failed to parse JSON output, using raw stdout")
                result_text = stdout_str

            combined = stderr_str + stdout_str
            retry_hit = any(e in combined for e in RETRY_ERRORS)
            if retry_hit and attempt < max_retries - 1:
                _log(f"Retry-able error detected, waiting {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                continue

            return {
                "success": proc.returncode == 0,
                "session_id": real_session_id or session_id,
                "content": result_text,
                "stderr": stderr_str,
                "error": stderr_str if proc.returncode != 0 else None,
            }

        except Exception as e:
            err = str(e)
            _log(f"Exception: {err}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            return {"success": False, "session_id": None, "error": err}

    return {"success": False, "session_id": None, "error": "Max retries exceeded"}
