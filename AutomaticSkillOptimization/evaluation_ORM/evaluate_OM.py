"""Batch output-eval runner —— Claude Code + DeepSeek 适配版。

对一个 generate 阶段的产物目录 (result_dir) 下所有 case,
通过 Claude Code CLI 并发调用 output-eval skill 进行 LLM-as-judge 打分。

每个 case 流程:
  1. 解析 case 目录名 `{category}_{case_id}_{english}_{uuid}` → dataset/{category}/{case_id}/rubric.json
  2. 拷贝 rubric.json → output_dir/{case_name}/evals_human/rubric.json
  3. 调 claude_chat,prompt 让模型用 output-eval skill 评估:
       - 产物目录 = result_dir/{case_name}/  (含 final.mp4 / shots / 等)
       - rubric.json 路径 = output_dir/{case_name}/evals_human/rubric.json
  4. skill 就地回写 rubric.json 的 `分数` / `反馈`,
     并产出同目录 sidecar `rubric_eval_detail.json`。

用法:
  python AutomaticSkillOptimization/evaluation_ORM/evaluate_ORM.py
"""
import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from AutomaticSkillOptimization.prompts import OUTPUT_EVAL_PROMPT_TEMPLATE
from AutomaticSkillOptimization.args import CLAUDE_WORKSPACE, OUTPUT_DIR as ASO_OUTPUT_DIR
from AutomaticSkillOptimization.inference_ClaudeCode.claude_cli_tools import claude_chat, claude_session_jsonl_path
from AutomaticSkillOptimization.utils import parse_result_dir_name

try:
    from json_repair import loads as repair_json_loads
except ImportError:
    repair_json_loads = None

try:
    from tqdm.asyncio import tqdm as tqdm_asyncio
    from tqdm import tqdm as _tqdm_sync  # 用于 .write() 路由
except ImportError:
    tqdm_asyncio = None
    _tqdm_sync = None


