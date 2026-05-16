"""Rocketship Detector — GitHub Trending 异军突起项目检测。

Scrapes GitHub Trending daily + weekly, extracts star velocity data,
identifies repos with explosive star growth. No API key needed.
Output: data/rocketship.json
"""

import json
import os
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "rocketship.json")
REQUEST_TIMEOUT = 15

HEADERS = {"User-Agent": "AI-News-Collector/1.0"}

AI_KW = [
    "ai", "llm", "gpt", "machine-learning", "deep-learning", "nlp", "transformer",
    "ml", "neural", "agent", "rag", "fine-tune", "embedding", "diffusion",
    "chatgpt", "claude", "gemini", "langchain", "pytorch", "tensorflow",
    "llama", "mistral", "stable-diffusion", "sora", "whisper", "openai",
    "anthropic", "deepseek", "qwen", "vlm", "lora", "rlhf", "prompt-engineering",
]

MIN_DAILY_STARS = 50
MIN_WEEKLY_STARS = 200
VELOCITY_THRESHOLD = 0.05  # daily/total > 5%


def parse_num(text):
    """'1,281' → 1281"""
    return int(text.replace(",", ""))


def scrape_trending(since="daily"):
    """Scrape GitHub Trending page. Returns list of repo dicts."""
    repos = []
    try:
        url = f"https://github.com/trending?since={since}&spoken_language_code="
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"[Rocketship] Trending {since}: HTTP {resp.status_code}")
            return repos

        soup = BeautifulSoup(resp.text, "html.parser")
        for article in soup.select("article.Box-row"):
            h2 = article.select_one("h2")
            if not h2:
                continue
            a_tag = h2.select_one("a")
            if not a_tag:
                continue

            href = a_tag.get("href", "").strip()
            full_name = href.strip("/")
            name = full_name.split("/")[-1] if "/" in full_name else full_name
            url = "https://github.com" + href

            desc_el = article.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            # Parse star data
            stars_today = 0
            total_stars = 0
            forks = 0

            # "X stars today" / "X stars this week"
            period_span = article.select_one("span.d-inline-block.float-sm-right")
            if period_span:
                period_text = period_span.get_text(strip=True)
                m = re.search(r"([\d,]+)\s+stars?", period_text)
                if m:
                    stars_today = parse_num(m.group(1))

            # Total stars & forks are in Link--muted spans
            muted_links = article.select("a.Link--muted")
            for link in muted_links:
                txt = link.get_text(strip=True)
                if re.match(r"^[\d,]+$", txt):
                    num = parse_num(txt)
                    svg = link.select_one("svg")
                    if svg:
                        aria = svg.get("aria-label", "")
                        if "fork" in aria.lower():
                            forks = num
                        elif "star" in aria.lower():
                            total_stars = num
                    # Heuristic: first big number = stars, second = forks
                    if total_stars == 0:
                        total_stars = num
                    elif forks == 0 and num != total_stars:
                        forks = num

            # Language
            lang_el = article.select_one('[itemprop="programmingLanguage"]')
            language = lang_el.get_text(strip=True) if lang_el else ""

            repos.append({
                "name": name,
                "full_name": full_name,
                "url": url,
                "description": description,
                "total_stars": total_stars,
                "stars_period": stars_today,
                "period": since,
                "forks": forks,
                "language": language,
            })
    except Exception as e:
        print(f"[Rocketship] Trending {since} 异常: {e}")
    return repos


def is_ai_related(repo):
    """Check if repo is AI/ML related by name + description."""
    combined = (repo.get("full_name", "") + " " + repo.get("description", "")).lower()
    return any(kw in combined for kw in AI_KW)


def detect_spikes(daily_repos, weekly_repos):
    """Merge daily+weekly data, score velocity, return top spikes."""
    # Index weekly repos by full_name
    weekly_map = {}
    for r in weekly_repos:
        weekly_map[r["full_name"]] = r

    scored = []
    seen = set()

    for r in daily_repos + weekly_repos:
        fn = r["full_name"]
        if fn in seen:
            continue
        seen.add(fn)

        if not is_ai_related(r):
            continue

        in_daily = r.get("period") == "daily"
        in_weekly = r.get("period") == "weekly"

        daily_match = next((d for d in daily_repos if d["full_name"] == fn), None)
        weekly_match = weekly_map.get(fn, {})

        daily_stars = daily_match.get("stars_period", 0) if daily_match else (r.get("stars_period", 0) if in_daily else 0)
        weekly_stars = weekly_match.get("stars_period", 0) if weekly_match else (r.get("stars_period", 0) if in_weekly else 0)

        total_stars = max(
            r.get("total_stars", 0),
            daily_match.get("total_stars", 0) if daily_match else 0,
            weekly_match.get("total_stars", 0),
        )
        if total_stars < 10:
            continue

        # Velocity score: daily stars as fraction of total
        effective_daily = daily_stars if daily_stars > 0 else weekly_stars / 7
        velocity = effective_daily / max(total_stars, 100)

        # Compute a composite burst score
        burst_score = 0
        if daily_stars >= 80:
            burst_score += min(daily_stars / 80, 8)
        if weekly_stars >= 300:
            burst_score += min(weekly_stars / 300, 6)
        if velocity >= 0.03:
            burst_score += min(velocity / 0.03, 4)
        # Bonus: small repos (< 5000 total) with high velocity
        if total_stars < 5000 and velocity > 0.05:
            burst_score += 3
        # Bonus: in both daily AND weekly trending (sustained growth)
        if daily_stars > 0 and weekly_stars > 0:
            burst_score += 2

        # Apply thresholds
        if burst_score < 1.5:
            continue

        scored.append({
            "name": r["name"],
            "full_name": r["full_name"],
            "url": r["url"],
            "description": r.get("description", ""),
            "total_stars": total_stars,
            "stars_today": daily_stars,
            "stars_this_week": weekly_stars,
            "forks": r.get("forks", 0),
            "language": r.get("language", ""),
            "velocity": round(velocity, 4),
            "burst_score": round(burst_score, 1),
            "in_daily": bool(daily_stars),
            "in_weekly": bool(weekly_stars),
        })

    scored.sort(key=lambda x: -x["burst_score"])
    return scored[:8]


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print("[Rocketship] 抓取 GitHub Trending daily...")
    daily = scrape_trending("daily")
    print(f"  daily: {len(daily)} repos")

    print("[Rocketship] 抓取 GitHub Trending weekly...")
    weekly = scrape_trending("weekly")
    print(f"  weekly: {len(weekly)} repos")

    spikes = detect_spikes(daily, weekly)
    print(f"[Rocketship] 检测到 {len(spikes)} 个异军突起项目")

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(spikes),
        "items": spikes,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    for s in spikes[:5]:
        print(f"  [{s['burst_score']:.1f}] {s['full_name']} "
              f"★{s['total_stars']:,} "
              f"+{s['stars_today']:,}/day "
              f"v={s['velocity']:.3f}")

    print(f"→ {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
