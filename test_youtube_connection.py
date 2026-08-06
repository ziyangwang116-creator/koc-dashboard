import os
import sys

import requests
from dotenv import load_dotenv


print("1. 诊断程序已启动")

load_dotenv()

api_key = os.getenv("YOUTUBE_API_KEY")

if not api_key:
    print("失败：未读取到 YOUTUBE_API_KEY")
    sys.exit(1)

print("2. 已读取到 API Key，但不会显示密钥内容")
print("3. 正在连接 YouTube Data API……")

try:
    response = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={
            "part": "snippet,statistics",
            "forHandle": "@YouTube",
            "key": api_key,
        },
        timeout=(5, 15),
    )

    print("4. 已收到服务器响应")
    print("HTTP 状态码：", response.status_code)

    try:
        data = response.json()
    except ValueError:
        print("失败：服务器返回的内容不是有效 JSON")
        print("返回内容前200个字符：", response.text[:200])
        sys.exit(1)

    if response.ok:
        items = data.get("items", [])
        print("连接成功")
        print("返回频道数量：", len(items))

        if items:
            channel = items[0]
            print("频道名称：", channel.get("snippet", {}).get("title"))
            print(
                "公开订阅数：",
                channel.get("statistics", {}).get("subscriberCount"),
            )
        else:
            print("API请求成功，但没有找到测试频道")
    else:
        error = data.get("error", {})
        reasons = [
            item.get("reason")
            for item in error.get("errors", [])
            if item.get("reason")
        ]
        print("Google 错误原因：", reasons)
        print("错误信息：", error.get("message", "未知错误"))

except requests.exceptions.ConnectTimeout:
    print("失败：连接 Google API 超时")
except requests.exceptions.ReadTimeout:
    print("失败：读取 Google API 响应超时")
except requests.exceptions.ProxyError as exc:
    print("失败：代理配置错误")
    print("异常类型：", type(exc).__name__)
except requests.exceptions.SSLError as exc:
    print("失败：SSL证书验证错误")
    print("异常类型：", type(exc).__name__)
except requests.exceptions.ConnectionError as exc:
    print("失败：网络连接错误")
    print("异常类型：", type(exc).__name__)
    print("异常摘要：", str(exc)[:500])
except requests.exceptions.RequestException as exc:
    print("失败：HTTP请求异常")
    print("异常类型：", type(exc).__name__)
    print("异常摘要：", str(exc)[:500])
except Exception as exc:
    print("失败：发生未预期异常")
    print("异常类型：", type(exc).__name__)
    print("异常摘要：", str(exc)[:500])