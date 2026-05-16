"""AI News Archiver — 将 >7 天的新闻从 news.json 归档到 archive/YYYY-MM-DD.json"""
import json
import os
from datetime import datetime, timedelta, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
NEWS_FILE = os.path.join(DATA_DIR, "news.json")
ZH_FILE = os.path.join(DATA_DIR, "news_zh.json")
RETENTION_DAYS = 7


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_archive(date_str):
    """加载某一天的归档（如果存在）"""
    path = os.path.join(ARCHIVE_DIR, f"{date_str}.json")
    items = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            items = data.get("items", [])
    return items, path


def save_archive(date_str, items):
    """保存某一天的归档"""
    path = os.path.join(ARCHIVE_DIR, f"{date_str}.json")
    data = {
        "date": date_str,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(items),
        "items": items,
    }
    save_json(path, data)
    return path


def main():
    news = load_json(NEWS_FILE)
    zh_data = load_json(ZH_FILE)

    if not news or not news.get("items"):
        print("[Archive] 无新闻可归档")
        return

    news_items = news["items"]

    # 构建 zh 查找表
    zh_map = {}
    if zh_data:
        for item in zh_data.get("items", []):
            zh_map[item["id"]] = item

    # 合并 zh 数据到每条新闻
    for item in news_items:
        z = zh_map.get(item["id"], {})
        item["title_zh"] = z.get("title_zh", "")
        item["summary_zh"] = z.get("summary_zh", "")
        item["tags_zh"] = z.get("tags_zh", [])
        item["oneliner"] = z.get("oneliner", "")

    # 计算截止日期
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

    recent = []
    archive_bins = {}  # date_str → [items]

    for item in news_items:
        pub_str = item.get("published", "")
        try:
            pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            # 无法解析日期，保留在 news.json
            recent.append(item)
            continue

        if pub_dt >= cutoff:
            recent.append(item)
        else:
            date_str = pub_dt.strftime("%Y-%m-%d")
            if date_str not in archive_bins:
                archive_bins[date_str] = []
            archive_bins[date_str].append(item)

    if not archive_bins:
        print("[Archive] 无过期新闻，跳过归档")
        return

    # 写入归档文件（合并已有）
    archived_total = 0
    for date_str, items in archive_bins.items():
        existing, _ = load_archive(date_str)
        existing_ids = {it["id"] for it in existing}
        new_items = [it for it in items if it["id"] not in existing_ids]
        merged = existing + new_items
        # 按发布时间排序
        merged.sort(key=lambda x: x.get("published", ""), reverse=True)
        save_archive(date_str, merged)
        archived_total += len(new_items)
        print(f"[Archive] {date_str}: +{len(new_items)} 条 (总计 {len(merged)} 条)")

    # 更新 news.json（只保留近期）
    news["items"] = recent
    news["total"] = len(recent)
    news["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_json(NEWS_FILE, news)

    # 更新 news_zh.json（只保留近期）
    if zh_data:
        recent_ids = {it["id"] for it in recent}
        zh_items = [it for it in zh_data.get("items", []) if it["id"] in recent_ids]
        zh_data["items"] = zh_items
        zh_data["total"] = len(zh_items)
        zh_data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_json(ZH_FILE, zh_data)

    print(f"[Archive] 归档完成: {archived_total} 条 → archive/, news.json 保留 {len(recent)} 条")


if __name__ == "__main__":
    main()
