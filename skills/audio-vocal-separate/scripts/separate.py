#!/usr/bin/env python3
"""audio-vocal-separate: 调 Demucs 把音频/视频里的人声和 BGM 分开。

约定: 用项目 uv venv 的 Python 跑:
    /Users/tanjie/project/claude_baseline/.venv/bin/python separate.py ...
"""
import argparse
import builtins
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_orig_print = builtins.print


def print(*args, **kwargs):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    _orig_print(f"[{ts}]", *args, **kwargs)


def resolve_output_dir(audio_path: str, session_key) -> str:
    get_out = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        "../../get-output-dir/scripts/get_output_dir.py",
    ))
    cmd = [sys.executable, get_out, "--subdir", "audios"]
    if session_key:
        cmd += ["--session-key", session_key]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    base = r.stdout.strip()
    if r.returncode != 0 or not base:
        detail = r.stderr.strip() or base
        raise RuntimeError(f"无法解析 session 输出目录: {detail}")
    name = Path(audio_path).stem
    return os.path.join(base, f"{name}_separated")


def detect_device(want: str) -> str:
    if want != "auto":
        return want
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def run_demucs(audio_path, out_root, model, two_stems, device, fmt, mp3_bitrate):
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", model,
        "-d", device,
        "-o", out_root,
    ]
    if two_stems == "vocals":
        cmd += ["--two-stems", "vocals"]
    if fmt == "mp3":
        cmd += ["--mp3", "--mp3-bitrate", str(mp3_bitrate)]
    cmd.append(audio_path)
    print(f"running demucs: model={model} device={device} two_stems={two_stems} fmt={fmt}")
    r = subprocess.run(cmd, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"demucs failed, rc={r.returncode}")


def collect_and_rename(out_root, model, stem, audio_path, fmt, two_stems):
    """Demucs 输出到 out_root/<model>/<stem>/{vocals,bass,drums,other,no_vocals}.{wav|mp3}
    我们抹平这一层,把 vocals/no_vocals 提到 out_root 顶层,no_vocals -> bgm。
    """
    src_dir = Path(out_root) / model / stem
    if not src_dir.is_dir():
        raise RuntimeError(f"demucs output dir not found: {src_dir}")
    ext = fmt
    moved = {}
    if two_stems == "vocals":
        mapping = {"vocals": "vocals", "no_vocals": "bgm"}
    else:
        mapping = {"vocals": "vocals", "drums": "drums",
                   "bass": "bass", "other": "other"}
    for src_name, dst_name in mapping.items():
        src = src_dir / f"{src_name}.{ext}"
        if src.is_file():
            dst = Path(out_root) / f"{dst_name}.{ext}"
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))
            moved[dst_name] = str(dst)
    # 清掉 demucs 留下的 <model>/<stem>/ 空目录
    try:
        shutil.rmtree(Path(out_root) / model)
    except Exception:
        pass
    return moved


def audio_duration(path: str):
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return float(out)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio_path", required=True)
    ap.add_argument("--model", default="htdemucs",
                    choices=["htdemucs", "htdemucs_ft", "mdx_extra", "htdemucs_6s"])
    ap.add_argument("--two_stems", default="vocals", choices=["vocals", "all"])
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    ap.add_argument("--format", default="wav", choices=["wav", "mp3"])
    ap.add_argument("--mp3_bitrate", type=int, default=192)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--session-key", dest="session_key", default=None, help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入session-key；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    args = ap.parse_args()

    audio_path = os.path.abspath(args.audio_path)
    if not os.path.isfile(audio_path):
        print(f"Error: not found: {audio_path}")
        sys.exit(1)

    out_dir = resolve_output_dir(audio_path, args.session_key)
    os.makedirs(out_dir, exist_ok=True)

    info_path = os.path.join(out_dir, "separate_info.json")
    vocals_path = os.path.join(out_dir, f"vocals.{args.format}")
    if not args.overwrite and os.path.isfile(vocals_path) and os.path.isfile(info_path):
        print(f"✅ skip (cached): {vocals_path}")
        with open(info_path) as f:
            _orig_print(f.read())
        return

    device = detect_device(args.device)
    print(f"input: {audio_path}  duration={audio_duration(audio_path)}s  device={device}")
    try:
        run_demucs(audio_path, out_dir, args.model, args.two_stems,
                   device, args.format, args.mp3_bitrate)
    except Exception as e:
        info = {"success": False, "error": str(e),
                "audio_path": audio_path, "device": device}
        with open(info_path, "w") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        print(f"❌ {e}")
        sys.exit(1)

    stem = Path(audio_path).stem
    moved = collect_and_rename(out_dir, args.model, stem,
                                audio_path, args.format, args.two_stems)

    info = {
        "success": True,
        "audio_path": audio_path,
        "model": args.model,
        "two_stems": args.two_stems,
        "device": device,
        "format": args.format,
        "duration_sec": audio_duration(audio_path),
        "outputs": moved,
    }
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"✅ done. outputs:")
    for k, v in moved.items():
        print(f"   {k}: {v}")
    print(f"   info: {info_path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"subprocess error: {e.stderr or e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
