"""Daily Briefing — AI 主编每日行业分析文章（叙事 + 趋势 + 降级兜底）"""
import json
import os
from datetime import datetime, timezone

import requests

from cache import Cache
from quality import check_cjk, score_output

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
NEWS_FILE = os.path.join(DATA_DIR, "news.json")
ZH_FILE = os.path.join(DATA_DIR, "news_zh.json")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
ROCKETSHIP_FILE = os.path.join(DATA_DIR, "rocketship.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "briefing.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
TOP_N = 15

SYSTEM_PROMPT = """你是 AI 行业分析主编。根据今日 AI 新闻的结构化数据，撰写一篇有洞察的行业分析日报。

输出严格 JSON（不要额外说明文字）：
{
  "headline": "20字以内，今日AI行业最值得关注的核心事件或趋势，像报纸标题一样有吸引力",
  "narrative": "600-1000字，这是一篇连贯的行业分析文章——不是新闻列表。把今日Top新闻串成一个有逻辑的叙事：今天AI行业发生了什么主线？哪些事件相互关联？背后的驱动力是什么（技术突破？商业竞争？政策变化？）？接下来行业会怎么走？要有观点和判断，像报纸头版编辑写的分析文章。引用具体文章作为证据时注明'据[来源]报道'。",
  "trends": [
    {
      "trend": "15字以内趋势名称",
      "description": "100字以内趋势分析",
      "evidence": ["支撑文章的id"]
    }
  ],
  "hot_projects": [
    {
      "full_name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "why_hot": "50字以内，解释为什么值得关注",
      "stars_today": 数字,
      "total_stars": 数字
    }
  ],
  "key_numbers": [
    {"label": "数字标签", "value": "数字/百分比"}
  ],
  "must_read_ids": ["5个最推荐阅读的文章id"],
  "text": "150字简版（兼容旧格式）",
  "top_items": ["3-5个中文标题（兼容旧格式）"]
}

规则：
1. 所有文字使用中文，技术术语保留英文原名并括号补充中文
2. headline 是核心：像真正的新闻标题，有信息量有吸引力
3. narrative 是最重要的产出：一篇完整的分析文章，不是新闻罗列。要有视角、有逻辑、有判断
4. trends 基于交叉证据提炼 2-3 条值得关注的趋势，每条引用支撑文章
5. key_numbers 提取 3-5 个今天最具冲击力的数字
6. must_read_ids 推荐 5 篇最值得阅读的文章
7. 保持客观但要有判断，不要过度夸张"""

CAT_LABELS_CN = {
    "model": "模型发布", "oss": "开源项目", "product": "产品/API",
    "research": "学术研究", "funding": "融资收购", "policy": "政策监管",
}


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_rich_prompt(items, zh_map, stats, rocketship):
    """Assemble structured Markdown input from all pipeline data."""
    parts = []

    # ── 数据概览 ──
    total = stats.get("total", len(items))
    cats = stats.get("categories", [])
    tags_top = stats.get("tags", [])[:5]
    sources_top = stats.get("sources", [])[:5]

    # Multi-source verification rate
    multi_count = sum(
        1 for it in items
        if it.get("verification", {}).get("level") == "multi-source"
    )
    multi_pct = round(multi_count / max(len(items), 1) * 100)

    parts.append("## 今日数据概览")
    parts.append(f"- 总计: {total} 篇文章")
    if cats:
        cat_strs = [f'{c["name"]}{c["count"]}篇' for c in cats[:5]]
    parts.append(f'- 分类分布: {", ".join(cat_strs)}')
    if tags_top:
        tag_strs = [f'{t["name"]}({t["count"]})' for t in tags_top]
    parts.append(f'- 热门标签: {", ".join(tag_strs)}')
    if sources_top:
        src_strs = [f'{s["name"]}({s["count"]})' for s in sources_top]
    parts.append(f'- 来源 Top 5: {", ".join(src_strs)}')
    parts.append(f"- 多源验证率: {multi_pct}% ({multi_count}/{len(items)}篇有2+来源交叉验证)")

    # ── Top 文章 ──
    parts.append("\n## 今日 Top 文章")
    for i, item in enumerate(items[:TOP_N]):
        zh = zh_map.get(item["id"], {})
        title_zh = zh.get("title_zh") or item.get("title", "")
        oneliner = zh.get("oneliner", "")
        key_facts = zh.get("key_facts", [])
        quote = zh.get("notable_quote", {})
        category_cn = CAT_LABELS_CN.get(item.get("category", ""), item.get("category", ""))
        score = item.get("score", 5)
        difficulty = item.get("difficulty", "intermediate")
        verification = item.get("verification", {})
        vlevel = verification.get("level", "single-source")
        vbadge = "多源" if vlevel == "multi-source" else "单源"

        parts.append(
            f"{i+1}. [{score}分][{category_cn}][{vbadge}] {title_zh}"
        )
        if oneliner:
            parts.append(f"   TL;DR: {oneliner}")
        if key_facts:
            parts.append(f"   关键数据: {'; '.join(key_facts[:3])}")
        if quote.get("zh"):
            parts.append(f"   金句: \"{quote['zh']}\"")
        parts.append(f"   难度: {difficulty}")

    # ── GitHub 异军突起 ──
    rs_items = rocketship.get("items", [])
    if rs_items:
        parts.append("\n## GitHub 异军突起项目")
        for r in rs_items[:5]:
            parts.append(
                f"- {r['full_name']}: ★{r.get('total_stars', 0):,} +{r.get('stars_today', 0)}/天 "
                f"({r.get('language', '')}) 爆发分:{r.get('burst_score', 0):.1f}"
            )
            if r.get("description"):
                parts.append(f"  描述: {r['description'][:120]}")

    # ── 关键实体关系 ──
    relations = []
    for item in items[:20]:
        for rel in item.get("relations", [])[:2]:
            relations.append(
                f"- {rel.get('from', '?')} —{rel.get('type', 'related')}→ {rel.get('to', '?')} "
                f"(from: {item.get('title', '')[:50]})"
            )
    if relations:
        parts.append("\n## 关键实体关系")
        parts.extend(relations[:15])

    return "\n".join(parts)


def build_fallback_briefing(items, zh_map, stats, rocketship):
    """Generate a data-driven briefing without calling Gemini."""
    cats = stats.get("categories", [])
    tags_top = stats.get("tags", [])
    total = stats.get("total", len(items))

    top_cat = cats[0]["name"] if cats else "AI新闻"
    top_tag = tags_top[0]["name"] if tags_top else ""

    multi_count = sum(
        1 for it in items
        if it.get("verification", {}).get("level") == "multi-source"
    )
    multi_pct = round(multi_count / max(len(items), 1) * 100)

    top5 = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:5]

    cat_text = ", ".join(f'{c["name"]}{c["count"]}篇' for c in cats[:4])
    overview = (
        f'今日共收录{total}篇AI新闻，分类分布：{cat_text}。'
        f'热门标签：{top_tag}（{tags_top[0]["count"]}篇）。'
        f'其中{multi_pct}%的文章有多来源交叉验证。'
    )

    # Build narrative from Top 5 oneliners
    narrative_parts = [overview]
    for it in top5:
        zh = zh_map.get(it["id"], {})
        title = zh.get("title_zh") or it.get("title", "")
        oneliner = zh.get("oneliner", "")
        if oneliner:
            narrative_parts.append(f"▸ {title}：{oneliner}")
        else:
            narrative_parts.append(f"▸ {title}")
    narrative = "\n\n".join(narrative_parts)

    # Hot projects from rocketship
    hot_projects = []
    for r in (rocketship.get("items", []) or [])[:3]:
        hot_projects.append({
            "full_name": r["full_name"],
            "url": r.get("url", f'https://github.com/{r["full_name"]}'),
            "why_hot": f'单日{r.get("stars_today", 0)}星，{r.get("language", "")}项目',
            "stars_today": r.get("stars_today", 0),
            "total_stars": r.get("total_stars", 0),
        })

    key_numbers = [
        {"label": "文章总数", "value": str(total)},
        {"label": "多源验证率", "value": f'{multi_pct}%'},
    ]
    if rocketship.get("items"):
        total_today = sum(r.get("stars_today", 0) for r in rocketship["items"] if r.get("stars_today"))
        if total_today > 0:
            key_numbers.append({"label": "GitHub星增", "value": f'+{total_today}'})

    must_read_ids = [it["id"] for it in top5]

    return {
        "headline": f'今日AI速览：{top_cat}最活跃',
        "narrative": narrative,
        "trends": [],
        "hot_projects": hot_projects,
        "key_numbers": key_numbers,
        "must_read_ids": must_read_ids,
        "text": overview[:150],
        "top_items": [
            (zh_map.get(it["id"], {}).get("title_zh") or it.get("title", ""))[:40]
            for it in top5
        ],
    }


