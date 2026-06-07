import json
import os
import shutil

from AutomaticSkillOptimization.args import OUTPUT_DIR
from AutomaticSkillOptimization.evaluation_PRM.execution_error_analysis import write_execution_error_report
from AutomaticSkillOptimization.utils import find_session_dir

EXECUTION_ERROR_CRITERION = "错误次数"
EXECUTION_ERROR_RUBRIC_ID = "fixed_P3"


def is_execution_error_rubric(item):
    if not isinstance(item, dict):
        return False
    return (
        item.get("id") == EXECUTION_ERROR_RUBRIC_ID
        or item.get("criterion") == EXECUTION_ERROR_CRITERION
    )


def remove_execution_error_rubric(rubric_data):
    """Remove the execution-error rubric from data sent to the LLM evaluator."""
    execution_error_rubric = None
    if not isinstance(rubric_data, dict):
        return rubric_data, execution_error_rubric
    process_rubric = rubric_data.get("process_rubric")
    if not isinstance(process_rubric, list):
        return rubric_data, execution_error_rubric
    filtered = []
    for item in process_rubric:
        if is_execution_error_rubric(item):
            if execution_error_rubric is None and isinstance(item, dict):
                execution_error_rubric = dict(item)
            continue
        filtered.append(item)
    rubric_data["process_rubric"] = filtered
    return rubric_data, execution_error_rubric


