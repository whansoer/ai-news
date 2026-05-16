"""Video Script — 短视频口播稿 30s/60s"""
import json
import os
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
NEWS_FILE = os.path.join(DATA_DIR, "news.json")
ZH_FILE = os.path.join(DATA_DIR, "news_zh.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "script.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

SYSTEM_PROMPT = """你是 AI 科普短视频编导。根据本周最热门的 AI 新闻，写两条口播稿。

格式：
{
  "topic": "话题",
  "scripts": {
    "30s": "30秒口播稿（约80字），快节奏，开门见山，适合短视频开头",
    "60s": "60秒口播稿（约180字），有一个简单的起承转合，适合完整短视频"
  },
  "hook": "视频开头的钩子一句话，5秒抓住注意力"
}

风格：口语化、有节奏感、适合朗读。像和朋友聊天一样自然，不要书面语。"""


def load_top_items():
    items = []
    if os.path.exists(NEWS_FILE):
        with open(NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            items = data.get("items", [])

    zh_map = {}
    if os.path.exists(ZH_FILE):
        with open(ZH_FILE, "r", encoding="utf-8") as f:
            zh_data = json.load(f)
            for item in zh_data.get("items", []):
                zh_map[item["id"]] = item

    items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:10]
    return items, zh_map


def main():
    if not GEMINI_KEY:
        print("[Script] 未设置 GEMINI_KEY，跳过")
        return

    items, zh_map = load_top_items()
    if not items:
        print("[Script] 无新闻")
        return

    lines = []
    for item in items:
        zh = zh_map.get(item["id"], {})
        title = zh.get("title_zh") or item.get("title", "")
        oneliner = zh.get("oneliner", "")
        angles = item.get("narrative_angles", [])
        lines.append(
            f'- [{item.get("score", 5)}分] {title}\n'
            + (f'  概括: {oneliner}\n' if oneliner else '')
            + (f'  叙事角度: {"; ".join(angles)}\n' if angles else '')
        )
    prompt = "本周最热 AI 新闻：\n" + "\n".join(lines)

    script = {"topic": "", "scripts": {"30s": "", "60s": ""}, "hook": ""}
    try:
        resp = requests.post(
            f"{API_URL}?key={GEMINI_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.6, "maxOutputTokens": 1024},
            },
            timeout=60,
        )
        data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            script = json.loads(content[start: end + 1])
    except Exception as e:
        print(f"[Script] API 失败: {e}")
        script["topic"] = zh_map.get(items[0]["id"], {}).get("title_zh") or items[0].get("title", "AI 新闻")
        script["scripts"]["30s"] = "今天AI圈又出大事了！快来看看最新进展。"
        script["scripts"]["60s"] = "大家好，今天来聊聊AI圈的最新动态。本周最值得关注的几件事，我们一起来看看。"
        script["hook"] = "AI圈又炸了！"

    script["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    s30 = len(script.get("scripts", {}).get("30s", ""))
    s60 = len(script.get("scripts", {}).get("60s", ""))
    print(f"口播稿完成 (30s:{s30}字, 60s:{s60}字) → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
