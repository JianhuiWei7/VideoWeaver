#!/usr/bin/env python3
"""
image-gen 图片生成脚本，基于Seedream API和gpt-image-2
"""
import os
import sys
import time
import argparse
import base64
import httpx
import io
import subprocess
import json
import re
import random
from io import BytesIO
from typing import Union, List, Optional
from pathlib import Path
from PIL import Image

from volcenginesdkarkruntime import Ark
from volcenginesdkarkruntime.types.images.images import SequentialImageGenerationOptions, ContentGenerationTool
from openai import OpenAI

# 从环境变量读取配置
available_keys = [val for key, val in os.environ.items() if key.startswith("ARK_API_KEY") and val]
ARK_API_KEY = random.choice(available_keys) if available_keys else ""
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

def _format_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

def log_task_start(prefix: str = "") -> float:
    start_time = time.time()
    label = f"{prefix} " if prefix else ""
    print(f"\n=== {label}任务启动时间: {_format_time(start_time)} ===")
    return start_time

def log_task_end(start_time: float, status: str = "finished", prefix: str = "", end_time: Optional[float] = None) -> None:
    end_time = end_time if end_time is not None else time.time()
    label = f"{prefix} " if prefix else ""
    print(f"\n=== {label}任务结束 对应启动时间: {_format_time(start_time)} 结束时间: {_format_time(end_time)} 状态: {status} ===")

