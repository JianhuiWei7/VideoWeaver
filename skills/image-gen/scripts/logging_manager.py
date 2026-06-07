#!/usr/bin/env python3
import os
import json
import subprocess
import sys
import argparse
from datetime import datetime

def get_log_file_path(session_key):
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if session_key:
            cmd.extend(["--session-key", session_key])
        cmd.extend(["--subdir", "images"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        folder = result.stdout.strip()
        if result.returncode != 0 or not folder or "Error" in folder or "Warning" in folder:
            detail = result.stderr.strip() or folder
            raise RuntimeError(f"Could not resolve output directory: {detail}")
    except Exception as e:
        raise RuntimeError(f"Could not resolve output directory: {e}")
        
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "multi-turn-log.json")

def init_log_if_not_exists(log_path):
    if not os.path.exists(log_path):
        initial_data = {
            "turns": [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(initial_data, f, indent=2, ensure_ascii=False)

def add_log(session_key, turn_data):
    log_path = get_log_file_path(session_key)
    init_log_if_not_exists(log_path)
    
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
         # If file is corrupted, reset it
        data = {
            "turns": [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

    # Auto-generate turn_id if not provided
    if "turn_id" not in turn_data:
        turn_data["turn_id"] = len(data["turns"]) + 1
    
    # Ensure timestamp for the turn
    if "created_at" not in turn_data:
        turn_data["created_at"] = datetime.now().isoformat()
    
    data["turns"].append(turn_data)
    data["updated_at"] = datetime.now().isoformat()
    
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"Log added to {log_path}")

def get_logs(session_key):
    log_path = get_log_file_path(session_key)
    if not os.path.exists(log_path):
        # Return empty structure if no log exists
        print(json.dumps({"turns": []}, indent=2, ensure_ascii=False))
        return
    
    with open(log_path, 'r', encoding='utf-8') as f:
        print(f.read())

def get_log_path(session_key):
    print(get_log_file_path(session_key))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-turn Image Gen Logging Manager")
    parser.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    subparsers = parser.add_subparsers(dest="command")
    
    # Add log command
    add_parser = subparsers.add_parser("add", help="Add a new turn log")
    add_parser.add_argument("--data", required=True, help="JSON string of turn data")
    
    # Get logs command
    get_parser = subparsers.add_parser("get", help="Get all logs")

    # Get path command (useful for displaying to user)
    path_parser = subparsers.add_parser("path", help="Get log file path")
    
    args = parser.parse_args()
    
    if args.command == "add":
        try:
            turn_data = json.loads(args.data)
            add_log(args.session_key, turn_data)
        except json.JSONDecodeError:
            print("Error: Invalid JSON data provided to --data")
            sys.exit(1)
        except Exception as e:
            print(f"Error adding log: {e}")
            sys.exit(1)
    elif args.command == "get":
        get_logs(args.session_key)
    elif args.command == "path":
        get_log_path(args.session_key)
    else:
        parser.print_help()
