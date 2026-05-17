"""AI News Translator — Google Gemini 免费翻译（带缓存）"""
import json
import os
import time
from datetime import datetime, timezone

import requests

from cache import Cache
from quality import check_cjk, check_entity_consistency, check_json_structure

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INPUT_FILE = os.path.join(DATA_DIR, "news.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "news_zh.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
MAX_ITEMS = 20
BATCH_SIZE = 10
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

SYSTEM_PROMPT = """你是一个 AI 新闻翻译专家。将给出的英文 AI 新闻标题和摘要翻译成中文。
规则：
1. 保留技术术语原名（如 GPT、Claude、LLM、RAG、Transformer 等），括号补充中文说明
2. 保持简洁，每条翻译控制在对应原文长度的 80%-120%
3. 输出格式：严格 JSON 数组，每个元素 {"id":"...", "title_zh":"...", "summary_zh":"...", "tags_zh":[...]}
4. **关键：title_zh 和 summary_zh 必须是中文翻译，不能直接复制英文原文！**"""


def load_news():
    if not os.path.exists(INPUT_FILE):
        print(f"[Translate] {INPUT_FILE} 不存在，跳过")
        return []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("items", [])[:MAX_ITEMS]


def build_user_prompt(batch):
    lines = []
    for item in batch:
        lines.append(
            f'id: {item["id"]}\n'
            f'title: {item["title"]}\n'
            f'summary: {item.get("summary", "")[:200]}\n'
            f'tags: {", ".join(item.get("tags", []))}\n'
        )
    return "\n---\n".join(lines)


def call_gemini(user_prompt, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{API_URL}?key={GEMINI_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {
                        "parts": [{"text": SYSTEM_PROMPT}]
                    },
                    "contents": [
                        {"role": "user", "parts": [{"text": user_prompt}]}
                    ],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 4096,
                    },
                },
                timeout=60,
            )
            if resp.status_code == 429:
                delay = 5 * (2 ** attempt)  # 5, 10, 20s exponential backoff
                print(f"[Translate] API 429 (配额超限)，{delay}s 后重试 (attempt {attempt+1}/{retries+1})")
                if attempt < retries:
                    time.sleep(delay)
                    continue
                return []
            if resp.status_code != 200:
                print(f"[Translate] API HTTP {resp.status_code}: {resp.text[:200]}")
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                return []
            data = resp.json()
            if "candidates" not in data or not data["candidates"]:
                print(f"[Translate] API 返回无 candidates: {json.dumps(data, ensure_ascii=False)[:300]}")
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                return []
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            start = content.find("[")
            end = content.rfind("]")
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start: end + 1])
                except json.JSONDecodeError:
                    # Batch parse failed — try to salvage individual objects
                    print(f"[Translate] JSON 数组解析失败，尝试逐条提取...")
                    objects = []
                    depth = 0
                    obj_start = -1
                    for i, ch in enumerate(content):
                        if ch == '{':
                            if depth == 0:
                                obj_start = i
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0 and obj_start >= 0:
                                try:
                                    obj = json.loads(content[obj_start: i + 1])
                                    objects.append(obj)
                                except json.JSONDecodeError:
                                    pass
                                obj_start = -1
                    if objects:
                        print(f"[Translate] 逐条提取成功: {len(objects)} 条")
                        return objects
                    return []
            return []
        except Exception as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"[Translate] API 失败: {e}")
    return []


def validate_translations(results, batch_ids, original_titles=None):
    """Return (valid, failed) — failed items have no CJK in title or summary.
    Also checks entity consistency if original_titles map is provided."""
    valid, failed = {}, set()
    orig = original_titles or {}
    for item in results:
        item_id = item.get("id", "")
        title = item.get("title_zh", "")
        summary = item.get("summary_zh", "")
        # Structural check
        struct_ok, _ = check_json_structure(item, ["title_zh"])
        # CJK check — both title and summary must contain Chinese
        cjk_ok = check_cjk(title) and check_cjk(summary)
        # Entity check (skip if no original title to compare)
        ent_score = check_entity_consistency(orig.get(item_id, ""), title) if orig else 1.0
        if struct_ok and cjk_ok and ent_score >= 0.3:
            valid[item_id] = {
                "title_zh": title,
                "summary_zh": summary,
                "tags_zh": item.get("tags_zh", []),
            }
        else:
            failed.add(item_id)
    for item_id in batch_ids:
        if item_id not in valid:
            failed.add(item_id)
    return valid, failed


