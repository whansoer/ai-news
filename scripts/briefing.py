"""Daily Briefing — 每日 AI 简报 (150字，适合朋友圈/即刻)"""
import json
import os
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
NEWS_FILE = os.path.join(DATA_DIR, "news.json")
ZH_FILE = os.path.join(DATA_DIR, "news_zh.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "briefing.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
TOP_N = 15

SYSTEM_PROMPT = """你是 AI 新闻简报编辑。根据今日最重要的 AI 新闻，写一条 150 字中文简报。

格式：
{
  "text": "150字以内的简报，适合朋友圈/即刻发布",
  "top_items": ["3-5条最值得关注的新闻标题"]
}

风格：轻松但有料，适合 AI 爱好者阅读。突出「今天发生了什么大事」和「为什么值得关注」。用一两句话总结趋势。"""


def load_top():
    items = []
    if os.path.exists(NEWS_FILE):
        with open(NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            items = data.get("items", [])

    # 加载中文数据
    zh_map = {}
    if os.path.exists(ZH_FILE):
        with open(ZH_FILE, "r", encoding="utf-8") as f:
            zh_data = json.load(f)
            for item in zh_data.get("items", []):
                zh_map[item["id"]] = item

    # 按分数排序取 Top N
    items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:TOP_N]
    return items, zh_map


def main():
    if not GEMINI_KEY:
        print("[Briefing] 未设置 GEMINI_KEY，跳过")
        return

    items, zh_map = load_top()
    if not items:
        print("[Briefing] 无新闻")
        return

    lines = []
    for item in items:
        zh = zh_map.get(item["id"], {})
        title = zh.get("title_zh") or item.get("title", "")
        oneliner = zh.get("oneliner", "")
        lines.append(
            f'- [{item.get("score", 5)}分] {title}'
            + (f' — {oneliner}' if oneliner else '')
        )
    prompt = "今日 Top AI 新闻：\n" + "\n".join(lines)

    briefing = {"text": "", "top_items": [], "updated": ""}
    try:
        resp = requests.post(
            f"{API_URL}?key={GEMINI_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.5, "maxOutputTokens": 512},
            },
            timeout=60,
        )
        data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            briefing = json.loads(content[start: end + 1])
    except Exception as e:
        print(f"[Briefing] API 失败: {e}")
        briefing["text"] = "今日 AI 新闻已更新，点击查看详情 →"
        briefing["top_items"] = [
            (zh_map.get(it["id"], {}).get("title_zh") or it.get("title", ""))[:40]
            for it in items[:5]
        ]

    briefing["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)

    print(f"简报完成 ({len(briefing.get('text', ''))} 字) → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
