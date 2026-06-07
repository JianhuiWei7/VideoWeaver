import json
import os
import shutil

WS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CONFIG_DIR = os.path.join(WS_ROOT, "AutomaticSkillOptimization", "configuration_files")

CODEX_WORKSPACE = os.path.join(WS_ROOT, "_codex_workspace")
CODEX_BIN = shutil.which("codex") or os.path.expanduser("~/.npm-global/bin/codex")
CODEX_SESSIONS_DIR = os.path.expanduser("~/.codex/sessions")

CLAUDE_BIN = shutil.which("claude") or os.path.expanduser("~/.npm-global/bin/claude")
CLAUDE_WORKSPACE = os.path.join(WS_ROOT, "_claude_workspace")

OPENCLAW_WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
OPENCLAW_SETTING_FILE = os.path.expanduser("~/.openclaw/openclaw.json")
OPENCLAW_APPROVAL_FILE = os.path.expanduser("~/.openclaw/exec-approvals.json")
EXTRA_SKILL_LOADING_DIR = [
    os.path.join(OPENCLAW_WORKSPACE, "composition_skills_vanilla"),
    os.path.join(OPENCLAW_WORKSPACE, "composition_skills_expert"),
]

FOUNDATION_SKILLS_DIR = os.path.join(WS_ROOT, "skills")
DATASET_DIR = os.path.join(WS_ROOT, "dataset")

OUTPUT_DIR = os.path.join(WS_ROOT, "generate_materials")
HALF_STOPPED_DIR = OUTPUT_DIR + "_half_stopped"
FAILED_DIR = OUTPUT_DIR + "_failed"
RUNNING_DIR = os.path.join(os.path.dirname(OUTPUT_DIR), "running_logs")
BACKUP_DIR = os.path.join(WS_ROOT, "backups")
BACKUP_ORIGINAL_CREATOR_PATH_EXPERT = os.path.join(BACKUP_DIR, "original_video-skill-creator")
BACKUP_ORIGINAL_CREATOR_PATH_VANILLA = os.path.join(BACKUP_DIR, "original_skill-creator")

# OpenClaw creator path
ORIGINAL_CREATOR_PATH_EXPERT = os.path.join(OPENCLAW_WORKSPACE, "skills", "video-skill-creator")
ORIGINAL_CREATOR_PATH_VANILLA = os.path.join(OPENCLAW_WORKSPACE, "skills", "skill-creator")

# CodeX creator path
CODEX_ORIGINAL_CREATOR_PATH_EXPERT = os.path.join(CODEX_WORKSPACE, ".agents", "skills", "video-skill-creator")
CODEX_ORIGINAL_CREATOR_PATH_VANILLA = os.path.join(CODEX_WORKSPACE, ".agents", "skills", "skill-creator")

# Claude Code creator path
CLAUDE_ORIGINAL_CREATOR_PATH_EXPERT = os.path.join(CLAUDE_WORKSPACE, ".claude", "skills", "video-skill-creator")
CLAUDE_ORIGINAL_CREATOR_PATH_VANILLA = os.path.join(CLAUDE_WORKSPACE, ".claude", "skills", "skill-creator")


def _copy_skills(workspace_dir, agents_subdir):
    agents_dir = os.path.join(workspace_dir, agents_subdir)
    skills_path = os.path.join(agents_dir, "skills")
    os.makedirs(agents_dir, exist_ok=True)

    if os.path.realpath(skills_path) == os.path.realpath(FOUNDATION_SKILLS_DIR):
        return

    if os.path.lexists(skills_path):
        if os.path.islink(skills_path) or os.path.isfile(skills_path):
            os.unlink(skills_path)
        else:
            shutil.rmtree(skills_path)

    shutil.copytree(FOUNDATION_SKILLS_DIR, skills_path)


