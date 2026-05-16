"""AI News Collector — 多源新闻采集脚本"""
import json
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
import requests
from bs4 import BeautifulSoup

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "news.json")
MAX_ITEMS = 200
REQUEST_TIMEOUT = 15

# ============================================================
# RSS 源配置
# ============================================================
RSS_FEEDS = [
    {"url": "https://huggingface.co/blog/feed.xml", "source": "Hugging Face", "category": "tools"},
    {"url": "https://openai.com/blog/rss.xml", "source": "OpenAI", "category": "industry"},
    {"url": "https://www.anthropic.com/feed.xml", "source": "Anthropic", "category": "industry"},
    {"url": "https://blog.google/technology/ai/rss/", "source": "Google AI", "category": "industry"},
    {"url": "https://rss.arxiv.org/rss/cs.AI", "source": "ArXiv (cs.AI)", "category": "academic"},
    {"url": "https://rss.arxiv.org/rss/cs.CL", "source": "ArXiv (cs.CL)", "category": "academic"},
    {"url": "https://www.artificialintelligence-news.com/feed/", "source": "AI News", "category": "industry"},
    {"url": "https://www.marktechpost.com/feed/", "source": "MarkTechPost", "category": "tools"},
    {"url": "https://syncedreview.com/feed/", "source": "Synced", "category": "academic"},
]

# ============================================================
# NewsAPI 配置（可选，需设置环境变量 NEWSAPI_KEY）
# ============================================================
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
NEWSAPI_URL = "https://newsapi.org/v2/everything"

# ============================================================
# HTML 标签清理
# ============================================================
def strip_html(text):
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def truncate(text, max_len=300):
    text = strip_html(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rsplit(" ", 1)[0] + "..."


def make_id(url):
    return hashlib.md5(url.encode()).hexdigest()[:12]


# ============================================================
# RSS 采集
# ============================================================
def fetch_rss(feed_info):
    items = []
    try:
        resp = requests.get(feed_info["url"], timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": "AI-News-Collector/1.0"})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        for entry in parsed.entries[:15]:
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub:
                pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
            else:
                pub_dt = datetime.now(timezone.utc)

            items.append(
                {
                    "id": make_id(entry.link),
                    "title": strip_html(entry.title),
                    "url": entry.link,
                    "source": feed_info["source"],
                    "category": feed_info["category"],
                    "summary": truncate(entry.get("summary") or entry.get("description", ""), 250),
                    "published": pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "tags": _extract_tags(strip_html(entry.title)),
                }
            )
    except Exception as e:
        print(f"[RSS] {feed_info['source']} 失败: {e}")
    return items


def _extract_tags(title):
    keywords = [
        "GPT", "Claude", "Gemini", "Llama", "Mistral", "DeepSeek", "Qwen",
        "OpenAI", "Anthropic", "Google", "Meta", "Microsoft",
        "LLM", "Agent", "RAG", "Fine-tune", "RLHF", "Prompt",
        "开源", "多模态", "Transformer", "Diffusion", "Embedding",
        "API", "部署", "推理", "训练", "GPU", "Benchmark",
    ]
    found = []
    title_lower = title.lower()
    for kw in keywords:
        if kw.lower() in title_lower:
            found.append(kw)
    return found[:5]


# ============================================================
# NewsAPI 采集（可选）
# ============================================================
def fetch_newsapi():
    if not NEWSAPI_KEY:
        print("[NewsAPI] 未设置 NEWSAPI_KEY，跳过")
        return []
    items = []
    try:
        resp = requests.get(
            NEWSAPI_URL,
            params={
                "q": "artificial intelligence OR machine learning OR large language model",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 20,
                "apiKey": NEWSAPI_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
        if data.get("status") != "ok":
            print(f"[NewsAPI] 返回错误: {data.get('message')}")
            return []

        for article in data.get("articles", []):
            pub_str = article.get("publishedAt", "")
            pub_dt = datetime.now(timezone.utc)
            if pub_str:
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            title = strip_html(article.get("title", ""))
            items.append(
                {
                    "id": make_id(article.get("url", title)),
                    "title": title,
                    "url": article.get("url", ""),
                    "source": article.get("source", {}).get("name", "NewsAPI"),
                    "category": "industry",
                    "summary": truncate(article.get("description", ""), 250),
                    "published": pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "tags": _extract_tags(title),
                }
            )
    except Exception as e:
        print(f"[NewsAPI] 异常: {e}")
    return items


# ============================================================
# GitHub Trending 爬虫（可选）
# ============================================================
def scrape_github_trending():
    items = []
    try:
        url = "https://github.com/trending?since=daily&spoken_language_code="
        headers = {"User-Agent": "AI-News-Collector/1.0"}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(resp.text, "html.parser")

        for repo in soup.select("article.Box-row")[:10]:
            h2 = repo.select_one("h2")
            if not h2:
                continue
            name = h2.get_text(strip=True)
            desc_el = repo.select_one("p")
            desc = desc_el.get_text(strip=True) if desc_el else ""
            link = "https://github.com" + h2.select_one("a")["href"] if h2.select_one("a") else ""

            # 只保留 AI/ML 相关
            combined = (name + " " + desc).lower()
            ai_kw = ["ai", "llm", "gpt", "machine-learning", "deep-learning", "nlp", "transformer",
                     "ml", "neural", "agent", "rag", "fine-tune", "embedding"]
            if not any(k in combined for k in ai_kw):
                continue

            items.append(
                {
                    "id": make_id(link),
                    "title": name,
                    "url": link,
                    "source": "GitHub Trending",
                    "category": "tools",
                    "summary": truncate(desc, 250),
                    "published": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "tags": _extract_tags(name + " " + desc),
                }
            )
    except Exception as e:
        print(f"[GitHub Trending] 异常: {e}")
    return items


# ============================================================
# 合并去重排序
# ============================================================
def merge_dedup_sort(all_items):
    seen = set()
    unique = []
    for item in sorted(all_items, key=lambda x: x["published"], reverse=True):
        key = (item["id"], item["title"].lower()[:80])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:MAX_ITEMS]


# ============================================================
# 主入口
# ============================================================
def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    all_items = []

    # RSS 并行采集
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_rss, f): f for f in RSS_FEEDS}
        for future in as_completed(futures):
            all_items.extend(future.result())

    # NewsAPI（串行，避免限流）
    all_items.extend(fetch_newsapi())

    # GitHub Trending（串行）
    all_items.extend(scrape_github_trending())

    # 合并去重排序
    final = merge_dedup_sort(all_items)

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(final),
        "items": final,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"采集完成: {len(final)} 条新闻 → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
