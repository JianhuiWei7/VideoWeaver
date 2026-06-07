## Python Environments
Make sure that the default python environment has installed the packages listed in `environment.txt`
openclaw usually do not use conda environment.

## Environment Configuration Patch

To bypass the default execution timeout limitation in `openclaw_sdk`, you need to manually modify the package configuration file.

**Target File:**
`envs/<self-env-name>/lib/python3.13/site-packages/openclaw_sdk/core/config.py`

**Modification (around Line 110):**
Change the maximum timeout limit from `3600` seconds to `100000` seconds.

```diff
- timeout_seconds: int = Field(default=300, ge=1, le=3600)
+ timeout_seconds: int = Field(default=300, ge=1, le=100000)
```

## Environment Variables and settings
You should set these environment variables and other settings in the openclaw.json file:

**⚠️ Important Note:** Please **merge (add)** these settings into your existing `~/.openclaw/openclaw.json` file. Do not directly replace the entire file, as you may overwrite and lose your other existing configurations. ALSO replace all the `~` to actual path.

```json
{
  "skills": {
      "load": {
        "extraDirs": [
          "~/.openclaw/workspace/composition_skills_vanilla",
          "~/.openclaw/workspace/composition_skills_expert"
        ],
        "watch": true,
        "watchDebounceMs": 250
      }
  },
  "env": {
    "shellEnv": {
      "enabled": false,
      "timeoutMs": 15000
    },
    "vars": {},
    "OUTPUT_DIR": "~/.openclaw/workspace/generate_materials",
    "ARK_API_KEY": "xxx",
    "TOS_ACCESS_KEY": "xxx",
    "TOS_SECRET_KEY": "xxx",
    "ASR_APPID": "xxx",
    "ASR_TOKEN": "xxx",
    "APP_ID": "xxx",
    "APP_SECRET": "xxx"
  },
  "agents": {
    "defaults": {
      "timeoutSeconds": 21600,
      "verboseDefault": "full",
      "maxConcurrent": 100,
      "subagents": {
        "maxConcurrent": 100
      }
    },
    "list": [
      {
        "id": "main"
      },
      {
        // OPTIONAL: here you can set multiple agents with the same model(use different ARK_API_KEY) as the backbone to increase concurrency.
        // id is recommended to start with main
        "id": "main2",
        "name": "main2",
        "agentDir": "~/.openclaw/agents/main2/agent",
        "workspace": "~/.openclaw/workspace",
        "model": "provider/model_id",
        "model": "doubao2/doubao-seed-2-0-pro-260215"

      }
    ]
  },
}
```

You should set the exec approvals in the `~/.openclaw/exec-approvals.json` file:
```json
"defaults": {
    "security": "full"
  },
```



