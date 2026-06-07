import difflib
import json
import os
import shutil

from tqdm import tqdm

from AutomaticSkillOptimization.utils import parse_result_dir_name, safe_segment


EXCLUDED_OBJECTIVE_CRITERIA = {
    "通过率",
    "输出目录合规性",
    "未调用子智能体工具 (subagent/session_spawn)",
}
EXCLUDED_FEEDBACK_IDS = {"fixed_P5"}


def collect_relative_files(root_dir):
    files = set()
    if not os.path.isdir(root_dir):
        return files

    for current_root, _, filenames in os.walk(root_dir):
        for filename in filenames:
            full_path = os.path.join(current_root, filename)
            files.add(os.path.relpath(full_path, root_dir))
    return files


def read_text_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def is_binary_file(path):
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
        return b"\0" in chunk
    except Exception:
        return True


def build_file_diff(old_file, new_file, old_label, new_label):
    if is_binary_file(old_file) or is_binary_file(new_file):
        old_size = os.path.getsize(old_file) if old_file and os.path.isfile(old_file) else 0
        new_size = os.path.getsize(new_file) if new_file and os.path.isfile(new_file) else 0
        if old_size == new_size and old_file and new_file:
            try:
                with open(old_file, "rb") as f:
                    old_bytes = f.read()
                with open(new_file, "rb") as f:
                    new_bytes = f.read()
                if old_bytes == new_bytes:
                    return []
            except Exception:
                pass
        return [
            f"Binary files differ: {old_label} ({old_size} bytes) -> {new_label} ({new_size} bytes)"
        ]

    old_lines = read_text_lines(old_file) if old_file and os.path.isfile(old_file) else []
    new_lines = read_text_lines(new_file) if new_file and os.path.isfile(new_file) else []
    if old_lines == new_lines:
        return []
    return list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=old_label,
        tofile=new_label,
        lineterm="",
    ))


def write_dir_diff_markdown(old_dir, new_dir, output_file, title):
    old_files = collect_relative_files(old_dir)
    new_files = collect_relative_files(new_dir)
    all_files = sorted(old_files | new_files)
    changed_files = []
    diff_blocks = []

    for rel_file in all_files:
        old_file = os.path.join(old_dir, rel_file) if rel_file in old_files else None
        new_file = os.path.join(new_dir, rel_file) if rel_file in new_files else None
        old_label = os.path.join(os.path.basename(old_dir), rel_file) if old_file else f"/dev/null/{rel_file}"
        new_label = os.path.join(os.path.basename(new_dir), rel_file) if new_file else f"/dev/null/{rel_file}"
        diff_lines = build_file_diff(old_file, new_file, old_label, new_label)
        if not diff_lines:
            continue
        changed_files.append(rel_file)
        diff_blocks.append((rel_file, diff_lines))

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"- Original: `{old_dir}`\n")
        f.write(f"- Optimized: `{new_dir}`\n")
        f.write(f"- Changed files: {len(changed_files)}\n\n")

        if not changed_files:
            f.write("No differences found.\n")
            return changed_files

        f.write("## Changed Files\n\n")
        for rel_file in changed_files:
            f.write(f"- `{rel_file}`\n")

        for rel_file, diff_lines in diff_blocks:
            f.write(f"\n## `{rel_file}`\n\n")
            f.write("````diff\n")
            f.write("\n".join(diff_lines))
            if diff_lines and not diff_lines[-1].endswith("\n"):
                f.write("\n")
            f.write("````\n")

    return changed_files


