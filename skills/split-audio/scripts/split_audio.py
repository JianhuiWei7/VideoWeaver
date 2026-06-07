import argparse
import os
import subprocess
import sys

def split_audio(video_path, output_dir):
    if not os.path.exists(video_path):
        print(f"Error: Video file not found at {video_path}")
        sys.exit(1)

    # Prepare directories and file paths
    video_name = os.path.basename(video_path)
    name_without_ext, ext = os.path.splitext(video_name)

    # If the original video already has "_no_audio" in its name, we might want to strip it for the audio file
    audio_name_base = name_without_ext.replace("_no_audio", "")
    
    # 1. Output audio path
    os.makedirs(output_dir, exist_ok=True)
    audio_output_path = os.path.join(output_dir, f"{audio_name_base}_audio.mp3")

    # 2. Output video without audio path
    video_no_audio_path = os.path.join(output_dir, f"{name_without_ext}_no_audio{ext}")

    print(f"Processing: {video_path}")
    print(f"Extracting audio to: {audio_output_path}")
    print(f"Extracting video to: {video_no_audio_path}")

    # Extract Audio
    try:
        # Extract audio using ffmpeg: -q:a 0 sets VBR quality, -map a selects audio streams
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-q:a", "0", "-map", "a", audio_output_path],
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ Audio extracted successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to extract audio. FFmpeg error:\n{e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("❌ FFmpeg is not installed or not found in PATH.")
        sys.exit(1)

    # Extract Video without Audio
    try:
        # Copy video stream, ignore audio stream (-an)
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-c:v", "copy", "-an", video_no_audio_path],
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ Muted video generated successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to generate muted video. FFmpeg error:\n{e.stderr}")
        sys.exit(1)

    print("\nAll done!")
    print(f"Audio: {audio_output_path}")
    print(f"Video (no audio): {video_no_audio_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract audio from a video and create a muted version of the video.")
    parser.add_argument("video_path", help="Path to the input video file")
    parser.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    
    args = parser.parse_args()
    
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "videos"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output_dir = result.stdout.strip()
        if result.returncode != 0 or not output_dir or "Error" in output_dir or "Warning" in output_dir:
            detail = result.stderr.strip() or output_dir
            print(f"Error: Could not resolve output directory\n{detail}")
            sys.exit(1)
    except Exception as e:
        print(f"Error: Could not resolve output directory: {e}")
        sys.exit(1)
        
    split_audio(args.video_path, output_dir)
