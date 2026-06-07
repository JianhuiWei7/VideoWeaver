import os
# Install SDK:  pip install 'volcengine-python-sdk[ark]' .
from volcenginesdkarkruntime import Ark 
from volcenginesdkarkruntime.types.images.images import ContentGenerationTool

client = Ark(
    # The base URL for model invocation
    base_url="https://ark.cn-beijing.volces.com/api/v3", 
    # Get API Key：https://console.volcengine.com/ark/region:ark+cn-beijing/apikey
    api_key=os.getenv('ARK_API_KEY'), 
)

imagesResponse = client.images.generate(
    # Replace with Model ID
    model="doubao-seedream-5-0-260128",
    prompt="使用检索功能。生成一张iPhone 17 promax的图片",
    size="2048x2048",
    output_format="png",
    response_format="url",
    tools=[ContentGenerationTool(type="web_search")],
    watermark=False,
    
)
print("tool_usage.web_search:", imagesResponse.usage.tool_usage.web_search)
print(imagesResponse.data[0].url)