def call_gemini(prompt, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{API_URL}?key={GEMINI_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4096},
                },
                timeout=90,
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
                import time
                time.sleep(2 * (attempt + 1))
            else:
                print(f"[Briefing] API 失败: {e}")
    return None


def parse_json_safe(content):
    """Extract top-level JSON object, counting braces to handle nested objects."""
    depth = 0
    start = -1
    for i, ch in enumerate(content):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(content[start: i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def validate_briefing(briefing):
    """Return True if the briefing passes quality checks."""
    if not isinstance(briefing, dict):
        return False
    headline = briefing.get("headline", "")
    narrative = briefing.get("narrative", "")
    if not check_cjk(headline) or len(headline) < 5:
        print(f"[Briefing] headline 质量不达标: len={len(headline)}, cjk={check_cjk(headline)}")
        return False
    if not check_cjk(narrative) or len(narrative) < 80:
        print(f"[Briefing] narrative 质量不达标: len={len(narrative)}, cjk={check_cjk(narrative)}")
        return False
    return True


def main():
    # ── Load all data files ──
    news_data = load_json(NEWS_FILE)
    items = news_data.get("items", [])
    if not items:
        print("[Briefing] 无新闻")
        return

    zh_map = {}
    zh_data = load_json(ZH_FILE)
    for it in zh_data.get("items", []):
        zh_map[it["id"]] = it

    stats = load_json(STATS_FILE)
    rocketship = load_json(ROCKETSHIP_FILE)

    # Score-sort items for top-N selection
    scored_items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    top_items = scored_items[:TOP_N]

    os.makedirs(DATA_DIR, exist_ok=True)
    briefing = {}

    # ── Cache check ──
    cache = Cache("briefing")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache_key = cache.make_key(
        today,
        *(f'{it["id"]}:{it.get("score", 0)}:{zh_map.get(it["id"], {}).get("oneliner", "")[:40]}'
          for it in top_items),
        f'stats:{stats.get("total", 0)}:{stats.get("categories", [{}])[0].get("count", 0) if stats.get("categories") else 0}',
        f'rocketship:{"|".join(r["full_name"] for r in rocketship.get("items", [])[:3])}',
    )

    cached = cache.get(cache_key)
    if cached and cached.get("text") and check_cjk(cached.get("narrative", "")):
        briefing = cached
        briefing["_from_cache"] = True
        print(f"[Briefing] 缓存命中，跳过 API")
    elif GEMINI_KEY:
        # ── Call Gemini with rich context ──
        prompt = build_rich_prompt(scored_items, zh_map, stats, rocketship)
        result = call_gemini(prompt)
        if result and validate_briefing(result):
            briefing = result
        else:
            print("[Briefing] API 返回无效或质量不达标，使用降级方案")
            briefing = build_fallback_briefing(
                scored_items, zh_map, stats, rocketship
            )
            briefing["_fallback"] = True
    else:
        print("[Briefing] 未设置 GEMINI_KEY，使用本地数据生成日报")
        briefing = build_fallback_briefing(
            scored_items, zh_map, stats, rocketship
        )
        briefing["_fallback"] = True

    # ── Ensure backward-compatible fields ──
    if not briefing.get("text"):
        briefing["text"] = briefing.get("narrative", "")[:150]
    if not briefing.get("top_items"):
        briefing["top_items"] = [
            (zh_map.get(it["id"], {}).get("title_zh") or it.get("title", ""))[:40]
            for it in top_items[:5]
        ]
    if not briefing.get("meta"):
        multi_count = sum(
            1 for it in scored_items
            if it.get("verification", {}).get("level") == "multi-source"
        )
        briefing["meta"] = {
            "total_articles": stats.get("total", len(items)),
            "multi_source_pct": round(multi_count / max(len(scored_items), 1) * 100),
        }

    # ── Cache and save ──
    if not briefing.get("_from_cache"):
        briefing_clean = {k: v for k, v in briefing.items() if not k.startswith("_")}
        cache.set(cache_key, briefing_clean)
        cache.save()
        print(f"[Briefing] 缓存已保存: {cache.hits()} 条")

    briefing["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)

    print(f"简报完成: headline={briefing.get('headline', '')[:30]}, "
          f"narrative_len={len(briefing.get('narrative', ''))} → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
