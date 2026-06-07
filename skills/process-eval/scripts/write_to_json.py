import json
import argparse
import sys
import os
import subprocess

def get_output_dir(session_key):
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if session_key:
            cmd.extend(["--session-key", session_key])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        log_dir = result.stdout.strip()
        if result.returncode != 0 or not log_dir or "Error" in log_dir or "Warning" in log_dir:
            detail = result.stderr.strip() or log_dir
            return None, f"Error: Could not resolve output directory: {detail}"
        return log_dir, None
    except Exception as e:
        return None, f"Error: Could not resolve output directory"

def write_to_json(data, output_path):
    """
    Write data (dict or list) to a JSON file with proper formatting.
    """
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"Successfully wrote data to {output_path}")
        return True
    except Exception as e:
        print(f"Error writing to {output_path}: {e}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Write JSON data to a file")
    parser.add_argument('--output_filename', '-o', required=True, help="Name of the output JSON file (e.g. rubrics_eval.json)")
    parser.add_argument('--session_key', '-k', help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    parser.add_argument('--data', '-d', help="JSON string data to write. If not provided, reads from stdin.")
    
    args = parser.parse_args()
    
    # Get output directory
    log_dir, err = get_output_dir(args.session_key)
    if err:
        print(err, file=sys.stderr)
        sys.exit(1)
        
    output_path = os.path.join(log_dir, args.output_filename)
    
    # Get data from argument or stdin
    json_str = args.data
    if not json_str:
        if not sys.stdin.isatty():
            json_str = sys.stdin.read()
        else:
            print("Error: No data provided via --data argument or stdin.", file=sys.stderr)
            sys.exit(1)
            
    try:
        # Parse the string into a Python object first to ensure it's valid JSON
        data = json.loads(json_str)
        write_to_json(data, output_path)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON data provided. {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