def generate_optimization_diffs(original_skill_dir, optimized_skill_dir, original_creator_dir,
                                optimized_creator_dir, diff_dir):
    os.makedirs(diff_dir, exist_ok=True)
    skills_diff_dir = os.path.join(diff_dir, "skills")
    os.makedirs(skills_diff_dir, exist_ok=True)

    original_skill_names = {
        item for item in os.listdir(original_skill_dir)
        if os.path.isdir(os.path.join(original_skill_dir, item))
    } if os.path.isdir(original_skill_dir) else set()
    optimized_skill_names = {
        item for item in os.listdir(optimized_skill_dir)
        if os.path.isdir(os.path.join(optimized_skill_dir, item))
    } if os.path.isdir(optimized_skill_dir) else set()

    matched_skill_names = sorted(original_skill_names & optimized_skill_names)
    only_original = sorted(original_skill_names - optimized_skill_names)
    only_optimized = sorted(optimized_skill_names - original_skill_names)
    skill_diff_records = []

    for skill_name in tqdm(matched_skill_names, desc="Generating Skill Diffs"):
        old_skill_dir = os.path.join(original_skill_dir, skill_name)
        new_skill_dir = os.path.join(optimized_skill_dir, skill_name)
        output_file = os.path.join(skills_diff_dir, f"{safe_segment(skill_name)}.md")
        changed_files = write_dir_diff_markdown(
            old_skill_dir,
            new_skill_dir,
            output_file,
            f"Skill Diff: {skill_name}",
        )
        skill_diff_records.append((skill_name, output_file, changed_files))

    creator_diff_file = os.path.join(diff_dir, "video-skill-creator.md")
    creator_changed_files = []
    if os.path.isdir(original_creator_dir) and os.path.isdir(optimized_creator_dir):
        creator_changed_files = write_dir_diff_markdown(
            original_creator_dir,
            optimized_creator_dir,
            creator_diff_file,
            "Creator Skill Diff: video-skill-creator",
        )

    index_file = os.path.join(diff_dir, "INDEX.md")
    with open(index_file, "w", encoding="utf-8") as f:
        f.write("# Optimization Diff Index\n\n")
        f.write(f"- Original skills: `{original_skill_dir}`\n")
        f.write(f"- Optimized skills: `{optimized_skill_dir}`\n")
        f.write(f"- Original creator: `{original_creator_dir}`\n")
        f.write(f"- Optimized creator: `{optimized_creator_dir}`\n\n")
        f.write(f"- Matched skill folders: {len(matched_skill_names)}\n")
        f.write(f"- Only in original skills: {len(only_original)}\n")
        f.write(f"- Only in optimized skills: {len(only_optimized)}\n")
        f.write(f"- Creator changed files: {len(creator_changed_files)}\n\n")

        if only_original:
            f.write("## Only In Original Skills\n\n")
            for skill_name in only_original:
                f.write(f"- `{skill_name}`\n")
            f.write("\n")

        if only_optimized:
            f.write("## Only In Optimized Skills\n\n")
            for skill_name in only_optimized:
                f.write(f"- `{skill_name}`\n")
            f.write("\n")

        f.write("## Matched Skill Diffs\n\n")
        for skill_name, output_file, changed_files in skill_diff_records:
            rel_path = os.path.relpath(output_file, diff_dir)
            f.write(f"- [{skill_name}]({rel_path}) - changed files: {len(changed_files)}\n")

        if os.path.isfile(creator_diff_file):
            f.write("\n## Creator Diff\n\n")
            f.write(f"- [video-skill-creator](video-skill-creator.md) - changed files: {len(creator_changed_files)}\n")

    return index_file


def archive_dir_if_exists(src_dir, dst_parent, dst_name):
    if not os.path.isdir(src_dir):
        return None

    os.makedirs(dst_parent, exist_ok=True)
    dst_path = os.path.join(dst_parent, dst_name)
    if os.path.exists(dst_path):
        shutil.rmtree(dst_path)
    shutil.move(src_dir, dst_path)
    return dst_path


def get_llm_eval_path(item_path):
    eval_file = os.path.join(item_path, "evals", "rubrics_eval.json")
    return eval_file if os.path.isfile(eval_file) else None


