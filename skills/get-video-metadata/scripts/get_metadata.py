import os
import subprocess
import json
import argparse
from typing import Dict, Any


def get_video_metadata_ffprobe(video_path: str) -> Dict[str, Any]:
    """使用 ffprobe 获取视频元数据。返回 { duration_s, width, height, fps }，失败时抛出异常。"""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        raise FileNotFoundError("ffprobe not found in PATH; please install ffmpeg")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr or 'unknown error'}")
    try:
        probe_data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse ffprobe output: {e}")
    video_stream = None
    for stream in probe_data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break
    if not video_stream:
        raise RuntimeError("No video stream found in file")
    width = video_stream.get("width")
    height = video_stream.get("height")
    fps_str = video_stream.get("r_frame_rate", "0/1")
    if "/" in fps_str:
        num, den = map(float, fps_str.split("/"))
        fps = num / den if den != 0 else 0.0
    else:
        fps = float(fps_str) if fps_str else 0.0
    duration = None
    if "format" in probe_data and "duration" in probe_data["format"]:
        duration = float(probe_data["format"]["duration"])
    elif "duration" in video_stream:
        duration = float(video_stream["duration"])
    if duration is None:
        raise RuntimeError("Could not determine video duration")

    total_frames = 0
    if "nb_frames" in video_stream:
        try:
            total_frames = int(video_stream["nb_frames"])
        except ValueError:
            pass
    
    if total_frames == 0 and duration is not None and fps > 0:
        total_frames = int(duration * fps)

    return {
        "duration_s": round(duration, 2),
        "width": width,
        "height": height,
        "fps": round(fps, 2),
        "total_frames": total_frames,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get video metadata using ffprobe")
    parser.add_argument("--video_path", type=str, required=True, help="Path to video file")
    args = parser.parse_args()
    try:
        metadata = get_video_metadata_ffprobe(args.video_path)
        print(json.dumps(metadata, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {str(e)}", flush=True)
        exit(1)