def load_and_prepare_rubric(rubric_path, skip_rubric_ids=None):
    """加载 rubric_deterministic.json，去掉 execution-error rubric，可选跳过指定 ID。

    Returns (rubric_content_json_str, execution_error_rubric_template).
    rubric_content 为 None 表示文件不存在。
    """
    if not os.path.isfile(rubric_path):
        return None, None

    with open(rubric_path, "r", encoding="utf-8") as f:
        rubric_content = f.read()

    execution_error_rubric_template = None
    try:
        rubric_data = json.loads(rubric_content)
        rubric_data, execution_error_rubric_template = remove_execution_error_rubric(rubric_data)
        if skip_rubric_ids:
            process_rubric = rubric_data.get("process_rubric")
            if isinstance(process_rubric, list):
                rubric_data["process_rubric"] = [
                    item for item in process_rubric
                    if not (isinstance(item, dict) and item.get("id") in skip_rubric_ids)
                ]
        rubric_content = json.dumps(rubric_data, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        pass

    return rubric_content, execution_error_rubric_template


def deterministic_execution_error_rubric(report, template=None, report_path=None, base_dir=None):
    total = int(report.get("total_execution_count") or 0)
    errors = int(report.get("error_execution_count") or 0)
    score = 1.0 if total <= 0 else max(0.0, 1.0 - errors / total)
    feedback_path = report_path
    if report_path and base_dir:
        try:
            feedback_path = os.path.relpath(report_path, base_dir)
        except ValueError:
            feedback_path = report_path
    item = dict(template or {})
    item.update(
        {
            "id": item.get("id") or EXECUTION_ERROR_RUBRIC_ID,
            "criterion": item.get("criterion") or EXECUTION_ERROR_CRITERION,
            "score": round(score, 6),
            "feedback": f"details are shown in: {feedback_path}" if errors else "",
        }
    )
    return item


def generation_trace_path(item_path):
    """返回 item_path 下的 generation trace jsonl 文件路径。"""
    if not item_path or not os.path.isdir(item_path):
        return None
    for filename in ("original_ReAct.jsonl", "ReAct_process.jsonl"):
        path = os.path.join(item_path, filename)
        if os.path.isfile(path):
            return path
    return None


def ensure_execution_error_eval(item_path, execution_error_template=None, rubrics_path=None):
    """从 generation trace jsonl 统计执行错误，写入 fixed_P3 的确定性评分。"""
    if not item_path:
        return False

    trace_path = generation_trace_path(item_path)
    if not trace_path:
        print(f"⚠️ generation trace jsonl not found: {item_path}")
        return False

    report_path = os.path.join(item_path, "evals", "execution_error_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    report_path, full_report = write_execution_error_report(trace_path, report_path=report_path)
    deterministic_item = deterministic_execution_error_rubric(
        full_report.get("concise_report") or {},
        execution_error_template,
        report_path=str(report_path),
        base_dir=item_path,
    )

    if rubrics_path is None:
        rubrics_path = os.path.join(item_path, "evals", "rubrics_eval.json")
    if not os.path.isfile(rubrics_path):
        print(f"⚠️ rubrics_eval.json not found; wrote execution report only: {report_path}")
        return True

    try:
        with open(rubrics_path, "r", encoding="utf-8") as f:
            rubrics_eval = json.load(f)
        if not isinstance(rubrics_eval, dict):
            print(f"⚠️ rubrics_eval.json is not an object: {rubrics_path}")
            return False
        process_rubric = rubrics_eval.get("process_rubric")
        if not isinstance(process_rubric, list):
            process_rubric = []
        process_rubric = [item for item in process_rubric if not is_execution_error_rubric(item)]
        process_rubric.append(deterministic_item)
        rubrics_eval["process_rubric"] = process_rubric
        with open(rubrics_path, "w", encoding="utf-8") as f:
            json.dump(rubrics_eval, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(
            f"✅ Deterministic execution-error eval written for {os.path.basename(item_path)}: "
            f"{full_report.get('concise_report', {}).get('error_execution_count', 0)}/"
            f"{full_report.get('concise_report', {}).get('total_execution_count', 0)} errors"
        )
        return True
    except Exception as e:
        print(f"⚠️ Failed to patch deterministic execution-error eval for {item_path}: {e}")
        return False


def check_eval_done(agent_id, eval_session_name, gen_session_name=None, search_dirs=None):
    if search_dirs is None:
        search_dirs = [OUTPUT_DIR]

    if gen_session_name:
        gen_dir = find_session_dir(gen_session_name, agent_id=agent_id, search_dirs=search_dirs)
        if gen_dir:
            evals_dir = os.path.join(gen_dir, "evals")
            if os.path.isdir(evals_dir):
                react_file = os.path.join(evals_dir, "ReAct_process.json")
                rubrics_file = os.path.join(evals_dir, "rubrics_eval.json")
                if os.path.isfile(react_file) and os.path.isfile(rubrics_file):
                    try:
                        with open(react_file, "r", encoding="utf-8") as rf:
                            react_data = json.load(rf)
                        with open(rubrics_file, "r", encoding="utf-8") as rubf:
                            rubrics_data = json.load(rubf)
                        if len(react_data) > 3 and rubrics_data:
                            return True
                    except Exception:
                        pass

    if search_dirs != [OUTPUT_DIR]:
        return False

    session_path = find_session_dir(eval_session_name, agent_id=agent_id, search_dirs=search_dirs)
    if session_path and os.path.isdir(session_path):
        react_file = os.path.join(session_path, "ReAct_process.json")
        rubrics_file = os.path.join(session_path, "rubrics_eval.json")
        if os.path.isfile(react_file) and os.path.isfile(rubrics_file):
            try:
                with open(react_file, "r", encoding="utf-8") as rf:
                    react_data = json.load(rf)
                with open(rubrics_file, "r", encoding="utf-8") as rubf:
                    rubrics_data = json.load(rubf)
                if len(react_data) > 3 and rubrics_data:
                    return True
            except Exception:
                pass
    return False


def load_execution_error_rubric_template(rubric_path):
    try:
        with open(rubric_path, "r", encoding="utf-8") as f:
            rubric_data = json.load(f)
        _, execution_error_rubric = remove_execution_error_rubric(rubric_data)
        return execution_error_rubric
    except Exception:
        return None


def copy_human_rubrics(dataset_dir, category, case_id, item_path):
    """复制 rubric.json / rubric.xlsx 到 item_path/evals_human/。"""
    evals_human_dir = os.path.join(item_path, "evals_human")
    copied = False
    for filename in ("rubric.json", "rubric.xlsx"):
        src = os.path.join(dataset_dir, category, case_id, filename)
        if os.path.isfile(src):
            os.makedirs(evals_human_dir, exist_ok=True)
            shutil.copy2(src, os.path.join(evals_human_dir, filename))
            copied = True
    return copied
