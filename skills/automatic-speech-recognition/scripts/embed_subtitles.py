import argparse
import subprocess
import os
import sys

def escape_path_for_ffmpeg(path):
    """
    处理 ffmpeg subtitles 滤镜的路径转义
    将特殊字符如反斜杠、冒号、单引号和逗号进行转义
    """
    return path.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'").replace(',', '\\,')

def main():
    parser = argparse.ArgumentParser(description="自动将 SRT 字幕硬编码嵌入到视频文件中")
    parser.add_argument("--session-key", type=str, help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    parser.add_argument("--video", required=True, help="输入的视频文件路径 (如 .mp4)")
    parser.add_argument("--srt", required=True, help="输入的 SRT 字幕文件路径")
    parser.add_argument("--output", help="输出的视频文件名（将固定保存在当前会话对应的目录下）。如果不指定，将生成带有 '_with_subtitles' 后缀的文件")
    
    args = parser.parse_args()
    
    # Get SESSION_ID folder
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "asr"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        folder = result.stdout.strip()
        if result.returncode != 0 or not folder or "Error" in folder or "Warning" in folder:
            detail = result.stderr.strip() or folder
            raise ValueError(f"Could not resolve output directory: {detail}")
    except Exception as e:
        print(f"Warning: Could not resolve output directory: {e}")
        return

    video_path = os.path.abspath(args.video)
    srt_path = os.path.abspath(args.srt)
    
    if not os.path.exists(video_path):
        sys.exit(f"❌ 错误: 找不到视频文件: {video_path}")
    if not os.path.exists(srt_path):
        sys.exit(f"❌ 错误: 找不到字幕文件: {srt_path}")
        
    base = os.path.splitext(os.path.basename(video_path))[0]
    ext = os.path.splitext(video_path)[1]
    
    if not args.output:
        output_path = os.path.join(folder, f"{base}_with_subtitles{ext}")
    else:
        # 只取文件名，确保输出固定在 session 文件夹
        filename = os.path.basename(args.output)
        output_path = os.path.join(folder, filename)
        
    print(f"⏳ 开始将字幕嵌入视频...")
    print(f"🎬 视频: {video_path}")
    print(f"📝 字幕: {srt_path}")
    print(f"💾 输出: {output_path}")
    
    escaped_srt = escape_path_for_ffmpeg(srt_path)
    
    # 构造 ffmpeg 命令，-y 表示自动覆盖已存在文件
    command = [
        "ffmpeg",
        "-y", 
        "-i", video_path,
        "-vf", f"subtitles={escaped_srt}",
        output_path
    ]
    
    try:
        # 执行命令并捕获输出
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"\n✅ 成功！带字幕的视频已保存至: {output_path}")
        else:
            print(f"\n❌ 嵌入失败，FFmpeg 报错信息:\n{result.stderr}")
    except FileNotFoundError:
        print("\n❌ 错误: 系统中未找到 FFmpeg 工具。请确保已经安装 ffmpeg（例如通过 brew install ffmpeg）。")

if __name__ == "__main__":
    main()
