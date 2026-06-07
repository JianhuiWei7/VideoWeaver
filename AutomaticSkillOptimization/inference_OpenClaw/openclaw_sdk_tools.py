import asyncio
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime as dt
from openclaw_sdk import OpenClawClient
from openclaw_sdk.core.config import ExecutionOptions
import argparse

from AutomaticSkillOptimization.args import OUTPUT_DIR


def openclaw_sessions_path(agent_id):
    return os.path.expanduser(f"~/.openclaw/agents/{agent_id}/sessions/sessions.json")

def parse_jsonl_content(jsonl_path, output_dir):
    
    if not os.path.exists(jsonl_path):
        print(f">>> Warning: Session file not found: {jsonl_path}")
        return []
        
    formatted_logs = []
    current_assistant_content = []

    try:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if record.get("type") != "message":
                    continue

                message = record.get("message", {})
                role = message.get("role")
                content_list = message.get("content", [])
                
                if role == "user":
                    text_content = ""
                    if isinstance(content_list, list):
                        for item in content_list:
                            if item.get("type") == "text":
                                text_content += item.get("text", "")
                    
                    match = re.search(r'Sender \(untrusted metadata\):[\s\S]*?```[\s\S]*?```\s*\[.*?\]\s*(.*)', text_content, re.DOTALL)
                    if match:
                        text_content = match.group(1).strip()
                    
                    if current_assistant_content:
                        formatted_logs.append({
                            "role": "assistant",
                            "content": current_assistant_content
                        })
                        current_assistant_content = []
                    
                    user_log = {
                        "role": "user",
                        "content": text_content
                    }
                    
                    if "OpenClaw runtime context (internal)" in text_content:
                        session_id_match = re.search(r'session_id:\s*([a-f0-9\-]+)', text_content)
                        session_key_match = re.search(r'session_key:\s*([a-zA-Z0-9\-:]+)', text_content)
                        
                        if session_id_match:
                            sub_session_id = session_id_match.group(1)
                            if session_key_match:
                                session_key = session_key_match.group(1)
                                # 如果在generate_materials目录下有以session_key_session_id命名的文件夹，就移动到output_dir
                                session_path = os.path.join(OUTPUT_DIR, session_key + f"_{sub_session_id}")
                                if os.path.isdir(session_path):
                                    os.makedirs(output_dir, exist_ok=True)
                                    shutil.move(session_path, os.path.join(output_dir, session_key))
                                    print(f">>> Moved session {session_key} to {output_dir}/{session_key}")
                            base_dir = os.path.dirname(jsonl_path)
                            sub_jsonl_path = os.path.join(base_dir, f"{sub_session_id}.jsonl")
                            
                            found_sub_path = None
                            if os.path.exists(sub_jsonl_path):
                                found_sub_path = sub_jsonl_path
                            else:
                                possible_files = glob.glob(os.path.join(base_dir, f"{sub_session_id}.jsonl.*"))
                                if possible_files:
                                    found_sub_path = possible_files[0]
                                    
                            if found_sub_path:
                                sub_logs = parse_jsonl_content(found_sub_path, os.path.join(output_dir, session_key))
                                user_log["subagent_logs"] = sub_logs

                    formatted_logs.append(user_log)

                elif role == "assistant":
                    if isinstance(content_list, list):
                        for item in content_list:
                            if item.get("type") == "thinking":
                                current_assistant_content.append({
                                    "type": "thinking",
                                    "content": item.get("thinking")
                                })
                            elif item.get("type") == "toolCall":
                                current_assistant_content.append({
                                    "type": "tool_call",
                                    "name": item.get("name"),
                                    "arguments": item.get("arguments")
                                })
                            elif item.get("type") == "text":
                                current_assistant_content.append({
                                    "type": "final_return",
                                    "content": item.get("text")
                                })

                elif role == "toolResult":
                    tool_name = message.get("toolName")
                    result_text = ""
                    if isinstance(content_list, list):
                        for item in content_list:
                            if item.get("type") == "text":
                                result_text += item.get("text", "")
                    
                    tool_result_entry = {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "content": result_text
                    }
                    
                    details = message.get("details")
                    if details:
                        tool_result_entry["details"] = details

                    current_assistant_content.append(tool_result_entry)
                    
        if current_assistant_content:
             formatted_logs.append({
                 "role": "assistant",
                 "content": current_assistant_content
             })

        return formatted_logs
    except Exception as e:
        print(f">>> Error parsing log file: {e}")
        return formatted_logs

