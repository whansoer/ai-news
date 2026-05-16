"""Daily Briefing — 每日 AI 简报 (150字，适合朋友圈/即刻)（带缓存）"""
import json
import os
from datetime import datetime, timezone

import requests

from cache import Cache
from quality import check_briefing_top_items, check_output_length, check_cjk, score_output

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
  "top_items": ["3-5条最值得关注的新闻标题（使用中文）"]
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

    # Cache: key = today + hash of top article IDs + scores
    briefing = {}  # 确保变量始终定义
    cache = Cache("briefing")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache_key = cache.make_key(today, *(f'{it["id"]}:{it.get("score",0)}' for it in items))
    cached = cache.get(cache_key)
    if cached and cached.get("text"):
        cached_text = cached.get("text", "")
        if len(cached_text) >= 15 and any(
            '一' <= c <= '鿿' or c.isascii() and c.isalpha()
            for c in cached_text
        ):
            briefing = cached
            briefing["_from_cache"] = True
            print(f"[Briefing] 缓存命中，跳过 API")

    if not briefing.get("text"):
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

    # Sanity check: if text is garbled (short, no CJK or ASCII letters), use fallback
    text = briefing.get("text", "")
    scores = score_output(text) if (briefing.get("_from_cache") or text) else {}
    ok_len, text_len = check_output_length(text, 15)
    has_cjk_chars = check_cjk(text)
    has_valid_chars = has_cjk_chars or (bool(text) and any(c.isascii() and c.isalpha() for c in text))
    if not has_valid_chars or not ok_len:
        print(f"[Briefing] 输出乱码/过短 (len={text_len}, cjk={has_cjk_chars})，使用降级文本")
        briefing["text"] = "今日 AI 新闻已更新，点击查看详情 →"
        briefing["top_items"] = [
            (zh_map.get(it["id"], {}).get("title_zh") or it.get("title", ""))[:40]
            for it in items[:5]
        ]

    # Cross-step verification: top_items should match actual news titles
    all_titles = [item.get("title", "") for item in items]
    ok_xref, matched_n, unmatched = check_briefing_top_items(briefing, all_titles)
    if not ok_xref:
        print(f"[Briefing] 交叉验证: {matched_n} 匹配, {len(unmatched)} 不匹配 → {unmatched[:3]}")

    # Cache the valid result (not garble, not fallback)
    if briefing.get("text") and not briefing.get("_from_cache"):
        briefing_clean = {k: v for k, v in briefing.items() if not k.startswith("_")}
        cache.set(cache_key, briefing_clean)
        cache.save()
        print(f"[Briefing] 缓存已保存: {cache.hits()} 条")

    briefing["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)

    print(f"简报完成 ({len(briefing.get('text', ''))} 字) → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
