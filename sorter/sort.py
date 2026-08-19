import os
import base64
import requests
import re
import time

from tqdm import tqdm

# ===== 配置 =====
API_KEY = os.getenv("SILICONFLOW_API_KEY")
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
MODEL = "Qwen/Qwen3-VL-32B-Instruct"

IMAGE_DIR = "."   # 图片目录
SLEEP_TIME = 0.15        # 防止限流


# ===== 工具函数 =====
def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def clean_filename(text):
    text = text.strip()

    # 去非法字符
    text = re.sub(r'[\\/*?:"<>|]', "", text)

    # 合并多余空格
    text = re.sub(r"\s+", " ", text)

    return text[:40]


def generate_name(image_path):
    base64_image = encode_image(image_path)

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = """
请给这个表情包生成一个中文文件名，模仿中国互联网常见表情包命名风格：

要求：
1. 可以包含人物或来源（如：警察、葛优、贴吧表情等）
2. 优先使用短句、吐槽、命令句或情绪表达
3. 允许网络用语、抽象表达(仅在有必要时候)
4. 不要标点符号（除了空格）
5. 控制在 8-20 个字
6. 输出仅一行文件名，不要解释
7. 尽量避免过于通顺或书面语，可以略微不自然或口语化

风格分布（尽量随机）：
- 人物+台词（如：警察 你继续说）
- 吐槽句（如：被生活压扁）
- 攻击/命令句（如：说 你是猪）
- 贴吧表情风格（如：贴吧表情 滑稽流汗）

示例：
警察 你继续说
葛优 你要是唠这个我可不困了
贴吧表情 滑稽流汗
让我先尝尝你的味道
被生活压扁
"""

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 80,
        "temperature": 0.9
    }

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()

    result = resp.json()
    text = result["choices"][0]["message"]["content"]

    return clean_filename(text)


def get_unique_path(directory, filename):
    base, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1

    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base}_{counter}{ext}"
        counter += 1

    return os.path.join(directory, candidate)


# ===== 主流程 =====
def main():
    if not API_KEY:
        raise ValueError("请设置 SILICONFLOW_API_KEY 环境变量")

    files = [
        f for f in os.listdir(IMAGE_DIR)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
    ]

    for fname in tqdm(files):
        old_path = os.path.join(IMAGE_DIR, fname)

        try:
            desc = generate_name(old_path)
            ext = os.path.splitext(fname)[1]

            new_filename = f"{desc}{ext}"
            new_path = get_unique_path(IMAGE_DIR, new_filename)

            os.rename(old_path, new_path)

            time.sleep(SLEEP_TIME)

        except Exception as e:
            print(f"❌ 失败: {fname} -> {e}")


if __name__ == "__main__":
    main()