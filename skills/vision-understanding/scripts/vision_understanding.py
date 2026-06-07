import os
import time
import argparse
import mimetypes
import random
from openai import OpenAI
from volcenginesdkarkruntime import Ark

# 全局配置
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seed-2-0-pro-260215"
DEFAULT_VIDEO_FPS = 1.0
MAX_RETRIES = 15
WAIT_SECONDS = 5

def _upload_media_to_ark(media_path: str, video_fps: float = DEFAULT_VIDEO_FPS):
    """上传媒体文件（图片/视频）到 Ark，返回 (file_id, media_type)，media_type 为 image/video"""
    # 先判断文件类型
    mime_type, _ = mimetypes.guess_type(media_path)
    if not mime_type:
        raise ValueError(f"无法识别文件类型: {media_path}")
    
    api_key = os.getenv("ARK_API_KEY")
    
    client = Ark(api_key=api_key)
    
    if mime_type.startswith("image/"):
        media_type = "image"
        # 图片上传不需要预处理配置
        file = client.files.create(
            file=open(media_path, "rb"),
            purpose="user_data",
        )
    elif mime_type.startswith("video/"):
        media_type = "video"
        # 视频上传支持fps配置
        file = client.files.create(
            file=open(media_path, "rb"),
            purpose="user_data",
            preprocess_configs={
                "video": {
                    "fps": video_fps,
                }
            },
        )
    else:
        raise ValueError(f"不支持的文件类型: {mime_type}，仅支持图片和视频")
    
    # 等待文件处理完成
    while file.status == "processing":
        time.sleep(2)
        file = client.files.retrieve(file.id)
        
    return file.id, media_type

def vision_understanding(
    media_paths: list[str],
    prompt: str,
    model: str = DEFAULT_MODEL,
    video_fps: float = DEFAULT_VIDEO_FPS
) -> str:
    """
    统一的视觉理解接口，支持同时传入多个图片和视频，按顺序进行理解
    :param media_paths: 媒体文件路径列表，支持同时传入图片和视频，按传入顺序处理
    :param prompt: 查询提示词
    :param model: 要使用的模型，默认doubao-seed-2-0-pro-260215
    :param video_fps: 视频采样帧率，默认1.0
    :return: 内容描述文本
    """
    api_key = os.getenv("ARK_API_KEY")
    
    client = OpenAI(
        base_url=ARK_BASE_URL,
        api_key=api_key,
    )
    
    # 逐个上传所有媒体文件
    content_list = []
    ark_client = Ark(base_url=ARK_BASE_URL, api_key=api_key)
    try:
        for path in media_paths:
            print(f"正在上传: {os.path.basename(path)}...")
            file_id, media_type = _upload_media_to_ark(path, video_fps)
            content_list.append({
                "type": f"input_{media_type}",
                "file_id": file_id
            })
            print(f"上传完成: {os.path.basename(path)} -> file_id: {file_id[:20]}...")
        
        # 最后添加提示词
        content_list.append({
            "type": "input_text",
            "text": prompt
        })
        print(f"视觉理解提示词: {prompt}")
        # 轮询重试，处理视频还在processing的情况
        for attempt in range(MAX_RETRIES):
            try:
                print(f"正在分析内容（尝试 {attempt+1}/{MAX_RETRIES}）...")
                response = client.responses.create(
                    model=model,
                    input=[
                        {
                            "role": "user",
                            "content": content_list
                        }
                    ],
                )
                
                # 打印推理过程（如果有）
                try:
                    reasoning = response.output[0].summary[0].text
                    if reasoning:
                        print(f"\n[Vision Understanding Reasoning]\n{reasoning}\n")
                except Exception:
                    pass
                
                # 返回结果
                return response.output[1].content[0].text.strip()
            
            except Exception as e:
                err_str = str(e).lower()
                if "invalid state" in err_str and "processing" in err_str:
                    if attempt == MAX_RETRIES - 1:
                        raise RuntimeError(f"媒体文件处理超时，已重试{MAX_RETRIES}次") from e
                    print(f"媒体还在处理中，{WAIT_SECONDS}秒后重试...")
                    time.sleep(WAIT_SECONDS)
                    continue
                raise
    finally:
        # 清理已上传的文件
        for item in content_list:
            if "file_id" in item:
                file_id = item["file_id"]
                try:
                    ark_client.files.delete(file_id=file_id)
                    print(f"已自动清理临时文件: {file_id}")
                except Exception as e:
                    print(f"清理临时文件失败 {file_id}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified vision understanding tool based on Volcengine Ark API")
    parser.add_argument("--media", required=True, nargs='+', help="List of media file paths (images/videos)")
    parser.add_argument("--prompt", required=True, help="Question about the media content")
    parser.add_argument("--fps", type=float, default=DEFAULT_VIDEO_FPS, help="Sampling FPS for videos, default 1.0")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use, default doubao-seed-2-0-pro-260215")
    
    args = parser.parse_args()
    
    
    # 验证所有媒体文件存在
    for path in args.media:
        if not os.path.exists(path):
            print(f"错误: 媒体文件不存在: {path}")
            exit(1)
    
    try:
        result = vision_understanding(args.media, args.prompt, args.model, args.fps)
        print("\n=== 视觉理解结果 ===")
        print(result)
    except Exception as e:
        print(f"处理失败: {e}")
        exit(1)
