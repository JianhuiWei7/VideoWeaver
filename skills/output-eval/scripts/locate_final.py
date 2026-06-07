"""定位产物目录中的 final.mp4。

规则:
  1) 文件名含 final/merged/output (不区分大小写) → 优先
  2) 否则取时长最长且接近 target_duration (±10%) 的 mp4
  3) 若仍多于 1 个,按修改时间最新

用法:
    python locate_final.py --dir <产物目录> [--target-duration 60]
输出:
    JSON: {"final": "<path>", "candidates": [{"path":..,"duration":..,"mtime":..}, ...]}
"""
from __future__ import annotations
import argparse
import json
import pathlib
import re
import subprocess
import sys


PREFER = re.compile(r"(final|merged|output)", re.IGNORECASE)


def ffprobe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=20)
        return float(r.stdout.strip())
    except Exception:
        return -1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--target-duration", type=float, default=None)
    args = ap.parse_args()

    root = pathlib.Path(args.dir).expanduser().resolve()
    if not root.exists():
        print(json.dumps({"error": f"dir not found: {root}"}))
        sys.exit(1)

    mp4s = list(root.rglob("*.mp4"))
    cands = []
    for p in mp4s:
        cands.append({
            "path": str(p),
            "duration": ffprobe_duration(str(p)),
            "mtime": p.stat().st_mtime,
            "preferred_name": bool(PREFER.search(p.name)),
        })

    if not cands:
        print(json.dumps({"final": None, "candidates": []}))
        return

    # 优先按名字
    by_name = [c for c in cands if c["preferred_name"] and c["duration"] > 0]
    if by_name:
        final = max(by_name, key=lambda c: (c["mtime"], c["duration"]))
    elif args.target_duration:
        # 按时长贴近 target
        ok = [c for c in cands if c["duration"] > 0 and
              abs(c["duration"] - args.target_duration) / args.target_duration < 0.10]
        if ok:
            final = max(ok, key=lambda c: c["duration"])
        else:
            final = max([c for c in cands if c["duration"] > 0], key=lambda c: c["duration"])
    else:
        final = max([c for c in cands if c["duration"] > 0] or cands,
                    key=lambda c: c.get("duration", 0))

    print(json.dumps({"final": final["path"], "candidates": cands},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()