async def get_available_agent_ids(base_agent_id="main"):
    try:
        async with await OpenClawClient.connect() as client:
            agents = await client.list_agents()
            valid_ids = [agent.agent_id for agent in agents if agent.agent_id.startswith(base_agent_id)]
            if not valid_ids:
                return [base_agent_id]
            return valid_ids
    except Exception as e:
        print(f"Failed to fetch agents via SDK: {e}")
        return [base_agent_id]

def get_available_agent_ids_CLI_version(base_agent_id="main"):
    try:
        result = subprocess.run(["openclaw", "agents", "list", "--json"], capture_output=True, text=True, check=True)
        agents = json.loads(result.stdout)
        valid_ids = [a['id'] for a in agents if a['id'].startswith(base_agent_id)]
        if not valid_ids:
            return [base_agent_id]
        return valid_ids
    except Exception as e:
        print(f"Failed to fetch agents: {e}")
        return [base_agent_id]
    
def convert_jsonl_to_json(jsonl_path, agent_id, session_name, session_id):
    """
    将 .jsonl 格式的 Session 日志转换为结构化的 .json 日志文件
    """
    output_dir = os.path.join(OUTPUT_DIR, f"agent:{agent_id}:{session_name}_{session_id}")
    os.makedirs(output_dir, exist_ok=True)
    output_filename = os.path.join(output_dir, "ReAct_process.json")
    original_jsonl_path = os.path.join(output_dir, "original_ReAct.jsonl")
    if os.path.exists(jsonl_path):
        print(f">>> Copying original jsonl file to {original_jsonl_path}")
        shutil.copy2(jsonl_path, original_jsonl_path)
    formatted_logs = parse_jsonl_content(jsonl_path, os.path.dirname(output_filename))
    
    if formatted_logs:
        os.makedirs(os.path.dirname(output_filename), exist_ok=True)
        try:
            with open(output_filename, 'w', encoding='utf-8', errors='replace') as f:
                json.dump(formatted_logs, f, indent=2, ensure_ascii=False) 
            return output_filename
        except Exception as e:
            print(f">>> Error writing JSON output: {e}")
            return None
    return None



def get_session_id_CLI_version(agent_id, session_name, max_retries=3, verbose=True):
    """通过 CLI 获取 Session ID，带重试机制"""
    target_key = f"agent:{agent_id}:{session_name}"
    for attempt in range(max_retries):
        try:
            cmd_result = subprocess.run(["openclaw", "sessions", "--all-agents", "--json"], capture_output=True, text=True, check=False)
            if cmd_result.returncode == 0:
                json_match = re.search(r'^\{.*\}', cmd_result.stdout, re.DOTALL)
                if not json_match:
                    print(f">>> CLI output was not valid JSON. Stdout: {cmd_result.stdout[:200]}")
                    return None
                json_content = json_match.group()
                session_data = json.loads(json_content)
                sessions_list = session_data.get('sessions', [])
                
                # 根据 key 匹配对应的 Session
                for sess in sessions_list:
                    if sess.get("key").lower() == target_key.lower():
                        session_id = sess.get('sessionId')
                        if verbose:
                            print(f">>> Found Session ID for {target_key}: {session_id}")
                        return session_id
                
                print(f">>> Warning: No active session found for key {target_key} in CLI.")
                return None # 没找到就不用重试了，大概率确实不存在
            else:
                print(f">>> CLI command failed with return code {cmd_result.returncode}. Stderr: {cmd_result.stderr}")
        except Exception as e:
            print(f">>> Failed to fetch session ID: {e}")
        
        if attempt < max_retries - 1:
            print(f">>> Retrying get_session_id ({attempt + 1}/{max_retries})...")
            time.sleep(2)
            
    print(f">>> Error: Exhausted all {max_retries} retries for get_session_id.")
    return None

