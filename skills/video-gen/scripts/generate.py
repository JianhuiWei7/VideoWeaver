#!/usr/bin/env python3
import os
import sys
import json
import re
import math
import time
import base64
import shutil
import tempfile
import subprocess
import urllib.request
import argparse
import random
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from volcenginesdkarkruntime import Ark
LOG_FILE = ""
LAST_SEEDANCE_END_TIME = None

# --- 日志同时输出到控制台和文件 ---
class TeeOutput:
    def __init__(self, stream1, stream2):
        self.stream1 = stream1
        self.stream2 = stream2
    def write(self, data):
        self.stream1.write(data)
        self.stream2.write(data)
        self.flush()
    def flush(self):
        self.stream1.flush()
        self.stream2.flush()

def _format_time(timestamp: float) -> str:
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))

def log_task_start(prefix: str = "") -> float:
    start_time = time.time()
    label = f"{prefix} " if prefix else ""
    print(f"\n=== {label}任务启动时间: {_format_time(start_time)} ===")
    return start_time

def log_task_end(start_time: float, status: str = "finished", prefix: str = "", end_time: Optional[float] = None) -> None:
    end_time = end_time if end_time is not None else time.time()
    label = f"{prefix} " if prefix else ""
    print(f"\n=== {label}任务结束 对应启动时间: {_format_time(start_time)} 结束时间: {_format_time(end_time)} 状态: {status} ===")

# --- Dependencies Check ---
try:
    import requests
    from openai import OpenAI
except ImportError as e:
    print(f"Error: Required package missing: {e}. Install it via pip.")
    sys.exit(1)

# --- Configuration ---
# You can modify these paths as needed
INPUT_DIR = Path("")
OUTPUT_DIR = Path("")

# TOS Configuration
TOS_AK = os.getenv("TOS_ACCESS_KEY")
TOS_SK = os.getenv("TOS_SECRET_KEY")
TOS_ENDPOINT = "tos-cn-beijing.volces.com"
TOS_REGION = "cn-beijing"
TOS_BUCKET = "visualgen"

MAX_VIDEO_PIXELS = 927408

