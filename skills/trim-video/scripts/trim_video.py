import os
import argparse
from pathlib import Path
from moviepy import VideoFileClip
import builtins
from datetime import datetime

# 定义新的print函数，覆盖内置的print，带上时间戳
original_print = builtins.print
def print(*args, **kwargs):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    original_print(f"[{current_time}]", *args, **kwargs)

def trim_video(input_path, start_time, end_time, output_dir):
    """
    剪辑视频的函数
    
    参数:
    input_path (str): 输入视频文件的路径
    start_time (float): 剪辑的起始时间（秒）
    end_time (float): 剪辑的终止时间（秒）
    output_dir (str): 输出目录路径
    
    返回:
    bool: 剪辑成功返回True，失败返回False
    """
    try:
        # 检查输入文件是否存在
        if isinstance(input_path, Path):
            input_path = str(input_path)
        if not os.path.exists(input_path):
            print(f"❌ 错误: 输入文件 '{input_path}' 不存在")
            return False
        
        # 自动生成输出路径
        base_name = os.path.basename(input_path)
        name_without_ext, ext = os.path.splitext(base_name)
        output_path = os.path.join(output_dir, f"{name_without_ext}_trimmed_{start_time}_{end_time}{ext}")
        
        # 确保输出目录存在
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        # 检查时间参数是否有效
        if start_time < 0 or end_time <= start_time:
            print(f"❌ 错误: 起始时间和终止时间参数无效 (start={start_time}, end={end_time})")
            return False
        
        print(f"🎬 开始剪辑视频: {input_path}")
        print(f"⏱️ 剪辑范围: {start_time}s - {end_time}s")
        
        # 加载视频文件
        with VideoFileClip(input_path) as video:
            # 检查结束时间是否超过视频时长
            if end_time > video.duration:
                print(f"⚠️ 警告: 终止时间超过视频时长，将使用视频结束时间 {video.duration:.2f}s")
                end_time = video.duration
            
            if start_time >= video.duration:
                print(f"❌ 错误: 起始时间 ({start_time}s) 超过视频时长 ({video.duration:.2f}s)")
                return False

            # 剪辑视频
            # 注意：moviepy v2 使用 subclipped
            trimmed_video = video.subclipped(start_time, end_time)
            
            # 保存剪辑后的视频
            # 默认启用音频 (audio=True) 并使用 aac 编码，以保证兼容性
            trimmed_video.write_videofile(
                output_path,
                codec="libx264",  # 使用H.264编码
                audio_codec="aac", 
                bitrate="5000k",  # 视频比特率，可根据需要调整
                logger=None # 禁用moviepy自带的logger，使用我们自己的日志输出或者进度条
            )
        
        print(f"✅ Video trimmed successfully: {output_path}")
        return True
    
    except Exception as e:
        print(f"❌ An error occurred during video trimming: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(description="Trim video based on start and end time.")
    parser.add_argument("--input_path", required=True, help="Path to the input video file")
    parser.add_argument("--start_time", type=float, required=True, help="Start time in seconds")
    parser.add_argument("--end_time", type=float, required=True, help="End time in seconds")
    parser.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    
    args = parser.parse_args()
    
    try:
        import sys
        import subprocess
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
    
    input_path = args.input_path
    start_time = args.start_time
    end_time = args.end_time
    
    success = trim_video(input_path, start_time, end_time, output_dir)
    
    if not success:
        import sys
        sys.exit(1)

if __name__ == "__main__":
    main()