def get_session_id(agent_id, session_name, max_retries=3, verbose=True):
    """通过 SDK 获取 Session ID，包装为同步调用函数"""
    async def _get():
        target_key = f"agent:{agent_id}:{session_name}"
        for attempt in range(max_retries):
            try:
                async with await OpenClawClient.connect() as client:
                    sessions_list = await client.gateway.sessions_list()
                    
                    # 根据 key 匹配对应的 Session
                    for sess in sessions_list:
                        if sess.get("key", "").lower() == target_key.lower():
                            session_id = sess.get("sessionId")
                            if verbose:
                                print(f">>> Found Session ID for {target_key}: {session_id}")
                            return session_id
                    
                    print(f">>> Warning: No active session found for key {target_key} via SDK.")
                    return None
            except Exception as e:
                print(f">>> Failed to fetch session ID via SDK: {e}")
            
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
        # 如果当前线程已经在运行事件循环，我们在新线程里运行 asyncio.run
        result = []
        def run_in_thread():
            result.append(asyncio.run(_get()))
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()
        return result[0] if result else None
    else:
        # 如果当前线程没有运行事件循环，直接运行
        return asyncio.run(_get())

def get_session_file_path(agent_id, session_name):
    """查找 Session 对应的日志文件路径"""
    try:
        sessions_json_path = openclaw_sessions_path(agent_id)
        if os.path.exists(sessions_json_path):
            with open(sessions_json_path, 'r') as f:
                sessions_data = json.load(f)
                # key 格式: agent:{agent_id}:{session_name}
                session_key = f"agent:{agent_id}:{session_name}"
                if session_key in sessions_data:
                     return sessions_data[session_key].get("sessionFile")
    except Exception as e:
        print(f">>> Error locating session file: {e}")
    return None

async def check_status(agent_id, session_name):
    """查询并返回指定 Agent Session 的当前状态"""
    try:
        async with await OpenClawClient.connect() as client:
            agent = client.get_agent(agent_id, session_name=session_name)
            status = await agent.get_status()
            # status is an Enum, we return its string value
            return status.value
    except Exception as e:
        print(f">>> Error fetching status for {agent_id}:{session_name} - {e}")
        return "unknown"

async def delete_session(agent_id, session_name, max_retries=5):
    """彻底删除指定的 Agent Session 及其对话记忆"""
    # 先检查 session 是否存在
    session_id = get_session_id(agent_id, session_name, verbose=False)
    if not session_id:
        print(f">>> Session agent:{agent_id}:{session_name} does not exist, skipping deletion.")
        return {"ok": True, "deleted": False}

    for attempt in range(max_retries):
        try:
            async with await OpenClawClient.connect() as client:
                agent = client.get_agent(agent_id, session_name=session_name)
                session_key = agent.session_key
                result = await client.gateway.sessions_delete(session_key)
                if result.get("ok"):
                    deleted_status = "already deleted/archived" if not result.get("deleted") else "deleted"
                    print(f">>> Session: {session_key} - Status: {deleted_status}")
                    return result
                else:
                    print(f">>> Failed to delete session: {session_key}, response: {result}")
                    if attempt < max_retries - 1:
                        print(f">>> Retrying delete_session ({attempt + 1}/{max_retries})...")
                        await asyncio.sleep(10)
                    else:
                        return result
        except Exception as e:
            print(f">>> Error deleting session {agent_id}:{session_name} - {e}")
            if attempt < max_retries - 1:
                print(f">>> Retrying delete_session ({attempt + 1}/{max_retries})...")
                await asyncio.sleep(10)
            else:
                return None

