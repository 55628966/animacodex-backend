"""
大六壬 (Da Liu Ren) 占卜引擎 — 天盘/四课/三传/十二天将

三式之一。天盘动、地盘静、四课为局势、三传为走势。
全确定性计算。输出结构化数据，不生成面向用户的解读。

Author: Anima Codex core engine
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import datetime
import math


# ══════════════════════════════════════════════
# 基础枚举与常量
# ══════════════════════════════════════════════

class Wuxing(Enum):
    WOOD = "木"; FIRE = "火"; EARTH = "土"; METAL = "金"; WATER = "水"


class Stem(Enum):
    JIA="甲"; YI="乙"; BING="丙"; DING="丁"; WU="戊"
    JI="己"; GENG="庚"; XIN="辛"; REN="壬"; GUI="癸"


class Branch(Enum):
    ZI="子"; CHOU="丑"; YIN="寅"; MAO="卯"; CHEN="辰"; SI="巳"
    WU="午"; WEI="未"; SHEN="申"; YOU="酉"; XU="戌"; HAI="亥"


ALL_STEMS = list(Stem)
ALL_BRANCHES = list(Branch)

STEM_VAL = {s: i+1 for i, s in enumerate(ALL_STEMS)}
BRANCH_VAL = {b: i+1 for i, b in enumerate(ALL_BRANCHES)}
BRANCH_BY_VAL = {i+1: b for i, b in enumerate(ALL_BRANCHES)}
STEM_BY_VAL = {i+1: s for i, s in enumerate(ALL_STEMS)}

# 五行查表
BRANCH_WX: dict[Branch, Wuxing] = {
    Branch.ZI:Wuxing.WATER, Branch.CHOU:Wuxing.EARTH, Branch.YIN:Wuxing.WOOD,
    Branch.MAO:Wuxing.WOOD, Branch.CHEN:Wuxing.EARTH, Branch.SI:Wuxing.FIRE,
    Branch.WU:Wuxing.FIRE, Branch.WEI:Wuxing.EARTH, Branch.SHEN:Wuxing.METAL,
    Branch.YOU:Wuxing.METAL, Branch.XU:Wuxing.EARTH, Branch.HAI:Wuxing.WATER,
}

STEM_WX: dict[Stem, Wuxing] = {
    Stem.JIA:Wuxing.WOOD, Stem.YI:Wuxing.WOOD, Stem.BING:Wuxing.FIRE,
    Stem.DING:Wuxing.FIRE, Stem.WU:Wuxing.EARTH, Stem.JI:Wuxing.EARTH,
    Stem.GENG:Wuxing.METAL, Stem.XIN:Wuxing.METAL, Stem.REN:Wuxing.WATER,
    Stem.GUI:Wuxing.WATER,
}

# 寄宫：天干寄于地支
QIAN_GONG: dict[Stem, int] = {
    Stem.JIA:3, Stem.YI:5, Stem.BING:6, Stem.DING:8, Stem.WU:6,
    Stem.JI:8, Stem.GENG:9, Stem.XIN:11, Stem.REN:12, Stem.GUI:2,
}

# 中气 → 月将映射 (节气索引0=冬至 → 月将地支值)
ZHONGQI_YUEJIANG = [2, 1, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3]
# 冬至→丑, 大寒→子, 雨水→亥, 春分→戌, 谷雨→酉, 小满→申,
# 夏至→未, 大暑→午, 处暑→巳, 秋分→辰, 霜降→卯, 小雪→寅

# 月将名
YUEJIANG_NAMES = {12:"登明", 11:"河魁", 10:"从魁", 9:"传送", 8:"小吉", 7:"胜光",
                   6:"太乙", 5:"天罡", 4:"太冲", 3:"功曹", 2:"大吉", 1:"神后"}

# 贵人起法
GUIREN_DAY: dict[int, int] = {1:2, 2:1, 3:12, 4:12, 5:2, 6:1, 7:2, 8:7, 9:4, 10:4}
GUIREN_NIGHT: dict[int, int] = {1:8, 2:9, 3:10, 4:10, 5:8, 6:9, 7:8, 8:3, 9:6, 10:6}

# 十二天将
TWELVE_GENERALS = ["贵人","螣蛇","朱雀","六合","勾陈","青龙","天空","白虎","太常","玄武","太阴","天后"]

# 地支关系
BRANCH_CLASH: dict[int, int] = {1:7, 7:1, 2:8, 8:2, 3:9, 9:3, 4:10, 10:4, 5:11, 11:5, 6:12, 12:6}

GENERATES = {Wuxing.WOOD:Wuxing.FIRE, Wuxing.FIRE:Wuxing.EARTH, Wuxing.EARTH:Wuxing.METAL,
             Wuxing.METAL:Wuxing.WATER, Wuxing.WATER:Wuxing.WOOD}
CONTROLS = {Wuxing.WOOD:Wuxing.EARTH, Wuxing.EARTH:Wuxing.WATER, Wuxing.WATER:Wuxing.FIRE,
            Wuxing.FIRE:Wuxing.METAL, Wuxing.METAL:Wuxing.WOOD}


# ══════════════════════════════════════════════
# 节气/月将计算
# ══════════════════════════════════════════════

def _solar_longitude(date: datetime.date) -> float:
    """太阳黄经（度）。优先使用 pyswisseph 精确到角秒；不可用时退化为简化算法。"""
    try:
        import swisseph as swe
        jd = swe.julday(date.year, date.month, date.day, 0.0)
        xx, _ = swe.calc_ut(jd, swe.SUN, swe.FLG_SWIEPH | swe.FLG_SPEED)
        return xx[0]  # longitude in degrees
    except ImportError:
        pass

    # 退化简化算法
    y, m, d = date.year, date.month, date.day
    if m <= 2:
        y -= 1; m += 12
    a = y // 100; b = 2 - a + a // 4
    jd = int(365.25*(y+4716)) + int(30.6001*(m+1)) + d + b - 1524.5
    n = jd - 2451545.0
    L = (280.46646 + 0.98564736*n) % 360
    g = (357.52911 + 0.98560028*n) % 360
    gr = math.radians(g)
    L = (L + 1.914602*math.sin(gr) + 0.019993*math.sin(2*gr)) % 360
    return L


def get_yuejiang(date: datetime.date) -> int:
    """返回月将地支值 1-12。
    算法：根据太阳黄经确定当前中气，中气对应的月将即为当月将。
    简化：直接按太阳黄经每30°一段映射到12中气区间。
    """
    lng = _solar_longitude(date)
    # 太阳黄经 0°=春分 ≈ 3月21日
    # 中气从冬至(270°)开始，每30°一个中气
    # 冬至=270°→大吉丑, 大寒=300°→神后子, 雨水=330°→登明亥,
    # 春分=0°→河魁戌, 谷雨=30°→从魁酉, 小满=60°→传送申,
    # 夏至=90°→小吉未, 大暑=120°→胜光午, 处暑=150°→太乙巳,
    # 秋分=180°→天罡辰, 霜降=210°→太冲卯, 小雪=240°→功曹寅
    # 将太阳黄经映射到 [(lng - 270 + 360) % 360 // 30]
    idx = int(((lng - 270 + 360) % 360) / 30) % 12
    return ZHONGQI_YUEJIANG[idx]


def get_zhan_shi(hour: int, minute: int = 0) -> int:
    """返回时辰地支值 1-12（子=1）"""
    t = (hour * 60 + minute + 30) % 1440
    shichen = t // 120
    return shichen + 1


# ══════════════════════════════════════════════
# 天盘
# ══════════════════════════════════════════════

def build_tianpan(yuejiang: int, zhan_shi: int) -> list[int]:
    """月将加占时 → 天盘。tianpan[pos] = 该地盘位置上的天盘地支值"""
    tp = [0] * 13
    pos = zhan_shi
    tp[pos] = yuejiang
    branch = yuejiang
    for _ in range(11):
        pos = pos % 12 + 1
        branch = branch % 12 + 1
        tp[pos] = branch
    return tp


def tianpan_inverse(tp: list[int]) -> dict[int, int]:
    """天盘逆查：天盘地支值 → 地盘位置"""
    return {tp[p]: p for p in range(1, 13)}


# ══════════════════════════════════════════════
# 旬遁干
# ══════════════════════════════════════════════

def compute_xun_dun(day_stem_val: int, day_branch_val: int) -> list[int]:
    """日干支 → 12个地盘位置对应的遁干(1-10)。位置在旬空的返回0"""
    offset = (day_branch_val - day_stem_val) % 12
    xun_shou = offset + 1  # 旬首地支值
    xd = [0] * 13
    for pos in range(1, 13):
        dist = (pos - xun_shou + 12) % 12
        if dist >= 10:
            xd[pos] = 0  # 旬空
        else:
            s = (dist + 1)
            xd[pos] = s if s <= 10 else s - 10
    return xd


# ══════════════════════════════════════════════
# 四课
# ══════════════════════════════════════════════

@dataclass
class Lesson:
    index: int                # 1-4
    upper_stem: int           # 上神天干 1-10
    upper_branch: int         # 上神地支 1-12
    lower_stem: int           # 下神天干
    lower_branch: int         # 下神地支
    is_lower_ke_upper: bool = False   # 下克上（贼）
    is_upper_ke_lower: bool = False   # 上克下（克）


def compute_four_lessons(day_stem: Stem, day_branch: Branch, tp: list[int], xd: list[int]) -> list[Lesson]:
    """计算四课"""
    ds = STEM_VAL[day_stem]
    db = BRANCH_VAL[day_branch]
    lessons = []

    # 第一课：日干寄宫 → 上神
    p1 = QIAN_GONG[day_stem]
    b1 = tp[p1]
    s1 = xd[p1] if xd[p1] else ds
    l1 = Lesson(1, s1, b1, ds, p1)
    _check_ke(l1)
    lessons.append(l1)

    # 第二课：第一课上神 → 上神
    p2 = b1
    b2 = tp[p2]
    s2 = xd[p2] if xd[p2] else (xd[p1] if xd[p1] else ds)
    l2 = Lesson(2, s2, b2, s1 if s1 else ds, b1)
    _check_ke(l2)
    lessons.append(l2)

    # 第三课：日支 → 上神
    p3 = db
    b3 = tp[p3]
    s3 = xd[p3] if xd[p3] else ds
    l3 = Lesson(3, s3, b3, ds, db)
    _check_ke(l3)
    lessons.append(l3)

    # 第四课：第三课上神 → 上神
    p4 = b3
    b4 = tp[p4]
    s4 = xd[p4] if xd[p4] else (xd[p3] if xd[p3] else ds)
    l4 = Lesson(4, s4, b4, s3 if s3 else ds, b3)
    _check_ke(l4)
    lessons.append(l4)

    return lessons


def _check_ke(l: Lesson):
    """检查一课中的生克"""
    lw = BRANCH_WX[BRANCH_BY_VAL[l.lower_branch]]
    uw = BRANCH_WX[BRANCH_BY_VAL[l.upper_branch]]
    if CONTROLS.get(lw) == uw:
        l.is_lower_ke_upper = True
    if CONTROLS.get(uw) == lw:
        l.is_upper_ke_lower = True


# ══════════════════════════════════════════════
# 三传 — 九宗门
# ══════════════════════════════════════════════

def _chuan_chain(start_branch: int, tp: list[int]) -> tuple[int, int, int]:
    """初传 → 中传(初传上神) → 末传(中传上神)"""
    chu = start_branch
    zhong = tp[chu]
    mo = tp[zhong]
    return (chu, zhong, mo)


def _is_yang(branch_val: int) -> bool:
    return branch_val % 2 == 1


def determine_sanchuan(lessons: list[Lesson], day_stem: Stem, day_branch: Branch,
                        tp: list[int], xd: list[int]) -> Optional[tuple[int, int, int, str]]:
    """
    九宗门推三传。
    返回 (初传, 中传, 末传, 方法名) 或 None
    """
    ds_val = STEM_VAL[day_stem]
    db_val = BRANCH_VAL[day_branch]

    # --- 伏吟检查 ---
    if all(tp[p] == p for p in range(1, 13)):
        return _fu_yin(ds_val, tp)

    # --- 反吟检查 ---
    if all(tp[p] == _opposite(p) for p in range(1, 13)):
        return _fan_yin(lessons, day_stem, day_branch, tp, xd)

    # --- 贼克 + 比用 + 涉害 ---
    ze = [l for l in lessons if l.is_lower_ke_upper]  # 下克上(贼)
    ke = [l for l in lessons if l.is_upper_ke_lower]   # 上克下(克)

    candidates = ze if ze else ke
    if candidates:
        method = "贼" if ze else "克"
        if len(candidates) == 1:
            c, z, m = _chuan_chain(candidates[0].upper_branch, tp)
            return (c, z, m, method)

        # 比用：同阴阳者优先
        ds_yang = _is_yang(ds_val)
        same_yin_yang = [l for l in candidates if _is_yang(l.upper_branch) == ds_yang]
        if same_yin_yang:
            chosen = same_yin_yang[0]  # 取第一课
            c, z, m = _chuan_chain(chosen.upper_branch, tp)
            return (c, z, m, "比用")

        # 涉害：数克 + 孟仲季
        counts = []
        for l in candidates:
            cnt = _she_hai_count(l.lower_branch, l.upper_branch, tp, l.is_lower_ke_upper)
            mzj = _meng_zhong_ji(l.upper_branch)
            counts.append((cnt, -mzj, l))  # 克多优先，同克孟优先
        counts.sort(key=lambda x: (-x[0], -x[1]))
        chosen = counts[0][2]
        c, z, m = _chuan_chain(chosen.upper_branch, tp)
        return (c, z, m, "涉害")

    # --- 遥克 ---
    ds_wx = STEM_WX[day_stem]
    haoshi = []
    danshe = []
    for l in lessons:
        uw = BRANCH_WX[BRANCH_BY_VAL[l.upper_branch]]
        if CONTROLS.get(uw) == ds_wx:      # 上克日干 → 蒿矢
            haoshi.append(l)
        if CONTROLS.get(ds_wx) == uw:       # 日干克上 → 弹射
            danshe.append(l)

    if haoshi:
        l = haoshi[0]
        c, z, m = _chuan_chain(l.upper_branch, tp)
        return (c, z, m, "蒿矢")
    if danshe:
        l = danshe[0]
        c, z, m = _chuan_chain(l.upper_branch, tp)
        return (c, z, m, "弹射")

    # --- 昴星 ---
    ds_yang = _is_yang(ds_val)
    
    # 检查别责条件：四课中有重复
    has_duplicate = False
    for i in range(4):
        for j in range(i+1, 4):
            if lessons[i].upper_branch == lessons[j].upper_branch and \
               lessons[i].lower_branch == lessons[j].lower_branch:
                has_duplicate = True
                break
    # 检查八专条件：日干寄宫 == 日支
    is_ba_zhuan = (QIAN_GONG[day_stem] == db_val)
    
    if is_ba_zhuan and not has_duplicate:
        # --- 八专 ---
        if ds_yang:
            # 阳日：日干寄宫顺数三位 → 上神 = 初传
            qg = QIAN_GONG[day_stem]
            pos = ((qg - 1 + 3) % 12) + 1
            chu = tp[pos]
        else:
            # 阴日：日支逆数三位 → 上神 = 初传
            pos = ((db_val - 1 - 3 + 12) % 12) + 1
            chu = tp[pos]
        # 中传末传皆日干上神
        zhong = tp[QIAN_GONG[day_stem]]
        mo = zhong
        return (chu, zhong, mo, "八专")
    
    if not ds_yang and has_duplicate and not is_ba_zhuan:
        # --- 别责（阴日+四课重复）---
        # 初传：日支三合前位之上神
        sanhe_groups = [(12,4,8), (11,3,7), (10,2,6), (9,1,5)]
        front = db_val
        for grp in sanhe_groups:
            if db_val in grp:
                idx = grp.index(db_val)
                front = grp[(idx - 1) % 3]
                break
        chu = tp[front]
        zhong = tp[QIAN_GONG[day_stem]]
        mo = zhong
        return (chu, zhong, mo, "别责")
    
    if ds_yang:
        chu = tp[10]
        zhong = tp[db_val]
        mo = tp[QIAN_GONG[day_stem]]
    else:
        inv = tianpan_inverse(tp)
        chu = inv.get(10, 10)
        zhong = tp[QIAN_GONG[day_stem]]
        mo = tp[db_val]
    return (chu, zhong, mo, "昴星")


def _meng_zhong_ji(branch_val: int) -> int:
    """孟仲季: 孟=1, 仲=2, 季=3"""
    if branch_val in (3, 6, 9, 12): return 1  # 寅申巳亥 = 孟
    if branch_val in (1, 4, 7, 10): return 2  # 子午卯酉 = 仲
    return 3  # 辰戌丑未 = 季


def _she_hai_count(lower: int, upper: int, tp: list[int], is_ze: bool) -> int:
    """涉害深度：计算克数（沿地盘顺序数到上神，计克我者次数）"""
    count = 0
    wx_lower = BRANCH_WX[BRANCH_BY_VAL[lower]]
    cur = lower
    while cur != upper:
        cur = cur % 12 + 1
        wx_cur = BRANCH_WX[BRANCH_BY_VAL[cur]]
        if CONTROLS.get(wx_cur) == wx_lower:
            count += 1
    return count


def _opposite(b: int) -> int:
    return ((b - 1 + 6) % 12) + 1


def _fu_yin(ds_val: int, tp: list[int]) -> tuple[int, int, int, str]:
    """伏吟三传"""
    fu_map = {1:(3,6,9), 2:(5,6,5), 3:(6,9,3), 4:(8,9,3),
              5:(6,9,3), 6:(8,9,3), 7:(9,12,3), 8:(11,12,3),
              9:(12,3,6), 10:(2,3,6)}
    if ds_val in fu_map:
        c, z, m = fu_map[ds_val]
        return (c, z, m, "伏吟")
    return (1, 4, 7, "伏吟")


def _fan_yin(lessons: list[Lesson], day_stem: Stem, day_branch: Branch,
              tp: list[int], xd: list[int]) -> Optional[tuple[int, int, int, str]]:
    """反吟三传"""
    db_val = BRANCH_VAL[day_branch]
    ds_val = STEM_VAL[day_stem]
    # 反吟必有克，走贼克
    ze = [l for l in lessons if l.is_lower_ke_upper]
    ke = [l for l in lessons if l.is_upper_ke_lower]
    cand = ze if ze else ke
    if cand:
        chosen = cand[0]
        c, z, m = _chuan_chain(chosen.upper_branch, tp)
        return (c, z, m, "反吟")

    # 无克：驿马法
    yi_ma = (db_val + 6) % 12
    if yi_ma == 0:
        yi_ma = 12
    chu = tp[yi_ma]
    zhong = tp[db_val]
    mo = tp[QIAN_GONG[day_stem]]
    return (chu, zhong, mo, "反吟·驿马")


# ══════════════════════════════════════════════
# 十二天将
# ══════════════════════════════════════════════

def place_generals(day_stem_val: int, is_daytime: bool, tp: list[int]) -> list[str]:
    """安十二天将。返回 generals[pos] = 将名，1-indexed"""
    branch = GUIREN_DAY[day_stem_val] if is_daytime else GUIREN_NIGHT[day_stem_val]
    inv = tianpan_inverse(tp)
    earth_pos = inv.get(branch, branch)

    gens = [""] * 13
    if earth_pos in {12, 1, 2, 3, 4, 5}:
        for i in range(12):
            p = ((earth_pos - 1 + i) % 12) + 1
            gens[p] = TWELVE_GENERALS[i]
    else:
        for i in range(12):
            p = ((earth_pos - 1 - i) % 12) + 1
            gens[p] = TWELVE_GENERALS[i]
    return gens


# ══════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════

@dataclass
class DaLiuRenResult:
    """大六壬完整课式"""
    # 时间
    date: str                          # 占卜日期
    shichen: int                       # 占时辰 1-12
    is_daytime: bool                   # 昼/夜

    # 干支
    day_stem: int                      # 日干 1-10
    day_branch: int                    # 日支 1-12

    # 月将
    yuejiang: int                      # 月将地支值 1-12
    yuejiang_name: str                 # 月将名

    # 天盘
    tianpan: list[int] = field(default_factory=lambda: [0]*13)  # tianpan[pos]=天盘地支

    # 遁干
    xun_dun: list[int] = field(default_factory=lambda: [0]*13)  # xun_dun[pos]=天干1-10或0(空)

    # 四课
    lessons: list = field(default_factory=list)

    # 三传
    sanchuan: Optional[tuple[int, int, int]] = None  # (初,中,末) 地支值
    sanchuan_method: str = ""                         # 九宗门方法名

    # 十二天将
    generals: list[str] = field(default_factory=lambda: [""]*13)


# ══════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════

def cast_daliuren(
    date: Optional[datetime.date] = None,
    hour: Optional[int] = None,
    minute: int = 0,
    day_stem: Optional[Stem] = None,
    day_branch: Optional[Branch] = None,
) -> DaLiuRenResult:
    """
    起大六壬课。

    若未提供 date，默认今天。
    若未提供 day_stem/day_branch，从日历推算（简化版本）。
    """
    if date is None:
        date = datetime.date.today()
    if hour is None:
        now = datetime.datetime.now()
        hour = now.hour

    # 时辰
    shichen = get_zhan_shi(hour, minute)
    is_daytime = 5 <= shichen <= 9  # 卯到申为昼

    # 月将
    yj = get_yuejiang(date)

    # 日干支 — 复用八字引擎已验证的三源交叉公式
    if day_stem is None or day_branch is None:
        from bazi_engine.core import day_gz_index
        idx = day_gz_index(date)
        ds_idx = (idx % 10) + 1
        db_idx = (idx % 12) + 1
        day_stem = STEM_BY_VAL[ds_idx]
        day_branch = BRANCH_BY_VAL[db_idx]

    ds_val = STEM_VAL[day_stem]
    db_val = BRANCH_VAL[day_branch]

    # 天盘
    tp = build_tianpan(yj, shichen)

    # 旬遁干
    xd = compute_xun_dun(ds_val, db_val)

    # 四课
    lessons = compute_four_lessons(day_stem, day_branch, tp, xd)

    # 三传
    sc = determine_sanchuan(lessons, day_stem, day_branch, tp, xd)

    # 天将
    gens = place_generals(ds_val, is_daytime, tp)

    result = DaLiuRenResult(
        date=date.isoformat(),
        shichen=shichen,
        is_daytime=is_daytime,
        day_stem=ds_val,
        day_branch=db_val,
        yuejiang=yj,
        yuejiang_name=YUEJIANG_NAMES.get(yj, ""),
        tianpan=tp,
        xun_dun=xd,
        lessons=lessons,
        sanchuan=(sc[0], sc[1], sc[2]) if sc else None,
        sanchuan_method=sc[3] if sc else "",
        generals=gens,
    )
    return result


def result_to_dict(r: DaLiuRenResult) -> dict:
    """序列化为 API 可用的 dict"""
    def lesson_dict(l: Lesson) -> dict:
        return {
            "index": l.index,
            "upper": {"stem": STEM_BY_VAL[l.upper_stem].value if l.upper_stem else "",
                       "branch": BRANCH_BY_VAL[l.upper_branch].value},
            "lower": {"stem": STEM_BY_VAL[l.lower_stem].value if l.lower_stem else "",
                       "branch": BRANCH_BY_VAL[l.lower_branch].value},
            "ze": l.is_lower_ke_upper,
            "ke": l.is_upper_ke_lower,
        }

    sc = r.sanchuan
    return {
        "date": r.date,
        "shichen": BRANCH_BY_VAL[r.shichen].value,
        "day_time": "day" if r.is_daytime else "night",
        "day_stem": STEM_BY_VAL[r.day_stem].value,
        "day_branch": BRANCH_BY_VAL[r.day_branch].value,
        "yuejiang": r.yuejiang_name,
        "tianpan": {BRANCH_BY_VAL[p].value: BRANCH_BY_VAL[r.tianpan[p]].value for p in range(1, 13)},
        "xun_dun": {BRANCH_BY_VAL[p].value: (STEM_BY_VAL[r.xun_dun[p]].value if r.xun_dun[p] else "空") for p in range(1, 13)},
        "lessons": [lesson_dict(l) for l in r.lessons],
        "sanchuan": {
            "chu": BRANCH_BY_VAL[sc[0]].value,
            "zhong": BRANCH_BY_VAL[sc[1]].value,
            "mo": BRANCH_BY_VAL[sc[2]].value,
        } if sc else None,
        "sanchuan_method": r.sanchuan_method,
        "generals": {BRANCH_BY_VAL[p].value: r.generals[p] for p in range(1, 13) if r.generals[p]},
    }
