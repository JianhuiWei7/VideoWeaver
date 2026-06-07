---
name: vision-understanding
description: 基于字节跳动火山引擎Ark平台的多模态理解工具，支持图像理解和视频理解两种能力。只要用户提到分析图片内容、理解图片、查询图片里有什么、图片中的人物/物体动作/信息、回答图片相关问题，或者分析视频内容、理解视频、查询视频里发生了什么、回答视频相关问题等需求时，必须优先使用本技能，不要尝试通过手动提取帧的方式分析视频或其他方式分析图片。
---
# 视觉理解工具（vision-understanding）

**环境依赖:** `openai`、`volcenginesdkarkruntime`

本技能整合了图像理解和视频理解能力，基于火山引擎Ark平台的豆包多模态模型实现。



## 核心功能

### 统一视觉理解接口
支持同时传入多个图片和视频，按顺序上传到Ark并进行内容理解，返回统一的描述结果，支持自定义查询提示词。

#### 函数定义
```python
def vision_understanding(media_paths: list[str], prompt: str = "请详细描述这些媒体的内容，包括所有可见的人物、物体、场景、动作、事件和文字信息") -> str:
    """
    统一的视觉理解接口，支持同时传入多个图片和视频，按顺序进行理解
    :param media_paths: 媒体文件路径列表，支持同时传入图片和视频，按传入顺序处理
    :param prompt: 查询提示词，默认是通用描述，可自定义提问
    :return: 内容描述文本，失败返回空字符串
    """
```

## 使用示例

### 自然语言提问示例
1. **单张图片识别**：`帮我看看这张发票上的金额是多少`
2. **单个视频内容总结**：`给我总结下这个视频讲了什么故事`
3. **多张图片对比**：`对比这两张截图里的界面有什么不同`
4. **视频+图片混合分析**：`视频里出现的人物和这张照片里的是不是同一个人`
5. **细节查询**：`这个视频第30秒的画面里有几个杯子，分别是什么颜色的`
6. **跨媒体推理**：`结合这张设计图和演示视频，告诉我这个产品的功能是什么`

### 命令行调用示例
1. 单张图片分析：
```bash
python vision-understanding/scripts/vision_understanding.py --media test.jpg --prompt "描述这张图片的内容"
```
2. 单个视频分析（自定义帧率）：
```bash
python vision-understanding/scripts/vision_understanding.py --media demo.mp4 --fps 2.0 --prompt "总结视频里的主要事件"
```
3. 多个媒体混合对比：
```bash
python vision-understanding/scripts/vision_understanding.py --media demo.mp4 screenshot1.jpg screenshot2.png --prompt "对比视频和两张截图的内容，找出不同点"
```
4. 使用指定模型分析：
```bash
python vision-understanding/scripts/vision_understanding.py --media test.jpg --model doubao-seed-1-8-251228 --prompt "识别这张图里的文字"
```