def image_to_base64(
    image_source: Union[str, Path, Image.Image], 
    image_format: str = None,
    direct: bool=False
) -> str:
    """
    将图片（文件路径、Path对象或PIL.Image对象）转换为Base64编码的Data URI.

    :param image_source: 图片的来源。可以是：
    - 字符串类型的文件路径 (str)
    - pathlib.Path 对象
    - PIL.Image.Image 对象
    :param image_format: 图片的格式，例如 'png', 'jpeg', 'gif' 等。
    - 如果 image_source 是文件路径或Path对象，此参数可选。若不提供，将从文件扩展名推断。
    - 如果 image_source 是 PIL Image 对象，此参数推荐提供，默认为 'png'。
    :return: Base64编码的Data URI字符串 (例如 "data:image/png;base64,iVBOR...")
    :raises TypeError: 如果 image_source 不是支持的类型。
    :raises FileNotFoundError: 如果提供的路径不存在。
    :raises ValueError: 如果无法从文件路径推断格式，且未提供 image_format。
    """
    
    # 1. 判断输入是文件路径 (str 或 Path) 还是 PIL Image 对象
    if isinstance(image_source, (str, Path)):
        # --- 处理文件路径 (str 或 Path) ---
        if direct:
            with open(image_source, "rb") as image_file:
                encoded = base64.b64encode(image_file.read()).decode('utf-8')
                return encoded
        # os.path.exists() 可以直接处理 str 和 Path 对象
        if not os.path.exists(image_source):
            raise FileNotFoundError(f"文件未找到: {image_source}")
        
        # 如果未指定格式，推理出原来的格式是什么
        if image_format is None:
            # Path 对象有更方便的 .suffix 属性
            if isinstance(image_source, Path):
                extension = image_source.suffix
            else: # 如果是字符串，使用 os.path.splitext
                _, extension = os.path.splitext(image_source)
            
            if not extension:
                raise ValueError("无法从文件路径推断图片格式，请提供 image_format 参数。")
            # 去掉点号并转为小写，例如 '.PNG' -> 'png'
            image_format = extension.lstrip('.').lower()


        if image_format != "jpeg":
            image_format = "jpeg"
            # 对 PNG, JPG 等统一处理，转为 JPEG 再编码
            image = Image.open(image_source).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG")
            buffer.seek(0)
            encoded_string = base64.b64encode(buffer.read()).decode("utf-8")
        else:
            # 其他格式直接读取并编码
            with open(image_source, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")

    elif isinstance(image_source, Image.Image):
        # used when sample frames from video and feed it to seed1.6
        # --- 处理 PIL Image 对象 ---
        # 默认使用png
        if image_format is None:
            image_format = 'png'
        
        save_format = 'jpeg' if image_format.lower() == 'jpg' else image_format.lower()

        buffer = BytesIO()
        image_source.save(buffer, format=save_format.upper())
        encoded_bytes = base64.b64encode(buffer.getvalue())
        encoded_string = encoded_bytes.decode("utf-8")

    else:
        # --- 处理不支持的类型 ---
        raise TypeError(
            "输入 'image_source' 必须是文件路径 (str, pathlib.Path) 或 PIL.Image.Image 对象。"
        )

    # 2. 组装成 Data URI 格式并返回
    mime_type = 'jpeg' if image_format.lower() == 'jpg' else image_format.lower()
    return f"data:image/{mime_type};base64,{encoded_string}"

def get_resolution_string(resolution: str, ratio: str, min_pixels: int = 3686400) -> str:
    """
    根据给定的分辨率标准和宽高比，计算并返回具体的分辨率字符串，确保总像素数不低于最小值。

    Args:
    resolution (str): 分辨率标准，如 "1k", "2k", "4k"。
    ratio (str): 宽高比，如 "16:9", "4:3", "1:1"。
    min_pixels (int): 要求的最低像素总数，默认值为 3686400。

    Returns:
    str: 格式化的分辨率字符串，如 "1920x1080"。

    Raises:
    ValueError: 如果输入的分辨率或宽高比不被支持。
    """
    if resolution is None and ratio is None:
        return None
    
    # Check for direct resolution strings like "2560x1440" or "1024x768"
    if re.match(r'^\d+x\d+$', resolution):
        return resolution

    # 1. 定义支持的分辨率及其对应的长边像素值
    resolution_map = {
        "1k": 1920,
        "2k": 2560,
        "4k": 3840
    }

    # 2. 定义支持的宽高比
    ratio_map = {
        "1:1": (1, 1),
        "4:3": (4, 3),
        "3:4": (3, 4),
        "21:9": (21, 9),
        "16:9": (16, 9),
        "9:16": (9, 16),
        "3:2": (3, 2),
        "2:3": (2, 3)
    }

    # 检查输入是否有效
    if resolution not in resolution_map:
        raise ValueError(f"不支持的分辨率: {resolution}。支持的分辨率为: {list(resolution_map.keys())}")
    if ratio not in ratio_map:
        raise ValueError(f"不支持的宽高比: {ratio}。支持的宽高比为: {list(ratio_map.keys())}")

    # 获取基准像素和比例
    base_pixels = resolution_map[resolution]
    w_ratio, h_ratio = ratio_map[ratio]

    # 3. 计算初始宽高
    if w_ratio > h_ratio:
        # 宽是长边
        width = base_pixels
        height = int((width * h_ratio) / w_ratio)
    elif h_ratio > w_ratio:
        # 高是长边
        height = base_pixels
        width = int((height * w_ratio) / h_ratio)
    else: # w_ratio == h_ratio (1:1)
        # 正方形，宽和高相等
        width = height = base_pixels

    # 4. 检查总像素数是否满足最低要求，如果不满足则按比例放大
    total_pixels = width * height
    if total_pixels < min_pixels:
        # 计算需要放大的比例因子
        scale_factor = (min_pixels / total_pixels) ** 0.5
        # 按比例放大宽高，并取整（向上取整确保满足要求）
        width = int(width * scale_factor)
        height = int(height * scale_factor)
        
        # 确保宽高都是整数且保持比例（微调）
        if w_ratio > h_ratio:
            height = int((width * h_ratio) / w_ratio)
        elif h_ratio > w_ratio:
            width = int((height * w_ratio) / h_ratio)
        
        # 再次检查，如果仍不满足则增加1像素
        while width * height < min_pixels:
            if w_ratio > h_ratio:
                width += 1
                height = int((width * h_ratio) / w_ratio)
            else:
                height += 1
                width = int((height * w_ratio) / h_ratio)

    # 5. 格式化并返回结果
    return f"{width}x{height}"

def get_gpt_image_2_valid_resolution(resolution: str, ratio: str) -> str:
    """
    根据 gpt-image-2 的官方限制计算有效的分辨率：
    1. 最大边长 <= 3840px
    2. 边长必须是 16px 的倍数
    3. 长边与短边比例不能超过 3:1
    4. 总像素数在 655,360 到 8,294,400 之间
    """
    if resolution == "auto":
        return "auto"

    # 如果是支持的热门尺寸，直接返回以加快速度
    popular_sizes = ["1024x1024", "1536x1024", "1024x1536", "2048x2048", "2048x1152", "3840x2160", "2160x3840"]
    if resolution in popular_sizes:
        return resolution

    # 解析基础宽高
    if re.match(r'^\d+x\d+$', resolution):
        w, h = map(int, resolution.split('x'))
    else:
        # 使用 1k/2k/4k 映射为基准长边
        if resolution == "1k":
            L = 1024 if ratio == "1:1" else 1536
        elif resolution == "2k":
            L = 2048
        elif resolution == "4k":
            L = 3840
        else:
            L = 2048  # 默认使用 2k 作为基准

        ratio_map = {
            "1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4),
            "21:9": (21, 9), "16:9": (16, 9), "9:16": (9, 16),
            "3:2": (3, 2), "2:3": (2, 3), "None": (16, 9)
        }
        w_ratio, h_ratio = ratio_map.get(ratio, (16, 9))

        if w_ratio >= h_ratio:
            w = L
            h = int(L * h_ratio / w_ratio)
        else:
            h = L
            w = int(L * w_ratio / h_ratio)

    # 1. 限制长短边比例 <= 3:1
    if w / h > 3:
        w = h * 3
    elif h / w > 3:
        h = w * 3

    # 2. 限制最大边长 <= 3840
    if w > 3840 or h > 3840:
        scale = 3840 / max(w, h)
        w, h = int(w * scale), int(h * scale)

    # 3. 限制总像素数 [655360, 8294400]
    pixels = w * h
    if pixels > 8294400:
        scale = (8294400 / pixels) ** 0.5
        w, h = int(w * scale), int(h * scale)
    elif pixels < 655360:
        scale = (655360 / pixels) ** 0.5
        w, h = int(w * scale), int(h * scale)

    # 4. 必须是 16 的倍数
    w = max(16, round(w / 16) * 16)
    h = max(16, round(h / 16) * 16)

    # 5. 微调：舍入到 16 倍数后可能会轻微越界，需确保硬性指标
    if w > 3840: w = 3840
    if h > 3840: h = 3840
    
    while w * h > 8294400:
        if w >= h: w -= 16
        else: h -= 16
    while w * h < 655360:
        if w <= h: w += 16
        else: h += 16
        
    # 二次检查 3:1 比例（极少情况由于减法导致比例越界）
    if w / h > 3:
        w = h * 3
        w = max(16, round(w / 16) * 16)
    elif h / w > 3:
        h = w * 3
        h = max(16, round(h / 16) * 16)

    return f"{w}x{h}"

def gpt_image2_generate_or_edit(
    prompt: str,
    output_path: str,
    img_path: Union[str, List[str]] = None,
    resolution: str = "2k",
    ratio: str = "16:9",
    quality: str = "auto",
    max_images: int = 1,
    task_start_time: Optional[float] = None,
):
    """
    使用 gpt-image-2 生成或编辑图片
    """
    effective_start_time = task_start_time if task_start_time is not None else time.time()
    if not OPENAI_API_KEY:
        raise ValueError("Please configure OPENAI_API_KEY environment variable")

    # Map resolution and ratio to OpenAI supported sizes
    size = get_gpt_image_2_valid_resolution(resolution, ratio)
        
    if max_images > 1:
        print("Warning: gpt-image-2 目前每次只生成/编辑1张图片，忽略 max_images 参数")

    is_edit = img_path is not None
    
    print_lines = [f"Submitting GPT-Image-2 Request: \n prompt={prompt}"]
    if is_edit:
        print_lines.append(f"with reference image(s): {img_path}")
    print_lines.append(f"with model: gpt-image-2")
    print_lines.append(f"resolution: {resolution}")
    print_lines.append(f"ratio: {ratio}")
    print_lines.append(f"mapped size: {size}")
    print_lines.append(f"quality: {quality}")
    print("\n".join(print_lines))
    
    if is_edit:
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url="https://aidp-i18ntt-sg.tiktok-row.net/gpt/openapi/online/v2/crawl/openai",
        )
        if isinstance(img_path, str):
            img_path = [img_path]
            
        opened_images = [open(p, "rb") for p in img_path]
        
        try:
            result = client.images.edit(
                model="gpt-image-2",
                image=opened_images,
                prompt=prompt,
                size=size,
                quality=quality,
                extra_headers={"api-key": OPENAI_API_KEY},
            )
        finally:
            for f in opened_images:
                f.close()
    else:
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url="https://aidp-i18ntt-sg.tiktok-row.net/api/modelhub/online/v2/crawl/openai",
        )
        result = client.images.generate(
            model="gpt-image-2",
            prompt=prompt,
            size=size,
            quality=quality,
            extra_headers={"api-key": OPENAI_API_KEY},
        )

    image_base64 = result.data[0].b64_json
    img = base64.b64decode(image_base64)
    with open(output_path, 'wb') as f:
        f.write(img)
        
    end_time = time.time()
    elapsed_time = end_time - effective_start_time
    mins, secs = divmod(elapsed_time, 60)
    
    # 尝试从 result 中提取 token/cost 信息
    token_used = "N/A"
    if hasattr(result, 'usage') and result.usage:
        # 如果返回对象中存在 usage 对象
        if hasattr(result.usage, 'total_tokens'):
            token_used = str(result.usage.total_tokens)
        elif hasattr(result.usage, 'output_tokens'):
            token_used = str(result.usage.output_tokens)
            
    print(f"💰 [quality: {quality}] Token Used: {token_used}")
    print(f"🖼️ Successfully saved image: {output_path}")
    print(f"⏱️ 任务生成完成！开始时间: {_format_time(effective_start_time)} 结束时间: {_format_time(end_time)} 所用时间: {int(mins)}min, {int(secs)}sec")
    return end_time


