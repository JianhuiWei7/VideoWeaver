import argparse
import os
import subprocess
import sys

def trim_audio(input_path, start_time, end_time, output_dir):
    if not os.path.exists(input_path):
        print(f"Error: Audio file not found at {input_path}")
        sys.exit(1)

    if float(start_time) < 0:
        print("Error: start_time must be greater than or equal to 0.")
        sys.exit(1)
        
    if float(start_time) >= float(end_time):
        print("Error: start_time must be less than end_time.")
        sys.exit(1)

    # Prepare directories and file paths
    audio_name = os.path.basename(input_path)
    name_without_ext, ext = os.path.splitext(audio_name)

    # Output audio path in the output directory
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{name_without_ext}_trimmed_{start_time}_{end_time}{ext}")

    print(f"Processing: {input_path}")
    print(f"Trimming from {start_time}s to {end_time}s")
    print(f"Output will be saved to: {output_path}")

    try:
        # Trim audio using ffmpeg
        # -ss specifies start time, -to specifies end time
        # -c copy does a stream copy without re-encoding, which is very fast and lossless
        # However, for exact precision in audio, sometimes re-encoding or just using -ss and -t is safer.
        # Let's use -ss and -to with -c copy first for efficiency.
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-ss", str(start_time), "-to", str(end_time), "-c", "copy", output_path],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"✅ Audio trimmed successfully: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"❌ An error occurred during audio trimming. FFmpeg error:\n{e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("❌ FFmpeg is not installed or not found in PATH.")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trim an audio file from start_time to end_time.")
    parser.add_argument("--input_path", required=True, help="Path to the input audio file")
    parser.add_argument("--start_time", required=True, type=float, help="Start time in seconds")
    parser.add_argument("--end_time", required=True, type=float, help="End time in seconds")
    parser.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    
    args = parser.parse_args()
    
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "audios"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output_dir = result.stdout.strip()
        if result.returncode != 0 or not output_dir or "Error" in output_dir or "Warning" in output_dir:
            detail = result.stderr.strip() or output_dir
            print(f"Error: Could not resolve output directory\n{detail}")
            sys.exit(1)
    except Exception as e:
        print(f"Error: Could not resolve output directory: {e}")
        sys.exit(1)
        
    trim_audio(args.input_path, args.start_time, args.end_time, output_dir)
