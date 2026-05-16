"""Cross-source verification — mark articles as multi-source or single-source.

No Gemini call needed. Uses entity extraction + title similarity + time window
to detect when multiple sources cover the same story.

Adds a `verification` field to each article in news.json:
{
  "level": "multi-source" | "single-source",
  "corroborating_ids": [...],
  "score": 1-10
}
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INPUT_FILE = os.path.join(DATA_DIR, "news.json")


def extract_entities(title: str) -> set:
    """Extract key entities from a title: company names, model names, event names."""
    entities = set()
    # Known companies
    companies = [
        "OpenAI", "Google", "DeepMind", "Meta", "Microsoft", "Anthropic",
        "Nvidia", "AMD", "Intel", "Apple", "Amazon", "Tesla", "xAI",
        "Mistral", "Stability AI", "Hugging Face", "Cohere", "Perplexity",
        "Midjourney", "Runway", "ElevenLabs", "Character.AI", "Inflection",
        "Baidu", "Alibaba", "Tencent", "ByteDance", "DeepSeek",
    ]
    # Known model families
    models = [
        "GPT-5", "GPT-4", "GPT-4o", "Claude 4", "Claude Opus", "Claude Sonnet",
        "Gemini 3", "Gemini 2", "Gemma", "Llama 4", "Llama 3", "Mistral",
        "DeepSeek", "Grok", "Stable Diffusion", "Sora", "DALL-E",
        "Midjourney V", "Flux", "o3", "o4", "Grok-3",
    ]
    title_lower = title.lower()
    for comp in companies:
        if comp.lower() in title_lower:
            entities.add(comp.lower())
    for model in models:
        if model.lower() in title_lower:
            entities.add(model.lower())
    # Regex: extract proper nouns (consecutive capitalized words)
    proper_nouns = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b', title)
    for pn in proper_nouns:
        if len(pn) > 8:
            entities.add(pn.lower())
    return entities


def word_overlap(title_a: str, title_b: str) -> float:
    """Jaccard similarity of significant words (3+ chars, not stopwords)."""
    stop = {"the", "and", "for", "with", "from", "this", "that", "what", "how",
            "new", "its", "not", "are", "was", "has", "can", "will", "your"}
    words_a = {w.lower() for w in re.findall(r'[a-zA-Z]{3,}', title_a) if w.lower() not in stop}
    words_b = {w.lower() for w in re.findall(r'[a-zA-Z]{3,}', title_b) if w.lower() not in stop}
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def compute_verification(items: list) -> dict:
    """For each item, compute verification level and score.

    Returns: dict[id] -> verification dict
    """
    result = {}
    n = len(items)
    if n < 2:
        for item in items:
            result[item["id"]] = {
                "level": "single-source",
                "corroborating_ids": [],
                "score": 1,
            }
        return result

    # Build index: entity -> list of article ids
    entity_index = defaultdict(list)
    entities_map = {}
    for item in items:
        title = item.get("title", "")
        ents = extract_entities(title)
        entities_map[item["id"]] = ents
        for e in ents:
            entity_index[e].append(item["id"])

    # Check each pair
    corroborating = defaultdict(list)  # id -> [ids that corroborate]
    for i, item_a in enumerate(items):
        id_a = item_a["id"]
        title_a = item_a.get("title", "")
        pub_a = parse_time(item_a.get("published", ""))
        for j, item_b in enumerate(items):
            if i >= j:
                continue
            id_b = item_b["id"]
            title_b = item_b.get("title", "")
            pub_b = parse_time(item_b.get("published", ""))

            score = 0
            # Entity overlap
            ents_a = entities_map.get(id_a, set())
            ents_b = entities_map.get(id_b, set())
            shared_ents = ents_a & ents_b
            if shared_ents:
                score += min(len(shared_ents) * 3, 6)
            # Word overlap
            overlap = word_overlap(title_a, title_b)
            if overlap > 0.3:
                score += int(overlap * 10)
            # Time proximity (within 24h)
            if pub_a and pub_b:
                delta = abs((pub_a - pub_b).total_seconds())
                if delta < 86400:  # 24h
                    score += 2
                if delta < 43200:  # 12h
                    score += 1

            if score >= 4:  # threshold for corroboration
                corroborating[id_a].append(id_b)
                corroborating[id_b].append(id_a)

    # Assign levels
    for item in items:
        oid = item["id"]
        corr = corroborating.get(oid, [])
        if len(corr) >= 1:
            result[oid] = {
                "level": "multi-source",
                "corroborating_ids": corr,
                "score": min(10, 3 + len(corr) * 2),
            }
        else:
            result[oid] = {
                "level": "single-source",
                "corroborating_ids": [],
                "score": max(1, 10 - len(entities_map.get(oid, set()))),
            }

    return result


def parse_time(ts: str):
    """Parse ISO timestamp, return datetime or None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def main():
    if not os.path.exists(INPUT_FILE):
        print(f"[Verify] {INPUT_FILE} 不存在，跳过")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        print("[Verify] 无新闻")
        return

    verification = compute_verification(items)

    multi = 0
    for item in items:
        vid = item["id"]
        v = verification.get(vid, {"level": "single-source", "corroborating_ids": [], "score": 1})
        item["verification"] = v
        if v["level"] == "multi-source":
            multi += 1

    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[Verify] 完成: {multi}/{len(items)} 多源验证 → {INPUT_FILE}")


if __name__ == "__main__":
    main()
