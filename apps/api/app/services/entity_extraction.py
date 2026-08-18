"""
Entity extraction service for the news aggregation system.

Extracts named entities (sports, leagues, persons, locations, scores) from
article titles and summaries to enhance clustering beyond simple title
similarity.  Pure-Python implementation — no external NLP libraries required.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class EntityType(StrEnum):
    SPORT = "sport"
    LEAGUE = "league"
    PERSON = "person"
    LOCATION = "location"
    SCORE = "score"
    OTHER = "other"


@dataclass
class ExtractedEntity:
    """A single entity extracted from text."""

    text: str
    entity_type: EntityType
    confidence: float = 1.0

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


# ---------------------------------------------------------------------------
# Terminology dictionaries
# ---------------------------------------------------------------------------

SPORT_TERMS: dict[str, str] = {
    # Chinese → canonical key
    "足球": "football",
    "篮球": "basketball",
    "网球": "tennis",
    "排球": "volleyball",
    "乒乓球": "table tennis",
    "羽毛球": "badminton",
    "棒球": "baseball",
    "橄榄球": "rugby",
    "冰球": "ice hockey",
    "曲棍球": "hockey",
    "高尔夫": "golf",
    "田径": "athletics",
    "游泳": "swimming",
    "拳击": "boxing",
    "格斗": "fighting",
    "综合格斗": "mma",
    "摔跤": "wrestling",
    "赛车": "motorsport",
    "自行车": "cycling",
    "板球": "cricket",
    "手球": "handball",
    "水球": "water polo",
    "斯诺克": "snooker",
    "台球": "billiards",
    "电竞": "esports",
    "电子竞技": "esports",
    "滑雪": "skiing",
    "花样滑冰": "figure skating",
    "马拉松": "marathon",
    # English → canonical key (lowercase lookup)
    "football": "football",
    "soccer": "football",
    "basketball": "basketball",
    "tennis": "tennis",
    "volleyball": "volleyball",
    "table tennis": "table tennis",
    "badminton": "badminton",
    "baseball": "baseball",
    "rugby": "rugby",
    "ice hockey": "ice hockey",
    "hockey": "hockey",
    "golf": "golf",
    "athletics": "athletics",
    "swimming": "swimming",
    "boxing": "boxing",
    "mma": "mma",
    "wrestling": "wrestling",
    "motorsport": "motorsport",
    "cycling": "cycling",
    "cricket": "cricket",
    "handball": "handball",
    "snooker": "snooker",
    "esports": "esports",
    "skiing": "skiing",
    "figure skating": "figure skating",
    "marathon": "marathon",
    "f1": "motorsport",
    "formula 1": "motorsport",
}

LEAGUE_TERMS: dict[str, str] = {
    # Chinese aliases → canonical key
    "英超": "premier league",
    "西甲": "la liga",
    "德甲": "bundesliga",
    "意甲": "serie a",
    "法甲": "ligue 1",
    "欧冠": "champions league",
    "欧联": "europa league",
    "欧联杯": "europa league",
    "中超": "chinese super league",
    "中甲": "china league one",
    "日职联": "j-league",
    "韩k联": "k-league",
    "世界杯": "world cup",
    "欧洲杯": "euro",
    "亚洲杯": "asian cup",
    "美洲杯": "copa america",
    "非洲杯": "afcon",
    "奥运": "olympics",
    "奥运会": "olympics",
    # English aliases
    "premier league": "premier league",
    "epl": "premier league",
    "la liga": "la liga",
    "bundesliga": "bundesliga",
    "serie a": "serie a",
    "ligue 1": "ligue 1",
    "champions league": "champions league",
    "uefa champions league": "champions league",
    "europa league": "europa league",
    "conference league": "conference league",
    "chinese super league": "chinese super league",
    "csl": "chinese super league",
    "j-league": "j-league",
    "j1 league": "j-league",
    "k-league": "k-league",
    "k league 1": "k-league",
    "nba": "nba",
    "nfl": "nfl",
    "mlb": "mlb",
    "nhl": "nhl",
    "wnba": "wnba",
    "g-league": "g-league",
    "euroleague": "euroleague",
    "world cup": "world cup",
    "fifa world cup": "world cup",
    "euro": "euro",
    "uefa euro": "euro",
    "asian cup": "asian cup",
    "copa america": "copa america",
    "afcon": "afcon",
    "olympics": "olympics",
    "commonwealth games": "commonwealth games",
    "atp": "atp",
    "wta": "wta",
    "grand slam": "grand slam",
    "wimbledon": "wimbledon",
    "us open": "us open",
    "french open": "french open",
    "australian open": "australian open",
    "ufc": "ufc",
    "bellator": "bellator",
    "one championship": "one championship",
    "超级碗": "super bowl",
    "super bowl": "super bowl",
}

# Locations — a compact but useful list of countries and major cities
# frequently appearing in sports news.
LOCATION_TERMS: set[str] = {
    # Countries (Chinese + English)
    "中国",
    "美国",
    "英国",
    "法国",
    "德国",
    "西班牙",
    "意大利",
    "葡萄牙",
    "荷兰",
    "比利时",
    "巴西",
    "阿根廷",
    "墨西哥",
    "日本",
    "韩国",
    "澳大利亚",
    "加拿大",
    "俄罗斯",
    "乌克兰",
    "波兰",
    "瑞典",
    "丹麦",
    "挪威",
    "瑞士",
    "奥地利",
    "克罗地亚",
    "塞尔维亚",
    "土耳其",
    "埃及",
    "摩洛哥",
    "尼日利亚",
    "喀麦隆",
    "塞内加尔",
    "哥伦比亚",
    "智利",
    "乌拉圭",
    "巴拉圭",
    "china",
    "usa",
    "united states",
    "uk",
    "united kingdom",
    "england",
    "france",
    "germany",
    "spain",
    "italy",
    "portugal",
    "netherlands",
    "belgium",
    "brazil",
    "argentina",
    "mexico",
    "japan",
    "south korea",
    "australia",
    "canada",
    "russia",
    "ukraine",
    "poland",
    "sweden",
    "denmark",
    "norway",
    "switzerland",
    "austria",
    "croatia",
    "serbia",
    "turkey",
    "egypt",
    "morocco",
    "nigeria",
    "cameroon",
    "senegal",
    "colombia",
    "chile",
    "uruguay",
    # Major cities (Chinese + English)
    "北京",
    "上海",
    "广州",
    "深圳",
    "成都",
    "伦敦",
    "巴黎",
    "马德里",
    "巴塞罗那",
    "慕尼黑",
    "米兰",
    "罗马",
    "东京",
    "大阪",
    "首尔",
    "纽约",
    "洛杉矶",
    "芝加哥",
    "迈阿密",
    "多伦多",
    "悉尼",
    "墨尔本",
    "莫斯科",
    "beijing",
    "shanghai",
    "guangzhou",
    "shenzhen",
    "chengdu",
    "london",
    "paris",
    "madrid",
    "barcelona",
    "munich",
    "milan",
    "rome",
    "tokyo",
    "osaka",
    "seoul",
    "new york",
    "los angeles",
    "chicago",
    "miami",
    "toronto",
    "sydney",
    "melbourne",
    "moscow",
    "manchester",
    "liverpool",
    "dortmund",
    "berlin",
    "amsterdam",
    "lisbon",
}


# ---------------------------------------------------------------------------
# Compiled regex helpers
# ---------------------------------------------------------------------------

# Score pattern: "3-2", "108-102", "3:2" (common in some sports contexts)
_SCORE_RE = re.compile(r"\b(\d{1,3})\s*[-:]\s*(\d{1,3})\b")

# Capitalised English words / sequences (for person name detection)
_CAPITALISED_WORD_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")

# Chinese name heuristic: 2-4 character sequences of CJK Unified
# Ideographs that are NOT in the sports/league/location dictionaries.
_CHINESE_NAME_RE = re.compile(r"([\u4e00-\u9fff]{2,4})")

# Match multi-word English terms (up to 4 words) for dictionary lookup
_MULTI_WORD_RE = re.compile(r"\b([A-Za-z][A-Za-z ]{1,30}?)\b")


# ---------------------------------------------------------------------------
# Core extraction functions
# ---------------------------------------------------------------------------


def extract_entities(text: str) -> list[ExtractedEntity]:
    """Extract entities from a single text string.

    Returns a deduplicated list of :class:`ExtractedEntity` instances sorted
    by confidence (descending).
    """
    if not text or not text.strip():
        return []

    entities: list[ExtractedEntity] = []
    seen: set[tuple[str, EntityType]] = set()

    def _add(raw_text: str, etype: EntityType, confidence: float = 1.0) -> None:
        key = (raw_text.lower().strip(), etype)
        if key not in seen:
            seen.add(key)
            entities.append(
                ExtractedEntity(text=raw_text.strip(), entity_type=etype, confidence=confidence)
            )

    text_lower = text.lower()

    # 1. Sports -----------------------------------------------------------
    for term in SPORT_TERMS:
        if term in text_lower:
            # Prefer the original-case substring from the input text
            idx = text_lower.find(term)
            original = text[idx : idx + len(term)]
            _add(original, EntityType.SPORT, confidence=0.95)

    # 2. Leagues ----------------------------------------------------------
    for term in LEAGUE_TERMS:
        if term in text_lower:
            idx = text_lower.find(term)
            original = text[idx : idx + len(term)]
            _add(original, EntityType.LEAGUE, confidence=0.95)

    # 3. Locations --------------------------------------------------------
    for loc in LOCATION_TERMS:
        if loc in text_lower:
            idx = text_lower.find(loc)
            original = text[idx : idx + len(loc)]
            _add(original, EntityType.LOCATION, confidence=0.90)

    # 4. Scores -----------------------------------------------------------
    for m in _SCORE_RE.finditer(text):
        score_text = m.group(0)
        # Heuristic: at least one side > 5 → likely a real sport score
        a, b = int(m.group(1)), int(m.group(2))
        if a > 5 or b > 5 or (a + b >= 3 and a != b):
            _add(score_text, EntityType.SCORE, confidence=0.85)
        else:
            _add(score_text, EntityType.SCORE, confidence=0.60)

    # 5. English proper nouns (person names) ------------------------------
    # Collect already-matched spans so we don't re-classify them.
    matched_spans: list[tuple[int, int]] = []
    for term in list(SPORT_TERMS) + list(LEAGUE_TERMS) + list(LOCATION_TERMS):
        start = 0
        while True:
            idx = text_lower.find(term, start)
            if idx == -1:
                break
            matched_spans.append((idx, idx + len(term)))
            start = idx + 1

    def _overlaps(span: tuple[int, int]) -> bool:
        for s, e in matched_spans:
            if span[0] < e and span[1] > s:
                return True
        return False

    for m in _CAPITALISED_WORD_RE.finditer(text):
        if _overlaps(m.span()):
            continue
        word = m.group(1)
        # Skip very common English words that aren't names
        if word.lower() in _STOP_WORDS:
            continue
        _add(word, EntityType.PERSON, confidence=0.55)

    # 6. Chinese name heuristic -------------------------------------------
    # We look for 2-4 character CJK sequences that are NOT already captured
    # as sport/league/location terms.
    for m in _CHINESE_NAME_RE.finditer(text):
        segment = m.group(1)
        seg_lower = segment.lower()
        if seg_lower in SPORT_TERMS or seg_lower in LEAGUE_TERMS or seg_lower in LOCATION_TERMS:
            continue
        if _overlaps(m.span()):
            continue
        # Very short common words that are unlikely to be names
        if segment in _CHINESE_STOP_WORDS:
            continue
        _add(segment, EntityType.PERSON, confidence=0.45)

    # Sort by confidence descending
    entities.sort(key=lambda e: e.confidence, reverse=True)
    return entities


def extract_article_entities(
    article_title: str,
    article_summary: str = "",
) -> list[ExtractedEntity]:
    """Extract and combine entities from an article's title and summary.

    Title entities receive a small confidence boost because titles tend to
    contain the most important entities.
    """
    title_entities = extract_entities(article_title)
    summary_entities = extract_entities(article_summary) if article_summary else []

    # Merge, giving title entities priority and a small confidence boost.
    merged: dict[tuple[str, EntityType], ExtractedEntity] = {}

    for ent in title_entities:
        key = (ent.text.lower(), ent.entity_type)
        boosted = min(1.0, ent.confidence + 0.05)
        merged[key] = ExtractedEntity(
            text=ent.text, entity_type=ent.entity_type, confidence=boosted
        )

    for ent in summary_entities:
        key = (ent.text.lower(), ent.entity_type)
        if key in merged:
            # Already found in title — keep the higher confidence
            existing = merged[key]
            existing.confidence = min(1.0, max(existing.confidence, ent.confidence + 0.02))
        else:
            merged[key] = ExtractedEntity(
                text=ent.text,
                entity_type=ent.entity_type,
                confidence=ent.confidence,
            )

    result = list(merged.values())
    result.sort(key=lambda e: e.confidence, reverse=True)
    return result


# ---------------------------------------------------------------------------
# Entity similarity
# ---------------------------------------------------------------------------


def compute_entity_similarity(
    entities_a: list[ExtractedEntity],
    entities_b: list[ExtractedEntity],
) -> float:
    """Compute a similarity score in [0.0, 1.0] between two entity lists.

    The score is a weighted combination of:
      - Exact entity text matches            (weight 0.5)
      - Same-type entity overlap             (weight 0.3)
      - Sport / league category match        (weight 0.2)
    """
    if not entities_a and not entities_b:
        return 1.0  # both empty → trivially identical
    if not entities_a or not entities_b:
        return 0.0

    # --- 1. Exact match component (weight 0.5) --------------------------
    set_a = {(e.text.lower(), e.entity_type) for e in entities_a}
    set_b = {(e.text.lower(), e.entity_type) for e in entities_b}

    union = set_a | set_b
    intersection = set_a & set_b

    exact_score = len(intersection) / len(union) if union else 0.0

    # --- 2. Same-type overlap component (weight 0.3) --------------------
    types_a: dict[EntityType, set[str]] = {}
    types_b: dict[EntityType, set[str]] = {}

    for e in entities_a:
        types_a.setdefault(e.entity_type, set()).add(e.text.lower())
    for e in entities_b:
        types_b.setdefault(e.entity_type, set()).add(e.text.lower())

    type_score = 0.0
    all_types = set(types_a) | set(types_b)
    if all_types:
        per_type_scores: list[float] = []
        for t in all_types:
            sa = types_a.get(t, set())
            sb = types_b.get(t, set())
            u = sa | sb
            i = sa & sb
            per_type_scores.append(len(i) / len(u) if u else 0.0)
        type_score = sum(per_type_scores) / len(per_type_scores)

    # --- 3. Sport / league match component (weight 0.2) -----------------
    def _canonical_set(ents: list[ExtractedEntity]) -> set[str]:
        result: set[str] = set()
        for e in ents:
            low = e.text.lower()
            if e.entity_type == EntityType.SPORT and low in SPORT_TERMS:
                result.add(f"sport:{SPORT_TERMS[low]}")
            elif e.entity_type == EntityType.LEAGUE and low in LEAGUE_TERMS:
                result.add(f"league:{LEAGUE_TERMS[low]}")
            # Also check raw text in case entity_type was not set correctly
            if low in SPORT_TERMS:
                result.add(f"sport:{SPORT_TERMS[low]}")
            if low in LEAGUE_TERMS:
                result.add(f"league:{LEAGUE_TERMS[low]}")
        return result

    cat_a = _canonical_set(entities_a)
    cat_b = _canonical_set(entities_b)

    cat_union = cat_a | cat_b
    cat_inter = cat_a & cat_b
    category_score = len(cat_inter) / len(cat_union) if cat_union else 0.0

    # --- Weighted sum ----------------------------------------------------
    total = 0.5 * exact_score + 0.3 * type_score + 0.2 * category_score
    return round(min(1.0, max(0.0, total)), 4)


# ---------------------------------------------------------------------------
# Stop-word lists (kept private)
# ---------------------------------------------------------------------------

_STOP_WORDS: set[str] = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "need",
    "dare",
    "ought",
    "used",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "as",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "between",
    "out",
    "off",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "when",
    "where",
    "why",
    "how",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "because",
    "but",
    "and",
    "or",
    "if",
    "while",
    "that",
    "this",
    "these",
    "those",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "it",
    "its",
    "he",
    "she",
    "they",
    "them",
    "his",
    "her",
    "their",
    "we",
    "us",
    "our",
    "you",
    "your",
    "i",
    "me",
    "my",
    "about",
    "up",
    "down",
    "new",
    "first",
    "last",
    "long",
    "high",
    "old",
    "big",
    "small",
    "large",
    "next",
    "early",
    "late",
    "win",
    "wins",
    "won",
    "loss",
    "losses",
    "lost",
    "draw",
    "match",
    "game",
    "games",
    "team",
    "teams",
    "player",
    "players",
    "season",
    "round",
    "stage",
    "final",
    "semi",
    "quarter",
    "group",
    "cup",
    "championship",
    "championships",
    "league",
    "division",
    "conference",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}

_CHINESE_STOP_WORDS: set[str] = {
    "的是",
    "不是",
    "没有",
    "可以",
    "已经",
    "还是",
    "或者",
    "而且",
    "但是",
    "因为",
    "所以",
    "如果",
    "虽然",
    "然后",
    "这个",
    "那个",
    "我们",
    "他们",
    "你们",
    "自己",
    "什么",
    "怎么",
    "一个",
    "两个",
    "比赛",
    "赛季",
    "球队",
    "球员",
    "教练",
    "冠军",
    "决赛",
    "联赛",
    "第一",
    "第二",
    "第三",
    "最后",
    "今天",
    "昨天",
    "明天",
    "目前",
    "现在",
    "今年",
    "去年",
    "明年",
    "本场",
    "全场",
    "上半场",
    "下半场",
    "进球",
    "得分",
    "失利",
    "获胜",
    "战胜",
    "击败",
    "战平",
}