def get_human_eval_path(item_path):
    output_eval_item_path = os.path.join(
        f"{os.path.dirname(item_path).rstrip(os.sep)}_output_eval",
        os.path.basename(item_path),
    )
    eval_file = os.path.join(output_eval_item_path, "evals_human", "rubric_eval_detail.json")
    return eval_file if os.path.isfile(eval_file) else None


def load_eval_data(eval_path):
    if not eval_path:
        return {}

    with open(eval_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        return {}

    return data


def get_eval_paths(item_path, eval_source):
    if eval_source == "none":
        return []

    paths = []
    if eval_source in ["llm", "both"]:
        llm_eval_path = get_llm_eval_path(item_path)
        if llm_eval_path:
            paths.append(llm_eval_path)

    if eval_source in ["human", "both"]:
        human_eval_path = get_human_eval_path(item_path)
        if human_eval_path:
            paths.append(human_eval_path)

    return paths


def get_objective_eval_paths(item_path, eval_source):
    if eval_source == "none":
        return get_eval_paths(item_path, "both")

    return get_eval_paths(item_path, eval_source)


def iter_rubric_items(eval_data):
    if not isinstance(eval_data, dict):
        return

    for rubric_key in ["process_rubric", "output_rubric"]:
        rubric_list = eval_data.get(rubric_key, [])
        if not isinstance(rubric_list, list):
            continue

        for item in rubric_list:
            if isinstance(item, dict):
                yield item


def extract_objective_criteria(item_path, eval_source):
    objectives = []
    seen = set()

    for eval_path in get_objective_eval_paths(item_path, eval_source):
        try:
            eval_data = load_eval_data(eval_path)
        except Exception:
            continue

        for item in iter_rubric_items(eval_data):
            criterion = item.get("criterion")
            if not criterion:
                continue

            criterion = " ".join(str(criterion).split())
            if not criterion or criterion in seen:
                continue
            if criterion in EXCLUDED_OBJECTIVE_CRITERIA:
                continue

            natural_language_question = item.get("natural_language_question", "")
            if natural_language_question:
                natural_language_question = " ".join(str(natural_language_question).split())

            seen.add(criterion)
            objective = {"criterion": criterion}
            if natural_language_question:
                objective["natural_language_question"] = natural_language_question
            objectives.append(objective)

    return objectives


def append_valid_human_feedback(eval_data, human_eval_path):
    try:
        h_data = load_eval_data(human_eval_path)

        atoms = h_data.get("atoms", [])
        if isinstance(atoms, list):
            for h_item in atoms:
                if not isinstance(h_item, dict):
                    continue
                h_score = h_item.get("score")
                h_feedback = h_item.get("feedback", "")
                h_evidence = h_item.get("evidence", "")
                if h_score is None and h_feedback == "" and h_evidence == "":
                    continue

                if h_feedback == "" and h_evidence:
                    h_item["feedback"] = h_evidence

                for metadata_key in ("confidence", "data_sources", "model_calls"):
                    h_item.pop(metadata_key, None)

                rubric_id = str(h_item.get("id", ""))
                rubric_key = "process_rubric" if rubric_id.startswith(("P", "fixed_P")) else "output_rubric"
                if rubric_key not in eval_data:
                    eval_data[rubric_key] = []
                eval_data[rubric_key].append(h_item)

        for rubric_key in ["process_rubric", "output_rubric"]:
            h_rubrics = h_data.get(rubric_key, [])

            for h_item in h_rubrics:
                h_score = h_item.get("分数")
                h_feedback = h_item.get("反馈")

                if h_score != "" or h_feedback != "":
                    if h_score != "":
                        h_item["score"] = float(h_score) if isinstance(h_score, (int, float, str)) else h_score

                    if h_feedback != "":
                        h_item["feedback"] = h_feedback

                    if rubric_key not in eval_data:
                        eval_data[rubric_key] = []
                    eval_data[rubric_key].append(h_item)
    except Exception:
        pass

    return eval_data


def normalize_human_eval_data(human_eval_path):
    eval_data = {"process_rubric": [], "output_rubric": []}
    return append_valid_human_feedback(eval_data, human_eval_path)


def is_low_score_rubric_item(rubric_item):
    try:
        return float(rubric_item.get("score", rubric_item.get("分数", 1))) < 1.0
    except (TypeError, ValueError):
        return False


def is_excluded_feedback_item(rubric_item):
    rubric_id = str(rubric_item.get("id", ""))
    criterion = rubric_item.get("criterion")
    return rubric_id in EXCLUDED_FEEDBACK_IDS or criterion in EXCLUDED_OBJECTIVE_CRITERIA


def keep_only_low_score_feedback(eval_data):
    if not isinstance(eval_data, dict):
        return eval_data

    filtered = dict(eval_data)
    for rubric_key in ["process_rubric", "output_rubric"]:
        rubric_list = eval_data.get(rubric_key, [])
        if not isinstance(rubric_list, list):
            filtered[rubric_key] = []
            continue
        filtered[rubric_key] = [
            item for item in rubric_list
            if (
                isinstance(item, dict)
                and is_low_score_rubric_item(item)
                and not is_excluded_feedback_item(item)
            )
        ]
    return filtered


def load_eval_feedback_data(item_path, eval_source):
    if eval_source == "none":
        return None

    if eval_source == "llm":
        llm_eval_path = get_llm_eval_path(item_path)
        if not llm_eval_path:
            return None
        try:
            return keep_only_low_score_feedback(load_eval_data(llm_eval_path))
        except Exception:
            return None

    if eval_source == "human":
        human_eval_path = get_human_eval_path(item_path)
        if not human_eval_path:
            return None
        return keep_only_low_score_feedback(normalize_human_eval_data(human_eval_path))

    if eval_source == "both":
        eval_data = {"process_rubric": [], "output_rubric": []}
        found_eval = False

        llm_eval_path = get_llm_eval_path(item_path)
        if llm_eval_path:
            try:
                eval_data = load_eval_data(llm_eval_path)
                found_eval = True
            except Exception:
                pass

        human_eval_path = get_human_eval_path(item_path)
        if human_eval_path:
            eval_data = append_valid_human_feedback(eval_data, human_eval_path)
            found_eval = True

        if not found_eval:
            return None

        return keep_only_low_score_feedback(eval_data)

    return None


def prepare_eval_data(item_path, args):
    if args.eval_source == "none":
        return {
            "objective_criteria": extract_objective_criteria(item_path, args.eval_source)
        }

    return load_eval_feedback_data(item_path, args.eval_source)


def has_low_score(eval_data):
    for rubric_list in [eval_data.get("process_rubric", []), eval_data.get("output_rubric", [])]:
        for rubric_item in rubric_list:
            if is_low_score_rubric_item(rubric_item):
                return True
    return False


def load_allowed_cases(dataset_dir, split_file, split_name):
    if split_name == "all":
        return None

    if split_file is None:
        candidate = os.path.join(dataset_dir, "split_train_test_ood.json")
        split_file = candidate if os.path.isfile(candidate) else None

    if split_file is None:
        print("No split file found; optimizing over all datapoints.")
        return None

    split_file = os.path.abspath(os.path.expanduser(split_file))
    if not os.path.isfile(split_file):
        raise FileNotFoundError(f"Split file not found: {split_file}")

    with open(split_file, "r", encoding="utf-8") as f:
        split_data = json.load(f)

    split_items = split_data.get(split_name)
    if not isinstance(split_items, list):
        raise ValueError(f"Split file {split_file} does not contain a list for '{split_name}'")

    allowed_cases = set()
    for item in split_items:
        parts = str(item).strip("/").split("/")
        if len(parts) < 2:
            continue
        allowed_cases.add((parts[0], parts[1]))

    print(f"Loaded split '{split_name}' from {split_file}: {len(allowed_cases)} cases.")
    return allowed_cases
