---
name: get-image-metadata
description: 图片元数据获取工具，使用exiftool/ffprobe提取图片的分辨率、格式、文件大小、EXIF拍摄信息等基础参数。当用户问及图片的宽高、分辨率、格式、拍摄时间、设备信息等元数据信息时，必须优先使用本技能，不要手动调用相关命令。
---

# Get Image Metadata Skill
基于exiftool实现的图片元数据提取工具，可以快速获取图片的宽度、高度、格式、文件大小、EXIF相关信息。

## 依赖
1. 已安装exiftool（或ffmpeg包含的ffprobe命令）
2. Python 3.7+环境

## 使用方法
### 参数说明
- `image_path`: 本地图片文件的绝对路径

### 调用方式
```bash
python get-image-metadata/scripts/get_image_metadata.py --image_path <图片路径>
```

## 示例
用户提问：`/tmp/test.png这个图片的分辨率是多少，是什么格式？`
调用命令：
```bash
python get-image-metadata/scripts/get_image_metadata.py --image_path /tmp/test.png
```

返回结果示例：
```json
{
  "width": 1920,
  "height": 1080,
  "format": "png",
  "size_bytes": 1234567,
  "exif": {
    "create_time": "2026-03-13 00:00:00",
    "camera_model": "iPhone 15 Pro"
  }
}
```