def calculate_cost_from_jsonl(jsonl_path):
    # add cache hit rate to cost summary
    cost_summary = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cacheRead_tokens": 0,
        "cacheWrite_tokens": 0,
        "total_tokens": 0,
        "cache_hit_rate": None,
        "cost": {
            "input": 0.0,
            "output": 0.0,
            "cacheRead": 0.0,
            "cacheWrite": 0.0,
            "total": 0.0,
            "unit": "N/A"
        }
    }
    if not os.path.exists(jsonl_path):
        return cost_summary
        
    try:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("type") == "message":
                        message_obj = record.get("message", {})
                        usage = message_obj.get("usage")
                        if usage:
                            inp = usage.get("input", 0)
                            out = usage.get("output", 0)
                            cache_read = usage.get("cacheRead", 0)
                            cache_write = usage.get("cacheWrite", 0)
                            
                            cost_summary["input_tokens"] += inp
                            cost_summary["output_tokens"] += out
                            cost_summary["cacheRead_tokens"] += cache_read
                            cost_summary["cacheWrite_tokens"] += cache_write
                            cost_summary["total_tokens"] += usage.get("totalTokens", 0)
                            
                            cost_dict = usage.get("cost")
                            if cost_dict:
                                cost_summary["cost"]["input"] += cost_dict.get("input", 0.0)
                                cost_summary["cost"]["output"] += cost_dict.get("output", 0.0)
                                cost_summary["cost"]["cacheRead"] += cost_dict.get("cacheRead", 0.0)
                                cost_summary["cost"]["cacheWrite"] += cost_dict.get("cacheWrite", 0.0)
                                cost_summary["cost"]["total"] += cost_dict.get("total", 0.0)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f">>> Error calculating cost from jsonl: {e}")
    cache_eligible_tokens = cost_summary["input_tokens"] + cost_summary["cacheRead_tokens"]
    if cache_eligible_tokens > 0:
        cost_summary["cache_hit_rate"] = cost_summary["cacheRead_tokens"] / cache_eligible_tokens
    return cost_summary

def calculate_tool_call_numbers(jsonl_path):
    tool_call_count = 0
    user_message_count = 0
    count_tools = False
    saw_second_user_message = False
    if not os.path.exists(jsonl_path):
        return tool_call_count
        
    try:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("type") == "message":
                        message_obj = record.get("message", {})
                        content_list = message_obj.get("content", [])
                        if message_obj.get("role") == "user":
                            if isinstance(content_list, list):
                                has_text = any(item.get("type") == "text" for item in content_list if isinstance(item, dict))
                                has_tool_result = any(item.get("type") in {"toolResult", "tool_result"} for item in content_list if isinstance(item, dict))
                                if has_text and not has_tool_result:
                                    user_message_count += 1
                                    if user_message_count >= 2:
                                        count_tools = True
                                        saw_second_user_message = True
                            elif isinstance(content_list, str):
                                user_message_count += 1
                                if user_message_count >= 2:
                                    count_tools = True
                                    saw_second_user_message = True
                        elif count_tools and message_obj.get("role") == "assistant":
                            content_list = message_obj.get("content", [])
                            if isinstance(content_list, list):
                                for item in content_list:
                                    if isinstance(item, dict) and item.get("type") in {"toolCall", "tool_use"}:
                                        tool_call_count += 1
                except json.JSONDecodeError:
                    continue
        if not saw_second_user_message:
            return 0
    except Exception as e:
        print(f">>> Error calculating tool calls from jsonl: {e}")
    return tool_call_count

