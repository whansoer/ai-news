"""Build search index — 生成 search.html 供 Pagefind 索引"""
import json
import os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
NEWS_FILE = os.path.join(DATA_DIR, "news.json")
FAVORITES_ARCHIVE_FILE = os.path.join(DATA_DIR, "favorites_archive.json")
SEARCH_FILE = os.path.join(DATA_DIR, "search.html")


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build():
    items = []

    # 当前 news.json
    news = load_json(NEWS_FILE)
    if news:
        items.extend(news.get("items", []))

    # 所有归档
    if os.path.exists(ARCHIVE_DIR):
        for fn in sorted(os.listdir(ARCHIVE_DIR)):
            if fn.endswith(".json") and not fn.endswith(".tmp"):
                archive = load_json(os.path.join(ARCHIVE_DIR, fn))
                if archive:
                    items.extend(archive.get("items", []))

    # 收藏归档
    fav_archive = load_json(FAVORITES_ARCHIVE_FILE)
    if fav_archive:
        items.extend(fav_archive.get("items", []))

    # 去重（按 id，保留第一个出现的）
    seen = set()
    unique = []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    def esc(s):
        if not s:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    html_parts = [
        '<!DOCTYPE html>',
        '<html lang="zh-CN">',
        '<head><meta charset="UTF-8"><title>AI News Search Index</title></head>',
        '<body>',
        '<main>',
        f'<h1>AI News Search Index — {len(unique)} items, updated {datetime.now(timezone.utc).strftime("%Y-%m-%d")}</h1>',
    ]

    for item in unique:
        title = item.get("title_zh") or item.get("title", "")
        summary = item.get("summary_zh") or item.get("summary", "")
        oneliner = item.get("oneliner", "")
        tags = ", ".join((item.get("tags_zh") or item.get("tags", [])))
        source = item.get("source", "")
        published = item.get("published", "")
        url = item.get("url", "")
        item_id = item["id"]

        html_parts.append(
            f'<article>'
            f'<h2><span data-pagefind-meta="title">{esc(title)}</span></h2>'
            f'<p class="meta">'
            f'<span data-pagefind-meta="id">{esc(item_id)}</span> '
            f'<span data-pagefind-meta="source">{esc(source)}</span> '
            f'<span data-pagefind-meta="published">{esc(published)}</span> '
            f'<span data-pagefind-meta="url">{esc(url)}</span>'
            f'</p>'
            f'<p class="oneliner">{esc(oneliner)}</p>'
            f'<p class="summary">{esc(summary)}</p>'
            f'<p class="tags">{esc(tags)}</p>'
            f'</article>'
        )

    html_parts.append('</main></body></html>')

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEARCH_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))

    print(f"[BuildSearch] 生成搜索索引: {len(unique)} 条 → {SEARCH_FILE}")


if __name__ == "__main__":
    build()
