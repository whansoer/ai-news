"""AI News Summarizer — 抓取原文 + Gemini 一句话概括"""
import json
import os
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INPUT_FILE = os.path.join(DATA_DIR, "news.json")
ZH_FILE = os.path.join(DATA_DIR, "news_zh.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
MAX_ARTICLES = 20
BATCH_SIZE = 5
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

SYSTEM_PROMPT = """你是一个科技新闻编辑。用一句简洁的中文概括文章核心内容。
规则：
1. 严格一句话，50-80个汉字
2. 突出「谁做了什么 / 发布了什么 / 意味着什么」
3. 保留技术术语原名
4. 输出严格JSON数组：[{"id":"...", "oneliner":"..."}]"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AINewsBot/1.0; +https://github.com/whansoer/ai-news)"
}


def load_news():
    if not os.path.exists(INPUT_FILE):
        print(f"[Summarize] {INPUT_FILE} 不存在，跳过")
        return []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("items", [])[:MAX_ARTICLES]


def load_zh():
    if not os.path.exists(ZH_FILE):
        return {}
    with open(ZH_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for item in data.get("items", []):
        out[item["id"]] = item
    return out


def extract_text(html, url):
    """从 HTML 中提取正文"""
    soup = BeautifulSoup(html, "html.parser")
    # 移除噪音
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    # 优先取文章主体
    article = soup.find("article") or soup.find("main") or soup.body
    if not article:
        return ""

    text = article.get_text(separator=" ", strip=True)
    # 清理多余空白
    text = re.sub(r"\s+", " ", text)
    # 截断，保留中间部分可能有更多实质内容
    if len(text) > 3000:
        text = text[:1500] + text[-1500:]
    return text


def fetch_article(url):
    """抓取文章正文"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        ct = resp.headers.get("Content-Type", "")
        if "text/html" not in ct:
            return ""
        # 检测字符编码
        resp.encoding = resp.apparent_encoding or "utf-8"
        return extract_text(resp.text, url)
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
            start = content.find("[")
            end = content.rfind("]")
            if start >= 0 and end > start:
                return json.loads(content[start: end + 1])
            return []
        except Exception as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"[Summarize] API 失败: {e}")
    return []


def main():
    if not GEMINI_KEY:
        print("[Summarize] 未设置 GEMINI_KEY，跳过")
        return

    items = load_news()
    if not items:
        print("[Summarize] 无新闻")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    zh_map = load_zh()

    # Step 1: 抓取原文
    articles = []
    for i, item in enumerate(items):
        text = fetch_article(item["url"])
        if text and len(text) > 100:
            articles.append({"id": item["id"], "text": text, "title": item["title"]})
        else:
            articles.append({"id": item["id"], "text": "", "title": item["title"]})
        if i < len(items) - 1:
            time.sleep(1)  # 请求间隔

    fetched = sum(1 for a in articles if a["text"])
    print(f"[Summarize] 抓取完成: {fetched}/{len(articles)} 篇")

    # Step 2: 分批发 Gemini 总结
    oneliners = {}
    valid = [a for a in articles if a["text"]]
    for i in range(0, len(valid), BATCH_SIZE):
        batch = valid[i: i + BATCH_SIZE]
        parts = []
        for a in batch:
            parts.append(f'id: {a["id"]}\ncontent: {a["text"][:2500]}\n')
        prompt = "\n---\n".join(parts)
        results = call_gemini(prompt)
        for r in results:
            oneliners[r.get("id", "")] = r.get("oneliner", "")
        if i + BATCH_SIZE < len(valid):
            time.sleep(2)

    # Step 3: 合并到 news_zh.json
    for item in items:
        oid = item["id"]
        if oid not in zh_map:
            zh_map[oid] = {"id": oid, "title_zh": "", "summary_zh": "", "tags_zh": [], "oneliner": ""}
        zh_map[oid]["oneliner"] = oneliners.get(oid, "")

    zh_items = [zh_map.get(item["id"], {"id": item["id"]}) for item in items]

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(zh_items),
        "items": zh_items,
    }

    with open(ZH_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    has_oneliner = sum(1 for i in zh_items if i.get("oneliner"))
    print(f"一句话概括: {has_oneliner}/{len(zh_items)} 条 → {ZH_FILE}")


if __name__ == "__main__":
    main()