def setup_codex_workspace():
    os.makedirs(CODEX_WORKSPACE, exist_ok=True)

    # CodeX mutates the fixed skill dir for baseline/existing-skill runs, so use
    # a private copy instead of a symlink to avoid modifying FOUNDATION_SKILLS_DIR.
    _copy_skills(CODEX_WORKSPACE, ".agents")

    src = os.path.join(_CONFIG_DIR, "codex", "AGENTS.md")
    dst = os.path.join(CODEX_WORKSPACE, "AGENTS.md")
    if not os.path.exists(dst):
        shutil.copy2(src, dst)

    codex_dir = os.path.join(CODEX_WORKSPACE, ".codex")
    os.makedirs(codex_dir, exist_ok=True)
    dst = os.path.join(codex_dir, "config.toml")

    src = os.path.join(_CONFIG_DIR, "codex", "config.toml")
    with open(src, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("{{OUTPUT_DIR}}", OUTPUT_DIR)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(content)


def setup_claude_workspace():
    os.makedirs(CLAUDE_WORKSPACE, exist_ok=True)

    # Claude may also mutate loaded skills during experiments; use a private copy.
    _copy_skills(CLAUDE_WORKSPACE, ".claude")

    claude_dir = os.path.join(CLAUDE_WORKSPACE, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    dst = os.path.join(claude_dir, "settings.json")

    src = os.path.join(_CONFIG_DIR, "claude", "settings.json")
    with open(src, "r", encoding="utf-8") as f:
        settings = json.load(f)

    settings.setdefault("env", {})["OUTPUT_DIR"] = OUTPUT_DIR

    with open(dst, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def setup_openclaw_workspace():
    os.makedirs(OPENCLAW_WORKSPACE, exist_ok=True)
    # OPENCLAW_WORKSPACE is usually this workspace, so skills/ may already be the
    # foundation source. _copy_skills guards that case and only copies otherwise.
    _copy_skills(OPENCLAW_WORKSPACE, "")

    # --- openclaw.json: OUTPUT_DIR + skills.load.extraDirs ---
    if not os.path.isfile(OPENCLAW_SETTING_FILE):
        print(f"WARNING: openclaw setting file not found: {OPENCLAW_SETTING_FILE}")
        return

    with open(OPENCLAW_SETTING_FILE, "r", encoding="utf-8") as f:
        settings = json.load(f)

    existing_output_dir = settings.get("env", {}).get("OUTPUT_DIR")
    if existing_output_dir is not None:
        existing_output_path = os.path.abspath(os.path.expanduser(existing_output_dir))
        expected_output_path = os.path.abspath(os.path.expanduser(OUTPUT_DIR))
        if existing_output_path != expected_output_path:
            print(f"CONFLICT: env.OUTPUT_DIR already set to '{existing_output_dir}' (expected '{OUTPUT_DIR}'), aborting setup.")
            return
    else:
        settings.setdefault("env", {})["OUTPUT_DIR"] = OUTPUT_DIR

    # --- exec-approvals.json: defaults.security = full ---
    if os.path.isfile(OPENCLAW_APPROVAL_FILE):
        with open(OPENCLAW_APPROVAL_FILE, "r", encoding="utf-8") as f:
            approvals = json.load(f)
        existing_security = approvals.get("defaults", {}).get("security")
        if existing_security is not None:
            if existing_security != "full":
                print(f"CONFLICT: exec-approvals.json defaults.security already set to '{existing_security}' (expected 'full'), aborting setup.")
                return
        else:
            approvals.setdefault("defaults", {})["security"] = "full"
    else:
        approvals = {}
        approvals.setdefault("defaults", {})["security"] = "full"

    # --- write openclaw.json ---
    skills_load = settings.setdefault("skills", {}).setdefault("load", {})
    skills_load["watch"] = True
    skills_load["watchDebounceMs"] = 250

    existing_extra = skills_load.get("extraDirs", [])
    for d in EXTRA_SKILL_LOADING_DIR:
        if d not in existing_extra:
            skills_load.setdefault("extraDirs", []).append(d)

    with open(OPENCLAW_SETTING_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    print(f"Updated {OPENCLAW_SETTING_FILE}")

    # --- write exec-approvals.json ---
    approvals.setdefault("defaults", {})["security"] = "full"
    with open(OPENCLAW_APPROVAL_FILE, "w", encoding="utf-8") as f:
        json.dump(approvals, f, ensure_ascii=False, indent=2)
    print("=" * 62)
    print("⚠️  WARNING: Set exec-approvals.json defaults.security to 'full'.")
    print("⚠️  This allows ALL file edits and writes without approval.")
    print("=" * 62)