# tqdm 活跃时把日志走 tqdm.write,避免被滚动盖掉进度条;否则降级为 print
def tprint(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    if _tqdm_sync is not None:
        _tqdm_sync.write(msg)
    else:
        print(msg, **kwargs)

DEFAULT_RESULT_DIR = "OC_Seed_expert_skills/0510_2333_expert_res_on_skills_FINAL_EXPERT_SKILLS"
DEFAULT_DATASET_DIR = "dataset"


def default_output_dir(result_dir: str) -> str:
    return f"{result_dir.rstrip('/')}_output_eval"


def parse_bool(value: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "t"}:
        return True
    if normalized in {"false", "0", "no", "n", "f"}:
        return False
    raise argparse.ArgumentTypeError("expected True or False")


def _copy_original_react_log(session_id: str | None, rubric_path: Path, case_name: str) -> Path | None:
    """Copy Claude Code's raw project jsonl into this case's output directory."""
    if not session_id:
        tprint(f"[{case_name}] ⚠️ no session_id returned; cannot copy original_ReAct.jsonl")
        return None

    src = Path(claude_session_jsonl_path(session_id))
    if not src.is_file():
        tprint(f"[{case_name}] ⚠️ Claude project jsonl not found for session_id={session_id}")
        return None

    dst = rubric_path.parent.parent / "original_ReAct.jsonl"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    tprint(f"[{case_name}] 🧾 original ReAct copied: {dst}")
    return dst


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def setup_overall_log(output_dir: str):
    logs_dir = Path(output_dir) / "_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    overall_log = logs_dir / "000_overall.log"
    log_file = open(overall_log, "w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)
    sys.stderr = Tee(sys.__stderr__, log_file)
    return overall_log


running_cases: set = set()
done_cases: set = set()
failed_cases: set = set()


def dataset_categories(dataset_dir: Path) -> set[str]:
    if not dataset_dir.is_dir():
        return set()
    return {p.name for p in dataset_dir.iterdir() if p.is_dir()}


def has_video(artifact_dir: Path) -> bool:
    return any(artifact_dir.rglob("*.mp4"))


def _backup_file(path: Path, suffix: str) -> Path:
    backup = path.with_name(f"{path.name}.{suffix}_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(path, backup)
    return backup


def _move_case_to_half_stopped(rubric_path: Path, case_name: str) -> Path | None:
    """Move an interrupted per-case eval folder under output_dir/half_stopped/."""
    case_out_root = rubric_path.parent.parent
    if not case_out_root.exists():
        tprint(f"[{case_name}] half-stopped move skipped; output folder does not exist: {case_out_root}")
        return None

    half_root = case_out_root.parent / "half_stopped"
    half_root.mkdir(parents=True, exist_ok=True)
    dst = half_root / case_out_root.name
    if dst.exists():
        dst = half_root / f"{case_out_root.name}_{datetime.now():%Y%m%d_%H%M%S}"

    try:
        shutil.move(str(case_out_root), str(dst))
        tprint(f"[{case_name}] half-stopped output moved: {case_out_root} → {dst}")
        return dst
    except Exception as exc:
        tprint(f"[{case_name}] ⚠️ failed to move half-stopped output: {exc}")
        return None


def _move_case_to_failed(rubric_path: Path, case_name: str) -> Path | None:
    """Move a failed per-case eval folder under output_dir/failed/."""
    case_out_root = rubric_path.parent.parent
    if not case_out_root.exists():
        tprint(f"[{case_name}] failed move skipped; output folder does not exist: {case_out_root}")
        return None

    failed_root = case_out_root.parent / "failed"
    failed_root.mkdir(parents=True, exist_ok=True)
    dst = failed_root / case_out_root.name
    if dst.exists():
        shutil.rmtree(dst)

    try:
        shutil.move(str(case_out_root), str(dst))
        tprint(f"[{case_name}] failed output moved: {case_out_root} → {dst}")
        return dst
    except Exception as exc:
        tprint(f"[{case_name}] ⚠️ failed to move failed output: {exc}")
        return None


def _mark_case_failed(rubric_path: Path, case_name: str, session_name: str):
    failed_case_dir = _move_case_to_failed(rubric_path, case_name)
    if failed_case_dir is not None:
        _move_session_outputs_to_case_dir(session_name, case_name, failed_case_dir)


def _move_session_outputs_to_case_dir(session_name: str, case_name: str, case_out_root: Path) -> list[Path]:
    """Move interrupted get-output-dir session folders into the archived case folder."""
    output_root = Path(ASO_OUTPUT_DIR)
    if not output_root.is_dir():
        tprint(f"[{case_name}] session move skipped; session output root not found: {output_root}")
        return []

    session_dirs = [
        p for p in output_root.iterdir()
        if p.is_dir() and p.name.startswith(f"{session_name}_")
    ]
    if not session_dirs:
        tprint(f"[{case_name}] session output not found under {output_root}/{session_name}_*")
        return []

    case_out_root.mkdir(parents=True, exist_ok=True)
    moved = []
    for src in session_dirs:
        dst = case_out_root / src.name
        if dst.exists():
            dst = case_out_root / f"{src.name}_{datetime.now():%Y%m%d_%H%M%S}"
        try:
            shutil.move(str(src), str(dst))
            moved.append(dst)
            tprint(f"[{case_name}] session output moved: {src} → {dst}")
        except Exception as exc:
            tprint(f"[{case_name}] ⚠️ failed to move session output {src}: {exc}")
    return moved


def _repair_rubric_json(rubric_path: Path, parse_error: Exception) -> dict | None:
    """用 json-repair 尝试修复坏掉的 rubric.json,成功后原地写回规范 JSON。"""
    if repair_json_loads is None:
        tprint(f"⚠️ invalid rubric json and json_repair not installed: {rubric_path} ({parse_error})")
        return None

    raw = rubric_path.read_text(encoding="utf-8")
    try:
        repaired = repair_json_loads(raw)
    except Exception as repair_error:
        tprint(f"⚠️ failed to repair rubric json: {rubric_path} ({parse_error}; repair: {repair_error})")
        return None

    if not isinstance(repaired, dict):
        tprint(f"⚠️ repaired rubric json has invalid shape: {rubric_path} (top-level {type(repaired).__name__})")
        return None

    backup = _backup_file(rubric_path, "broken")
    rubric_path.write_text(json.dumps(repaired, ensure_ascii=False, indent=2), encoding="utf-8")
    tprint(f"🩹 repaired rubric.json via json_repair: {rubric_path}; backup → {backup}")
    return repaired


def _load_rubric_object(rubric_path: Path) -> dict | None:
    """读取 rubric.json; 只有顶层是 dict 才返回,否则视为坏文件。"""
    try:
        data = json.loads(rubric_path.read_text(encoding="utf-8"))
    except Exception as e:
        data = _repair_rubric_json(rubric_path, e)
        if data is None:
            tprint(f"⚠️ invalid rubric json, will refresh from dataset: {rubric_path} ({e})")
            return None
    if not isinstance(data, dict):
        tprint(f"⚠️ invalid rubric shape, will refresh from dataset: {rubric_path} (top-level {type(data).__name__})")
        return None
    return data


def _backup_and_copy_rubric(src_rubric: Path, dst_rubric: Path, reason: str):
    if dst_rubric.exists():
        backup = dst_rubric.with_name(f"{dst_rubric.name}.invalid_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.move(str(dst_rubric), str(backup))
        tprint(f"⚠️ refreshed rubric.json ({reason}); backup → {backup}")
    shutil.copy2(src_rubric, dst_rubric)


def _prepare_case_output(src_rubric: Path, dst_rubric: Path, overwrite: bool):
    """Create the per-case output directory and initialize rubric.json at task start."""
    dst_rubric.parent.mkdir(parents=True, exist_ok=True)

    if not overwrite and rubric_needs_refresh(dst_rubric):
        _backup_and_copy_rubric(src_rubric, dst_rubric, "invalid existing rubric")
        return

    # overwrite 时强制刷新 rubric.json;否则若已存在(可能是续跑的半成品)就保留
    if overwrite or not dst_rubric.is_file():
        shutil.copy2(src_rubric, dst_rubric)


def rubric_needs_refresh(rubric_path: Path) -> bool:
    if not rubric_path.is_file():
        return False
    return _load_rubric_object(rubric_path) is None


def already_scored(rubric_path: Path) -> bool:
    """rubric.json 的 output_rubric 各项 `分数` 都已非空 → 视为已打分。
    `fixed_O1` (通过率) 设计上永远留空,不参与判定。
    """
    if not rubric_path.is_file():
        return False
    data = _load_rubric_object(rubric_path)
    if data is None:
        return False
    output_rubric = data.get("output_rubric") or []
    if not output_rubric:
        return False
    SKIP_IDS = {"fixed_O1"}
    for item in output_rubric:
        if item.get("id") in SKIP_IDS:
            continue
        score = item.get("分数")
        if score is None or score == "":
            return False
    return True


async def run_one_case(case_name: str,
                        artifact_dir: Path,
                        src_rubric: Path,
                        rubric_path: Path,
                        logs_dir: Path,
                        timeout_seconds: int,
                        max_retries: int,
                        retry_delay: int,
                        dry_run: bool,
                        overwrite: bool,
                        cwd: str = CLAUDE_WORKSPACE):
    """对单个 case 调 claude_chat 跑 output-eval。"""
    session_name = f"eval_output_{case_name}"
    prompt = OUTPUT_EVAL_PROMPT_TEMPLATE.format(
        artifact_dir=str(artifact_dir.resolve()),
        rubric_path=str(rubric_path.resolve()),
    )
    log_file = str(logs_dir / f"{session_name}.log")

    if dry_run:
        print(f"[DRY-RUN] {case_name}\n  artifact={artifact_dir}\n  rubric={rubric_path}\n"
              f"  --- prompt to agent ---\n{prompt}\n  --- end prompt ---")
        return True

    running_cases.add(case_name)
    start = datetime.now()
    tprint(f"[{case_name}] start at {start:%H:%M:%S}")
    _prepare_case_output(src_rubric, rubric_path, overwrite)

    try:
        result = await claude_chat(
            session_name=session_name,
            message=prompt,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay=retry_delay,
            log_file=log_file,
            overwrite_log=True,
            reasoning="off",
            cwd=cwd,
        )
    except asyncio.CancelledError:
        tprint(f"[{case_name}] cancelled")
        half_stopped_case_dir = _move_case_to_half_stopped(rubric_path, case_name)
        if half_stopped_case_dir is not None:
            _move_session_outputs_to_case_dir(session_name, case_name, half_stopped_case_dir)
        running_cases.discard(case_name)
        raise
    except Exception as e:
        tprint(f"[{case_name}] ❌ exception: {e}")
        running_cases.discard(case_name)
        failed_cases.add(case_name)
        _mark_case_failed(rubric_path, case_name, session_name)
        return False

    dur = (datetime.now() - start).total_seconds()
    running_cases.discard(case_name)
    _copy_original_react_log(result.get("session_id"), rubric_path, case_name)

    if not result.get("success"):
        err = result.get("error") or result.get("stderr", "unknown")
        tprint(f"[{case_name}] ❌ claude_chat failed in {dur:.0f}s: {err[:200]}")
        failed_cases.add(case_name)
        _mark_case_failed(rubric_path, case_name, session_name)
        return False

    # 不管打分是否完整,都把 get-output-dir 生成的整个 session 输出目录搬到 output_eval 里
    _relocate_session_output(session_name, rubric_path, case_name)

    if already_scored(rubric_path):
        tprint(f"[{case_name}] ✅ scored in {dur:.0f}s")
        done_cases.add(case_name)
        return True

    tprint(f"[{case_name}] ⚠️ chat ok but rubric.json scores not all filled in {dur:.0f}s")
    failed_cases.add(case_name)
    _move_case_to_failed(rubric_path, case_name)
    return False


def _relocate_session_output(session_name: str, rubric_path: Path, case_name: str):
    """Move the get-output-dir session folder into output_eval/<case>/.

    output-eval writes cache via get-output-dir --subdir cache, which resolves to:
      ASO_OUTPUT_DIR/<session_name>_<session_id>/cache
    Move the whole ASO_OUTPUT_DIR/<session_name>_<session_id>/ folder so sibling
    artifacts are preserved with cache/.
    """
    case_out_root = rubric_path.parent.parent  # .../<case>/evals_human/rubric.json → .../<case>
    output_root = Path(ASO_OUTPUT_DIR)
    if not output_root.is_dir():
        tprint(f"[{case_name}] ⚠️ session output root not found: {output_root}")
        return

    session_dirs = [
        p for p in output_root.iterdir()
        if p.is_dir() and p.name.startswith(f"{session_name}_")
    ]
    session_dirs_with_cache = [p for p in session_dirs if (p / "cache").is_dir()]
    if not session_dirs_with_cache:
        tprint(f"[{case_name}] ⚠️ session output with cache not found under {output_root}/{session_name}_*")
        return

    src = max(session_dirs_with_cache, key=lambda p: (p / "cache").stat().st_mtime)
    dst = case_out_root / src.name
    try:
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        tprint(f"[{case_name}] 📦 session output moved: {src} → {dst}")
    except Exception as e:
        tprint(f"[{case_name}] ⚠️ relocate {src} failed: {e}")


def collect_tasks(args) -> list[dict]:
    result_dir = Path(args.result_dir)
    output_dir = Path(args.output_dir)
    dataset_dir = Path(args.dataset_dir)
    categories = dataset_categories(dataset_dir)

    tasks = []
    skipped: list[tuple[str, str]] = []

    for entry in sorted(result_dir.iterdir()):
        if not entry.is_dir():
            continue
        case_name = entry.name
        if case_name.startswith(("eval_", "failed_", "half_stopped_")):
            continue

        category, case_id, _ = parse_result_dir_name(case_name, categories)
        if not category or not case_id:
            skipped.append((case_name, "name-not-parseable"))
            continue

        src_rubric = dataset_dir / category / case_id / "rubric.json"
        if not src_rubric.is_file():
            skipped.append((case_name, f"dataset rubric missing: {src_rubric}"))
            continue

        artifact_dir = entry
        if not has_video(artifact_dir):
            skipped.append((case_name, "no mp4 in artifact dir"))
            continue

        dst_rubric = output_dir / case_name / "evals_human" / "rubric.json"

        if not args.overwrite and already_scored(dst_rubric):
            skipped.append((case_name, "already scored (use --overwrite to redo)"))
            continue

        tasks.append({
            "case_name": case_name,
            "artifact_dir": artifact_dir,
            "src_rubric": src_rubric,
            "rubric_path": dst_rubric,
        })

    if args.limit and args.limit > 0:
        tasks = tasks[:args.limit]

    if skipped:
        print("Skipped cases:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")
    return tasks


async def main_async(args):
    tasks = collect_tasks(args)
    if not tasks:
        print("No cases to eval.")
        return

    print(f"Total eval tasks: {len(tasks)}  concurrency={args.concurrency}")

    logs_dir = Path(args.output_dir) / "_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(args.concurrency)

    async def sem_runner(t):
        async with sem:
            await run_one_case(
                case_name=t["case_name"],
                artifact_dir=t["artifact_dir"],
                src_rubric=t["src_rubric"],
                rubric_path=t["rubric_path"],
                logs_dir=logs_dir,
                timeout_seconds=args.timeout_seconds,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
                cwd=CLAUDE_WORKSPACE,
            )

    coros = [sem_runner(t) for t in tasks]
    if tqdm_asyncio is not None:
        # tqdm.asyncio.tqdm.gather 在 stdout 是 TTY 时显示进度条,
        # 同时 per-case 日志已经用 tprint() 路由,不会撞条
        await tqdm_asyncio.gather(*coros, total=len(coros), desc="eval",
                                   dynamic_ncols=True, mininterval=0.5)
    else:
        print("(tqdm 未安装,显示原始日志;pip install tqdm 可获得进度条)")
        await asyncio.gather(*coros, return_exceptions=False)

    total = len(tasks)
    print("\n--- Eval Summary ---")
    print(f"Total: {total}  ✅ Done: {len(done_cases)}  ❌ Failed: {len(failed_cases)}")

    # Run metadata (谁/哪个目录 + 成败列表)
    run_meta_path = Path(args.output_dir) / "batch_eval_output_run.json"
    run_meta_path.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "result_dir": args.result_dir,
        "output_dir": args.output_dir,
        "dataset_dir": args.dataset_dir,
        "concurrency": args.concurrency,
        "total": total,
        "done": sorted(done_cases),
        "failed": sorted(failed_cases),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Run meta → {run_meta_path}")

    # Aggregated rubric summary (summary.json + summary.md)
    try:
        generate_eval_output_summary(
            args=args,
            done_cases=done_cases,
            failed_cases=failed_cases,
        )
    except Exception as e:
        print(f"⚠️ summary generation failed: {e}")


# ============================================================================
# Summary generation (output_rubric only; 跳过 O1)
# ============================================================================

# 不参与统计的 atom id (O1 是通过率,user 明确不打)
SKIPPED_RUBRIC_IDS = {"fixed_O1"}


def _score_of(item) -> float | None:
    """从一条 rubric 取分数;空 / 非法 / None 都返回 None (表示该项缺评分)。"""
    for k in ("分数", "score"):
        if k in item:
            v = item.get(k)
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None
    return None


def _walk_case_rubrics(output_dir: Path, categories: set[str]):
    """yield (case_name, category, output_rubric_list) for each case 有 rubric.json 的目录。"""
    for entry in sorted(output_dir.iterdir()):
        if not entry.is_dir():
            continue
        rp = entry / "evals_human" / "rubric.json"
        if not rp.is_file():
            continue
        data = _load_rubric_object(rp)
        if data is None:
            print(f"⚠️ failed to parse or repair {rp}")
            continue
        category = data.get("category")
        if not category:
            cat, _, _ = parse_result_dir_name(entry.name, categories)
            category = cat or "unknown"
        rubrics = data.get("output_rubric") or []
        yield entry.name, category, rubrics


def generate_eval_output_summary(args, done_cases: set, failed_cases: set):
    """聚合 output_rubric 评分:
       - {output_dir}/summary.json — 机器可读 (per category / overall / per criterion)
       - {output_dir}/summary.md   — HTML table (类目 × criterion + Average + All 行)
    """
    output_dir = Path(args.output_dir)
    categories = dataset_categories(Path(args.dataset_dir))

    # category → criterion_id → {obtained, possible}
    cat_crit: dict[str, dict[str, dict[str, float]]] = {}
    # category → {obtained, possible, case_count}
    cat_total: dict[str, dict[str, float]] = {}
    # criterion_id → criterion_name (展示用)
    crit_name: dict[str, str] = {}
    # 每个 case 的均分,方便排查
    per_case: list[dict] = []

    for case_name, category, rubrics in _walk_case_rubrics(output_dir, categories):
        case_obtained = 0.0
        case_possible = 0.0
        case_crit_scores: dict[str, float | None] = {}
        for r in rubrics:
            cid = r.get("id") or ""
            if cid in SKIPPED_RUBRIC_IDS:
                continue
            crit_name.setdefault(cid, r.get("criterion") or cid)
            sc = _score_of(r)
            case_crit_scores[cid] = sc
            if sc is None:
                continue  # 缺评分不计入分母,避免拉低均值
            cat_crit.setdefault(category, {}).setdefault(cid, {"obtained": 0.0, "possible": 0.0})
            cat_crit[category][cid]["obtained"] += sc
            cat_crit[category][cid]["possible"] += 1.0
            case_obtained += sc
            case_possible += 1.0
        cat_total.setdefault(category, {"obtained": 0.0, "possible": 0.0, "case_count": 0})
        cat_total[category]["obtained"] += case_obtained
        cat_total[category]["possible"] += case_possible
        cat_total[category]["case_count"] += 1
        per_case.append({
            "case_name": case_name,
            "category": category,
            "avg": (case_obtained / case_possible) if case_possible > 0 else None,
            "obtained": case_obtained,
            "possible": case_possible,
            "scores": case_crit_scores,
        })

    # criterion 列顺序:按 id 字典序 (fixed_O2..O8) 稳定
    criterion_ids = sorted(crit_name.keys())

    # 组装 summary
    scores_by_category: dict[str, dict] = {}
    overall_crit: dict[str, dict[str, float]] = {}
    overall_obtained = 0.0
    overall_possible = 0.0
    overall_cases = 0
    for cat, totals in cat_total.items():
        per_crit = {}
        for cid in criterion_ids:
            stats = cat_crit.get(cat, {}).get(cid)
            if not stats or stats["possible"] <= 0:
                per_crit[cid] = None
                continue
            per_crit[cid] = {
                "score": stats["obtained"] / stats["possible"],
                "obtained": stats["obtained"],
                "possible": stats["possible"],
            }
            overall_crit.setdefault(cid, {"obtained": 0.0, "possible": 0.0})
            overall_crit[cid]["obtained"] += stats["obtained"]
            overall_crit[cid]["possible"] += stats["possible"]
        avg = (totals["obtained"] / totals["possible"]) if totals["possible"] > 0 else None
        scores_by_category[cat] = {
            "avg": avg,
            "obtained": totals["obtained"],
            "possible": totals["possible"],
            "case_count": totals["case_count"],
            "per_criterion": per_crit,
        }
        overall_obtained += totals["obtained"]
        overall_possible += totals["possible"]
        overall_cases += totals["case_count"]

    overall_per_crit = {}
    for cid in criterion_ids:
        s = overall_crit.get(cid)
        if not s or s["possible"] <= 0:
            overall_per_crit[cid] = None
            continue
        overall_per_crit[cid] = {
            "score": s["obtained"] / s["possible"],
            "obtained": s["obtained"],
            "possible": s["possible"],
        }

    summary = {
        "timestamp": datetime.now().isoformat(),
        "args": vars(args),
        "skipped_rubric_ids": sorted(SKIPPED_RUBRIC_IDS),
        "criterion_ids": criterion_ids,
        "criterion_names": {cid: crit_name[cid] for cid in criterion_ids},
        "case_count": overall_cases,
        "success_count": len(done_cases),
        "failed_count": len(failed_cases),
        "overall": {
            "avg": (overall_obtained / overall_possible) if overall_possible > 0 else None,
            "obtained": overall_obtained,
            "possible": overall_possible,
            "per_criterion": overall_per_crit,
        },
        "scores_by_category": scores_by_category,
        "per_case": per_case,
    }

    summary_json = output_dir / "summary.json"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"summary.json → {summary_json}")

    # 写 markdown HTML 表格
    summary_md = output_dir / "summary.md"
    summary_md.write_text(_render_summary_markdown(summary), encoding="utf-8")
    print(f"summary.md → {summary_md}")


def _render_summary_markdown(summary: dict) -> str:
    from html import escape

    def fmt(v):
        return "" if v is None else f"{v:.4f}"

    criterion_ids = summary["criterion_ids"]
    criterion_names = summary["criterion_names"]
    by_cat = summary["scores_by_category"]
    overall = summary["overall"]

    lines = []
    lines.append(f"# Output Eval Summary\n")
    lines.append(f"- Generated: {summary['timestamp']}")
    lines.append(f"- Total cases: **{summary['case_count']}**  ✅ success: {summary['success_count']}  ❌ failed: {summary['failed_count']}")
    lines.append(f"- Skipped rubric ids: `{', '.join(summary['skipped_rubric_ids'])}`")
    overall_avg = overall.get("avg")
    lines.append(f"- Overall average: **{fmt(overall_avg)}**  ({overall['obtained']:.1f} / {overall['possible']:.0f})\n")

    # HTML 表格
    lines.append("<table>")
    lines.append("  <thead>")
    lines.append("    <tr>")
    lines.append('      <th rowspan="2">Category</th>')
    lines.append(f'      <th colspan="{len(criterion_ids)}">Output Rubric (per criterion)</th>')
    lines.append('      <th rowspan="2">Cases</th>')
    lines.append('      <th rowspan="2">Average</th>')
    lines.append("    </tr>")
    lines.append("    <tr>")
    for cid in criterion_ids:
        label = f"{cid.replace('fixed_', '')} {criterion_names.get(cid, cid)}"
        lines.append(f"      <th>{escape(label)}</th>")
    lines.append("    </tr>")
    lines.append("  </thead>")
    lines.append("  <tbody>")

    for cat in sorted(by_cat.keys()):
        row = by_cat[cat]
        lines.append("    <tr>")
        lines.append(f"      <td>{escape(cat)}</td>")
        for cid in criterion_ids:
            stats = row["per_criterion"].get(cid)
            lines.append(f"      <td>{fmt(stats['score'] if stats else None)}</td>")
        lines.append(f"      <td>{row['case_count']}</td>")
        lines.append(f"      <td>{fmt(row['avg'])}</td>")
        lines.append("    </tr>")

    # 总计行
    lines.append("    <tr>")
    lines.append("      <td><b>All</b></td>")
    for cid in criterion_ids:
        stats = overall["per_criterion"].get(cid)
        lines.append(f"      <td><b>{fmt(stats['score'] if stats else None)}</b></td>")
    lines.append(f"      <td><b>{summary['case_count']}</b></td>")
    lines.append(f"      <td><b>{fmt(overall_avg)}</b></td>")
    lines.append("    </tr>")

    lines.append("  </tbody>")
    lines.append("</table>\n")

    # 失败 case 列表
    failed = [c["case_name"] for c in summary.get("per_case", []) if c.get("possible", 0) == 0]
    if failed:
        lines.append(f"\n## ⚠️ Cases without any score ({len(failed)})\n")
        for c in failed:
            lines.append(f"- {c}")

    return "\n".join(lines) + "\n"


def parse_args():
    p = argparse.ArgumentParser(description="Batch output-eval runner (Claude Code 适配版)")
    p.add_argument("--result-dir", default=DEFAULT_RESULT_DIR,
                   help="包含 {category}_{case_id}_..._{uuid}/ 的产物根目录")
    p.add_argument("--output-dir", default=None,
                   help="评测输出根目录; 默认使用 {result-dir}_output_eval")
    p.add_argument("--dataset-dir", default=DEFAULT_DATASET_DIR,
                   help="dataset 根目录,用于读取每个 case 的原始 rubric.json")
    p.add_argument("--concurrency", type=int, default=10, help="并发评测的 case 数")
    p.add_argument("--limit", type=int, default=3, help="最多评测的有效 case 数; 默认 3,设为 0 表示不限制")
    p.add_argument("--timeout-seconds", type=int, default=7200, help="单 case 子进程超时秒数")
    p.add_argument("--max-retries", type=int, default=3, help="claude_chat 内部重试次数")
    p.add_argument("--retry-delay", type=int, default=60, help="重试间隔秒数")
    p.add_argument("--mode", choices=["resume", "rerun"], default="resume",
                   help="resume 跳过已完整打分 case; rerun 强制重跑")
    p.add_argument("--overwrite", action=argparse.BooleanOptionalAction, default=False,
                   help="强制重跑已有打分; resume 默认跳过已完整打分 case")
    p.add_argument("--dry-run", type=parse_bool, default=True,
                   help="True 只打印将要执行的 case,不调用 claude; False 直接运行")
    p.add_argument("--use-deepseek", action=argparse.BooleanOptionalAction, default=True,
                   help="默认使用 DeepSeek Anthropic-compatible backend; 需要 DEEPSEEK_API_KEY")
    args = p.parse_args()
    if args.output_dir is None:
        args.output_dir = default_output_dir(args.result_dir)
    args.result_dir = os.path.abspath(os.path.expanduser(args.result_dir))
    args.output_dir = os.path.abspath(os.path.expanduser(args.output_dir))
    args.dataset_dir = os.path.abspath(os.path.expanduser(args.dataset_dir))
    return args


if __name__ == "__main__":
    args = parse_args()
    if args.mode == "rerun":
        args.overwrite = True
    if args.mode == "resume" and args.overwrite:
        sys.exit("--overwrite is not compatible with --mode resume; use --mode rerun.")
    if args.concurrency <= 0:
        sys.exit(f"--concurrency must be positive, got {args.concurrency}.")
    if args.use_deepseek:
        os.environ.setdefault("USE_DEEPSEEK", "1")

    if not os.path.isdir(args.result_dir):
        sys.exit(f"result-dir not found: {args.result_dir}")
    if not os.path.isdir(args.dataset_dir):
        sys.exit(f"dataset-dir not found: {args.dataset_dir}")
    skill_dir = Path(CLAUDE_WORKSPACE) / ".claude" / "skills" / "output-eval"
    if not skill_dir.is_dir():
        sys.exit(f"skill dir not found under CLAUDE_WORKSPACE: {skill_dir}")
    os.makedirs(args.output_dir, exist_ok=True)
    overall_log = setup_overall_log(args.output_dir)
    print(f"result_dir   = {args.result_dir}")
    print(f"output_dir  = {args.output_dir}")
    print(f"dataset_dir = {args.dataset_dir}")
    print(f"concurrency = {args.concurrency}")
    print(f"mode        = {args.mode}")
    print(f"use_deepseek= {args.use_deepseek}")
    print(f"claude_workspace = {CLAUDE_WORKSPACE}")
    print(f"overall_log = {overall_log}")
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
