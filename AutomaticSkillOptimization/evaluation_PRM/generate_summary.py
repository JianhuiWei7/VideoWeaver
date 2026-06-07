import os
import json
from html import escape


def sync_deterministic_execution_error_eval(item_path, rubrics_path):
    """Refresh fixed_P3/错误次数 from original_ReAct.jsonl before summary aggregation."""
    from AutomaticSkillOptimization.evaluation_PRM.evaluation_utils import ensure_execution_error_eval

    if not os.path.isfile(rubrics_path):
        return None
    ensure_execution_error_eval(item_path, rubrics_path=rubrics_path)
    with open(rubrics_path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_eval_summary(args, done_sessions, failed_sessions, new_generate_materials_dir):
    """
    生成一个 summary.json 文件, 记录任务执行的结果
    """
    skipped_rubric = {"fixed_P2", "fixed_P5"}
    valid_output_rubric = {"技术规格达标"}

    def get_rubric_score(rubric):
        for score_key in ("score", "分数"):
            if score_key in rubric:
                try:
                    return float(rubric.get(score_key) or 0)
                except (ValueError, TypeError):
                    return 0.0
        return 0.0

    def add_rubric_stats(rubric_stats, category, rubric_type, rubrics):
        if category not in rubric_stats:
            rubric_stats[category] = {"process_rubric": {}, "output_rubric": {}}
        for rubric in rubrics:
            criterion = rubric.get("criterion") or "unknown"
            if criterion not in rubric_stats[category][rubric_type]:
                rubric_stats[category][rubric_type][criterion] = {
                    "obtained": 0.0,
                    "possible": 0.0
                }
            rubric_stats[category][rubric_type][criterion]["obtained"] += get_rubric_score(rubric)
            rubric_stats[category][rubric_type][criterion]["possible"] += 1.0

    def merge_overall_rubric_stats(overall_stats, category_rubric_stats):
        for rubric_type, criterion_stats in category_rubric_stats.items():
            for criterion, stats in criterion_stats.items():
                if criterion not in overall_stats[rubric_type]:
                    overall_stats[rubric_type][criterion] = {
                        "obtained": 0.0,
                        "possible": 0.0
                    }
                overall_stats[rubric_type][criterion]["obtained"] += stats["obtained"]
                overall_stats[rubric_type][criterion]["possible"] += stats["possible"]

    def format_rubric_stats(rubric_stats):
        formatted = {"process_rubric": {}, "output_rubric": {}}
        for rubric_type, criterion_stats in rubric_stats.items():
            for criterion, stats in criterion_stats.items():
                if stats["possible"] <= 1:
                    continue
                formatted[rubric_type][criterion] = {
                    "score": stats["obtained"] / stats["possible"] if stats["possible"] > 0 else 0.0,
                    "obtained_points": stats["obtained"],
                    "possible_points": stats["possible"]
                }
        return formatted

    def write_markdown_table(table_summary_data, output_path):
        write_markdown_table_content(table_summary_data, output_path)

    def write_markdown_table_content(table_summary_data, output_path=None):
        def score_text(value):
            return "" if value is None else f"{value:.4f}"

        process_criteria = list(table_summary_data.get("overall_rubric_scores", {}).get("process_rubric", {}).keys())
        output_criteria = list(table_summary_data.get("overall_rubric_scores", {}).get("output_rubric", {}).keys())
        rows = []
        for category, category_data in table_summary_data.get("scores_by_category", {}).items():
            rubric_scores = category_data.get("rubric_scores", {})
            row = [category]
            for criterion in process_criteria:
                stats = rubric_scores.get("process_rubric", {}).get(criterion)
                row.append(score_text(stats.get("score") if stats else None))
            for criterion in output_criteria:
                stats = rubric_scores.get("output_rubric", {}).get(criterion)
                row.append(score_text(stats.get("score") if stats else None))
            row.append(score_text(category_data.get("score")))
            rows.append(row)

        overall_rubric_scores = table_summary_data.get("overall_rubric_scores", {})
        overall_row = ["All"]
        for criterion in process_criteria:
            stats = overall_rubric_scores.get("process_rubric", {}).get(criterion)
            overall_row.append(score_text(stats.get("score") if stats else None))
        for criterion in output_criteria:
            stats = overall_rubric_scores.get("output_rubric", {}).get(criterion)
            overall_row.append(score_text(stats.get("score") if stats else None))
        overall_row.append(score_text(table_summary_data.get("overall_score")))
        rows.append(overall_row)

        lines = []
        lines.append("<table>")
        lines.append("  <thead>")
        lines.append("    <tr>")
        lines.append('      <th rowspan="2">数据集</th>')
        if process_criteria:
            lines.append(f'      <th colspan="{len(process_criteria)}">Process</th>')
        if output_criteria:
            lines.append(f'      <th colspan="{len(output_criteria)}">Output</th>')
        lines.append('      <th rowspan="2">Average</th>')
        lines.append("    </tr>")
        lines.append("    <tr>")
        for criterion in process_criteria + output_criteria:
            lines.append(f"      <th>{escape(criterion)}</th>")
        lines.append("    </tr>")
        lines.append("  </thead>")
        lines.append("  <tbody>")
        for row in rows:
            lines.append("    <tr>")
            for cell in row:
                lines.append(f"      <td>{escape(cell)}</td>")
            lines.append("    </tr>")
        lines.append("  </tbody>")
        lines.append("</table>")

        content = "\n".join(lines) + "\n"
        if output_path is not None:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
        return content

    def write_complete_markdown(deterministic_summary_data, human_summary_data, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("## LLM Deterministic Summary\n\n")
            f.write(write_markdown_table_content(deterministic_summary_data))
            f.write("\n## Human Summary\n\n")
            f.write(write_markdown_table_content(human_summary_data))

    summary = {
        "args": vars(args) if hasattr(args, '__dict__') else args,
        "success_sessions": list(done_sessions),
        "failed_sessions": list(failed_sessions),
        "scores_by_category": {},
        "overall_score": 0.0
    }
    table_summary = {
        "args": vars(args) if hasattr(args, '__dict__') else args,
        "success_sessions": list(done_sessions),
        "failed_sessions": list(failed_sessions),
        "scores_by_category": {},
        "overall_score": 0.0,
        "skipped_rubric": sorted(skipped_rubric)
    }
    human_summary = {
        "args": vars(args) if hasattr(args, '__dict__') else args,
        "success_sessions": list(done_sessions),
        "failed_sessions": list(failed_sessions),
        "scores_by_category": {},
        "overall_score": 0.0
    }
    
    if new_generate_materials_dir != 'Not renamed' and os.path.isdir(new_generate_materials_dir):
        category_stats = {}
        table_category_stats = {}
        human_category_stats = {}
        category_rubric_stats = {}
        table_category_rubric_stats = {}
        human_category_rubric_stats = {}
        overall_rubric_stats = {"process_rubric": {}, "output_rubric": {}}
        table_overall_rubric_stats = {"process_rubric": {}, "output_rubric": {}}
        human_overall_rubric_stats = {"process_rubric": {}, "output_rubric": {}}
        total_obtained = 0.0
        total_possible = 0.0
        table_total_obtained = 0.0
        table_total_possible = 0.0
        human_total_obtained = 0.0
        human_total_possible = 0.0
        
        for item in os.listdir(new_generate_materials_dir):
            item_path = os.path.join(new_generate_materials_dir, item)
            if not os.path.isdir(item_path):
                continue
                
            rubrics_path = os.path.join(item_path, "evals", "rubrics_eval.json")
            if not os.path.isfile(rubrics_path):
                # 如果 evals/rubrics_eval.json 不存在，尝试兼容原来的根目录路径
                rubrics_path = os.path.join(item_path, "rubrics_eval.json")

            if os.path.isfile(rubrics_path):
                try:
                    data = sync_deterministic_execution_error_eval(item_path, rubrics_path)
                    if data is None:
                        with open(rubrics_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        
                    category = data.get("category", "unknown")
                    process_rubric = data.get("process_rubric", [])
                    output_rubric = data.get("output_rubric", [])
                    valid_output_rubrics = [
                        r for r in output_rubric
                        if r.get("criterion") in valid_output_rubric
                    ]
                    
                    obtained = 0.0
                    possible = 0.0
                    for r in process_rubric + valid_output_rubrics:
                        obtained += get_rubric_score(r)
                        possible += 1.0

                    table_obtained = 0.0
                    table_possible = 0.0
                    table_rubrics = [
                        r for r in process_rubric
                        if r.get("id") not in skipped_rubric
                    ] + valid_output_rubrics
                    table_process_rubric = [
                        r for r in process_rubric
                        if r.get("id") not in skipped_rubric
                    ]
                    for r in table_rubrics:
                        table_obtained += get_rubric_score(r)
                        table_possible += 1.0
                    
                    if category not in category_stats:
                        category_stats[category] = {"obtained": 0.0, "possible": 0.0, "case_count": 0}
                    if category not in table_category_stats:
                        table_category_stats[category] = {"obtained": 0.0, "possible": 0.0, "case_count": 0}
                        
                    category_stats[category]["obtained"] += obtained
                    category_stats[category]["possible"] += possible
                    category_stats[category]["case_count"] += 1

                    table_category_stats[category]["obtained"] += table_obtained
                    table_category_stats[category]["possible"] += table_possible
                    table_category_stats[category]["case_count"] += 1
                    
                    total_obtained += obtained
                    total_possible += possible
                    table_total_obtained += table_obtained
                    table_total_possible += table_possible

                    add_rubric_stats(category_rubric_stats, category, "process_rubric", process_rubric)
                    add_rubric_stats(category_rubric_stats, category, "output_rubric", valid_output_rubrics)
                    add_rubric_stats(table_category_rubric_stats, category, "process_rubric", table_process_rubric)
                    add_rubric_stats(table_category_rubric_stats, category, "output_rubric", valid_output_rubrics)
                    
                except Exception as e:
                    print(f"Failed to parse {rubrics_path}: {e}")

            human_rubrics_path = os.path.join(item_path, "evals_human", "rubric.json")
            if os.path.isfile(human_rubrics_path):
                try:
                    with open(human_rubrics_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    category = data.get("category", "unknown")
                    process_rubric = data.get("process_rubric", [])
                    output_rubric = data.get("output_rubric", [])

                    obtained = 0.0
                    possible = 0.0
                    for r in process_rubric + output_rubric:
                        obtained += get_rubric_score(r)
                        possible += 1.0

                    if category not in human_category_stats:
                        human_category_stats[category] = {"obtained": 0.0, "possible": 0.0, "case_count": 0}

                    human_category_stats[category]["obtained"] += obtained
                    human_category_stats[category]["possible"] += possible
                    human_category_stats[category]["case_count"] += 1

                    human_total_obtained += obtained
                    human_total_possible += possible

                    add_rubric_stats(human_category_rubric_stats, category, "process_rubric", process_rubric)
                    add_rubric_stats(human_category_rubric_stats, category, "output_rubric", output_rubric)

                except Exception as e:
                    print(f"Failed to parse {human_rubrics_path}: {e}")
        total_cases = 0
        for cat, stats in category_stats.items():
            avg_score = stats["obtained"] / stats["possible"] if stats["possible"] > 0 else 0.0
            summary["scores_by_category"][cat] = {
                "score": avg_score,
                "obtained_points": stats["obtained"],
                "possible_points": stats["possible"],
                "case_count": stats["case_count"]
            }
            if cat in category_rubric_stats:
                summary["scores_by_category"][cat]["rubric_scores"] = format_rubric_stats(category_rubric_stats[cat])
                merge_overall_rubric_stats(overall_rubric_stats, category_rubric_stats[cat])
            total_cases += stats["case_count"]

        table_total_cases = 0
        for cat, stats in table_category_stats.items():
            avg_score = stats["obtained"] / stats["possible"] if stats["possible"] > 0 else 0.0
            table_summary["scores_by_category"][cat] = {
                "score": avg_score,
                "obtained_points": stats["obtained"],
                "possible_points": stats["possible"],
                "case_count": stats["case_count"]
            }
            if cat in table_category_rubric_stats:
                table_summary["scores_by_category"][cat]["rubric_scores"] = format_rubric_stats(table_category_rubric_stats[cat])
                merge_overall_rubric_stats(table_overall_rubric_stats, table_category_rubric_stats[cat])
            table_total_cases += stats["case_count"]
            
        summary["overall_score"] = total_obtained / total_possible if total_possible > 0 else 0.0
        summary["total_obtained"] = total_obtained
        summary["total_possible"] = total_possible
        summary["total_cases"] = total_cases
        summary["overall_rubric_scores"] = format_rubric_stats(overall_rubric_stats)

        table_summary["overall_score"] = table_total_obtained / table_total_possible if table_total_possible > 0 else 0.0
        table_summary["total_obtained"] = table_total_obtained
        table_summary["total_possible"] = table_total_possible
        table_summary["total_cases"] = table_total_cases
        table_summary["overall_rubric_scores"] = format_rubric_stats(table_overall_rubric_stats)

        human_total_cases = 0
        for cat, stats in human_category_stats.items():
            avg_score = stats["obtained"] / stats["possible"] if stats["possible"] > 0 else 0.0
            human_summary["scores_by_category"][cat] = {
                "score": avg_score,
                "obtained_points": stats["obtained"],
                "possible_points": stats["possible"],
                "case_count": stats["case_count"]
            }
            if cat in human_category_rubric_stats:
                human_summary["scores_by_category"][cat]["rubric_scores"] = format_rubric_stats(human_category_rubric_stats[cat])
                merge_overall_rubric_stats(human_overall_rubric_stats, human_category_rubric_stats[cat])
            human_total_cases += stats["case_count"]

        human_summary["overall_score"] = human_total_obtained / human_total_possible if human_total_possible > 0 else 0.0
        human_summary["total_obtained"] = human_total_obtained
        human_summary["total_possible"] = human_total_possible
        human_summary["total_cases"] = human_total_cases
        human_summary["overall_rubric_scores"] = format_rubric_stats(human_overall_rubric_stats)
        
        summary_path = os.path.join(new_generate_materials_dir, "llm_deterministic_summary.json")
        try:
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=4)
            print(f"Summary successfully written to {summary_path}")
        except Exception as e:
            print(f"Failed to write summary: {e}")

        summary_markdown_path = os.path.join(new_generate_materials_dir, "llm_deterministic_summary.md")
        try:
            write_markdown_table(summary, summary_markdown_path)
            print(f"Deterministic markdown table successfully written to {summary_markdown_path}")
        except Exception as e:
            print(f"Failed to write deterministic markdown table: {e}")

        table_summary_path = os.path.join(new_generate_materials_dir, "llm_deterministic_summary_table.json")
        try:
            with open(table_summary_path, "w", encoding="utf-8") as f:
                json.dump(table_summary, f, ensure_ascii=False, indent=4)
            print(f"Table summary successfully written to {table_summary_path}")
        except Exception as e:
            print(f"Failed to write table summary: {e}")

        table_markdown_path = os.path.join(new_generate_materials_dir, "llm_deterministic_summary_table.md")
        try:
            write_markdown_table(table_summary, table_markdown_path)
            print(f"Markdown table successfully written to {table_markdown_path}")
        except Exception as e:
            print(f"Failed to write markdown table: {e}")

        human_summary_path = os.path.join(new_generate_materials_dir, "human_summary.json")
        try:
            with open(human_summary_path, "w", encoding="utf-8") as f:
                json.dump(human_summary, f, ensure_ascii=False, indent=4)
            print(f"Human summary successfully written to {human_summary_path}")
        except Exception as e:
            print(f"Failed to write human summary: {e}")

        human_markdown_path = os.path.join(new_generate_materials_dir, "human_summary.md")
        try:
            write_markdown_table(human_summary, human_markdown_path)
            print(f"Human markdown table successfully written to {human_markdown_path}")
        except Exception as e:
            print(f"Failed to write human markdown table: {e}")

        complete_markdown_path = os.path.join(new_generate_materials_dir, "完整.md")
        try:
            write_complete_markdown(table_summary, human_summary, complete_markdown_path)
            print(f"Complete markdown summary successfully written to {complete_markdown_path}")
        except Exception as e:
            print(f"Failed to write complete markdown summary: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch Run OpenClaw Agent Eval")
    parser.add_argument("--agent_id", type=str, default="main", help="Agent ID")
    parser.add_argument("--dataset_dir", type=str, default="dataset", help="Path to the dataset directory")
    parser.add_argument("--output_dir", type=str, default="20260401_1449_expert_generate_materials", help="Path to the directory containing output generated materials")
    parser.add_argument("--max_concurrency", type=int, default=20, help="Maximum number of concurrent tasks")
    parser.add_argument("--thinking", action="store_true", help="Enable thinking mode")
    parser.add_argument("--timeout_seconds", type=int, default=7200, help="Execution timeout in seconds")
    parser.add_argument("--max_retries", type=int, default=3, help="Maximum number of retries for rate limit errors")
    parser.add_argument("--retry_delay", type=int, default=60, help="Delay in seconds before retrying")
    args = parser.parse_args()

    new_generate_materials_dir = os.path.abspath(os.path.expanduser(args.output_dir))
    if not os.path.isdir(new_generate_materials_dir):
        print(f"Output directory not found: {new_generate_materials_dir}")
        exit(1)

    done_sessions = set()
    for item in os.listdir(new_generate_materials_dir):
        if os.path.isdir(os.path.join(new_generate_materials_dir, item)):
            done_sessions.add(item)
    failed_sessions = set()

    from AutomaticSkillOptimization.utils import generate_basic_results_summary
    generate_eval_summary(args, done_sessions, failed_sessions, new_generate_materials_dir)
    generate_basic_results_summary(new_generate_materials_dir)
