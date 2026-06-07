"""grid-generate: 把视频按时间或按镜头抽帧,拼成带序号 + 时间戳标注的网格总览图。"""
import argparse
import builtins
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from typing import Optional

import cv2
from PIL import Image, ImageDraw, ImageFont

# 带时间戳的 print
_orig_print = builtins.print


def print(*args, **kwargs):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    _orig_print(f"[{ts}]", *args, **kwargs)


# ---------- 通用 ----------

def parse_time_to_sec(s: str) -> float:
    """支持 'mm:ss' / 'mm:ss.x' / '12.5' / '12'"""
    s = s.strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(s)


def parse_time_range(rng: str):
    a, b = rng.split("-", 1)
    return parse_time_to_sec(a), parse_time_to_sec(b)


def fmt_mmss(sec: float) -> str:
    m = int(sec) // 60
    s = int(sec) % 60
    return f"{m:02d}:{s:02d}"


def resolve_output_path(video_path: str, mode: str, session_key: Optional[str]) -> str:
    # 调 get-output-dir 拿 session 输出目录
    script_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        "../../get-output-dir/scripts/get_output_dir.py",
    ))
    cmd = [sys.executable, script_path, "--subdir", "images"]
    if session_key:
        cmd += ["--session-key", session_key]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out_dir = result.stdout.strip()
    if result.returncode != 0 or not out_dir:
        detail = result.stderr.strip() or out_dir
        raise RuntimeError(f"无法解析输出目录: {detail}")
    name = os.path.splitext(os.path.basename(video_path))[0]
    suffix = "grid_overview" if mode == "by-time" else "shot_grid"
    return os.path.join(out_dir, f"{name}_{suffix}.jpg")


# ---------- 抽帧 ----------

def open_video(video_path: str):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total / fps if fps > 0 else 0.0
    return cap, fps, total, w, h, duration


def grab_frame_at(cap, t_sec: float, fps: float, total: int):
    target = min(int(t_sec * fps), max(total - 1, 0))
    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
    ok, frame = cap.read()
    if not ok:
        # 退到下一可读帧
        for _ in range(3):
            ok, frame = cap.read()
            if ok:
                break
    return frame if ok else None, target


# ---------- 镜头切分 ----------

def detect_shots(video_path: str):
    """用 PySceneDetect 检测镜头,返回 [{shot_id, start_sec, end_sec}]"""
    from scenedetect import detect, AdaptiveDetector
    scenes = detect(video_path, AdaptiveDetector())
    out = []
    for i, (s, e) in enumerate(scenes, start=1):
        out.append({
            "shot_id": f"shot_{i:02d}",
            "start_sec": s.get_seconds(),
            "end_sec": e.get_seconds(),
        })
    return out


def load_shots_json(path: str):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    norm = []
    for i, item in enumerate(data, start=1):
        sid = item.get("shot_id") or item.get("id") or f"shot_{i:02d}"
        s = item.get("start_sec", item.get("start"))
        e = item.get("end_sec", item.get("end"))
        if s is None or e is None:
            raise ValueError(f"shots_json item missing start/end: {item}")
        norm.append({"shot_id": sid, "start_sec": float(s), "end_sec": float(e)})
    return norm


# ---------- 采样点构造 ----------

def build_samples_by_time(duration: float, interval: float,
                           time_range, max_cells: int):
    t_lo, t_hi = (time_range if time_range else (0.0, duration))
    t_hi = min(t_hi, duration)
    if t_hi <= t_lo:
        return []
    pts = []
    t = t_lo
    while t < t_hi - 1e-3:
        pts.append(t)
        t += interval
    if not pts:
        pts.append(t_lo)
    if len(pts) > max_cells:
        idxs = [round(i * (len(pts) - 1) / (max_cells - 1)) for i in range(max_cells)]
        pts = [pts[i] for i in idxs]
    return [{"t_sec": p, "shot_id": None} for p in pts]


def build_samples_by_shot(shots, frame: str, time_range, max_cells: int):
    if time_range:
        t_lo, t_hi = time_range
        shots = [s for s in shots if s["end_sec"] > t_lo and s["start_sec"] < t_hi]
    samples = []
    for sh in shots:
        s, e = sh["start_sec"], sh["end_sec"]
        if frame == "first":
            t = s + 0.05
        elif frame == "last":
            t = max(e - 0.05, s)
        else:
            t = (s + e) / 2.0
        samples.append({"t_sec": t, "shot_id": sh["shot_id"]})
    if len(samples) > max_cells:
        idxs = [round(i * (len(samples) - 1) / (max_cells - 1)) for i in range(max_cells)]
        samples = [samples[i] for i in idxs]
    return samples


# ---------- 网格拼图 ----------

