"""共享的热点体育分类词表与分类归一化规则。

分类既用于采集时从真实标题提取标签，也用于读取历史快照时合并旧版本
使用过的别名。这里不生成任何内容，只对实际返回的标题、话题和视频做
确定性的分类。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.services.entity_extraction import EntityType, extract_entities
from app.services.sports_catalog import sport_profile_keywords

_HASHTAG_PATTERN = re.compile(r"#([\w\u4e00-\u9fff]{2,40})", re.UNICODE)
_CAMEL_CASE_PATTERN = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z]+)+$")


class TrendLabelType(StrEnum):
    """面向创作者的热点标签层级。"""

    TOPIC = "topic"
    EVENT = "event"
    PERSON = "person"
    TEAM = "team"
    LEAGUE = "league"
    LOCATION = "location"


@dataclass(frozen=True)
class TrendLabel:
    """A useful, explainable label extracted from real source text."""

    text: str
    label_type: TrendLabelType
    priority: int
    source: str
    confidence: float = 1.0


LABEL_PRIORITIES: dict[TrendLabelType, int] = {
    TrendLabelType.TOPIC: 100,
    TrendLabelType.EVENT: 80,
    TrendLabelType.PERSON: 60,
    TrendLabelType.TEAM: 55,
    TrendLabelType.LEAGUE: 45,
    TrendLabelType.LOCATION: 35,
}

# These terms describe the vertical or the publisher, not an actionable
# conversation. They are deliberately exact-match rules so a meaningful
# phrase such as "football transfer window" is not accidentally removed.
GENERIC_TREND_LABELS: frozenset[str] = frozenset(
    {
        "sport",
        "sports",
        "体育",
        "football",
        "soccer",
        "篮球",
        "basketball",
        "baseball",
        "tennis",
        "网球",
        "golf",
        "高尔夫",
        "racing",
        "赛车",
        "motorsport",
        "hockey",
        "ice_hockey",
        "volleyball",
        "排球",
        "badminton",
        "羽毛球",
        "swimming",
        "游泳",
        "athletics",
        "田径",
        "esports",
        "电竞",
        "fitness",
        "健身",
        "boxing",
        "拳击",
        "mma",
        "格斗",
        "espn",
        "sportscenter",
        "sky_sports",
        "fox_sports",
        "cctv5",
        "news",
        "sportsnews",
        "sports_news",
        "highlights",
        "highlight",
        "live",
        "viral",
        "trending",
        "fyp",
        "foryou",
        "foryoupage",
        "shorts",
        "reels",
        "tiktok",
        "official",
        "reaction",
        "video",
        # Low-information tags observed in monitored samples.
        "cookie",
        "redcarpet",
        "red_carpet",
        "nails",
        "gym",
    }
)

EVENT_LABELS: frozenset[str] = frozenset(
    {
        "olympics",
        "olympic",
        "奥运",
        "奥运会",
        "world_cup",
        "世界杯",
        "euro",
        "欧洲杯",
        "champions_league",
        "欧冠",
        "wimbledon",
        "us_open",
        "french_open",
        "australian_open",
        "grand_slam",
        "grand_prix",
        "super_bowl",
        "超级碗",
        "hall_of_fame",
        "halloffame",
        "hof",
        "名人堂",
        "nba_finals",
        "nfl_draft",
    }
)

LEAGUE_LABELS: frozenset[str] = frozenset(
    {
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "wnba",
        "ufc",
        "atp",
        "wta",
        "pga",
        "fifa",
        "uefa",
        "f1",
        "motogp",
        "nascar",
        "indycar",
    }
)

TEAM_LABELS: frozenset[str] = frozenset(
    {
        "celtics",
        "nuggets",
        "thunder",
        "mavs",
        "knicks",
        "raptors",
        "spurs",
        "sixers",
        "timberwolves",
        "lakers",
        "warriors",
        "heat",
        "suns",
        "arsenal",
        "chelsea",
        "liverpool",
        "manchester_city",
        "manchester_united",
        "巴塞罗那",
        "皇家马德里",
        "曼城",
        "曼联",
    }
)

_EVENT_MARKER_PATTERN = re.compile(
    r"(?:决赛|半决赛|季后赛|总决赛|锦标赛|公开赛|杯赛|选秀|联赛|奥运会|世界杯)"
    r"|(?:finals?|playoffs?|championship|tournament|draft|grand prix|open|cup)",
    re.IGNORECASE,
)

# 词表覆盖页面支持的体育分类。词表只负责发现真实文本中的词，不代表
# 该分类一定有数据；没有对应来源时，分类汇总会如实返回 0。
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("american_football", ("NFL", "橄榄球", "american football")),
    (
        "football",
        ("足球", "football", "soccer", "世界杯", "欧冠", "英超", "西甲", "德甲", "意甲", "中超"),
    ),
    ("basketball", ("NBA", "CBA", "篮球", "basketball")),
    ("baseball", ("棒球", "baseball", "MLB")),
    ("mma", ("UFC", "MMA", "格斗", "拳击", "boxing", "mixed martial arts")),
    ("motorsport", ("F1", "赛车", "racing", "MotoGP", "NASCAR", "IndyCar")),
    ("table_tennis", ("乒乓", "table tennis")),
    ("badminton", ("羽毛球", "badminton")),
    ("tennis", ("网球", "tennis")),
    ("olympics", ("奥运", "Olympic", "Olympics")),
    ("esports", ("电竞", "esports", "e-sports")),
    ("golf", ("高尔夫", "golf", "PGA")),
    ("volleyball", ("排球", "volleyball")),
    ("swimming", ("游泳", "swimming")),
    ("athletics", ("田径", "马拉松", "athletics", "marathon")),
    ("ice_hockey", ("曲棍球", "hockey", "NHL", "ice hockey")),
    ("fitness", ("健身", "fitness")),
)

SPORTS_KEYWORDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            keyword
            for _category, keywords in _CATEGORY_KEYWORDS
            for keyword in keywords
        ]
        + ["体育", "sports", "ESPN", "滑冰", "滑雪"]
        + [
            alias
            for _key, aliases in sport_profile_keywords()
            for alias in aliases
        ]
    )
)
SPORTS_KEYWORD_KEYS: frozenset[str] = frozenset(
    keyword.casefold().replace(" ", "_").replace("-", "_") for keyword in SPORTS_KEYWORDS
)

# 历史采集批次和不同 Provider 曾使用过以下别名。读取时统一到页面的
# 稳定分类键，避免“general_sports”有数据但“综合体育”标签显示为空。
CATEGORY_ALIASES: dict[str, str] = {
    "general": "sports",
    "general_sports": "sports",
    "sport": "sports",
    "sports": "sports",
    "soccer": "football",
    "hockey": "ice_hockey",
    "combat": "mma",
    "mixed_martial_arts": "mma",
}


def canonical_trend_category(value: str | None) -> str:
    """Return the stable UI/query key for a stored category value."""

    normalized = str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")
    if not normalized:
        return "sports"
    return CATEGORY_ALIASES.get(normalized, normalized)


def category_variants(value: str | None) -> set[str]:
    """Return stored aliases that should match one requested category."""

    canonical = canonical_trend_category(value)
    return {
        raw
        for raw, target in CATEGORY_ALIASES.items()
        if target == canonical
    } | {canonical}


def _label_key(value: str | None) -> str:
    return (
        str(value or "")
        .strip()
        .lstrip("#")
        .casefold()
        .replace(" ", "_")
        .replace("-", "_")
    )


def is_generic_trend_label(value: str | None) -> bool:
    """Return whether a label is only a sport/media umbrella term."""

    key = _label_key(value)
    return not key or key in GENERIC_TREND_LABELS


def _looks_like_person(value: str) -> bool:
    if _CAMEL_CASE_PATTERN.fullmatch(value):
        return True
    return any(
        entity.entity_type == EntityType.PERSON and entity.confidence >= 0.55
        for entity in extract_entities(value)
    )


def classify_trend_label(
    value: str | None,
    *,
    source: str = "inferred",
) -> TrendLabel | None:
    """Classify one candidate without inventing a label.

    The default dashboard intentionally excludes generic sport and publisher
    terms. Unknown non-generic labels are retained as topics for backwards
    compatibility with historical hashtag snapshots; newly collected labels
    carry a more precise type through :func:`extract_trend_labels`.
    """

    text = str(value or "").strip().lstrip("#").strip()
    key = _label_key(text)
    if not text or len(key) < 2 or is_generic_trend_label(key):
        return None

    if source == "hashtag":
        return TrendLabel(
            text, TrendLabelType.TOPIC, LABEL_PRIORITIES[TrendLabelType.TOPIC], source
        )
    if key in EVENT_LABELS or _EVENT_MARKER_PATTERN.fullmatch(text):
        return TrendLabel(
            text, TrendLabelType.EVENT, LABEL_PRIORITIES[TrendLabelType.EVENT], source
        )
    if key in TEAM_LABELS:
        return TrendLabel(
            text, TrendLabelType.TEAM, LABEL_PRIORITIES[TrendLabelType.TEAM], source
        )
    if _looks_like_person(text):
        return TrendLabel(
            text, TrendLabelType.PERSON, LABEL_PRIORITIES[TrendLabelType.PERSON], source
        )
    if key in LEAGUE_LABELS:
        return TrendLabel(
            text, TrendLabelType.LEAGUE, LABEL_PRIORITIES[TrendLabelType.LEAGUE], source
        )
    if key in {"china", "中国", "usa", "美国", "uk", "英国", "japan", "日本"}:
        return TrendLabel(
            text, TrendLabelType.LOCATION, LABEL_PRIORITIES[TrendLabelType.LOCATION], source
        )

    # Remaining controlled sport terms are still useful for deciding whether
    # a source is sports-related, but are not useful as dashboard labels.
    if key in SPORTS_KEYWORD_KEYS:
        return None

    return TrendLabel(text, TrendLabelType.TOPIC, LABEL_PRIORITIES[TrendLabelType.TOPIC], source)


def extract_trend_labels(text: str) -> tuple[TrendLabel, ...]:
    """Extract ranked topic/event/entity labels from real source text."""

    candidates: dict[tuple[str, TrendLabelType], TrendLabel] = {}

    def add(candidate: TrendLabel | None) -> None:
        if candidate is None:
            return
        key = (_label_key(candidate.text), candidate.label_type)
        previous = candidates.get(key)
        if previous is None or candidate.confidence > previous.confidence:
            candidates[key] = candidate

    for match in _HASHTAG_PATTERN.finditer(text):
        add(classify_trend_label(match.group(1), source="hashtag"))

    lowered = text.casefold()
    for event in EVENT_LABELS:
        phrase = event.replace("_", " ")
        if phrase in lowered:
            add(
                TrendLabel(
                    text=phrase,
                    label_type=TrendLabelType.EVENT,
                    priority=LABEL_PRIORITIES[TrendLabelType.EVENT],
                    source="event_dictionary",
                    confidence=0.95,
                )
            )

    # Use the title/first line for entity extraction. Summaries and long
    # descriptions contain too many incidental names to be useful labels.
    entity_text = text.splitlines()[0].strip() or text
    for match in re.finditer(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", entity_text):
        add(classify_trend_label(match.group(0), source="camel_case_entity"))
    for entity in extract_entities(entity_text):
        if entity.entity_type == EntityType.PERSON and entity.confidence >= 0.55:
            team_key = _label_key(entity.text)
            if team_key in TEAM_LABELS:
                add(
                    TrendLabel(
                        entity.text,
                        TrendLabelType.TEAM,
                        LABEL_PRIORITIES[TrendLabelType.TEAM],
                        "entity_extraction",
                        entity.confidence,
                    )
                )
                continue
            add(
                TrendLabel(
                    entity.text,
                    TrendLabelType.PERSON,
                    LABEL_PRIORITIES[TrendLabelType.PERSON],
                    "entity_extraction",
                    entity.confidence,
                )
            )
        elif entity.entity_type == EntityType.LEAGUE:
            add(
                TrendLabel(
                    entity.text,
                    TrendLabelType.LEAGUE,
                    LABEL_PRIORITIES[TrendLabelType.LEAGUE],
                    "entity_extraction",
                    entity.confidence,
                )
            )
        elif entity.entity_type == EntityType.LOCATION:
            add(
                TrendLabel(
                    entity.text,
                    TrendLabelType.LOCATION,
                    LABEL_PRIORITIES[TrendLabelType.LOCATION],
                    "entity_extraction",
                    entity.confidence,
                )
            )

    for term in SPORTS_KEYWORDS:
        if term.casefold() in lowered:
            add(classify_trend_label(term, source="controlled_vocabulary"))

    return tuple(
        sorted(
            candidates.values(),
            key=lambda item: (-item.priority, -item.confidence, _label_key(item.text)),
        )
    )


def is_sports_related(text: str) -> bool:
    lowered = text.casefold()
    return any(keyword.casefold() in lowered for keyword in SPORTS_KEYWORDS)


def trend_terms(text: str) -> set[str]:
    """Backward-compatible text-only view of useful trend labels."""

    return {label.text.strip()[:200] for label in extract_trend_labels(text) if label.text.strip()}


def infer_sports_category(text: str) -> str:
    lowered = text.casefold()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword.casefold() in lowered for keyword in keywords):
            return category
    for category, keywords in sport_profile_keywords():
        if any(keyword.casefold() in lowered for keyword in keywords):
            return category
    return "sports"
