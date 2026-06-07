"""ReAct_process.json  LLM  ReAct_process.txt——"""

import json
import os

from openai import OpenAI

PROCESS_SUMMARY = (
    "\n"
    "你是一个总结 ReAct 过程的助手。你会被给予一个大语言模型执行任务的过程"
    "（包含思考、工具调用、工具返回结果、最终回答等组成的 JSON 格式数据）。\n"
    "你需要将这个冗长复杂的 JSON 过程简化、总结为一个清晰、易读的步骤列表"
    "（txt 格式）。\n"
    "你需要推理出使用的skill具体是什么，在调用的时候，一直都是exec工具。"
    "但其实是使用某个skill下面的script.\n"
    "这可能是 read, video-gen, image-gen, merge-video等工具的script. "
    "你不能都说是exec工具。而要具体到某个skill\n"
    "并且，你需要将相关的参数也抄写一遍，当用到这些skills的时候。\n\n"
    "具体要求：\n"
    "1. 按时间顺序梳理执行步骤。\n"
    "2. 忽略过分细节的报错和重试，只保留关键动作。\n"
    "3. 格式必须为带有序号的列表，例如：\n"
    "4. 轮询等待的步骤可以不用保留，算作为冗余的消息。\n"
    "[01] 思考：分析用户需求，决定调用 xxx 工具。\n"
    "[02] 调用 xxx skill执行 xxx 任务，输入的参数为: xxx. "
    "并成功获取了 xxx 结果（或遇到 xxx 报错）。\n"
    "[03] 思考：根据上一步的结果，决定接下来...\n"
    "[04] 调用 xxx skill执行 xxx 任务，输入的参数为: xxx. "
    "并成功获取了 xxx 结果（或遇到 xxx 报错）。\n"
    "...\n"
    "[last] 最终回复：向用户输出了最终结果 xxx。\n\n"
    "请直接输出总结后的文本，不需要包含任何其他多余的寒暄或解释。\n"
    "以下是待总结的 JSON 数据：\n"
)

API_KEY = os.getenv("ARK_API_KEY")
DEFAULT_MODEL = "doubao-seed-2-0-pro-260215"
MAX_RETRIES = 3


def _summarize_with_llm(json_content, model):
    if not API_KEY:
        raise RuntimeError("ARK_API_KEY is not set.")

    client = OpenAI(
        api_key=API_KEY,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )

    prompt = f"{PROCESS_SUMMARY}\n\n```json\n{json_content}\n```"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise e


def _process_file(filepath, model):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    out_filepath = os.path.join(os.path.dirname(filepath), "ReAct_process.txt")
    if os.path.exists(out_filepath):
        return {"filepath": filepath, "status": "success", "out": out_filepath}

    flattened_data = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("role") == "assistant":
                if isinstance(item.get("content"), list):
                    flattened_data.extend(item["content"])
                else:
                    flattened_data.append(item)
    elif isinstance(data, dict):
        if "content" in data and isinstance(data["content"], list):
            flattened_data = data["content"]
        else:
            flattened_data = [data]

    summary_text = _summarize_with_llm(
        json.dumps(flattened_data, ensure_ascii=False, indent=2), model
    )

    with open(out_filepath, "w", encoding="utf-8") as f:
        f.write(summary_text)

    return {"filepath": filepath, "status": "success", "out": out_filepath}


def summarize_react_process_txt(react_file_path, session_name=None):
    label = f"[{session_name}] " if session_name else ""
    if not os.path.isfile(react_file_path):
        print(f"{label}Warning: ReAct_process.json not found: {react_file_path}")
        return False

    out_path = os.path.join(os.path.dirname(react_file_path), "ReAct_process.txt")
    if os.path.exists(out_path):
        print(f"{label}ReAct_process.txt already exists. Skipping.")
        return True

    try:
        res = _process_file(react_file_path, DEFAULT_MODEL)
        if res.get("status") != "success":
            print(f"{label}Warning: Step3 summary failed: {res.get('message', 'Unknown error')}")
            return False
        return True
    except Exception as e:
        print(f"{label}Warning: Step3 summary error: {e}")
        return False