def get_font(size: int):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",  # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # linux
        "/Library/Fonts/Arial.ttf",
    ]
    for f in candidates:
        if os.path.isfile(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
    return ImageFont.load_default()


def annotate_cell(img: Image.Image, idx_label: str, time_label: str,
                  shot_label: Optional[str]):
    """左上 [N] + 左下 mm:ss (有 shot 时拼 'shot_03 00:08')"""
    draw = ImageDraw.Draw(img, "RGBA")
    W, H = img.size

    # 字体大小按 cell 高度
    fs_top = max(12, int(H * 0.10))
    fs_bot = max(11, int(H * 0.09))
    font_top = get_font(fs_top)
    font_bot = get_font(fs_bot)

    def draw_label(text, font, anchor):
        # anchor: "tl" or "bl"
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            tw, th = draw.textsize(text, font=font)
        pad_x, pad_y = 4, 2
        if anchor == "tl":
            x, y = 4, 4
        else:  # bl
            x, y = 4, H - th - pad_y * 2 - 4
        draw.rectangle([x, y, x + tw + pad_x * 2, y + th + pad_y * 2],
                       fill=(0, 0, 0, 180))
        draw.text((x + pad_x, y + pad_y), text, fill=(255, 255, 255, 255), font=font)

    draw_label(idx_label, font_top, "tl")
    bot = f"{shot_label} {time_label}" if shot_label else time_label
    draw_label(bot, font_bot, "bl")


def build_grid(video_path: str, samples, cols: int, cell_w: int,
               padding: int, label: bool):
    cap, fps, total, vw, vh, duration = open_video(video_path)
    if not samples:
        cap.release()
        raise RuntimeError("没有可用的采样点 (检查 interval / time_range / 视频时长)")

    # cell 高度按视频宽高比
    cell_h = max(1, int(cell_w * vh / max(vw, 1)))

    n = len(samples)
    rows = math.ceil(n / cols)
    canvas_w = cols * cell_w + (cols + 1) * padding
    canvas_h = rows * cell_h + (rows + 1) * padding
    canvas = Image.new("RGB", (canvas_w, canvas_h), (20, 20, 20))

    cells_meta = []
    for i, samp in enumerate(samples):
        idx = i + 1
        t = samp["t_sec"]
        frame, frame_idx = grab_frame_at(cap, t, fps, total)
        if frame is None:
            # 黑格占位
            tile = Image.new("RGB", (cell_w, cell_h), (0, 0, 0))
        else:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            tile = Image.fromarray(frame_rgb).resize((cell_w, cell_h),
                                                     Image.LANCZOS)
        if label:
            annotate_cell(tile, f"[{idx}]", fmt_mmss(t), samp.get("shot_id"))

        r, c = divmod(i, cols)
        x = padding + c * (cell_w + padding)
        y = padding + r * (cell_h + padding)
        canvas.paste(tile, (x, y))

        cells_meta.append({
            "idx": idx,
            "t_sec": round(t, 3),
            "t_label": fmt_mmss(t),
            "shot_id": samp.get("shot_id"),
            "frame_idx": frame_idx,
        })

    cap.release()
    return canvas, cells_meta, cell_h, rows


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="grid-generate: 视频网格总览图生成")
    ap.add_argument("--video_path", required=True)
    ap.add_argument("--mode", choices=["by-time", "by-shot"], default="by-time")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--frame", choices=["first", "middle", "last"], default="first")
    ap.add_argument("--shots_json", default=None)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--cell_width", type=int, default=384)
    ap.add_argument("--padding", type=int, default=4)
    ap.add_argument("--max_cells", type=int, default=60)
    ap.add_argument("--time_range", default=None,
                    help='例 "00:10-00:50" 或 "10-50"')
    ap.add_argument("--no_label", action="store_true")
    ap.add_argument("--quality", type=int, default=92)
    ap.add_argument("--session-key", dest="session_key", default=None, help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入session-key；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    args = ap.parse_args()

    video_path = os.path.abspath(args.video_path)
    if not os.path.isfile(video_path):
        print(f"Error: video not found: {video_path}")
        sys.exit(1)

    output_path = resolve_output_path(video_path, args.mode, args.session_key)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    time_range = parse_time_range(args.time_range) if args.time_range else None

    # 取视频时长 (by-time 需要)
    cap0, _, _, _, _, duration = open_video(video_path)
    cap0.release()

    if args.mode == "by-time":
        samples = build_samples_by_time(duration, args.interval,
                                         time_range, args.max_cells)
    else:
        if args.shots_json:
            shots = load_shots_json(args.shots_json)
        else:
            print("检测镜头 (PySceneDetect)...")
            shots = detect_shots(video_path)
            print(f"检测到 {len(shots)} 个镜头")
        samples = build_samples_by_shot(shots, args.frame, time_range,
                                         args.max_cells)

    print(f"采样 {len(samples)} 帧, cols={args.cols}, cell_width={args.cell_width}")

    canvas, cells_meta, cell_h, rows = build_grid(
        video_path, samples, args.cols, args.cell_width,
        args.padding, label=not args.no_label,
    )

    # 写图 + sidecar
    canvas.save(output_path, "JPEG", quality=args.quality)
    sidecar_path = output_path + ".json"
    sidecar = {
        "video_path": video_path,
        "mode": args.mode,
        "interval": args.interval if args.mode == "by-time" else None,
        "frame": args.frame if args.mode == "by-shot" else None,
        "cols": args.cols,
        "rows": rows,
        "cell_width": args.cell_width,
        "cell_height": cell_h,
        "total_cells": len(cells_meta),
        "time_range": list(time_range) if time_range else None,
        "cells": cells_meta,
    }
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)

    print(f"✅ 网格图: {output_path}")
    print(f"✅ sidecar: {sidecar_path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"Error: subprocess failed: {e.stderr or e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error: {e}")
        sys.exit(1)
