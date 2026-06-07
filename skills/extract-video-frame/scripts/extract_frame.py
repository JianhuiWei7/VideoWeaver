import cv2
import argparse
from typing import Union, Optional
from pathlib import Path
import os
import builtins
from datetime import datetime

# 定义新的print函数，覆盖内置的print，带上时间戳
original_print = builtins.print
def print(*args, **kwargs):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    original_print(f"[{current_time}]", *args, **kwargs)

def extract_frame_from_video(
    video_path: str,
    output_dir: str,
    output_image_path: Optional[str] = None,
    frame_position: Union[int, str, float] = "last",
    jpeg_quality: int = 95
) -> Optional[str]:
    """改进的视频帧提取函数"""
    
    # 将字符串形式的数字转换为对应类型
    if isinstance(frame_position, str):
        if frame_position.replace('.', '', 1).isdigit():
            if '.' in frame_position:
                frame_position = float(frame_position)
            else:
                frame_position = int(frame_position)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"无法打开视频文件: {video_path}")
        return None

    # 获取视频信息
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if total_frames == 0:
        print("视频帧数为0，无法提取")
        cap.release()
        return None
    
    # 确定目标帧
    if isinstance(frame_position, str):
        pos = frame_position.lower()
        if pos == "last":
            target = max(total_frames - 1, 0)
        elif pos == "middle":
            target = total_frames // 2
        else:  # "first" 或其他
            target = 0
    elif isinstance(frame_position, float):
        # 作为时间(秒)处理
        target = min(int(frame_position * fps), total_frames - 1)
    else:
        # 作为帧号处理
        target = min(int(frame_position), total_frames - 1)
    
    # 尝试精确跳帧（对于非关键帧可能不准确）
    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
    
    # 尝试读取多几次确保获取清晰帧
    ret = False
    frame = None
    for _ in range(3):  # 尝试3次
        ret, frame = cap.read()
        if ret:
            break
    
    cap.release()
    
    if not ret or frame is None:
        print(f"读取帧失败，目标帧: {target}")
        return None
        
    # 如果未提供输出路径，则自动生成
    if not output_image_path:
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        
        # 根据请求的位置生成后缀
        if isinstance(frame_position, str) and frame_position.lower() in ["first", "last", "middle"]:
            suffix = f"_{frame_position.lower()}"
        else:
            suffix = f"_frame_{target}"
            
        output_image_path = os.path.join(output_dir, f"{video_name}{suffix}.jpeg")
    
    # 确保输出目录存在
    output_dir = os.path.dirname(output_image_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
    # 以指定质量保存
    if isinstance(output_image_path, Path):
        output_image_path = str(output_image_path)
        
    if output_image_path.lower().endswith('.jpg') or output_image_path.lower().endswith('.jpeg'):
        cv2.imwrite(output_image_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    else:
        cv2.imwrite(output_image_path, frame)
    
    print(f"✅ 帧已保存至: {output_image_path} (目标帧位置: {target} / 总帧数: {total_frames})")
    return output_image_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract a specific frame from a video.")
    parser.add_argument('--video_path', type=str, required=True, help='Path to the input video file.')
    parser.add_argument('--output_path', type=str, default=None, help='Path to save the extracted image. (Optional)')
    parser.add_argument('--position', type=str, default="last", help='Frame position: "first", "middle", "last", a frame number (int), or time in seconds (float).')
    parser.add_argument('--quality', type=int, default=95, help='JPEG quality (0-100), default is 95.')
    parser.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    
    args = parser.parse_args()
    
    try:
        import sys
        import subprocess
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "images"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output_dir = result.stdout.strip()
        if result.returncode != 0 or not output_dir or "Error" in output_dir or "Warning" in output_dir:
            detail = result.stderr.strip() or output_dir
            print(f"Error: Could not resolve output directory\n{detail}")
            sys.exit(1)
    except Exception as e:
        print(f"Error: Could not resolve output directory: {e}")
        sys.exit(1)
    
    result = extract_frame_from_video(
        video_path=args.video_path,
        output_dir=output_dir,
        output_image_path=args.output_path,
        frame_position=args.position,
        jpeg_quality=args.quality
    )
    
    if not result:
        sys.exit(1)
