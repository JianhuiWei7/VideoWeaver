import argparse
import os
from PIL import Image

def main():
    parser = argparse.ArgumentParser(description="Change an image's resolution.")
    parser.add_argument("--image_path", type=str, required=True, help="Path to the input image.")
    parser.add_argument("--resolution", type=str, required=True, help="Target resolution, e.g., '1920x1080'.")
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

    image_path = args.image_path
    resolution_str = args.resolution

    if not os.path.exists(image_path):
        print(f"Error: Image file not found at {image_path}")
        exit(1)

    try:
        target_width, target_height = map(int, resolution_str.lower().split('x'))
    except ValueError:
        print("Error: Invalid resolution format. Please use 'WIDTHxHEIGHT', e.g., '1920x1080'.")
        exit(1)

    try:
        img = Image.open(image_path)
    except Exception as e:
        print(f"Error opening image: {e}")
        exit(1)

    # Resize image to the target resolution
    try:
        # ANTIALIAS is deprecated in newer PIL, using LANCZOS
        img_resized = img.resize((target_width, target_height), Image.LANCZOS)
    except AttributeError:
        # Fallback for older PIL versions
        img_resized = img.resize((target_width, target_height), Image.ANTIALIAS)
    except Exception as e:
        print(f"Error resizing image: {e}")
        exit(1)

    # Generate output path
    base_name = os.path.basename(image_path)
    name_without_ext, ext = os.path.splitext(base_name)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{name_without_ext}_{resolution_str}{ext}")

    try:
        img_resized.save(output_path)
        print(output_path) # Output exactly the new saved image path
    except Exception as e:
        print(f"Error saving resized image: {e}")
        exit(1)

if __name__ == "__main__":
    main()