def seedream_generate_image(
    prompt: str,
    output_path: str,
    img_path: Union[str, List[str]] = None,
    model: str = "doubao-seedream-5-0-260128",
    resolution: str = "2k", 
    ratio: str = "16:9",
    max_images: int = 2,
    watermark: bool = False,
    seed: int = -1,
    web_search: bool = False,
    task_start_time: Optional[float] = None,
):
    """
    Generate images using Seedream API via Volcengine SDK.
    """
    effective_start_time = task_start_time if task_start_time is not None else time.time()
    if not ARK_API_KEY:
        raise ValueError("Please configure ARK_API_KEY environment variable")
    
    supported_resolutions = ["1k", "2k", "4k"]
    supported_ratios = ["1:1", "4:3", "3:4", "21:9", "16:9", "9:16", "3:2", "2:3", "None"]
    
    # Allow custom resolution like "1024x768"
    is_custom_resolution = bool(re.match(r'^\d+x\d+$', resolution))
    
    if resolution not in supported_resolutions and not is_custom_resolution:
        raise ValueError(f"resolution must be one of: {supported_resolutions} or a custom 'WidthxHeight' string (e.g. '1920x1080')")
    
    # Skip ratio validation if custom resolution is provided
    if not is_custom_resolution:
        if ratio not in supported_ratios:
            raise ValueError(f"ratio must be one of: {supported_ratios}")
    
    formatted_resolution = get_resolution_string(resolution, ratio)
    
    # Initialize client
    client = Ark(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key=ARK_API_KEY,
    )
    
    # Process reference image(s)
    img_path_list = []
    image_input = None
    if img_path is not None:
        if not isinstance(img_path, list):
            img_path_list = [img_path]
        else:
            img_path_list = img_path
        image_input = [image_to_base64(p) for p in img_path_list]
    
    print_lines = [f"Submitting Seedream Generate Image Request: \n prompt={prompt}"]
    if img_path_list:
        print_lines.append(f"with reference image(s): {img_path_list}")
    if seed is not None:
        print_lines.append(f"with seed: {seed}")
    if model:
        print_lines.append(f"with model: {model}")
    if formatted_resolution:
        print_lines.append(f"size: {formatted_resolution}")
    if ratio:
        print_lines.append(f"ratio: {ratio}")
    if max_images:
        print_lines.append(f"max_images: {max_images}")
    if watermark:
        print_lines.append(f"watermark: {watermark}")
    if web_search:
        print_lines.append(f"web search: enabled")
        
    print("\n".join(print_lines))
    
    # Prepare generation parameters
    params = {
        "model": model,
        "prompt": prompt,
        "size": formatted_resolution,
        "response_format": "url",
        "watermark": watermark,
        "seed": seed
    }
    
    if web_search:
        params["tools"] = [ContentGenerationTool(type="web_search")]
    
    if max_images > 1:
        # # Hack: The model requires explicit instruction in prompt to generate multiple images in auto mode
        # prompt += f"，生成一组共{max_images}张连贯插画"
        # params["prompt"] = prompt
        params["sequential_image_generation"] = "auto"
        params["sequential_image_generation_options"] = SequentialImageGenerationOptions(max_images=max_images)
        print(f"监测到要一次性生成 {max_images} 张图片，需要花费更多时间，请不要 kill 掉进程或重新生成，请耐心等待...")
    if image_input:
        params["image"] = image_input

    try:
        imagesResponse = client.images.generate(**params)
        print(f"Number of image generated: {len(imagesResponse.data)}")

        
        # Iterate through all image data
        for idx, image in enumerate(imagesResponse.data):
            image_url = image.url
            if not image_url:
                continue
            
            # Generate output path
            if max_images > 1:
                path_obj = Path(output_path)
                save_path = str(path_obj.parent / f"{path_obj.stem}_{idx+1}{path_obj.suffix}")
            else:
                save_path = output_path
            
            # print(f"URL: {image_url}, Size: {image.size if hasattr(image, 'size') else 'Unknown'}")
            
            # Download image
            try:
                with httpx.Client() as http_client:
                    download_response = http_client.get(image_url, timeout=60)
                    download_response.raise_for_status()
                    with open(save_path, "wb") as f:
                        f.write(download_response.content)
                if web_search:
                    print("Web search usage counts:", imagesResponse.usage.tool_usage.web_search)
                print("💰 Token Used:", imagesResponse.usage.output_tokens)
                print(f"🖼️ Successfully saved image: {save_path}")
            except Exception as e:
                print(f"❌ Failed to download image {image_url}: {e}")

        end_time = time.time()
        elapsed_time = end_time - effective_start_time
        mins, secs = divmod(elapsed_time, 60)
        print(f"⏱️ 任务生成完成！开始时间: {_format_time(effective_start_time)} 结束时间: {_format_time(end_time)} 所用时间: {int(mins)}min, {int(secs)}sec")
        return end_time

    except Exception as e:
        print(f"❌ Generation failed: {e}")
        import traceback
        traceback.print_exc()
        raise e

