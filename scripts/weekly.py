"""Weekly Digest — AI 精选周报"""
import json
import os
import time
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INPUT_FILE = os.path.join(DATA_DIR, "news.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "weekly.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
TOP_N = 10

SYSTEM_PROMPT = """你是 AI 行业周报编辑。根据本周最重要的 AI 新闻，写一份 300 字中文周报。

格式：
{
  "title": "本周 AI 周报 (日期范围)",
  "summary": "300字以内的周报正文，涵盖最重要的进展和趋势",
  "highlights": ["3-5条本周亮点"]
}

风格：专业但易读，突出「发生了什么」和「为什么重要」"""


def load_top():
    if not os.path.exists(INPUT_FILE):
        return []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    return sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:TOP_N]


def main():
    if not GEMINI_KEY:
        print("[Weekly] 未设置 GEMINI_KEY，跳过")
        return

    top = load_top()
    if not top:
        print("[Weekly] 无新闻")
        return

    # 日期范围
    dates = []
    for item in top:
        try:
            d = datetime.fromisoformat(item["published"].replace("Z", "+00:00"))
            dates.append(d)
        except (ValueError, KeyError):
            pass
    if dates:
        date_range = f"{min(dates).strftime('%m/%d')}-{max(dates).strftime('%m/%d')}"
    else:
        date_range = datetime.now(timezone.utc).strftime("%Y年第%W周")

    # 构建 prompt
    lines = []
    for item in top:
        lines.append(
            f'- [{item.get("score", 5)}分] {item["title"]} '
            f'({item.get("source", "")}) — {item.get("summary", "")[:120]}'
        )
    prompt = "本周 Top 10 AI 新闻：\n" + "\n".join(lines)

    # 调用 Gemini
    week_data = {"title": f"AI 周报 {date_range}", "summary": "", "highlights": []}
    try:
        resp = requests.post(
            f"{API_URL}?key={GEMINI_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.5, "maxOutputTokens": 1024},
            },
            timeout=60,
        )
        data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            week_data = json.loads(content[start: end + 1])
    except Exception as e:
        print(f"[Weekly] API 失败: {e}")
        week_data["summary"] = "本周 AI 新闻摘要（自动生成失败，请查看下方新闻列表）"
        week_data["highlights"] = [item["title"][:40] for item in top[:5]]

    week_data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    week_data["top_ids"] = [item["id"] for item in top]

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(week_data, f, ensure_ascii=False, indent=2)

    print(f"周报完成 → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
