import os
import shutil
import uuid
import random
import time
from pathlib import Path
from collections import Counter
import cv2
from moviepy import VideoFileClip, concatenate_videoclips
import argparse

import builtins
from datetime import datetime

# 定义新的print函数，覆盖内置的print，带上时间戳
original_print = builtins.print
def print(*args, **kwargs):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    original_print(f"[{current_time}]", *args, **kwargs)

def get_video_ratio(video_path):
    """
    Calculates the aspect ratio of a video file.
    """
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"Error: Could not open video file: {video_path}")
            return None

        width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        cap.release()

        if width == 0 or height == 0:
            return None

        ratio = width / height
        supported_ratios = {
            "16:9": 16/9,
            "9:16": 9/16,
            "4:3": 4/3,
            "3:4": 3/4,
            "1:1": 1.0,
            "21:9": 21/9,
        }

        closest_ratio = min(supported_ratios.keys(), key=lambda r: abs(supported_ratios[r] - ratio))
        return closest_ratio
    except Exception as e:
        print(f"Error getting video ratio for {video_path}: {e}")
        return None

def get_most_common_resolution_clip(clips):
    """
    从多个视频Clip中获取出现次数最多的分辨率对应的clip（作为基准）
    """
    if not clips:
        return None
    
    resolution_map = {}
    for clip in clips:
        res_key = (clip.w, clip.h)
        if res_key not in resolution_map:
            resolution_map[res_key] = []
        resolution_map[res_key].append(clip)
    
    max_count = 0
    most_common_res = None
    for res_key, clip_list in resolution_map.items():
        count = len(clip_list)
        if count > max_count:
            max_count = count
            most_common_res = res_key
        elif count == max_count:
            current_pixels = res_key[0] * res_key[1]
            max_pixels = most_common_res[0] * most_common_res[1] if most_common_res else 0
            if current_pixels > max_pixels:
                most_common_res = res_key
    
    if most_common_res:
        res_count = len(resolution_map[most_common_res])
        total_clips = len(clips)
        print(f"🔍 分辨率统计：共{total_clips}个视频，主流分辨率{most_common_res[0]}×{most_common_res[1]}（占{res_count}个）")
        return resolution_map[most_common_res][0]
    else:
        return None

