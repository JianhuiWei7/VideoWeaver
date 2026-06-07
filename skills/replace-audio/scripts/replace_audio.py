import argparse
import os
import subprocess
import sys

def replace_audio(video_path, audio_path, output_dir):
    if not os.path.exists(video_path):
        print(f"Error: Video file not found at {video_path}")
        sys.exit(1)
    if not os.path.exists(audio_path):
        print(f"Error: Audio file not found at {audio_path}")
        sys.exit(1)

    # Prepare directories and file paths
    video_name = os.path.basename(video_path)
    name_without_ext, _ = os.path.splitext(video_name)
    
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{name_without_ext}_replace_audio.mp4")

    print(f"Processing video: {video_path}")
    print(f"Processing audio: {audio_path}")
    print(f"Output to: {output_path}")

    try:
        # Use ffmpeg to replace audio. 
        # -map 0:v:0 maps video from first input
        # -map 1:a:0 maps audio from second input
        # -c:v copy copies the video stream without re-encoding
        # -c:a aac re-encodes audio to aac to ensure mp4 compatibility
        # -shortest stops encoding when the shortest stream ends (optional, depending on use-case, but safe to avoid static images or silence)
        subprocess.run(
            [
                "ffmpeg", "-y", 
                "-i", video_path, 
                "-i", audio_path, 
                "-map", "0:v:0", 
                "-map", "1:a:0", 
                "-c:v", "copy", 
                "-c:a", "aac", 
                "-shortest",
                output_path
            ],
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ Audio replaced successfully.")
        print(f"\nFinal output video: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to replace audio. FFmpeg error:\n{e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("❌ FFmpeg is not installed or not found in PATH.")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replace audio in a video with a new audio file.")
    parser.add_argument("video_path", help="Path to the input video file")
    parser.add_argument("audio_path", help="Path to the new audio file to inject")
    parser.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    
    args = parser.parse_args()
    
    try:
        # Path to get-output-dir script
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "videos"])
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            check=False
        )
        output_dir = result.stdout.strip()
        if result.returncode != 0 or not output_dir or "Error" in output_dir or "Warning" in output_dir:
            detail = result.stderr.strip() or output_dir
            print(f"Error: Could not resolve output directory\n{detail}")
            sys.exit(1)
    except Exception as e:
        print(f"Error: Could not resolve output directory: {e}")
        sys.exit(1)
        
    replace_audio(args.video_path, args.audio_path, output_dir)
