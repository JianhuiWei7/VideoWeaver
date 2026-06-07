#!/usr/bin/env python3
import argparse
import subprocess
import json
import os

def get_image_metadata(image_path):
    if not os.path.exists(image_path):
        return json.dumps({"error": "文件不存在"})
    
    try:
        # 使用exiftool获取元数据
        result = subprocess.run(
            ["exiftool", "-j", image_path],
            capture_output=True,
            text=True,
            check=True
        )
        metadata = json.loads(result.stdout)[0]
        
        res = {
            "width": metadata.get("ImageWidth", metadata.get("Width")),
            "height": metadata.get("ImageHeight", metadata.get("Height")),
            "format": metadata.get("FileTypeExtension", metadata.get("FileType")).lower(),
            "size_bytes": os.path.getsize(image_path),
            "exif": {}
        }
        
        # 提取常用EXIF信息
        if "CreateDate" in metadata:
            res["exif"]["create_time"] = metadata["CreateDate"]
        if "Model" in metadata:
            res["exif"]["camera_model"] = metadata["Model"]
        if "GPSLatitude" in metadata and "GPSLongitude" in metadata:
            res["exif"]["gps"] = {
                "latitude": metadata["GPSLatitude"],
                "longitude": metadata["GPSLongitude"]
            }
        
        return json.dumps(res, ensure_ascii=False, indent=2)
    
    except Exception as e:
        #  fallback到ffprobe如果exiftool不可用
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", image_path],
                capture_output=True,
                text=True,
                check=True
            )
            metadata = json.loads(result.stdout)
            stream = metadata["streams"][0]
            
            res = {
                "width": stream.get("width"),
                "height": stream.get("height"),
                "format": metadata["format"].get("format_name", "").split(",")[0],
                "size_bytes": int(metadata["format"].get("size", 0)),
                "exif": {}
            }
            return json.dumps(res, ensure_ascii=False, indent=2)
        except Exception as e2:
            return json.dumps({"error": f"获取元数据失败: {str(e)}, fallback失败: {str(e2)}"})

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="获取图片元数据")
    parser.add_argument("--image_path", required=True, help="图片文件路径")
    args = parser.parse_args()
    print(get_image_metadata(args.image_path))
