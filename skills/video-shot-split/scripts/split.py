import os
import subprocess
import csv
import tempfile
import shutil
import argparse
import json

def video_shot_count(video_path, output_dir=None, split=False):
    # Ensure the video path is absolute
    video_path = os.path.abspath(video_path)
    
    # Check if the video file exists
    if not os.path.exists(video_path):
        print(f"Error: Video file not found at {video_path}")
        return None
    
    # 标记是否使用临时文件夹
    use_temp_dir = False
    
    # 处理 output_dir 参数逻辑
    if split:
        # split=True 时必须传入有效的 output_dir
        if output_dir is None:
            print("Error: When split=True, a valid output_dir must be provided")
            return None, [] # 返回空列表符合需求
        else:
            os.makedirs(output_dir, exist_ok=True)
    else:
        # split=False 时，未传入 output_dir 则生成临时文件夹
        if output_dir is None:
            # 基于视频路径生成临时文件夹（在视频同级目录）
            video_dir = os.path.dirname(video_path)
            temp_dir_prefix = f"temp_scenedetect_{os.path.splitext(os.path.basename(video_path))[0]}_"
            output_dir = tempfile.mkdtemp(prefix=temp_dir_prefix, dir=video_dir)
            use_temp_dir = True
        else:
            os.makedirs(output_dir, exist_ok=True)
    
    # 构建 scenedetect 命令
    command = [
        'scenedetect',
        '-i',
        video_path,
        '-o',
        output_dir,
        'list-scenes',
        'detect-adaptive',
    ]
    if split:
        command.append('split-video')
    
    try:
        # 执行 scenedetect 命令
        subprocess.run(command, capture_output=True, text=True, check=True)
        
        if split:
            # 列出分割后的视频文件
            # 完整的视频路径
            video_files = sorted([
                os.path.join(output_dir, f) 
                for f in os.listdir(output_dir) 
                # 使用 endswith 匹配 Scene-开头且.mp4结尾的模式
                if f.endswith('.mp4') and 'Scene-' in f
            ])
            return len(video_files), video_files
        else:
            # 读取 CSV 文件统计镜头数
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            csv_file = f"{output_dir}/{base_name}-Scenes.csv"
            
            if os.path.exists(csv_file):
                with open(csv_file, 'r') as f:
                    reader = csv.reader(f)
                    # 跳过表头，统计行数
                    scene_count = sum(1 for row in reader) - 2
            else:
                print(f"Error: Scene CSV file not found: {csv_file}")
                scene_count = 0
            
            # 如果使用了临时文件夹，执行删除操作
            if use_temp_dir:
                try:
                    shutil.rmtree(output_dir)
                    print(f"Temporary directory {output_dir} deleted successfully")
                except Exception as e:
                    print(f"Warning: Failed to delete temporary directory {output_dir}: {e}")
            else:
                print(f"Shot information saved to: {csv_file}")
            
            print(f"Total {scene_count} Shots Detected for: {video_path}")
            return scene_count
        
    except subprocess.CalledProcessError as e:
        print(f"Error executing scenedetect command: {e}")
        print(f"Stderr: {e.stderr}")
        # 出错时也删除临时文件夹
        if use_temp_dir and os.path.exists(output_dir):
            try:
                shutil.rmtree(output_dir)
            except:
                pass
        return None
    except FileNotFoundError:
        print("Error: 'scenedetect' command not found. Make sure PySceneDetect is installed and in your PATH.")
        # 出错时也删除临时文件夹
        if use_temp_dir and os.path.exists(output_dir):
            try:
                shutil.rmtree(output_dir)
            except:
                pass
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Video shot split and count tool')
    parser.add_argument('--video_path', type=str, required=True, help='Absolute path to the video file')
    parser.add_argument('--split', type=lambda x: x.lower() == 'true', default=True, help='Whether to split video into scenes, default True')
    parser.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    args = parser.parse_args()
    
    try:
        import sys
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

    result = video_shot_count(args.video_path, output_dir, args.split)
    if args.split:
        if result is None:
            print("Error processing video")
        else:
            scene_count, video_files = result
            print(f"Total scenes detected: {scene_count}")
            print("Split video files:")
            for f in video_files:
                print(f"  - {f}")
    else:
        if result is None:
            print("Error processing video")
        else:
            print(f"Total scenes detected: {result}")
