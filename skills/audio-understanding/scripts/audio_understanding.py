import os
import time
import argparse
import mimetypes
from openai import OpenAI
from volcenginesdkarkruntime import Ark

# 全局配置
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"
MAX_RETRIES = 15
WAIT_SECONDS = 5

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}


def _upload_audio_to_ark(audio_path: str):
    """上传音频文件到 Ark，返回 file_id"""
    api_key = os.getenv("ARK_API_KEY")
    client = Ark(api_key=api_key)

    mime_type, _ = mimetypes.guess_type(audio_path)
    ext = os.path.splitext(audio_path)[1].lower()
    if not (mime_type and mime_type.startswith("audio/")) and ext not in AUDIO_EXTS:
        raise ValueError(f"不支持的文件类型: {audio_path}，仅支持音频文件 ({sorted(AUDIO_EXTS)})")

    file = client.files.create(
        file=open(audio_path, "rb"),
        purpose="user_data",
    )

    # 等待文件处理完成
    while file.status == "processing":
        time.sleep(2)
        file = client.files.retrieve(file.id)

    return file.id


def audio_understanding(
    audio_paths: list[str],
    prompt: str,
    model: str = DEFAULT_MODEL,
) -> str:
    """
    统一的音频理解接口，支持同时传入多段音频，按顺序进行理解
    :param audio_paths: 音频文件路径列表，按传入顺序处理
    :param prompt: 查询提示词
    :param model: 要使用的模型，默认 doubao-seed-2-0-lite-260428（火山方舟当前支持音频输入的多模态模型）
    :return: 内容描述文本
    """
    api_key = os.getenv("ARK_API_KEY")

    client = OpenAI(
        base_url=ARK_BASE_URL,
        api_key=api_key,
    )

    content_list = []
    ark_client = Ark(base_url=ARK_BASE_URL, api_key=api_key)
    try:
        for idx, path in enumerate(audio_paths, start=1):
            print(f"正在上传: {os.path.basename(path)}...")
            file_id = _upload_audio_to_ark(path)
            content_list.append({
                "type": "input_audio",
                "file_id": file_id,
            })
            print(f"上传完成: {os.path.basename(path)} -> file_id: {file_id[:20]}... (第 {idx} 段)")

        content_list.append({
            "type": "input_text",
            "text": prompt,
        })
        print(f"音频理解提示词: {prompt}")

        for attempt in range(MAX_RETRIES):
            try:
                print(f"正在分析音频（尝试 {attempt+1}/{MAX_RETRIES}）...")
                response = client.responses.create(
                    model=model,
                    input=[
                        {
                            "role": "user",
                            "content": content_list,
                        }
                    ],
                )

                try:
                    reasoning = response.output[0].summary[0].text
                    if reasoning:
                        print(f"\n[Audio Understanding Reasoning]\n{reasoning}\n")
                except Exception:
                    pass

                return response.output[1].content[0].text.strip()

            except Exception as e:
                err_str = str(e).lower()
                if "invalid state" in err_str and "processing" in err_str:
                    if attempt == MAX_RETRIES - 1:
                        raise RuntimeError(f"音频文件处理超时，已重试{MAX_RETRIES}次") from e
                    print(f"音频还在处理中，{WAIT_SECONDS}秒后重试...")
                    time.sleep(WAIT_SECONDS)
                    continue
                raise
    finally:
        for item in content_list:
            if "file_id" in item:
                file_id = item["file_id"]
                try:
                    ark_client.files.delete(file_id=file_id)
                    print(f"已自动清理临时文件: {file_id}")
                except Exception as e:
                    print(f"清理临时文件失败 {file_id}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified audio understanding tool based on Volcengine Ark API")
    parser.add_argument("--audio", required=True, nargs='+', help="List of audio file paths (mp3/wav/flac/m4a/ogg/aac)")
    parser.add_argument("--prompt", required=True, help="Question about the audio content")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use, default doubao-seed-2-0-lite-260428 (audio-capable)")

    args = parser.parse_args()

    for path in args.audio:
        if not os.path.exists(path):
            print(f"错误: 音频文件不存在: {path}")
            exit(1)

    try:
        result = audio_understanding(args.audio, args.prompt, args.model)
        print("\n=== 音频理解结果 ===")
        print(result)
    except Exception as e:
        print(f"处理失败: {e}")
        exit(1)
