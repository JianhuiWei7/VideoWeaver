# coding: utf-8
import argparse
import base64
import json
import os
import uuid
from typing import Optional, List, Dict

import requests

DEFAULT_HOST = os.getenv("AUDIO_GEN_HOST", "openspeech.bytedance.com")
DEFAULT_ENDPOINT = f"https://{DEFAULT_HOST}/api/v3/tts/unidirectional"
DEFAULT_RESOURCE_ID = os.getenv("AUDIO_GEN_RESOURCE_ID", "seed-tts-2.0")
DEFAULT_SAMPLE_RATE = 24000
SUPPORTED_ENCODINGS = ["mp3", "wav", "pcm", "opus"]
SUCCESS_CODE = 20000000


def _infer_encoding(output_path: str, encoding: Optional[str], fmt: Optional[str]) -> str:
    if encoding:
        return encoding.lower()
    if fmt:
        return fmt.lower()
    _, ext = os.path.splitext(output_path)
    if ext:
        return ext[1:].lower()
    return "mp3"


def tts_generate_to_file(
    text: str,
    voice_type: str,
    encoding: str,
    speed_ratio: float,
    volume_ratio: float,
    pitch_ratio: float,
    sample_rate: int,
    output_path: str,
    api_key: Optional[str] = None,
    app_id: Optional[str] = None,
    access_token: Optional[str] = None,
    resource_id: str = DEFAULT_RESOURCE_ID,
    output_timestamp: Optional[str] = None,
    verbose: bool = False
) -> None:
    headers = {
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }

    # 鉴权方式：优先使用新版API Key，否则使用旧版AppID+Token
    if api_key:
        headers["X-Api-Key"] = api_key
    elif app_id and access_token:
        headers["X-Api-App-Id"] = app_id
        headers["X-Api-Access-Key"] = access_token
    else:
        raise ValueError("Either api_key or app_id+access_token must be provided")

    payload = {
        "user": {
            "uid": str(uuid.uuid4()),
        },
        "req_params": {
            "speaker": voice_type,
            "audio_params": {
                "format": encoding,
                "sample_rate": sample_rate,
                "speed_ratio": speed_ratio,
                "volume_ratio": volume_ratio,
                "pitch_ratio": pitch_ratio,
                "enable_timestamp": output_timestamp is not None,
            },
            "text": text,
            "additions": json.dumps(
                {
                    "disable_markdown_filter": False,
                }
            ),
        },
    }

    session = requests.Session()
    audio_data = bytearray()
    timestamp_data: List[Dict] = []

    try:
        if verbose:
            print(f"Sending request to {DEFAULT_ENDPOINT}")
            print(f"Request ID: {headers['X-Api-Request-Id']}")

        response = session.post(
            DEFAULT_ENDPOINT,
            headers=headers,
            json=payload,
            stream=True,
            timeout=300
        )

        response.raise_for_status()

        if verbose:
            print(f"Response status: {response.status_code}")
            print(f"Log ID: {response.headers.get('X-Tt-Logid', 'N/A')}")

        buffer = ""
        for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
            if not chunk:
                continue

            buffer += chunk
            # 尝试解析完整的JSON对象
            while buffer:
                try:
                    # 查找JSON对象边界
                    if buffer.startswith("{"):
                        # 找到匹配的右括号
                        count = 0
                        end_idx = 0
                        for i, c in enumerate(buffer):
                            if c == "{":
                                count += 1
                            elif c == "}":
                                count -= 1
                                if count == 0:
                                    end_idx = i + 1
                                    break

                        if end_idx == 0:
                            # 不完整的JSON，继续接收
                            break

                        json_str = buffer[:end_idx]
                        buffer = buffer[end_idx:]

                        data = json.loads(json_str)
                        code = data.get("code")
                        message = data.get("message", "")

                        if code != 0 and code != SUCCESS_CODE:
                            raise RuntimeError(f"TTS failed: code={code}, message={message}, log_id={response.headers.get('X-Tt-Logid')}")

                        # 处理音频数据
                        audio_base64 = data.get("data")
                        if audio_base64:
                            audio_bytes = base64.b64decode(audio_base64)
                            audio_data.extend(audio_bytes)
                            if verbose:
                                print(f"Received audio chunk: {len(audio_bytes)} bytes")

                        # 处理时间戳
                        sentence = data.get("sentence")
                        if sentence and output_timestamp:
                            timestamp_data.append(sentence)
                            if verbose:
                                print(f"Received timestamp for: {sentence.get('text', '')}")

                        # 处理结束标记
                        if code == SUCCESS_CODE:
                            if verbose:
                                print(f"合成完成，总字符数: {data.get('usage', {}).get('text_words', 0)}")
                            break

                    else:
                        # 跳过非JSON开头的字符
                        buffer = buffer.lstrip()
                        break

                except json.JSONDecodeError:
                    # 不完整的JSON，继续接收
                    break

        # 检查音频数据
        if not audio_data:
            raise RuntimeError("No audio data received from server")

        # 保存音频文件
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_data)

        # 保存时间戳
        if output_timestamp and timestamp_data:
            os.makedirs(os.path.dirname(os.path.abspath(output_timestamp)) or ".", exist_ok=True)
            with open(output_timestamp, "w", encoding="utf-8") as f:
                json.dump({"sentences": timestamp_data}, f, ensure_ascii=False, indent=2)

        if verbose:
            print(f"音频文件大小: {len(audio_data)} bytes")
            if output_timestamp:
                print(f"时间戳包含 {len(timestamp_data)} 条语句")

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"HTTP request failed: {str(e)}")
    finally:
        session.close()


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OpenSpeech TTS V3 audio generator")
    p.add_argument("--session-key", help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    p.add_argument("--text", required=True, help="Text to synthesize")
    p.add_argument("--voice-type", required=True, help="Voice type id (e.g. zh_female_vv_uranus_bigtts)")
    p.add_argument("--output", default="out.mp3", help="Output audio filename (e.g. out.mp3)")
    p.add_argument("--encoding", choices=SUPPORTED_ENCODINGS, help="Audio encoding (mp3/wav/pcm/opus)")
    p.add_argument("--format", dest="fmt", choices=SUPPORTED_ENCODINGS, help="Alias for --encoding")
    p.add_argument("--speed", type=float, default=1.0, help="Speed ratio, default 1.0, range [0.5, 2.0]")
    p.add_argument("--volume", type=float, default=1.0, help="Volume ratio, default 1.0, range [0.5, 2.0]")
    p.add_argument("--pitch", type=float, default=1.0, help="Pitch ratio, default 1.0, range [0.5, 2.0]")
    p.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE, choices=[8000, 16000, 24000, 48000], help=f"Sample rate, default {DEFAULT_SAMPLE_RATE}")
    p.add_argument("--resource-id", default=DEFAULT_RESOURCE_ID, help=f"Resource ID, default {DEFAULT_RESOURCE_ID} (seed-tts-2.0/seed-tts-1.0/seed-icl-2.0等)")
    p.add_argument("--output-timestamp", help="Output timestamp JSON file path (optional)")
    p.add_argument("--verbose", action="store_true", help="Print debug info")
    return p


