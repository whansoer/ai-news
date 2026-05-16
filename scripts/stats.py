"""Stats Generator — 纯本地统计，不调 API"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INPUT_FILE = os.path.join(DATA_DIR, "news.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "stats.json")


def main():
    if not os.path.exists(INPUT_FILE):
        print("[Stats] news.json 不存在，跳过")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        print("[Stats] 无数据")
        return

    # 来源分布
    sources = Counter(item.get("source", "Unknown") for item in items)

    # 标签趋势
    all_tags = []
    for item in items:
        all_tags.extend(item.get("tags", []))
    tag_counts = Counter(all_tags)

    # 分类分布
    cat_labels = {
        "model": "模型发布", "oss": "开源项目", "product": "产品/API",
        "research": "学术研究", "funding": "融资收购", "policy": "政策监管",
    }
    categories = Counter(
        cat_labels.get(item.get("category", ""), item.get("category", "其他"))
        for item in items
    )

    # 每日趋势（最近 7 天）
    now = datetime.now(timezone.utc)
    daily = defaultdict(int)
    for item in items:
        try:
            pub = item.get("published", "")
            if pub:
                d = datetime.fromisoformat(pub.replace("Z", "+00:00")).strftime("%m-%d")
                daily[d] += 1
        except (ValueError, AttributeError):
            pass
    daily_trend = [{"date": k, "count": v} for k, v in sorted(daily.items())[-7:]]

    # 热度 Top 10
    top10 = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:10]

    os.makedirs(DATA_DIR, exist_ok=True)
    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(items),
        "sources": [{"name": k, "count": v} for k, v in sources.most_common(15)],
        "tags": [{"name": k, "count": v} for k, v in tag_counts.most_common(30)],
        "categories": [{"name": k, "count": v} for k, v in categories.most_common()],
        "dailyTrend": daily_trend,
        "top10": [
            {"id": i["id"], "title": i["title"], "score": i.get("score", 0), "source": i.get("source", "")}
            for i in top10
        ],
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"统计完成: {len(items)} 条 → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