def unify_video_resolution_dynamic(clip, ref_clip=None, original_path=None):
    """
    安全的动态分辨率统一函数：智能保留音频（无音轨则不输出音频），避免文件损坏、帧缺失导致的后半段静止
    """
    if original_path is None:
        raise ValueError("必须传入 original_path 参数！")
    
    has_audio = clip.audio is not None
    
    current_aspect = clip.w / clip.h
    ref_aspect = ref_clip.w / ref_clip.h if ref_clip else current_aspect
    if not abs(current_aspect - ref_aspect) < 0.02:
        raise ValueError(f"视频比例不一致！当前：{current_aspect:.4f}, 基准：{ref_aspect:.4f}")
    
    target_w, target_h = (ref_clip.w, ref_clip.h) if ref_clip else (clip.w, clip.h)
    target_w = target_w if target_w % 2 == 0 else target_w - 1
    target_h = target_h if target_h % 2 == 0 else target_h - 1

    if clip.w == target_w and clip.h == target_h:
        print(f"✅ 视频分辨率已满足要求 ({target_w}×{target_h})，无需处理：{original_path}")
        try:
            new_clip = VideoFileClip(original_path)
            return new_clip, True
        except Exception as e:
            print(f"❌ 重新加载视频失败：{original_path} | 错误：{str(e)}")
            return None, False
    
    target_fps = clip.fps if clip.fps > 0 else 24.0
    resized_clip = clip.resized((target_w, target_h))
    resized_clip = resized_clip.with_fps(target_fps)
    resized_clip = resized_clip.with_duration(resized_clip.reader.n_frames / target_fps)
    
    save_success = False
    temp_path = f"{original_path}.tmp_{os.getpid()}.mp4"
    try:
        write_params = {
            "codec": "libx264",
            "fps": target_fps,
            "ffmpeg_params": [
                '-pix_fmt', 'yuv420p',
                '-crf', '23',
                '-preset', 'medium',
                '-movflags', '+faststart',
                '-fflags', '+flush_packets'
            ],
            "logger": None,
            "threads": 4,
            "write_logfile": False
        }
        
        if has_audio:
            write_params["audio_codec"] = "aac"
            write_params["audio"] = True
            write_params["ffmpeg_params"].extend(['-b:a', '192k', '-ac', '2'])
        else:
            write_params["audio"] = False
            write_params["ffmpeg_params"].extend(['-an'])
        
        resized_clip.write_videofile(temp_path, **write_params)
        
        temp_clip = VideoFileClip(temp_path)
        temp_clip_duration = temp_clip.duration
        temp_clip_nframes = temp_clip.reader.n_frames
        
        if has_audio:
            if temp_clip.audio is None:
                raise ValueError("临时文件丢失音频轨道！")
            audio_duration = temp_clip.audio.duration
            if abs(audio_duration - temp_clip_duration) > 0.5:
                raise ValueError(f"音视频时长不匹配！视频{temp_clip_duration:.2f}秒，音频{audio_duration:.2f}秒")
        else:
            if temp_clip.audio is not None:
                raise ValueError("原视频无音轨，但临时文件生成了音频轨道！")
        
        expected_duration = temp_clip_nframes / target_fps
        if abs(temp_clip_duration - expected_duration) < 0.1:
            shutil.move(temp_path, original_path)
            save_success = True
        else:
            raise ValueError(f"临时文件帧不完整：预期时长{expected_duration:.2f}秒，实际{temp_clip_duration:.2f}秒")
        
        temp_clip.close()
    
    except Exception as e:
        print(f"❌ 保存视频失败：{original_path} | 错误：{str(e)}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
    finally:
        resized_clip.close()
        clip.close()
        if os.path.exists(temp_path) and not save_success:
            os.remove(temp_path)
    
    new_clip = None
    if save_success:
        time.sleep(0.5)
        try:
            new_clip = VideoFileClip(original_path)
            if has_audio and new_clip.audio is None:
                print(f"❌ 处理后的视频丢失音频：{original_path}")
                save_success = False
                new_clip.close()
                new_clip = None
            elif not has_audio and new_clip.audio is not None:
                print(f"❌ 原视频无音轨，但处理后生成了音频：{original_path}")
                save_success = False
                new_clip.close()
                new_clip = None
        except Exception as e:
            print(f"❌ 重新加载视频失败：{original_path} | 错误：{str(e)}")
            save_success = False
    
    return new_clip, save_success

def batch_unify_video_resolution(video_paths):
    """
    批量处理视频分辨率：输入路径列表，统一分辨率后覆盖原文件
    """
    video_paths = [str(p) if isinstance(p, Path) else p for p in video_paths]
    
    if not video_paths:
        raise ValueError("输入的视频路径列表不能为空！")
    
    valid_video_paths = []
    for path in video_paths:
        if os.path.exists(path):
            valid_video_paths.append(path)
        else:
            print(f"⚠️ 跳过不存在的视频文件：{path}")
    video_paths = valid_video_paths
    
    if not video_paths:
        raise ValueError("无可用的视频文件！")
    
    temp_clips = []
    for path in video_paths:
        try:
            clip = VideoFileClip(path)
            temp_clips.append(clip)
        except Exception as e:
            print(f"⚠️ 加载视频失败 {path} | 错误：{str(e)}")
            for loaded_clip in temp_clips:
                loaded_clip.close()
            raise
    
    ref_clip = get_most_common_resolution_clip(temp_clips)
    print(f"\n📌 基准分辨率：{ref_clip.w}×{ref_clip.h}")
    
    success_paths = []
    for idx, path in enumerate(video_paths):
        temp_clip = temp_clips[idx]
        try:
            resized_clip, success = unify_video_resolution_dynamic(
                clip=temp_clip,
                ref_clip=ref_clip,
                original_path=path
            )
            if success:
                success_paths.append(path)
            if resized_clip:
                resized_clip.close()
        except Exception as e:
            print(f"⚠️ 跳过视频 {path} | 处理失败：{str(e)}")
        finally:
            temp_clip.close()
    
    ref_clip.close()
    
    print(f"\n📊 批量处理完成：共{len(video_paths)}个视频，成功{len(success_paths)}个")
    return success_paths

def resize_to_custom_ratio(input_path, output_path, target_ratio="9:16", target_long_side=None):
    """
    按自定义比例缩放视频（无黑边），支持自动推导目标长边长度
    """
    w_ratio, h_ratio = map(int, target_ratio.split(":"))
    is_vertical = h_ratio > w_ratio

    clip = VideoFileClip(input_path)
    original_w, original_h = clip.size
    original_long_side = max(original_w, original_h)
    original_short_side = min(original_w, original_h)

    if target_long_side is None:
        original_ratio = original_short_side / original_long_side
        target_short_ratio = min(w_ratio, h_ratio) / max(w_ratio, h_ratio)
        scale_factor = target_short_ratio / original_ratio
        target_long_side = int(original_long_side * scale_factor)
        target_long_side = max(target_long_side, 360)

    if is_vertical:
        target_h = target_long_side
        target_w = int(target_h * w_ratio / h_ratio)
    else:
        target_w = target_long_side
        target_h = int(target_w * h_ratio / w_ratio)
    target_size = (target_w, target_h)

    scale_w = target_w / original_w
    scale_h = target_h / original_h
    scale_ratio = max(scale_w, scale_h)
    scaled_clip = clip.resized(scale_ratio)
    scaled_w, scaled_h = scaled_clip.size

    x1 = (scaled_w - target_w) // 2
    y1 = (scaled_h - target_h) // 2
    final_clip = scaled_clip.cropped(x1=x1, y1=y1, x2=x1+target_w, y2=y1+target_h)

    try:
        final_clip.write_videofile(output_path, fps=clip.fps, audio=True, audio_codec="aac", codec="libx264")
    except Exception as e:
        print(f"视频写入失败，尝试无音频流: {e}")
        final_clip.write_videofile(output_path, fps=clip.fps, audio=False, codec="libx264")
        
    final_clip.close()
    clip.close()

    print(f"自动推导目标长边长度：{target_long_side}，输出尺寸：{target_w}×{target_h}")
    return output_path

def create_default_filename():
    """生成默认输出文件名"""
    return f"merged_video_{random.randint(100000, 999999)}.mp4"

def _determine_target_fps(video_paths, target_fps=None):
    """Helper function to determine the target FPS for merging videos."""
    def get_input_video_fps(video_path):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            return None
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        if fps <= 0 or fps > 60:
            return None
        return round(fps)

    if target_fps is None:
        input_fps_list = [fps for path in video_paths if (fps := get_input_video_fps(path))]
        if input_fps_list:
            fps_counter = Counter(input_fps_list)
            target_fps = fps_counter.most_common(1)[0][0]
        else:
            target_fps = 24
    print(f"✅ Target FPS determined: {target_fps} FPS")
    return target_fps

def _unify_aspect_ratio(video_paths):
    """Helper function to unify the aspect ratio of videos."""
    ratios = [get_video_ratio(p) for p in video_paths if p and os.path.exists(p)]
    if not ratios:
        print("❌ Could not get aspect ratio from any video. Aborting merge.")
        return None, []

    most_common_ratio = Counter(ratios).most_common(1)[0][0]
    print(f"✅ Most common aspect ratio is: {most_common_ratio}")

    resized_video_paths = []
    temp_files = []
    for path in video_paths:
        if not path or not os.path.exists(path):
            continue
        
        current_ratio = get_video_ratio(path)
        if current_ratio and current_ratio != most_common_ratio:
            print(f"🔄 Resizing video {os.path.basename(path)} from ratio {current_ratio} to {most_common_ratio}...")
            temp_output_path = f"{os.path.splitext(path)[0]}_resized_{uuid.uuid4().hex[:8]}.mp4"
            resized_path = resize_to_custom_ratio(path, temp_output_path, most_common_ratio)
            if resized_path:
                resized_video_paths.append(resized_path)
                temp_files.append(resized_path)
            else:
                print(f"⚠️ Failed to resize video {os.path.basename(path)}. Using original.")
                resized_video_paths.append(path)
        else:
            resized_video_paths.append(path)
    
    return resized_video_paths, temp_files

def merge_videos(video_paths, output_filename=None, target_fps=None):
    """
    Merges multiple video files into a single file.
    It handles different aspect ratios by resizing videos to the most common one.

    :param video_paths: A list of paths to the video files.
    :param output_filename: The filename for the output video (optional). The directory will be automatically set to the first input video's directory.
    :param target_fps: The target frames per second for the output video (optional).
    :return: The path to the output video file if successful, otherwise None.
    """
    if not video_paths:
        print("⚠️ No video files provided.")
        return None

    # Use the first video's directory as the base directory
    base_dir = os.path.dirname(os.path.abspath(video_paths[0]))

    if output_filename is not None:
        # Just in case user accidentally passes a full path, extract the basename
        output_filename = os.path.basename(output_filename)
    else:
        output_filename = create_default_filename()

    output_path = os.path.join(base_dir, output_filename)

    target_fps = _determine_target_fps(video_paths, target_fps)

    temp_files = []
    clips = []
    final_clip = None
    temp_audiofile = None
    try:
        video_paths, temp_files = _unify_aspect_ratio(video_paths)

        video_paths = batch_unify_video_resolution(video_paths)
        if not video_paths:
             raise Exception("Failed to unify video resolution for any video.")

        video_paths = [str(p) for p in video_paths]

        if len(video_paths) == 1:
            shutil.copy2(video_paths[0], output_path)
            print(f"✅ Single video processed: {output_path}")
            return output_path

        print("Starting to merge videos...")
        clips = [VideoFileClip(path) for path in video_paths]
        
        final_clip = concatenate_videoclips(clips)

        if final_clip.audio is not None:
            output_stem = Path(output_filename).stem
            temp_audiofile = os.path.join(
                base_dir,
                f".{output_stem}_{os.getpid()}_{uuid.uuid4().hex}_moviepy_audio.m4a"
            )
            temp_files.append(temp_audiofile)

        final_clip.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=target_fps,
            temp_audiofile=temp_audiofile,
            remove_temp=True,
            ffmpeg_params=['-pix_fmt', 'yuv420p', '-crf', '23', '-preset', 'medium'],
            threads=4,
            logger=None
        )
        print(f"✅ Videos merged successfully: {output_path}")
        return output_path

    except Exception as e:
        print(f"❌ An error occurred during video merging: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        if final_clip:
            final_clip.close()
        for clip in clips:
            clip.close()
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    print(f"🗑️ Cleaned up temporary file: {temp_file}")
                except OSError as e:
                    print(f"🔥 Error cleaning up temp file {temp_file}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge multiple video files into a single file.")
    parser.add_argument('--video_paths', type=str, nargs='+', required=True, help='List of paths to the video files.')
    parser.add_argument('--output_filename', type=str, default=None, help='The filename for the output video (optional).')
    parser.add_argument('--target_fps', type=int, default=None, help='The target frames per second for the output video (optional).')
    
    args = parser.parse_args()
    
    result = merge_videos(args.video_paths, output_filename=args.output_filename, target_fps=args.target_fps)
    if result:
        print(f"Success! Output saved to: {result}")
    else:
        print("Failed to merge videos.")