def main() -> None:
    args = _build_arg_parser().parse_args()

    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        import sys, subprocess
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "text-to-speech"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        folder = result.stdout.strip()
        if result.returncode != 0 or not folder or "Error" in folder or "Warning" in folder:
            detail = result.stderr.strip() or folder
            raise ValueError(f"Could not resolve output directory: {detail}")
    except Exception as e:
        print(f"Error: Could not retrieve session directory: {e}. OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}")
        raise SystemExit(1)
        
    final_output = os.path.join(folder, os.path.basename(args.output))
    final_timestamp = os.path.join(folder, os.path.basename(args.output_timestamp)) if args.output_timestamp else None

    # 读取环境变量，支持新旧两种鉴权方式
    api_key = os.getenv("AUDIO_GEN_API_KEY")
    app_id = os.getenv("AUDIO_GEN_APPID")
    access_token = os.getenv("AUDIO_GEN_TOKEN")

    # 校验鉴权参数
    if not api_key and not (app_id and access_token):
        raise SystemExit(
            "Missing authentication credentials. Please set either:\n"
            "1. AUDIO_GEN_API_KEY (new recommended way), or\n"
            "2. Both AUDIO_GEN_APPID and AUDIO_GEN_TOKEN (old way)"
        )

    encoding = _infer_encoding(args.output, args.encoding, args.fmt)
    if encoding not in SUPPORTED_ENCODINGS:
        raise SystemExit(f"Unsupported encoding: {encoding}. Supported encodings: {', '.join(SUPPORTED_ENCODINGS)}")

    # 校验参数范围
    if not (0.5 <= args.speed <= 2.0):
        raise SystemExit("Speed ratio must be between 0.5 and 2.0")
    if not (0.5 <= args.volume <= 2.0):
        raise SystemExit("Volume ratio must be between 0.5 and 2.0")
    if not (0.5 <= args.pitch <= 2.0):
        raise SystemExit("Pitch ratio must be between 0.5 and 2.0")

    tts_generate_to_file(
        text=args.text,
        voice_type=args.voice_type,
        encoding=encoding,
        speed_ratio=args.speed,
        volume_ratio=args.volume,
        pitch_ratio=args.pitch,
        sample_rate=args.sample_rate,
        output_path=final_output,
        api_key=api_key,
        app_id=app_id,
        access_token=access_token,
        resource_id=args.resource_id,
        output_timestamp=final_timestamp,
        verbose=args.verbose
    )

    if os.path.exists(final_output) and os.path.getsize(final_output) > 0:
        print(f"Saved audio: {final_output}")
        if final_timestamp and os.path.exists(final_timestamp):
            print(f"Saved timestamp: {final_timestamp}")
    else:
        raise SystemExit("TTS completed but output file is empty.")


if __name__ == "__main__":
    main()