# --- Video Utilities (from video_utils.py) ---
def get_video_metadata_ffprobe(video_path: str) -> Dict[str, Any]:
    """Use ffprobe to get video metadata."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
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
    
    return {
        "duration_s": round(duration, 2),
        "width": width,
        "height": height,
        "fps": round(fps, 2),
    }

def _encode_file_to_base64(file_path: str) -> str:
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def _get_mime_type(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }
    return mime_types.get(ext, "application/octet-stream")

def _upload_video_to_tos(
    local_path: str, remote_path: Optional[str] = None, expires: int = 72000
) -> Optional[str]:
    try:
        import tos
        from tos import HttpMethodType
    except ImportError:
        print("Warning: 'tos' package not found. Video uploading will fail.")
        raise ImportError("To use TOS upload, please install: pip install tos")

    if not TOS_AK or not TOS_SK:
        raise ValueError("Please set TOS_ACCESS_KEY and TOS_SECRET_KEY environment variables")

    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Video file not found: {local_path}")

    if remote_path is None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = os.path.basename(local_path)
        remote_path = f"videos/{timestamp}_{filename}"

    client = tos.TosClientV2(TOS_AK, TOS_SK, TOS_ENDPOINT, TOS_REGION)

    file_size = os.path.getsize(local_path)
    if file_size > 20 * 1024 * 1024:
        client.upload_file(TOS_BUCKET, remote_path, local_path)
    else:
        client.put_object_from_file(TOS_BUCKET, remote_path, local_path)

    output = client.pre_signed_url(
        HttpMethodType.Http_Method_Get,
        TOS_BUCKET,
        remote_path,
        expires=expires,
    )
    return output.signed_url

def _download_output_video(url: str, output_path: str) -> None:
    urllib.request.urlretrieve(url, output_path)

def _extend_video(video_path: str, target_duration: int, output_path: Optional[str] = None) -> str:
    if not output_path:
        path_obj = Path(video_path)
        parent = path_obj.resolve().parent
        base_name = path_obj.stem
        ext = path_obj.suffix
        output_path = str(parent / f"{base_name}_auto_extend{ext}")
    
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", video_path,
                "-t", str(target_duration), "-c", "copy",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
        return output_path
    except Exception:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise

def _resize_video_if_needed(
    video_path: str, max_pixels: int = MAX_VIDEO_PIXELS, output_path: Optional[str] = None
) -> Tuple[str, Optional[str]]:
    meta = get_video_metadata_ffprobe(video_path)
    w, h = meta["width"], meta["height"]
    if w is None or h is None:
        return video_path, None
    if w * h <= max_pixels:
        return video_path, None
    
    scale = math.sqrt(max_pixels / (w * h))
    new_w = max(2, int(w * scale) // 2 * 2)
    new_h = max(2, int(h * scale) // 2 * 2)
    
    while new_w * new_h > max_pixels:
        new_w = max(2, new_w - 2)
        new_h = max(2, new_h - 2)
    
    if not output_path:
        path_obj = Path(video_path)
        parent = path_obj.resolve().parent
        base_name = path_obj.stem
        ext = path_obj.suffix
        output_path = str(parent / f"{base_name}_auto_resize{ext}")
    
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", f"scale={new_w}:{new_h}",
                "-c:a", "copy",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
        return output_path, None
    except Exception:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise

def seedance_edit(
    video_paths: List[str],
    image_paths: List[str],
    user_message: str,
    video_ratio: str = "16:9",
    video_resolution: str = "480p",
    save_path: str = "output.mp4",
    poll_interval: int = 10,
    duration: float = 5,
    first_frame_path: Optional[str] = None,
    last_frame_path: Optional[str] = None,
    model: str = "doubao-seedance-2-0-fast-260128",
    audio_paths: List[str] = None,
    task_start_time: Optional[float] = None,
    return_timing: bool = False,
) -> Any:
    """
    Call Seedance2Edit API for video editing.
    """
    global LAST_SEEDANCE_END_TIME
    LAST_SEEDANCE_END_TIME = None
    effective_start_time = task_start_time if task_start_time is not None else time.time()
    retry_messages = [
        "ContentGenerationError",
        "OutputVideoSensitiveContentDetected",
        "InternalServiceError"
    ]
    # TODO:修改数据预处理
    if audio_paths is None:
        audio_paths = []

    for p in video_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Video file not found: {p}")
    for p in image_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Reference image not found: {p}")
    for p in audio_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Reference audio not found: {p}")
    if first_frame_path and not os.path.exists(first_frame_path):
        raise FileNotFoundError(f"First frame image not found: {first_frame_path}")
    if last_frame_path and not os.path.exists(last_frame_path):
        raise FileNotFoundError(f"Last frame image not found: {last_frame_path}")

    processed_video_paths = []
    created_temp_files = []
    
    cwd = Path.cwd().resolve()
    tmp_dir = cwd / "tmp_files_deletable"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    for video_path in video_paths:
        video_meta = get_video_metadata_ffprobe(video_path)
        video_duration = video_meta["duration_s"]
        
        current_video_path = video_path
        
        path_obj = Path(video_path).resolve()
        try:
            rel_path = path_obj.relative_to(cwd)
            parts = rel_path.parent.parts
        except ValueError:
            parts = path_obj.parent.parts[1:]
            
        prefix = "_".join(parts) + "_" if parts and parts[0] != "" else ""
        base_name = path_obj.stem
        ext = path_obj.suffix
        
        if video_duration < 2:
            extend_out_name = f"{prefix}{base_name}_auto_extend{ext}"
            extend_out_path = str(tmp_dir / extend_out_name)
            current_video_path = _extend_video(current_video_path, 2, output_path=extend_out_path)
            created_temp_files.append(current_video_path)
        
        resize_out_name = f"{prefix}{base_name}_auto_resize{ext}" if video_duration >= 2 else f"{prefix}{base_name}_auto_extend_auto_resize{ext}"
        resize_out_path = str(tmp_dir / resize_out_name)
        
        new_video_path, _ = _resize_video_if_needed(current_video_path, output_path=resize_out_path)
        if new_video_path != current_video_path:
            created_temp_files.append(new_video_path)
        current_video_path = new_video_path
        
        processed_video_paths.append(current_video_path)
    try:
        available_keys = [val for key, val in os.environ.items() if key.startswith("ARK_API_KEY") and val]
        api_key = random.choice(available_keys) if available_keys else None
        if not api_key:
            raise ValueError("Please set ARK_API_KEY environment variable")

        content = [{"type": "text", "text": user_message}]

        # Add reference images
        for img_path in image_paths:
            image_base64 = _encode_file_to_base64(img_path)
            mime_type = _get_mime_type(img_path)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                    "role": "reference_image",
                }
            )

        # Add first frame if provided
        if first_frame_path:
            image_base64 = _encode_file_to_base64(first_frame_path)
            mime_type = _get_mime_type(first_frame_path)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                    "role": "first_frame",
                }
            )

        # Add last frame if provided
        if last_frame_path:
            image_base64 = _encode_file_to_base64(last_frame_path)
            mime_type = _get_mime_type(last_frame_path)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                    "role": "last_frame",
                }
            )

        # Add reference audios
        for audio_path in audio_paths:
            audio_base64 = _encode_file_to_base64(audio_path)
            mime_type = _get_mime_type(audio_path)
            content.append(
                {
                    "type": "audio_url",
                    "audio_url": {"url": f"data:{mime_type};base64,{audio_base64}"},
                    "role": "reference_audio",
                }
            )

        video_urls = []
        try:
            for video_path in processed_video_paths:
                video_url = _upload_video_to_tos(video_path)
                if not video_url:
                    raise RuntimeError("Failed to upload video to TOS")
                video_urls.append(video_url)
        except Exception as e:
            raise e

        for video_url in video_urls:
            content.append(
                {
                    "type": "video_url",
                    "video_url": {"url": video_url},
                    "role": "reference_video",
                }
            )

        client = Ark(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=api_key,
        )

        print_lines = [f"Submitting Seedance task: \n prompt={user_message}\n model={model}"]
        if save_path:
            print_lines.append(f"save_path={save_path}")
        if video_ratio:
            print_lines.append(f"video_ratio={video_ratio}")
        if video_resolution:
            print_lines.append(f"video_resolution={video_resolution}")
        if duration:
            print_lines.append(f"duration={duration}")
        if video_paths:
            print_lines.append(f"reference_videos={video_paths}")
        if audio_paths:
            print_lines.append(f"reference_audios={audio_paths}")
        if first_frame_path:
            print_lines.append(f"first_frame_path={first_frame_path}")
        if last_frame_path:
            print_lines.append(f"last_frame_path={last_frame_path}")
        if image_paths:
            print_lines.append(f"reference_images={image_paths}")
        if LOG_FILE:
            print_lines.append(f"log_files: {LOG_FILE}")

        print("\n".join(print_lines))

        max_retries = 2
        for attempt in range(max_retries + 1):
            attempt_started = False
            try:
                attempt_started = True

                client = Ark(
                    api_key=api_key,
                    base_url="https://ark.cn-beijing.volces.com/api/v3",
                )

                create_result = client.content_generation.tasks.create(
                    model=model,
                    content=content,
                    ratio=video_ratio,
                    duration=int(duration),
                    resolution=video_resolution,
                )
                task_id = create_result.id

                while True:
                    get_result = client.content_generation.tasks.get(task_id=task_id)
                    status = get_result.status

                    if status == "succeeded":
                        output_video_url = None
                        if hasattr(get_result, "content") and get_result.content:
                            task_content = get_result.content
                            if hasattr(task_content, "video_url"):
                                output_video_url = task_content.video_url
                            elif isinstance(task_content, dict) and "video_url" in task_content:
                                output_video_url = task_content["video_url"]

                        if not output_video_url:
                            raise RuntimeError("Task succeeded but returned no video URL")

                        video_save_path = save_path
                        _download_output_video(output_video_url, video_save_path)

                        end_time = time.time()
                        LAST_SEEDANCE_END_TIME = end_time
                        elapsed_time = end_time - effective_start_time
                        mins, secs = divmod(elapsed_time, 60)
                        print(f"Video Input: {True if video_paths else False}; 💰 Token Used:", get_result.usage.total_tokens)
                        print(f"⏱️ 任务生成完成！所用时间: {int(mins)}min, {int(secs)}sec")

                        if return_timing:
                            return video_save_path, end_time
                        return video_save_path

                    elif status == "failed":
                        err_msg = getattr(get_result, "error", None) or str(get_result)
                        raise RuntimeError(f"Seedance task failed: {err_msg}")

                    time.sleep(poll_interval)
                    print(f"Task status: {status}")
            except Exception as e:
                if attempt_started:
                    failure_time = time.time()
                    LAST_SEEDANCE_END_TIME = failure_time
                    elapsed_time = failure_time - effective_start_time
                    mins, secs = divmod(elapsed_time, 60)
                    print(f"⏱️ 任务失败，消耗时间: {int(mins)}min, {int(secs)}sec")
                err_str = str(e)
                if attempt < max_retries and any(msg in err_str for msg in retry_messages):
                    print(f"⚠️ 遇到错误: {err_str}，正在重试 ({attempt + 1}/{max_retries})...")
                    time.sleep(2)
                    continue
                raise

    finally:
        for tmp_file in created_temp_files:
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except Exception:
                pass

# --- Main Batch Processing Logic (from run_seedance_edit.py) ---
def extract_number_from_filename(filename: str) -> int:
    match = re.search(r'(\d+)', filename)
    return int(match.group(1)) if match else 0

def get_sorted_image_paths(folder_path: Path) -> List[str]:
    image_extensions = {'.png', '.jpeg', '.jpg', '.webp'}
    image_files = []
    
    for f in folder_path.iterdir():
        if f.is_file() and f.suffix.lower() in image_extensions:
            image_files.append(f)
    
    image_files.sort(key=lambda x: extract_number_from_filename(x.name))
    
    return [str(f) for f in image_files]

def get_sorted_video_paths(folder_path: Path) -> List[str]:
    video_extensions = {'.mp4', '.avi', '.mov', '.webm'}
    video_files = []
    
    for f in folder_path.iterdir():
        if f.is_file() and f.suffix.lower() in video_extensions:
            video_files.append(f)
    
    video_files.sort(key=lambda x: extract_number_from_filename(x.name))
    
    return [str(f) for f in video_files]

def get_sorted_audio_paths(folder_path: Path) -> List[str]:
    audio_extensions = {'.mp3', '.wav', '.m4a', '.ogg', '.flac'}
    audio_files = []
    
    for f in folder_path.iterdir():
        if f.is_file() and f.suffix.lower() in audio_extensions:
            audio_files.append(f)
    
    audio_files.sort(key=lambda x: extract_number_from_filename(x.name))
    
    return [str(f) for f in audio_files]

def get_json_prompt(folder_path: Path) -> str:
    for f in folder_path.iterdir():
        if f.is_file() and f.suffix.lower() == '.json':
            with open(f, 'r', encoding='utf-8') as file:
                data = json.load(file)
                if isinstance(data, list) and len(data) > 0:
                    return data[0].get('prompt', '')
                elif isinstance(data, dict):
                    return data.get('prompt', '')
    return None

def process_folder(folder_path: Path, output_dir: Path, model: str = "doubao-seedance-2-0-fast-260128") -> Tuple[bool, str]:
    folder_name = folder_path.name
    task_start_time = log_task_start()
    
    video_paths = get_sorted_video_paths(folder_path)
    image_paths = get_sorted_image_paths(folder_path)
    audio_paths = get_sorted_audio_paths(folder_path)
    
    if not video_paths and not image_paths and not audio_paths:
        log_task_end(task_start_time, status="failed")
        return False, f"No video, images or audios found in {folder_name}"
    
    user_message = get_json_prompt(folder_path)
    if not user_message:
        log_task_end(task_start_time, status="failed")
        return False, f"No prompt found in {folder_name}"
    
    output_path = output_dir / f"{folder_name}.mp4"
    
    if output_path.exists():
        log_task_end(task_start_time, status="skipped")
        return True, f"[Skip] {folder_name}.mp4 already exists"
    
    print(f"[Processing] {folder_name}")
    print(f" Videos: {[Path(p).name for p in video_paths] if video_paths else 'None'}")
    print(f" Images: {[Path(p).name for p in image_paths] if image_paths else 'None'}")
    print(f" Audios: {[Path(p).name for p in audio_paths] if audio_paths else 'None'}")
    print(f" Prompt: {user_message[:50]}...")
    
    try:
        video_save_path = seedance_edit(
            video_paths=video_paths,
            image_paths=image_paths,
            audio_paths=audio_paths,
            user_message=user_message,
            save_path=str(output_path),
            model=model,
        )
        log_task_end(task_start_time, status="success")
        return True, f"[Done] {folder_name}.mp4"
    except Exception as e:
        log_task_end(task_start_time, status="failed")
        return False, f"[Error] {folder_name}: {str(e)}"

def main():
    parser = argparse.ArgumentParser(description="Seedance 2.0 官方视频生成/编辑工具（支持单任务+批量）")
    parser.add_argument("--batch", action="store_true", help="启用批量处理模式，不执行单任务")
    parser.add_argument("--prompt", type=str, default="发挥你的想象力生成一个视频", help="单任务模式：生成提示词")
    parser.add_argument("--reference-video", action="append", default=[], help="单任务模式：参考视频路径，可多次传入")
    parser.add_argument("--reference-image", action="append", default=[], help="单任务模式：参考图片路径，可多次传入")
    parser.add_argument("--reference-audio", action="append", default=[], help="单任务模式：参考音频路径，可多次传入")
    parser.add_argument("--first-image", type=str, default="", help="单任务模式：首帧图片路径")
    parser.add_argument("--last-image", type=str, default="", help="单任务模式：尾帧图片路径")
    parser.add_argument("--output", type=str, default="output.mp4", help="单任务模式：输出视频保存路径")
    parser.add_argument("--ratio", type=str, default="16:9", help="单任务模式：输出视频比例，默认16:9")
    parser.add_argument("--resolution", type=str, default="480p", help="单任务模式：输出分辨率，默认480p")
    parser.add_argument("--duration", type=float, default=5, help="单任务模式：生成视频时长，默认匹配第一个参考视频时长")
    parser.add_argument("--poll-interval", type=int, default=10, help="单任务模式：任务轮询间隔秒数，默认10")
    parser.add_argument("--model", type=str, default="doubao-seedance-2-0-fast-260128", help="模型名称")
    parser.add_argument("--background", action="store_true", help="在后台运行任务并返回JSON状态信息")
    parser.add_argument("--internal-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--session-key", type=str, help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    
    args = parser.parse_args()

    global LOG_FILE
    # --- 获取 Session ID & 设置日志路径 ---
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "videos"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        log_dir = result.stdout.strip()
        if result.returncode != 0 or not log_dir or "Error" in log_dir or "Warning" in log_dir:
            detail = result.stderr.strip() or log_dir
            return f"Error: Could not resolve output directory: {detail}"
    except Exception as e:
        return f"Error: Could not resolve output directory"
    LOG_FILE = os.path.join(log_dir, "run.log")

    # --- 日志配置 ---
    # 确保日志目录存在
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    if not args.background and not args.internal_worker:
        # 交互模式：同时输出到控制台和文件
        log_f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stdout = TeeOutput(sys.stdout, log_f)
        sys.stderr = TeeOutput(sys.stderr, log_f)
    elif args.internal_worker:
        # 后台Worker模式：stdout/stderr 已被父进程重定向到日志文件
        # 强制刷新缓冲区，确保日志及时写入
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)

    # 默认前台运行模式，如果指定了 --background，则后台运行
    if args.background and not args.internal_worker:
        # 构建 Worker 命令
        cmd_args = [sys.executable, os.path.abspath(sys.argv[0])]
        # 传递所有参数，--background 不会被传递（如果需要也可以传，但内部只看 worker）
        for arg in sys.argv[1:]:
            if arg != "--background":
                cmd_args.append(arg)
        cmd_args.append("--internal-worker")
        
        try:
            # 以追加模式打开日志文件
            with open(LOG_FILE, "a") as f:
                # 启动子进程，重定向输出到日志，并与当前终端分离
                proc = subprocess.Popen(cmd_args, stdout=f, stderr=f, start_new_session=True)
            
            # 等待一小段时间检查进程是否立即退出（例如参数错误或环境缺失）
            time.sleep(15)
            
            if proc.poll() is None:
                # 进程仍在运行，认为启动成功
                result = {
                    "status": "running",
                    "pid": proc.pid,
                    "log_file": LOG_FILE
                }
            else:
                # 进程已退出，说明启动失败
                error_message = "Process exited immediately with code {}".format(proc.returncode)
                try:
                    # 尝试从日志中读取最后几行错误信息
                    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as log_f:
                        # 读取最后 1KB 数据，避免读取整个大文件
                        log_f.seek(0, os.SEEK_END)
                        file_size = log_f.tell()
                        seek_pos = max(0, file_size - 2048)
                        log_f.seek(seek_pos)
                        lines = log_f.readlines()
                        # 如果最后一行是不完整的，可能忽略它，这里简单取最后几行非空行
                        valid_lines = [line.strip() for line in lines if line.strip()]
                        if valid_lines:
                            error_message = "\n".join(valid_lines[-5:]) # 取最后5行作为错误提示
                except Exception:
                    pass

                result = {
                    "status": "error",
                    "message": error_message,
                    "pid": proc.pid,
                    "exit_code": proc.returncode,
                    "log_file": LOG_FILE
                }

            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            error_result = {
                "status": "error",
                "message": str(e)
            }
            print(json.dumps(error_result, ensure_ascii=False, indent=2))
            sys.exit(1)
        return

    # 批量处理模式
    if args.batch:
        if not INPUT_DIR.exists():
            print(f"Error: Input directory {INPUT_DIR} does not exist")
            return

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Iterate over category folders (e.g., "1", "2", ...)
        categories = [d for d in INPUT_DIR.iterdir() if d.is_dir()]
        
        # Sort categories numerically if possible, else alphabetically
        try:
            categories.sort(key=lambda x: int(x.name))
        except ValueError:
            categories.sort(key=lambda x: x.name)

        total_success = 0
        total_fail = 0

        for category_dir in categories:
            category_name = category_dir.name
            category_output_dir = OUTPUT_DIR / category_name
            category_output_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"\nProcessing Category: {category_name}")
            
            subfolders = []
            for item in category_dir.iterdir():
                if item.is_dir():
                    try:
                        folder_num = int(item.name)
                        subfolders.append((folder_num, item))
                    except ValueError:
                        continue
            
            subfolders.sort(key=lambda x: x[0])
            print(f" Found {len(subfolders)} cases in {category_name}")
            
            cat_success = 0
            cat_fail = 0
            
            for folder_num, folder_path in subfolders:
                success, message = process_folder(folder_path, category_output_dir, model=args.model)
                print(f" {message}")
                
                if success:
                    cat_success += 1
                else:
                    cat_fail += 1
            
            total_success += cat_success
            total_fail += cat_fail
            
            print(f" Category Summary - Success: {cat_success}, Failed: {cat_fail}")

        print(f"\n=== Grand Total ===")
        print(f"Total Success: {total_success}")
        print(f"Total Failed: {total_fail}")
        print(f"Output saved to: {OUTPUT_DIR}")
        return

    # 单任务模式（默认）
    if not args.prompt or not args.output:
        parser.error("单任务模式必须指定--prompt和--output")
    



    folder = log_dir
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    
    # args.output treats as filename
    output_filename = os.path.basename(args.output)
    final_save_path = os.path.join(folder, output_filename)

    log_prefix = "[Background Worker]" if args.internal_worker else ""
    task_start_time = log_task_start(prefix=log_prefix)
    task_status = "failed"
    task_end_time = None
    try:
        video_path, task_end_time = seedance_edit(
            video_paths=args.reference_video,
            image_paths=args.reference_image,
            audio_paths=args.reference_audio,
            user_message=args.prompt,
            video_ratio=args.ratio,
            video_resolution=args.resolution,
            save_path=final_save_path,
            poll_interval=args.poll_interval,
            duration=args.duration,
            first_frame_path=args.first_image,
            last_frame_path=args.last_image,
            model=args.model,
            task_start_time=task_start_time,
            return_timing=True,
        )
        print(f"✅ 生成成功！")
        print(f"视频保存地址: {video_path}")
        task_status = "success"
    except Exception as e:
        import traceback; traceback.print_exc(); print(f"❌ 生成失败: {str(e)}")
        task_end_time = LAST_SEEDANCE_END_TIME or time.time()
        log_task_end(task_start_time, status=task_status, prefix=log_prefix, end_time=task_end_time)
        sys.exit(1)
    log_task_end(task_start_time, status=task_status, prefix=log_prefix, end_time=task_end_time)
    return

if __name__ == "__main__":
    main()
