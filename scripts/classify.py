"""AI News Classifier — Gemini 分类 + 标签 + 热度评分，一次调用"""
import json
import os
import time
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INPUT_FILE = os.path.join(DATA_DIR, "news.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "news.json")

GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
MAX_ITEMS = 50
BATCH_SIZE = 15
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

SYSTEM_PROMPT = """你是 AI 新闻分析专家。分析每条新闻，输出严格 JSON 数组。

对每条新闻输出：
{
  "id": "原始id",
  "category": "model|oss|product|research|funding|policy",
  "tags": ["2-3个技术标签", "..."],
  "score": 1-10,
  "reason": "评分理由（10字以内）",
  "relations": [{"from": "实体A", "type": "releases|invests|depends_on", "to": "实体B"}, ...]
}

分类标准：
- model: 大模型发布、升级、评测
- oss: 开源项目、框架、工具
- product: 产品上线、API更新、商业应用
- research: 学术论文、技术报告、Benchmark
- funding: 融资、收购、IPO
- policy: 监管、法规、伦理、安全

评分标准（1-10）：
- 行业影响力 0-4分（OpenAI/Google/Meta等巨头动作 4分，个人项目 1分）
- 技术突破性 0-3分（全新范式 3分，微调改进 1分）
- 实用价值 0-3分（开发者立即可用 3分，纯理论 1分）

实体关系提取（relations）：
- 从标题和摘要中提取 0-3 条实体关系
- 实体类型：company（公司）、model（模型）、tech（技术）、person（人物）、event（事件/会议）
- 关系类型：releases（发布，如 OpenAI→GPT-5）、invests（投资/收购，如 Microsoft→OpenAI）、depends_on（基于/依赖，如 GPT-5→Transformer）
- 实体命名用英文原名，不要翻译
- 如果文中没有明确的实体关系，返回空数组 []"""


def load_news():
    if not os.path.exists(INPUT_FILE):
        return []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def build_prompt(batch):
    lines = []
    for item in batch:
        lines.append(
            f'id: {item["id"]}\n'
            f'title: {item["title"]}\n'
            f'summary: {item.get("summary", "")[:150]}\n'
            f'source: {item.get("source", "")}\n'
        )
    return "\n---\n".join(lines)


def call_gemini(prompt, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{API_URL}?key={GEMINI_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
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
                print(f"[Classify] API 失败: {e}")
    return []


def main():
    if not GEMINI_KEY:
        print("[Classify] 未设置 GEMINI_KEY，跳过")
        return

    data = load_news()
    if not data or not data.get("items"):
        print("[Classify] 无新闻")
        return

    items = data["items"][:MAX_ITEMS]
    classified = {}

    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i: i + BATCH_SIZE]
        results = call_gemini(build_prompt(batch))
        for r in results:
            cid = r.get("id", "")
            classified[cid] = {
                "category": r.get("category", "product"),
                "tags": r.get("tags", [])[:3],
                "score": max(1, min(10, r.get("score", 5))),
                "reason": r.get("reason", ""),
                "relations": r.get("relations", []),
            }
        if i + BATCH_SIZE < len(items):
            time.sleep(2)

    # 合并到 news.json
    for item in items:
        cid = item["id"]
        if cid in classified:
            c = classified[cid]
            item["category"] = c["category"]
            item["tags"] = c["tags"]
            item["score"] = c["score"]
            item["relations"] = c.get("relations", [])
        else:
            item.setdefault("category", "product")
            item.setdefault("tags", [])
            item.setdefault("score", 5)
            item.setdefault("relations", [])

    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    scored = sum(1 for i in items if i.get("score", 0) > 0)
    print(f"分类完成: {scored}/{len(items)} 条 → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