async def open_claw_chat(agent_id, session_name, message, thinking_enabled=True, timeout_seconds=7200, log_file=None, overwrite_log=False):
    def get_time_str():
        return dt.now().strftime('%Y-%m-%d %H:%M:%S')

    def custom_print(*args, **kwargs):
        prefix = f"[{session_name}] "
        msg = " ".join(str(a) for a in args)
        if msg.startswith('\n'):
            msg = '\n' + prefix + msg[1:]
        else:
            msg = prefix + msg
            
        if log_file:
            # First time calling custom_print in the function should handle overwrite if requested
            mode = "w" if overwrite_log and not hasattr(custom_print, "initialized") else "a"
            
            # The global Logger only intercepts sys.stdout, so we need to add the timestamp manually 
            # for the direct file write here to ensure the log file has timestamps.
            log_prefix = f"[{get_time_str()}] "
            log_msg = '\n' + log_prefix + msg[1:] if msg.startswith('\n') else log_prefix + msg
            
            with open(log_file, mode, encoding="utf-8") as f:
                print(log_msg, file=f, **kwargs)
            custom_print.initialized = True
        print(msg, **kwargs)

    response_data = {
        "time": "",
        "content": "",
        "cost": None,
        "tool_call_count": 0,
        "error": None
    }
    
    async with await OpenClawClient.connect() as client:
        agent = client.get_agent(agent_id, session_name=session_name)
        custom_print(f">>> Executing Agent with message: {message}")
        options = ExecutionOptions(timeout_seconds=timeout_seconds, thinking="enabled" if thinking_enabled else "disabled")
        
        try:
            result = await agent.execute(message, options=options)
            response_data["time"] = get_time_str()
            
            if result.content is None or str(result.content).strip() == "":
                raise ValueError("Agent returned empty content")
                
            content_str = str(result.content)
            if "API rate limit reached" in content_str or "TPM (Tokens Per Minute) limit of the model" in content_str:
                raise RuntimeError(f"API rate limit reached: {content_str}")
                
            response_data["content"] = result.content
            
            custom_print("\n=== Return Content ===")
            custom_print(result.content)
            
            # We will calculate cost later from the jsonl file
        except Exception as e:
            error_msg = str(e)
            response_data["error"] = error_msg
            custom_print("\n=== Execution Error ===")
            custom_print(f"Agent execution encountered an error: {error_msg}")
            if message == "/stop":
                custom_print("Note: Stop command sent. The timeout or error might be expected as the session is terminating.")
        
        current_session_id = get_session_id(agent_id, session_name)
        if current_session_id:
            session_file_path = get_session_file_path(agent_id, session_name)
            if session_file_path:
                output_filename = convert_jsonl_to_json(session_file_path, agent_id, session_name, current_session_id)
                custom_print(f"\n>>> Log saved to: {output_filename}")
                # 计算真实的 token 和 cost
                cost_summary = calculate_cost_from_jsonl(session_file_path)
                response_data["cost"] = cost_summary
                
                tool_call_count = calculate_tool_call_numbers(session_file_path)
                response_data["tool_call_count"] = tool_call_count
                
                custom_print("\n=== Cost Logs ===")
                custom_print(json.dumps(cost_summary, indent=2))
                custom_print(f"Total Tool Calls: {tool_call_count}")
            else:
                 custom_print(">>> Could not locate .jsonl session file to convert logs.")
        else:
             custom_print(f">>> Warning: Failed to get session ID for {agent_id}:{session_name}. Skipping jsonl log conversion.")
    
    return response_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run OpenClaw Agent Chat")
    parser.add_argument("--agent_id", type=str, default="main", help="Agent ID")
    parser.add_argument("--session_name", type=str, default="main", help="Session Name")
    parser.add_argument("--message", type=str, default="Hello", help="User Message")
    parser.add_argument("--thinking", action="store_true", help="Enable thinking mode")
    parser.add_argument("--timeout_seconds", type=int, default=7200, help="Execution timeout in seconds")
    parser.add_argument("--log_file", type=str, default="test.log", help="Log file path")
    parser.add_argument("--overwrite_log", action="store_true", help="Overwrite log file instead of appending")

    args = parser.parse_args()
    result = asyncio.run(open_claw_chat(args.agent_id, args.session_name, args.message, args.thinking, args.timeout_seconds, args.log_file, args.overwrite_log))
    print(result)
