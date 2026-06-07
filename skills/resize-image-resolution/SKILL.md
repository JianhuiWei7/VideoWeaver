---
name: resize-image-resolution
description: "【图片分辨率修改工具】将指定图片缩放（改变分辨率）到指定尺寸，并保存为新图片。新文件名默认为原文件名加上分辨率（如 name_1920x1080.jpg）。当用户要求修改图片尺寸、缩放图片、指定图片分辨率时，必须立即调用此技能。"
---

# Resize Image Resolution (修改图片分辨率)

**环境依赖:** `Pillow`


## 支持模式
### 图片缩放/改变分辨率
支持将图片改变到目标分辨率，通过重采样缩放（Resize）的方式，将图片强制转换为指定的分辨率大小：
- `--image_path`: 输入图片的绝对路径。
- `--resolution`: 目标分辨率（宽x高，如 `1920x1080`、`800x600`）。
- `--session-key`: **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。

## 典型使用案例

### 1. 修改图片到指定分辨率
只需指定原图路径和分辨率，会自动在基于 session 生成的特定输出目录下生成 `{图片文件名}_{分辨率}.{后缀}`：
```bash
python resize-image-resolution/scripts/resize_image_resolution.py \
  --image_path "/path/to/image.jpg" \
  --resolution "1920x1080" \
  --session-key "agent:{agent_id}:{session_id}"
```

## 运行模式与日志监控
**默认行为**：
该脚本为前台同步执行（Blocking），直接在终端输出执行结果。

**完成状态**：
- **成功**：脚本会输出新生成的图片绝对路径。
- **失败**：日志会输出具体的错误信息，并且脚本会以非零状态码退出。

## 参数说明
| 参数名 | 说明 |
|--------|------|
| `--image_path` | （**必填**）需要修改分辨率的输入图片文件绝对路径。 |
| `--resolution` | （**必填**）目标分辨率。支持字符串格式，如 `"1920x1080"`。 |
| `--session-key` | **(Optional; OpenClaw Required)** 输出目录 session-key。CodeX/Claude Code 环境会自动识别，不需要传入内容；OpenClaw 环境必须运行 `session_status` 获取session-key并且传入, 格式通常为 `agent:{agent_id}:{session_id}`。 |

## 执行规范
- **路径检查**：确保传入的 `--image_path` 在本地确实存在。
- **结果反馈**：修改成功后，向用户汇报："✅ 图片分辨率修改成功！已保存至：[输出路径]"。如果用户需要在聊天窗口查看，可以引导用户打开该文件。
