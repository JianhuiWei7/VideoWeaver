import argparse
import os
import subprocess
import sys

def change_fps(input_path, target_fps, output_dir):
    if not os.path.exists(input_path):
        print(f"错误: 输入视频 '{input_path}' 不存在。")
        sys.exit(1)

    # 解析文件路径
    filename, ext = os.path.splitext(os.path.basename(input_path))
    
    # 构造输出文件名: _fps_xxx.extension
    output_filename = f"{filename}_fps_{target_fps}{ext}"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)

    print(f"正在将 {input_path} 的帧率转换为 {target_fps} FPS...")
    print(f"输出视频将保存在: {output_path}")

    # 使用 ffmpeg 更改帧率
    command = [
        'ffmpeg',
        '-y',  # 覆盖已存在的文件
        '-i', input_path,
        '-filter:v', f'fps=fps={target_fps}',
        output_path
    ]

    try:
        subprocess.run(command, check=True)
        print(f"\n转换成功！视频已保存至: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"转换过程中出错: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("错误: 找不到 ffmpeg，请确保系统已安装 ffmpeg 并配置在环境变量中。")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修改视频帧率(FPS)并保存为新文件")
    parser.add_argument("input_video", help="输入视频文件的路径")
    parser.add_argument("target_fps", type=int, help="目标帧率 (例如: 30, 60)")
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
        
    change_fps(args.input_video, args.target_fps, output_dir)
