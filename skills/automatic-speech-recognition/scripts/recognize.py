# coding: utf-8
import argparse
import json
import os
import time
import uuid
import requests
import base64

DEFAULT_RESOURCE_ID = os.getenv("ASR_RESOURCE_ID", "volc.bigasr.auc_turbo")
DEFAULT_HOST = os.getenv("ASR_API_HOST", "openspeech.bytedance.com")
DEFAULT_API_PATH = "/api/v3/auc/bigmodel/recognize/flash"


def download_file(file_url):
    response = requests.get(file_url)
    if response.status_code == 200:
        return response.content
    else:
        raise Exception(f"下载文件失败，HTTP状态码: {response.status_code}")


def file_to_base64(file_path):
    with open(file_path, 'rb') as file:
        file_data = file.read()
        base64_data = base64.b64encode(file_data).decode('utf-8')
    return base64_data


def recognize_task(appid, token, file_url=None, file_path=None, enable_itn=True, enable_punc=True, enable_ddc=True, enable_speaker_info=False, verbose=False):
    recognize_url = f"https://{DEFAULT_HOST}{DEFAULT_API_PATH}"
    
    headers = {
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": DEFAULT_RESOURCE_ID,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Sequence": "-1",
    }

    audio_data = None
    if file_url:
        audio_data = {"url": file_url}
    elif file_path:
        base64_data = file_to_base64(file_path)
        audio_data = {"data": base64_data}

    if not audio_data:
        raise ValueError("必须提供 --file-url 或 --file-path 其中之一")

    request = {
        "user": {
            "uid": appid
        },
        "audio": audio_data,
        "request": {
            "model_name": "bigmodel",
            "enable_itn": enable_itn,
            "enable_punc": enable_punc,
            "enable_ddc": enable_ddc,
            "enable_speaker_info": enable_speaker_info,
        },
    }

    if verbose:
        print(f"请求URL: {recognize_url}")
        print(f"请求头: {json.dumps(headers, indent=2)}")
        print(f"请求体: {json.dumps(request, indent=2, ensure_ascii=False)}")

    response = requests.post(recognize_url, json=request, headers=headers)
    
    if verbose:
        print(f"响应状态码: {response.status_code}")
        print(f"响应头: {json.dumps(dict(response.headers), indent=2)}")

    if 'X-Api-Status-Code' in response.headers:
        status_code = response.headers["X-Api-Status-Code"]
        message = response.headers.get("X-Api-Message", "")
        logid = response.headers.get("X-Tt-Logid", "")
        
        if verbose:
            print(f"识别状态码: {status_code}")
            print(f"识别消息: {message}")
            print(f"请求LogID: {logid}")

        if status_code == '20000000':
            result = response.json()
            if verbose:
                print(f"识别结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
            return result, None
        else:
            return None, f"识别失败，状态码: {status_code}, 消息: {message}, LogID: {logid}"
    else:
        return None, f"识别失败，响应头异常: {dict(response.headers)}"


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="火山引擎ASR自动语音识别工具")
    p.add_argument("--session-key", type=str, help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    input_group = p.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--file-path", help="本地音频文件路径")
    input_group.add_argument("--file-url", help="在线音频文件URL")
    p.add_argument("--output", action="append", help="输出结果文件名（自动保存在输入音频同目录下），可多次指定，支持.json、.txt和.srt")
    p.add_argument("--enable-itn", action="store_true", default=True, help="启用文本规范化，默认开启")
    p.add_argument("--disable-itn", action="store_false", dest="enable_itn", help="禁用文本规范化")
    p.add_argument("--enable-punc", action="store_true", default=True, help="启用标点符号，默认开启")
    p.add_argument("--disable-punc", action="store_false", dest="enable_punc", help="禁用标点符号")
    p.add_argument("--enable-ddc", action="store_true", default=True, help="启用语气词识别，默认开启")
    p.add_argument("--disable-ddc", action="store_false", dest="enable_ddc", help="禁用语气词识别")
    p.add_argument("--enable-speaker-info", action="store_true", default=False, help="启用说话人分离，默认关闭")
    p.add_argument("--show-timestamps", action="store_true", help="在控制台和txt输出中显示时间戳")
    p.add_argument("--verbose", action="store_true", help="打印调试信息")
    return p


def main() -> None:
    args = _build_arg_parser().parse_args()

    # Get SESSION_ID folder
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        import sys, subprocess
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "asr"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        folder = result.stdout.strip()
        if result.returncode != 0 or not folder or "Error" in folder or "Warning" in folder:
            detail = result.stderr.strip() or folder
            raise ValueError(f"Could not resolve output directory: {detail}")
    except Exception as e:
        print(f"Error: Could not resolve output directory: {e}. OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}")
        return

    appid = os.getenv("ASR_APPID")
    token = os.getenv("ASR_TOKEN")
    if not appid or not token:
        raise SystemExit("缺少环境变量，请先设置 ASR_APPID 和 ASR_TOKEN。")

    start_time = time.time()
    if args.verbose:
        print(f"开始识别，时间: {time.asctime()}")

    result, err = recognize_task(
        appid=appid,
        token=token,
        file_url=args.file_url,
        file_path=args.file_path,
        enable_itn=args.enable_itn,
        enable_punc=args.enable_punc,
        enable_ddc=args.enable_ddc,
        enable_speaker_info=args.enable_speaker_info,
        verbose=args.verbose
    )

    if err:
        raise SystemExit(err)

    # 提取纯文本结果和字幕结果
    text_result = ""
    srt_result = ""
    if result.get("result") and result["result"].get("utterances"):
        srt_index = 1
        for utterance in result["result"]["utterances"]:
            text = utterance.get("text", "")
            start_time = utterance.get("start_time", 0)
            end_time = utterance.get("end_time", 0)
            
            # Convert ms to HH:MM:SS.mmm format
            def format_ms(ms, sep='.'):
                h = ms // 3600000
                m = (ms % 3600000) // 60000
                s = (ms % 60000) // 1000
                ms_rem = ms % 1000
                return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms_rem:03d}"
            
            if args.show_timestamps:
                text_result += f"[{format_ms(start_time)} -> {format_ms(end_time)}] {text}\n"
            else:
                text_result += text + "\n"
                
            srt_result += f"{srt_index}\n{format_ms(start_time, ',')} --> {format_ms(end_time, ',')}\n{text}\n\n"
            srt_index += 1
            
    text_result = text_result.strip()
    srt_result = srt_result.strip()

    # 输出到控制台
    print("\n=== 识别结果 ===")
    print(text_result)
    print(f"\n识别耗时: {time.time() - start_time:.2f} 秒")

    # 保存到文件
    if args.output:
        for output_name in args.output:
            # 确定输出目录：使用 session folder
            output_dir = folder
            
            # 仅使用文件名，忽略可能传入的路径
            filename = os.path.basename(output_name)
            output_path = os.path.join(output_dir, filename)
            
            os.makedirs(output_dir, exist_ok=True)
            ext = os.path.splitext(output_path)[1].lower()
            if ext == ".json":
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=4, ensure_ascii=False)
                if args.verbose:
                    print(f"完整结果已保存到: {output_path}")
            elif ext == ".txt":
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(text_result)
                if args.verbose:
                    print(f"文本结果已保存到: {output_path}")
            elif ext == ".srt":
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(srt_result)
                if args.verbose:
                    print(f"字幕文件已保存到: {output_path}")
            else:
                print(f"不支持的输出格式: {ext}，仅支持 .json、.txt 和 .srt")


if __name__ == "__main__":
    main()
