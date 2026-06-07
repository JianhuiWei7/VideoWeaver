import argparse
import os
import re
import subprocess
import sys


MEAN_VOLUME_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
MAX_AUTO_GAIN_DB = 12.0


def get_audio_stream_count(media_path):
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                media_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0

    return len([line for line in result.stdout.splitlines() if line.strip()])


def get_mean_volume_db(media_path, input_index=0):
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i", media_path,
                "-map", f"0:a:{input_index}",
                "-af", "volumedetect",
                "-f", "null",
                "-",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    match = MEAN_VOLUME_RE.search(result.stderr)
    return float(match.group(1)) if match else None


def calculate_added_audio_gain_db(video_path, audio_path):
    base_mean = get_mean_volume_db(video_path, 0)
    added_mean = get_mean_volume_db(audio_path, 0)
    if base_mean is None or added_mean is None:
        print("Warning: Could not analyze audio loudness. Mixing without automatic gain adjustment.")
        return 0.0

    gain = base_mean - added_mean
    gain = max(-MAX_AUTO_GAIN_DB, min(MAX_AUTO_GAIN_DB, gain))
    print(
        "Auto volume match: "
        f"base_mean={base_mean:.2f} dB, added_mean={added_mean:.2f} dB, "
        f"added_gain={gain:+.2f} dB"
    )
    return gain


def add_audio_track(video_path, audio_path, output_dir):
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
    output_path = os.path.join(output_dir, f"{name_without_ext}_add_audio_track.mp4")

    print(f"Processing video: {video_path}")
    print(f"Adding audio into default playback track: {audio_path}")
    print(f"Output to: {output_path}")

    try:
        audio_stream_count = get_audio_stream_count(video_path)
        if audio_stream_count:
            added_gain_db = calculate_added_audio_gain_db(video_path, audio_path)
            # Default audio becomes a mix of original default audio + new audio.
            # Original audio streams and the added audio are also preserved as
            # non-default tracks so the source tracks are not lost.
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex",
                (
                    f"[1:a:0]volume={added_gain_db:.2f}dB[added];"
                    "[0:a:0][added]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                    "alimiter=limit=0.95[mixed]"
                ),
                "-map", "0:v:0",
                "-map", "[mixed]",
                "-map", "0:a?",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-disposition:a:0", "default",
            ]
            for idx in range(audio_stream_count + 1):
                cmd.extend([f"-disposition:a:{idx + 1}", "0"])
            cmd.append(output_path)
        else:
            # If the source video has no audio, the provided audio becomes the
            # default playback track.
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-disposition:a:0", "default",
                output_path,
            ]

        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ Audio mixed into the default playback track successfully.")
        print(f"\nFinal output video: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to add audio track. FFmpeg error:\n{e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("❌ FFmpeg is not installed or not found in PATH.")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mix an audio file into a video's default playback track while preserving original audio tracks.")
    parser.add_argument("video_path", help="Path to the input video file")
    parser.add_argument("audio_path", help="Path to the audio file to mix into the default playback track")
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

    add_audio_track(args.video_path, args.audio_path, output_dir)
