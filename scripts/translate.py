"""AI News Translator — Google Gemini 免费翻译"""
import json
import os
import time
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INPUT_FILE = os.path.join(DATA_DIR, "news.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "news_zh.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
MAX_ITEMS = 50
BATCH_SIZE = 10
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

SYSTEM_PROMPT = """你是一个 AI 新闻翻译专家。将给出的英文 AI 新闻标题和摘要翻译成中文。
规则：
1. 保留技术术语原名（如 GPT、Claude、LLM、RAG、Transformer 等），括号补充中文说明
2. 保持简洁，每条翻译控制在对应原文长度的 80%-120%
3. 输出格式：严格 JSON 数组，每个元素 {"id":"...", "title_zh":"...", "summary_zh":"...", "tags_zh":[...]}"""


def load_news():
    if not os.path.exists(INPUT_FILE):
        print(f"[Translate] {INPUT_FILE} 不存在，跳过")
        return []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("items", [])[:MAX_ITEMS]


def build_user_prompt(batch):
    lines = []
    for item in batch:
        lines.append(
            f'id: {item["id"]}\n'
            f'title: {item["title"]}\n'
            f'summary: {item.get("summary", "")[:200]}\n'
            f'tags: {", ".join(item.get("tags", []))}\n'
        )
    return "\n---\n".join(lines)


def call_gemini(user_prompt, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{API_URL}?key={GEMINI_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {
                        "parts": [{"text": SYSTEM_PROMPT}]
                    },
                    "contents": [
                        {"role": "user", "parts": [{"text": user_prompt}]}
                    ],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 4096,
                    },
                },
                timeout=60,
            )
            data = resp.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            start = content.find("[")
            end = content.rfind("]")
            if start >= 0 and end > start:
                return json.loads(content[start: end + 1])
            return []
        except Exception as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"[Translate] API 失败: {e}")
    return []


def translate_batch(batch):
    if not batch:
        return []
    user_prompt = build_user_prompt(batch)
    results = call_gemini(user_prompt)
    out = {}
    for item in results:
        item_id = item.get("id", "")
        out[item_id] = {
            "title_zh": item.get("title_zh", ""),
            "summary_zh": item.get("summary_zh", ""),
            "tags_zh": item.get("tags_zh", []),
        }
    for item in batch:
        if item["id"] not in out:
            out[item["id"]] = {
                "title_zh": item.get("title", ""),
                "summary_zh": item.get("summary", ""),
                "tags_zh": item.get("tags", []),
            }
    return out


def main():
    if not GEMINI_KEY:
        print("[Translate] 未设置 GEMINI_KEY，跳过翻译")
        return

    items = load_news()
    if not items:
        print("[Translate] 无新闻可翻译")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    translated = {}

    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i: i + BATCH_SIZE]
        results = translate_batch(batch)
        translated.update(results)
        if i + BATCH_SIZE < len(items):
            time.sleep(2)

    zh_items = []
    for item in items:
        t = translated.get(item["id"], {})
        zh_items.append({
            "id": item["id"],
            "title_zh": t.get("title_zh", item.get("title", "")),
            "summary_zh": t.get("summary_zh", item.get("summary", "")),
            "tags_zh": t.get("tags_zh", item.get("tags", [])),
        })

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(zh_items),
        "items": zh_items,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"翻译完成: {len(zh_items)} 条 → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
