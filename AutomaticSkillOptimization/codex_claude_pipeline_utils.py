import asyncio
import os
import shutil

from AutomaticSkillOptimization.args import FOUNDATION_SKILLS_DIR, OUTPUT_DIR
from AutomaticSkillOptimization.utils import find_final_video_paths, find_session_dir


def foundation_skill_names():
    if not os.path.isdir(FOUNDATION_SKILLS_DIR):
        return set()
    return {
        item
        for item in os.listdir(FOUNDATION_SKILLS_DIR)
        if os.path.isdir(os.path.join(FOUNDATION_SKILLS_DIR, item))
    }


def clean_composition_skills_from_fixed_dir(skill_dir, dry_run=False, label="fixed skill dir"):
    if not skill_dir or not os.path.isdir(skill_dir):
        return
    preserved_skills = foundation_skill_names()
    for item in sorted(os.listdir(skill_dir)):
        skill_path = os.path.join(skill_dir, item)
        if not os.path.isdir(skill_path) or item in preserved_skills:
            continue
        if dry_run:
            print(f"Dry run: would remove stale composition skill {item} from {label} {skill_dir}")
        else:
            shutil.rmtree(skill_path)
            print(f"Removed stale composition skill {item} from {label}")


def sync_composition_skills_to_fixed_dir(source_dir, skill_dir, dry_run=False, label="fixed skill dir"):
    if not os.path.isdir(source_dir):
        return []
    clean_composition_skills_from_fixed_dir(skill_dir, dry_run=dry_run, label=label)

    source_items = []
    if os.path.isfile(os.path.join(source_dir, "SKILL.md")):
        source_items.append((os.path.basename(os.path.normpath(source_dir)), source_dir))
    else:
        for item in sorted(os.listdir(source_dir)):
            src = os.path.join(source_dir, item)
            if os.path.isdir(src):
                source_items.append((item, src))

    copied = []
    for item, src in source_items:
        dst = os.path.join(skill_dir, item)
        copied.append(item)
        if dry_run:
            print(f"Dry run: would copy composition skill {src} to {dst}")
            continue
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    return copied


def skill_names_in_dir(skill_dir):
    if not os.path.isdir(skill_dir):
        return set()
    if os.path.isfile(os.path.join(skill_dir, "SKILL.md")):
        return {os.path.basename(os.path.normpath(skill_dir))}
    return {
        item
        for item in os.listdir(skill_dir)
        if os.path.isdir(os.path.join(skill_dir, item))
    }


def skill_exists_for_run(skill_name, skill_dir, args):
    if args.use_existing_skill_dir and args.existing_skill_dir:
        return skill_name in skill_names_in_dir(args.existing_skill_dir)
    return os.path.isdir(os.path.join(skill_dir, skill_name))


async def formalize_gen_output(session_name, args, session_ids=None):
    if args.skip_copy:
        return
    if not hasattr(formalize_gen_output, "copy_lock"):
        formalize_gen_output.copy_lock = asyncio.Lock()
    session_id = session_ids.get(session_name) if session_ids else None
    async with formalize_gen_output.copy_lock:
        gen_dir = find_session_dir(session_name, session_id=session_id, search_dirs=[OUTPUT_DIR])
        if gen_dir and os.path.exists(gen_dir) and os.path.dirname(os.path.abspath(gen_dir)) != os.path.abspath(args.new_generate_materials_path):
            final_dst = os.path.join(args.new_generate_materials_path, os.path.basename(gen_dir))
            try:
                if os.path.exists(final_dst):
                    shutil.rmtree(final_dst)
                shutil.move(gen_dir, final_dst)
                print(f"[{session_name}] Moved output to {final_dst}")
            except Exception as e:
                print(f"[{session_name}] Failed to move gen_dir to final dest: {e}")


def check_gen_done(session_name, session_id=None, *, agent_id=None, search_dirs=None, after_timestamp=None):
    """Return a final video path when a generation session has completed."""
    if search_dirs is None:
        search_dirs = [OUTPUT_DIR]

    session_path = find_session_dir(
        session_name,
        agent_id=agent_id,
        session_id=session_id,
        search_dirs=search_dirs,
    )
    if not session_path or not os.path.isdir(session_path):
        return None

    video_paths = find_final_video_paths(session_path)
    if not video_paths:
        return None
    fp = video_paths[0]
    if after_timestamp:
        try:
            if os.path.getmtime(fp) < after_timestamp:
                return None
        except Exception:
            pass
    return fp


def check_gen_artifacts_done(session_name, search_dirs=None, *, agent_id=None, session_id=None):
    """Return session dir when final.mp4, ReAct_process.json, and ReAct_process.txt exist."""
    if search_dirs is None:
        search_dirs = [OUTPUT_DIR]

    session_path = find_session_dir(
        session_name,
        agent_id=agent_id,
        session_id=session_id,
        search_dirs=search_dirs,
    )
    if not session_path or not os.path.isdir(session_path):
        return None
    if not check_gen_done(session_name, session_id, agent_id=agent_id, search_dirs=search_dirs):
        return None
    if not os.path.isfile(os.path.join(session_path, "ReAct_process.json")):
        return None
    if not os.path.isfile(os.path.join(session_path, "ReAct_process.txt")):
        return None
    return session_path
