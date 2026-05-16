"""Deep Research — AI-powered deep analysis of top 2 stories.

Fetches article text, sends to Gemini for structured deep analysis.
Output: data/deepresearch.json
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from cache import Cache
from quality import check_cjk, check_json_structure

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INPUT_FILE = os.path.join(DATA_DIR, "news.json")
ZH_FILE = os.path.join(DATA_DIR, "news_zh.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "deepresearch.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
TOP_N = 2

SYSTEM_PROMPT = """你是 AI 行业深度分析师。对给定的 AI 新闻进行深度分析，输出严格 JSON：

{
  "id": "文章id",
  "title_zh": "中文标题（如果是英文标题需要翻译）",
  "thesis": "核心观点，100字以内。这篇文章的核心论点是什么？",
  "key_data": ["关键数据点1", "关键数据点2", "关键数据点3"],
  "impact": "行业影响，100字以内。这件事对AI行业意味着什么？",
  "why_matters": "值得关注的原因，50字以内",
  "related_context": "相关背景补充，50字以内。这条新闻与最近什么趋势/事件有关？"
}

规则：
1. 所有文字字段必须使用中文
2. key_data 提取 2-4 条可引用的关键数据点
3. 保持客观，不要过度解读
4. 如果无法从原文获取足够信息，基于标题和摘要进行分析"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AINewsBot/1.0; +https://github.com/whansoer/ai-news)"
}


def load_top():
    if not os.path.exists(INPUT_FILE):
        return [], {}
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:TOP_N]

    zh_map = {}
    if os.path.exists(ZH_FILE):
        with open(ZH_FILE, "r", encoding="utf-8") as f:
            zh_data = json.load(f)
            for item in zh_data.get("items", []):
                zh_map[item["id"]] = item
    return items, zh_map


def fetch_article(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        ct = resp.headers.get("Content-Type", "")
        if "text/html" not in ct:
            return ""
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        article = soup.find("article") or soup.find("main") or soup.body
        if not article:
            return ""
        text = article.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        if len(text) > 3000:
            text = text[:1500] + text[-1500:]
        return text
    except Exception:
        return ""


def call_gemini(prompt, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{API_URL}?key={GEMINI_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048},
                },
                timeout=60,
            )
            data = resp.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start: end + 1])
            return None
        except Exception as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"[DeepResearch] API 失败: {e}")
    return None


def main():
    if not GEMINI_KEY:
        print("[DeepResearch] 未设置 GEMINI_KEY，跳过")
        return

    items, zh_map = load_top()
    if not items:
        print("[DeepResearch] 无新闻")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    cache = Cache("deepresearch")
    results = []
    cache_hits = 0

    for item in items:
        oid = item["id"]
        zh = zh_map.get(oid, {})
        title = zh.get("title_zh") or item.get("title", "")
        summary = zh.get("summary_zh") or item.get("summary", "")

        # Cache key: article ID + first 500 chars of fetched text
        article_text = fetch_article(item["url"])
        text_snippet = (article_text or summary)[:500]
        ckey = cache.make_key(oid, title, text_snippet)

        cached = cache.get(ckey)
        if cached and check_cjk(cached.get("thesis", "")):
            results.append(cached)
            cache_hits += 1
            print(f"[DeepResearch] 缓存命中: {title[:40]}")
            continue

        # Build prompt
        prompt = f"""分析以下 AI 新闻：

标题：{title}
摘要：{summary[:300]}
正文摘要：{text_snippet[:1500]}

请按 JSON 格式输出深度分析。"""

        result = call_gemini(prompt)
        if result:
            ok, errs = check_json_structure(result, ["thesis", "impact", "why_matters"])
            has_cjk_chars = check_cjk(result.get("thesis", ""))
            if ok and has_cjk_chars:
                result["id"] = oid
                results.append(result)
                cache.set(ckey, result)
            else:
                print(f"[DeepResearch] 质量不达标 {oid}: struct={ok}, cjk={has_cjk_chars}")
                # Fallback: build from available data
                results.append({
                    "id": oid,
                    "title_zh": title,
                    "thesis": summary[:100] if summary else "暂无深度分析",
                    "key_data": [],
                    "impact": "",
                    "why_matters": "",
                    "related_context": "",
                    "_fallback": True,
                })
        else:
            results.append({
                "id": oid,
                "title_zh": title,
                "thesis": summary[:100] if summary else "暂无深度分析",
                "key_data": [],
                "impact": "",
                "why_matters": "",
                "related_context": "",
                "_fallback": True,
            })

        time.sleep(1)  # Rate limit

    cache.save()

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(results),
        "items": results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[DeepResearch] 完成: {cache_hits} 缓存, {len(results)} 条 → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
