"""Versioned sports taxonomy and collection targets for hotspot discovery.

The catalog is a plan for querying real sources; it is not a data seed.  A
sport is only shown as having coverage after a live provider returns records.
Keeping the taxonomy in one module lets the collector, API and UI share the
same keys without platform-specific branches or hard-coded page lists.
"""

from dataclasses import dataclass
from typing import Literal

SportTier = Literal["mainstream", "general"]


@dataclass(frozen=True)
class SportProfile:
    key: str
    name_zh: str
    name_en: str
    query: str
    tier: SportTier

    @property
    def default_target(self) -> int:
        return 50 if self.tier == "mainstream" else 10


def _main(key: str, zh: str, en: str, query: str | None = None) -> SportProfile:
    return SportProfile(key, zh, en, query or en, "mainstream")


def _general(key: str, zh: str, en: str, query: str | None = None) -> SportProfile:
    return SportProfile(key, zh, en, query or en, "general")


# The first tier deliberately contains 50 distinct, globally recognizable
# sports.  Competition properties (Olympics, World Cup, etc.) remain event
# labels, not sports, so the two dimensions cannot be accidentally mixed.
MAINSTREAM_SPORTS: tuple[SportProfile, ...] = (
    _main("football", "足球", "Football", "soccer football"),
    _main("basketball", "篮球", "Basketball"),
    _main("tennis", "网球", "Tennis"),
    _main("baseball", "棒球", "Baseball"),
    _main("cricket", "板球", "Cricket"),
    _main("volleyball", "排球", "Volleyball"),
    _main("badminton", "羽毛球", "Badminton"),
    _main("table_tennis", "乒乓球", "Table tennis"),
    _main("golf", "高尔夫", "Golf"),
    _main("swimming", "游泳", "Swimming"),
    _main("athletics", "田径", "Athletics"),
    _main("gymnastics", "体操", "Gymnastics"),
    _main("boxing", "拳击", "Boxing"),
    _main("mma", "综合格斗", "MMA"),
    _main("wrestling", "摔跤", "Wrestling"),
    _main("cycling", "自行车", "Cycling"),
    _main("motorsport", "赛车", "Motorsport"),
    _main("formula1", "一级方程式", "Formula 1", "Formula 1 F1"),
    _main("nascar", "纳斯卡", "NASCAR"),
    _main("moto_gp", "MotoGP", "MotoGP"),
    _main("ice_hockey", "冰球", "Ice hockey"),
    _main("field_hockey", "曲棍球", "Field hockey"),
    _main("rugby", "橄榄球", "Rugby"),
    _main("american_football", "美式橄榄球", "American football"),
    _main("handball", "手球", "Handball"),
    _main("skiing", "滑雪", "Skiing"),
    _main("snowboarding", "单板滑雪", "Snowboarding"),
    _main("figure_skating", "花样滑冰", "Figure skating"),
    _main("speed_skating", "速度滑冰", "Speed skating"),
    _main("skateboarding", "滑板", "Skateboarding"),
    _main("surfing", "冲浪", "Surfing"),
    _main("rowing", "赛艇", "Rowing"),
    _main("sailing", "帆船", "Sailing"),
    _main("archery", "射箭", "Archery"),
    _main("shooting", "射击", "Shooting sport"),
    _main("fencing", "击剑", "Fencing"),
    _main("judo", "柔道", "Judo"),
    _main("taekwondo", "跆拳道", "Taekwondo"),
    _main("karate", "空手道", "Karate"),
    _main("weightlifting", "举重", "Weightlifting"),
    _main("equestrian", "马术", "Equestrian"),
    _main("triathlon", "铁人三项", "Triathlon"),
    _main("biathlon", "冬季两项", "Biathlon"),
    _main("bobsleigh", "雪车", "Bobsleigh"),
    _main("luge", "雪橇", "Luge"),
    _main("curling", "冰壶", "Curling"),
    _main("esports", "电子竞技", "Esports"),
    _main("para_sports", "残疾人体育", "Para sports"),
    _main("diving", "跳水", "Diving"),
    _main("water_polo", "水球", "Water polo"),
)


# The second tier expands discovery without allowing less common sports to
# consume the same request budget as the primary editorial signals.
GENERAL_SPORTS: tuple[SportProfile, ...] = (
    _general("australian_rules", "澳式足球", "Australian rules football"),
    _general("futsal", "五人制足球", "Futsal"),
    _general("beach_soccer", "沙滩足球", "Beach soccer"),
    _general("beach_volleyball", "沙滩排球", "Beach volleyball"),
    _general("kabaddi", "卡巴迪", "Kabaddi"),
    _general("sepak_takraw", "藤球", "Sepak takraw"),
    _general("padel", "板式网球", "Padel"),
    _general("squash", "壁球", "Squash"),
    _general("racquetball", "壁球（美式）", "Racquetball"),
    _general("pickleball", "匹克球", "Pickleball"),
    _general("pelota", "巴斯克 pelota", "Basque pelota"),
    _general("lawn_bowls", "草地滚球", "Lawn bowls"),
    _general("croquet", "槌球", "Croquet"),
    _general("disc_golf", "飞盘高尔夫", "Disc golf"),
    _general("mini_golf", "迷你高尔夫", "Mini golf"),
    _general("darts", "飞镖", "Darts"),
    _general("snooker", "斯诺克", "Snooker"),
    _general("billiards", "台球", "Billiards"),
    _general("speedway", "场地摩托车赛", "Speedway"),
    _general("rally", "拉力赛", "Rally racing"),
    _general("drifting", "漂移", "Drifting"),
    _general("motocross", "越野摩托", "Motocross"),
    _general("monster_trucks", "怪兽卡车", "Monster trucks"),
    _general("dog_sports", "犬类运动", "Dog sports"),
    _general("rodeo", "牛仔竞技", "Rodeo"),
    _general("powerlifting", "力量举", "Powerlifting"),
    _general("bodybuilding", "健美", "Bodybuilding"),
    _general("cheerleading", "啦啦队", "Cheerleading"),
    _general("dance_sport", "体育舞蹈", "Dance sport"),
    _general("modern_pentathlon", "现代五项", "Modern pentathlon"),
)

SPORTS_CATALOG: tuple[SportProfile, ...] = MAINSTREAM_SPORTS + GENERAL_SPORTS
SPORTS_CATALOG_VERSION = "sports-hotspot-taxonomy-v1"

if len(MAINSTREAM_SPORTS) != 50 or len(GENERAL_SPORTS) != 30:  # pragma: no cover
    raise RuntimeError("sports hotspot taxonomy must contain 50 + 30 profiles")


def sport_profile_keywords() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return aliases used by deterministic category inference."""

    return tuple(
        (
            profile.key,
            tuple(dict.fromkeys((profile.name_en, profile.query, profile.name_zh))),
        )
        for profile in SPORTS_CATALOG
    )