def translate_batch(batch):
    if not batch:
        return []
    batch_ids = {item["id"] for item in batch}
    orig_titles = {item["id"]: item.get("title", "") for item in batch}
    user_prompt = build_user_prompt(batch)
    results = call_gemini(user_prompt)
    out, failed = validate_translations(results, batch_ids, orig_titles)

    # Retry failed items once individually with a stronger prompt
    if failed:
        retry_items = [item for item in batch if item["id"] in failed]
        retry_orig = {item["id"]: item.get("title", "") for item in retry_items}
        retry_prompt = "【重要：必须翻译成中文！不要保留英文原文！】\n" + build_user_prompt(retry_items)
        retry_results = call_gemini(retry_prompt)
        retry_out, still_failed = validate_translations(retry_results, {item["id"] for item in retry_items}, retry_orig)
        out.update(retry_out)
        failed = still_failed

    # Fallback: mark as English original + flag
    for item in batch:
        if item["id"] not in out:
            out[item["id"]] = {
                "title_zh": item.get("title", ""),
                "summary_zh": item.get("summary", ""),
                "tags_zh": item.get("tags", []),
                "_fallback": True,
            }
    return out


def main():
    if not GEMINI_KEY:
        print("[Translate] 未设置 GEMINI_KEY，跳过翻译")
        return

    items = load_news()
    if not items:
        print("[Translate] 无新闻可翻译")
        return
    # Sort by score descending — high-value articles get translated first
    items.sort(key=lambda x: x.get("score", 0), reverse=True)
    items = items[:MAX_ITEMS]

    os.makedirs(DATA_DIR, exist_ok=True)
    cache = Cache("translate")
    translated = {}
    uncached = []
    cache_hits = 0

    # Pass 1: check cache for each item
    for item in items:
        key = cache.make_key(
            item["id"],
            item.get("title", ""),
            item.get("summary", "")[:200],
            ",".join(item.get("tags", [])),
        )
        cached = cache.get(key)
        if cached and not cached.get("_fallback"):
            # Re-validate: cached translation must still have CJK
            if check_cjk(cached.get("title_zh", "")) and check_cjk(cached.get("summary_zh", "")):
                translated[item["id"]] = cached
                cache_hits += 1
                continue
        uncached.append(item)

    print(f"[Translate] 缓存命中: {cache_hits}/{len(items)}, 需翻译: {len(uncached)}")

    # Pass 2: translate uncached items in batches
    for i in range(0, len(uncached), BATCH_SIZE):
        batch = uncached[i: i + BATCH_SIZE]
        results = translate_batch(batch)
        translated.update(results)
        # Cache individual results — skip fallback entries to prevent bad data persistence
        for item in batch:
            result = results.get(item["id"])
            if result and not result.get("_fallback"):
                key = cache.make_key(
                    item["id"],
                    item.get("title", ""),
                    item.get("summary", "")[:200],
                    ",".join(item.get("tags", [])),
                )
                cache.set(key, result)
        if i + BATCH_SIZE < len(uncached):
            time.sleep(2)

    cache.save()
    print(f"[Translate] 缓存已保存: {cache.hits()} 条")

    zh_items = []
    for item in items:
        t = translated.get(item["id"], {})
        zh_items.append({
            "id": item["id"],
            "title_zh": t.get("title_zh", item.get("title", "")),
            "summary_zh": t.get("summary_zh", item.get("summary", "")),
            "tags_zh": t.get("tags_zh", item.get("tags", [])),
        })

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(zh_items),
        "items": zh_items,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"翻译完成: {len(zh_items)} 条 → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
