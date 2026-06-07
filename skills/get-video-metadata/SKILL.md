---
name: get-video-metadata
description: 视频元数据获取工具，使用ffprobe提取视频的时长、分辨率、帧率、总帧数等基础参数。当用户问及视频的时长、宽高、分辨率、帧率、总帧数等元数据信息时，必须优先使用本技能，不要手动调用ffmpeg/ffprobe命令。
---

# Get Video Metadata Skill
基于ffprobe实现的视频元数据提取工具，可以快速获取视频的时长、宽度、高度、帧率、总帧数信息。

## 依赖
1. 已安装ffmpeg（包含ffprobe命令）
2. Python 3.7+环境

## 使用方法
### 参数说明
- `video_path`: 本地视频文件的绝对路径

### 调用方式
```bash
python get-video-metadata/scripts/get_metadata.py --video_path <视频路径>
```

## 示例
用户提问：`/tmp/test.mp4这个视频有多长，分辨率是多少？`
调用命令：
```bash
python get-video-metadata/scripts/get_metadata.py --video_path /tmp/test.mp4
```

返回结果示例：
```json
{
  "duration_s": 12.34,
  "width": 1920,
  "height": 1080,
  "fps": 30.0,
  "total_frames": 370
}
```
