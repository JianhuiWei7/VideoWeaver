"""⚠️ DEPRECATED — 请改用 `grid-generate` skill。

新调用方式 (产出带 sidecar JSON):
    python ../../grid-generate/scripts/grid_generate.py \
        --video_path <path> --mode by-time --interval 2.0 \
        --cols 6 --output_path grid.jpg

本文件仅作为历史 fallback 保留,不再维护,新代码请勿引用。

原用法 (保留以便老调用方知道对应关系):
    python build_grid.py --video <path> --interval 2.0 --out grid.jpg [--tile 384] [--cols 0]

参数:
    --interval  抽帧间隔秒数 (默认 2.0)
    --tile      单格短边像素 (默认 384,保持原比例)
    --cols      网格列数,0=自动按 sqrt
    --max-frames 最多抽多少帧 (默认 36,超出会动态拉大间隔)
"""
from __future__ import annotations
import argparse
import math
import subprocess
import tempfile
from pathlib import Path

import cv2  # opencv-python


def ffprobe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=20)
    return float(r.stdout.strip())


def extract_frame(video: str, t: float, out_path: str):
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
         "-i", video, "-frames:v", "1", "-q:v", "2", out_path],
        check=True)


def fmt_ts(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tile", type=int, default=384)
    ap.add_argument("--cols", type=int, default=0)
    ap.add_argument("--max-frames", type=int, default=36)
    args = ap.parse_args()

    dur = ffprobe_duration(args.video)
    interval = args.interval
    n = int(dur / interval) + 1
    if n > args.max_frames:
        interval = dur / args.max_frames
        n = args.max_frames

    cols = args.cols or max(1, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / cols)

    with tempfile.TemporaryDirectory() as td:
        tiles = []
        for i in range(n):
            t = i * interval
            fp = f"{td}/f_{i:03d}.jpg"
            try:
                extract_frame(args.video, t, fp)
            except subprocess.CalledProcessError:
                continue
            img = cv2.imread(fp)
            if img is None:
                continue
            # resize 保持比例,短边=tile
            h, w = img.shape[:2]
            scale = args.tile / min(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
            # crop center 到 (tile, tile) 让网格对齐
            h, w = img.shape[:2]
            y0 = (h - args.tile) // 2
            x0 = (w - args.tile) // 2
            img = img[max(0, y0):y0 + args.tile, max(0, x0):x0 + args.tile]
            # 叠字
            label = f"#{i+1:02d} {fmt_ts(t)}"
            cv2.rectangle(img, (4, args.tile - 28), (160, args.tile - 4), (0, 0, 0), -1)
            cv2.putText(img, label, (8, args.tile - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(img)

        if not tiles:
            raise RuntimeError("no frames extracted")

        # 拼网格 (黑色 gutter 4px)
        gutter = 4
        canvas_h = rows * args.tile + (rows + 1) * gutter
        canvas_w = cols * args.tile + (cols + 1) * gutter
        canvas = 0 * cv2.imread(tiles[0:1][0].dtype.name + "_dummy", 1) if False else None
        import numpy as np
        canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
        for idx, tile in enumerate(tiles):
            r, c = divmod(idx, cols)
            y = gutter + r * (args.tile + gutter)
            x = gutter + c * (args.tile + gutter)
            canvas[y:y + args.tile, x:x + args.tile] = tile

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(args.out, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"saved {args.out}  ({n} frames, {cols}x{rows} grid, tile={args.tile}px)")


if __name__ == "__main__":
    main()