def main():
    parser = argparse.ArgumentParser(description="AI图片生成工具")
    parser.add_argument("--prompt", help="生成小猫", type=str, default="生成1张小猫照片")
    parser.add_argument("--output_file_name", help="生成图片的文件名", type=str, default="output.jpg")
    parser.add_argument("--img_path", action="append", help="参考图路径（图生图模式，可指定多次传入多张参考图）")
    parser.add_argument("--model", default="doubao-seedream-5-0-260128", help="使用的模型，支持 doubao-seedream 系列和 gpt-image-2")
    parser.add_argument("--resolution", default="2k", help="分辨率，支持 1k/2k/4k 或 WidthxHeight (gpt-image-2会自动映射)")
    parser.add_argument("--ratio", default="16:9", choices=["1:1", "4:3", "3:4", "21:9", "16:9", "9:16", "3:2", "2:3", "None"], help="图片比例")
    parser.add_argument("--quality", default="auto", choices=["low", "medium", "high", "auto"], help="生成图片质量（仅 gpt-image-2 支持）")
    parser.add_argument("--max_images", type=int, default=1, help="生成图片数量（1-10）")
    parser.add_argument("--watermark", action="store_true", help="是否添加水印")
    parser.add_argument("--seed", type=int, default=-1, help="随机种子")
    parser.add_argument("--web_search", action="store_true", help="是否启用联网搜索功能")
    parser.add_argument("--session-key", type=str, help="可选的输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 session_status 获取session-key并且传入, 格式通常为 agent:{agent_id}:{session_id}。")
    
    args = parser.parse_args()
    # Get SESSION_ID
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../get-output-dir/scripts/get_output_dir.py"))
        cmd = [sys.executable, script_path]
        if args.session_key:
            cmd.extend(["--session-key", args.session_key])
        cmd.extend(["--subdir", "images"])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        folder = result.stdout.strip()
        if result.returncode != 0 or not folder or "Error" in folder or "Warning" in folder:
            detail = result.stderr.strip() or folder
            raise ValueError(f"Could not resolve output directory: {detail}")
    except Exception as e:
        print(f"Warning: Could not resolve output directory: {e}")
        return
        
    # --- 日志同时输出到控制台和文件 ---
    class TeeOutput:
        def __init__(self, stream1, stream2):
            self.stream1 = stream1
            self.stream2 = stream2
        def write(self, data):
            self.stream1.write(data)
            self.stream2.write(data)
            self.flush()
        def flush(self):
            self.stream1.flush()
            self.stream2.flush()
            
    LOG_FILE = os.path.join(folder, "run.log")
    IS_BACKGROUND = "--background" in sys.argv
    IS_WORKER = "--internal-worker" in sys.argv

    if not IS_BACKGROUND and not IS_WORKER:
        # 交互模式：同时输出到控制台和文件
        log_f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stdout = TeeOutput(sys.stdout, log_f)
        sys.stderr = TeeOutput(sys.stderr, log_f)
    elif IS_WORKER:
        # 后台Worker模式：stdout/stderr 已被父进程重定向到日志文件
        # 强制刷新缓冲区，确保日志及时写入
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    
    output_path = os.path.join(folder, args.output_file_name)
    
    log_prefix = "[Background Worker]" if IS_WORKER else ""
    generation_start_time = log_task_start(prefix=log_prefix)
    generation_end_time = None
    task_status = "failed"
    try:
        if args.model == "gpt-image-2":
            generation_end_time = gpt_image2_generate_or_edit(
                prompt=args.prompt,
                output_path=output_path,
                img_path=args.img_path,
                resolution=args.resolution,
                ratio=args.ratio,
                quality=args.quality,
                max_images=args.max_images,
                task_start_time=generation_start_time,
            )
        else:
            generation_end_time = seedream_generate_image(
                prompt=args.prompt,
                output_path=output_path,
                img_path=args.img_path,
                model=args.model,
                resolution=args.resolution,
                ratio=args.ratio,
                max_images=args.max_images,
                watermark=args.watermark,
                seed=args.seed,
                web_search=args.web_search,
                task_start_time=generation_start_time,
            )
        task_status = "success"
    except Exception as e:
        generation_end_time = time.time()
        elapsed_time = generation_end_time - generation_start_time
        mins, secs = divmod(elapsed_time, 60)
        print(f"⏱️ 任务失败，开始时间: {_format_time(generation_start_time)} 结束时间: {_format_time(generation_end_time)} 消耗时间: {int(mins)}min, {int(secs)}sec")
        print(f"生成失败: {e}")
        log_task_end(generation_start_time, status=task_status, prefix=log_prefix, end_time=generation_end_time)
        sys.exit(1)
    log_task_end(generation_start_time, status=task_status, prefix=log_prefix, end_time=generation_end_time)

if __name__ == "__main__":
    main()
