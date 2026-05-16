"""AI News Pruner — 删除 >30 天归档，保护收藏条目"""
import json
import os
from datetime import datetime, timedelta, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
FAVORITES_FILE = os.path.join(DATA_DIR, "favorites.json")
FAVORITES_ARCHIVE_FILE = os.path.join(DATA_DIR, "favorites_archive.json")
RETENTION_DAYS = 30


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


def main():
    # 加载受保护的收藏 ID
    favorites = load_json(FAVORITES_FILE)
    protected_ids = set()
    if favorites:
        protected_ids = set(favorites.get("ids", []))

    if not os.path.exists(ARCHIVE_DIR):
        print("[Prune] 无归档目录，跳过")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    archive_files = sorted(
        [f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".json") and not f.endswith(".tmp")]
    )

    favorites_saved = []
    deleted_count = 0

    for filename in archive_files:
        # 解析日期: YYYY-MM-DD.json
        date_str = filename.replace(".json", "")
        try:
            file_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"[Prune] 跳过无法解析日期的文件: {filename}")
            continue

        if file_date >= cutoff:
            continue  # 未过期，保留

        filepath = os.path.join(ARCHIVE_DIR, filename)

        # 提取受保护的条目
        saved_from_this = 0
        if protected_ids:
            data = load_json(filepath)
            if data:
                for item in data.get("items", []):
                    if item["id"] in protected_ids:
                        favorites_saved.append(item)
                        protected_ids.discard(item["id"])
                        saved_from_this += 1

        # 原子删除
        tmp = filepath + ".tmp"
        try:
            os.remove(filepath)
        except OSError:
            pass
        if os.path.exists(tmp):
            os.remove(tmp)

        deleted_count += 1
        print(f"[Prune] 删除过期归档: {filename}" + (f" (保存收藏 {saved_from_this} 条)" if saved_from_this else ""))

    # 合并已保存的收藏条目
    if favorites_saved:
        existing_favs = []
        if os.path.exists(FAVORITES_ARCHIVE_FILE):
            existing_favs = load_json(FAVORITES_ARCHIVE_FILE)
            if existing_favs:
                existing_favs = existing_favs.get("items", [])

        existing_ids = {it["id"] for it in existing_favs}
        new_favs = [it for it in favorites_saved if it["id"] not in existing_ids]
        merged = existing_favs + new_favs

        fav_output = {
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total": len(merged),
            "items": merged,
        }
        save_json(FAVORITES_ARCHIVE_FILE, fav_output)
        print(f"[Prune] 收藏条目已转存到 favorites_archive.json: +{len(new_favs)} 条 (总计 {len(merged)} 条)")

    print(f"[Prune] 清理完成: 删除 {deleted_count} 个归档文件")


if __name__ == "__main__":
    main()
