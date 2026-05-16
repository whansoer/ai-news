"""Quality checker — unified Gemini output validation.

Usage:
    from quality import check_cjk, check_json_structure, check_output_length, score_output

    ok, errors = check_json_structure(result, ["title_zh", "summary_zh"])
    if not ok:
        print(f"Struct invalid: {errors}")
"""

import re

# CJK Unicode range: U+4E00–U+9FFF (CJK Unified Ideographs)
# Plus extensions: U+3400–U+4DBF, U+20000–U+2A6DF
_CJK_RANGES = [
    ('一', '鿿'),
    ('㐀', '䶿'),
]


def check_cjk(text: str) -> bool:
    """Return True if text contains at least one CJK character."""
    if not text:
        return False
    return any(lo <= c <= hi for lo, hi in _CJK_RANGES for c in text)


def cjk_ratio(text: str) -> float:
    """Ratio of CJK characters in text (0.0 – 1.0)."""
    if not text:
        return 0.0
    cjk_count = sum(1 for lo, hi in _CJK_RANGES for c in text if lo <= c <= hi)
    # Exclude whitespace and punctuation from denominator
    meaningful = sum(1 for c in text if not c.isspace() and c not in '，。！？、；：""''（）…—')
    if meaningful == 0:
        return 0.0
    return cjk_count / max(meaningful, 1)


def check_json_structure(result: dict, required_fields: list) -> tuple:
    """Return (ok, errors_list). Validates required fields exist and are non-empty."""
    errors = []
    if not isinstance(result, dict):
        return False, ["result is not a dict"]
    for field in required_fields:
        if field not in result:
            errors.append(f"missing field: {field}")
        elif result[field] is None:
            errors.append(f"field is None: {field}")
        elif isinstance(result[field], str) and not result[field].strip():
            errors.append(f"field is empty string: {field}")
        elif isinstance(result[field], list) and len(result[field]) == 0:
            errors.append(f"field is empty list: {field}")
    return len(errors) == 0, errors


def check_output_length(text: str, min_chars: int, max_chars: int = 99999) -> tuple:
    """Return (ok, actual_length). Check if text is within length bounds."""
    length = len(text) if text else 0
    return min_chars <= length <= max_chars, length


def check_entity_consistency(original_title: str, translated_title: str) -> float:
    """Score 0.0–1.0: how many English tokens from original appear in translation.
    High score = key entities preserved. Low score = entities lost or hallucinated."""
    if not original_title or not translated_title:
        return 0.0
    # Extract English-looking tokens (2+ uppercase/lowercase letters)
    eng_tokens = set(re.findall(r'[A-Z][a-zA-Z0-9]{1,}', original_title))
    if not eng_tokens:
        return 1.0  # No English entities to preserve
    preserved = sum(1 for t in eng_tokens if t.lower() in translated_title.lower())
    return preserved / len(eng_tokens)


def check_briefing_top_items(briefing: dict, news_titles: list) -> tuple:
    """Verify briefing top_items match actual news titles.
    Returns (ok, matched_count, unmatched_items)."""
    top_items = briefing.get("top_items", [])
    if not top_items:
        return False, 0, top_items
    titles_lower = [t.lower().strip() for t in news_titles if t]
    matched = 0
    unmatched = []
    for item in top_items:
        item_lower = item.lower().strip()
        if any(item_lower in t or t in item_lower for t in titles_lower):
            matched += 1
        else:
            unmatched.append(item)
    return matched >= len(top_items) * 0.5, matched, unmatched


def score_output(text: str, expected_lang: str = "zh") -> dict:
    """Score a Gemini output on multiple quality dimensions. Returns dict summary."""
    scores = {}
    if expected_lang == "zh":
        ratio = cjk_ratio(text)
        scores["cjk_ratio"] = round(ratio, 3)
        scores["likely_chinese"] = ratio > 0.3
    scores["length"] = len(text) if text else 0
    scores["too_short"] = len(text) < 15 if text else True
    return scores
