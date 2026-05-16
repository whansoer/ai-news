"""Topic Outline — 每周话题深稿大纲"""
import json
import os
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
NEWS_FILE = os.path.join(DATA_DIR, "news.json")
ZH_FILE = os.path.join(DATA_DIR, "news_zh.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "outline.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

SYSTEM_PROMPT = """你是 AI 行业深度分析作者。根据本周最重要的 AI 新闻，选一个最值得深写的话题，输出一份结构化文章大纲。

格式：
{
  "topic": "话题标题",
  "hook": "开篇钩子，50字以内，吸引读者继续阅读",
  "sections": [
    {
      "heading": "章节标题",
      "content": "该章节要点，30-50字",
      "refs": ["引用的新闻标题1", "引用的新闻标题2"]
    }
  ],
  "conclusion": "结尾总结，50字以内",
  "suggested_title": "建议的文章标题"
}

要求：
- 大纲 4-6 个章节，逻辑递进（背景→现状→分析→展望）
- refs 引用实际新闻，至少 2 条
- 面向 AI 爱好者，深度但易懂
- 每个章节标注可引用的数据点或金句来源"""


def load_week_items():
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

    # 取 Top 20 高分新闻
    items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:20]
    return items, zh_map


def main():
    if not GEMINI_KEY:
        print("[Outline] 未设置 GEMINI_KEY，跳过")
        return

    items, zh_map = load_week_items()
    if not items:
        print("[Outline] 无新闻")
        return

    lines = []
    for item in items:
        zh = zh_map.get(item["id"], {})
        title = zh.get("title_zh") or item.get("title", "")
        oneliner = zh.get("oneliner", "")
        facts = zh.get("key_facts", [])
        quote = zh.get("notable_quote", {})
        lines.append(
            f'- [{item.get("score", 5)}分][{item.get("category", "")}] {title}\n'
            + (f'  概括: {oneliner}\n' if oneliner else '')
            + (f'  数据: {"; ".join(facts)}\n' if facts else '')
            + (f'  金句: {quote.get("zh", "")}\n' if quote.get("zh") else '')
        )
    prompt = "本周 AI 新闻 Top 20（含素材）：\n" + "\n".join(lines)

    outline = {"topic": "", "hook": "", "sections": [], "conclusion": "", "suggested_title": ""}
    try:
        resp = requests.post(
            f"{API_URL}?key={GEMINI_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.5, "maxOutputTokens": 2048},
            },
            timeout=60,
        )
        data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            outline = json.loads(content[start: end + 1])
    except Exception as e:
        print(f"[Outline] API 失败: {e}")
        outline["topic"] = "本周 AI 热点话题"
        outline["hook"] = "本周 AI 领域又发生了哪些值得关注的大事？一起来看。"
        outline["sections"] = [
            {"heading": "本周要闻", "content": "", "refs": [it["title"][:30] for it in items[:3]]}
        ]
        outline["conclusion"] = "AI 发展日新月异，保持关注。"
        outline["suggested_title"] = "AI 周观察"

    outline["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(outline, f, ensure_ascii=False, indent=2)

    print(f"大纲完成 ({len(outline.get('sections', []))} 章节) → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
