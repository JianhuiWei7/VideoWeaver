import argparse
import os
import subprocess
import sys
from PIL import Image

MIN_SIDE = 100


def main():
    parser = argparse.ArgumentParser(description="Split an image into a 2x2 grid (4 sub-images).")
    parser.add_argument("--image_path", type=str, required=True, help="Path to the input image.")
    parser.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    args = parser.parse_args()

    try:
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
    if not os.path.exists(image_path):
        print(f"Error: Image file not found at {image_path}")
        sys.exit(1)

    try:
        img = Image.open(image_path)
    except Exception as e:
        print(f"Error opening image: {e}")
        sys.exit(1)

    width, height = img.size
    if width < MIN_SIDE or height < MIN_SIDE:
        print(f"Error: Image too small ({width}x{height}). Minimum required is {MIN_SIDE}x{MIN_SIDE}.")
        sys.exit(1)

    mid_w = width // 2
    mid_h = height // 2

    # 1=top-left, 2=top-right, 3=bottom-left, 4=bottom-right
    boxes = [
        (0, 0, mid_w, mid_h),
        (mid_w, 0, width, mid_h),
        (0, mid_h, mid_w, height),
        (mid_w, mid_h, width, height),
    ]

    base_name = os.path.basename(image_path)
    name_without_ext, ext = os.path.splitext(base_name)
    os.makedirs(output_dir, exist_ok=True)

    output_paths = []
    try:
        for i, box in enumerate(boxes, start=1):
            sub = img.crop(box)
            out_path = os.path.join(output_dir, f"{name_without_ext}_grid_{i}{ext}")
            sub.save(out_path)
            output_paths.append(out_path)
    except Exception as e:
        print(f"Error splitting/saving image: {e}")
        sys.exit(1)

    for p in output_paths:
        print(p)


if __name__ == "__main__":
    main()
