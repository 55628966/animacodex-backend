# -*- coding: utf-8 -*-
"""四柱补充字段: 纳音、星运(十二长生)、自坐、空亡、神煞。

全部为查表/推导, 无外部依赖, 纯计算。
"""

from .constants import STEMS, BRANCHES, HIDDEN_STEMS, STEM_ELEMENT, STEM_YANG, ten_god

# ═══════════════════════════════════════════════════════════════════════
# 1. 纳音 (Nayin) — 60甲子纳音表
# ═══════════════════════════════════════════════════════════════════════

_NAYIN_TABLE = {
    0: "海中金", 1: "海中金",        # 甲子 乙丑
    2: "炉中火", 3: "炉中火",        # 丙寅 丁卯
    4: "大林木", 5: "大林木",        # 戊辰 己巳
    6: "路旁土", 7: "路旁土",        # 庚午 辛未
    8: "剑锋金", 9: "剑锋金",        # 壬申 癸酉
    10: "山头火", 11: "山头火",      # 甲戌 乙亥
    12: "涧下水", 13: "涧下水",      # 丙子 丁丑
    14: "城头土", 15: "城头土",      # 戊寅 己卯
    16: "白蜡金", 17: "白蜡金",      # 庚辰 辛巳
    18: "杨柳木", 19: "杨柳木",      # 壬午 癸未
    20: "泉中水", 21: "泉中水",      # 甲申 乙酉
    22: "屋上土", 23: "屋上土",      # 丙戌 丁亥
    24: "霹雳火", 25: "霹雳火",      # 戊子 己丑
    26: "松柏木", 27: "松柏木",      # 庚寅 辛卯
    28: "长流水", 29: "长流水",      # 壬辰 癸巳
    30: "沙中金", 31: "沙中金",      # 甲午 乙未
    32: "山下火", 33: "山下火",      # 丙申 丁酉
    34: "平地木", 35: "平地木",      # 戊戌 己亥
    36: "壁上土", 37: "壁上土",      # 庚子 辛丑
    38: "金箔金", 39: "金箔金",      # 壬寅 癸卯
    40: "覆灯火", 41: "覆灯火",      # 甲辰 乙巳
    42: "天河水", 43: "天河水",      # 丙午 丁未
    44: "大驿土", 45: "大驿土",      # 戊申 己酉
    46: "钗钏金", 47: "钗钏金",      # 庚戌 辛亥
    48: "桑柘木", 49: "桑柘木",      # 壬子 癸丑
    50: "大溪水", 51: "大溪水",      # 甲寅 乙卯
    52: "沙中土", 53: "沙中土",      # 丙辰 丁巳
    54: "天上火", 55: "天上火",      # 戊午 己未
    56: "石榴木", 57: "石榴木",      # 庚申 辛酉
    58: "大海水", 59: "大海水",      # 壬戌 癸亥
}




def _gz60_index_simple(stem: str, branch: str) -> int:
    """干支 → 六十甲子序号 (甲子=0), 简洁遍历。"""
    for i in range(60):
        if STEMS[i % 10] == stem and BRANCHES[i % 12] == branch:
            return i
    raise ValueError(f"无效干支组合: {stem}{branch}")


def nayin(stem: str, branch: str) -> str:
    """返回干支对应的纳音五行, 如 '庚午' → '路旁土'。"""
    idx = _gz60_index_simple(stem, branch)
    return _NAYIN_TABLE.get(idx, "未知")


# ═══════════════════════════════════════════════════════════════════════
# 2. 星运 (Star Fortune) — 十二长生
# ═══════════════════════════════════════════════════════════════════════

_STAGES = ("长生", "沐浴", "冠带", "临官", "帝旺", "衰", "病", "死", "墓", "绝", "胎", "养")

# 每个天干的「长生」地支索引 (阳干顺行, 阴干逆行)
_CHANGSHENG_BRANCH: dict[str, int] = {
    "甲": 11,  # 亥
    "乙": 6,   # 午
    "丙": 2,   # 寅
    "丁": 8,   # 酉
    "戊": 2,   # 寅 (同丙)
    "己": 8,   # 酉 (同丁)
    "庚": 5,   # 巳
    "辛": 0,   # 子
    "壬": 7,   # 申
    "癸": 3,   # 卯
}


def star_fortune(day_stem: str, branch: str) -> str:
    """根据日干和地支查十二长生阶段(星运)。

    阳干顺行 12 阶段, 阴干逆行。
    """
    bi = BRANCHES.index(branch)
    cs_start = _CHANGSHENG_BRANCH[day_stem]
    yang = STEM_YANG[STEMS.index(day_stem)]
    if yang:
        offset = (bi - cs_start) % 12
    else:
        offset = (cs_start - bi) % 12
    return _STAGES[offset]


# ═══════════════════════════════════════════════════════════════════════
# 3. 自坐 (Zi Zuo) — 地支本气对日主的十神
# ═══════════════════════════════════════════════════════════════════════

def zi_zuo(day_stem: str, branch: str) -> str:
    """地支本气(藏干第一位)相对于日主的十神。"""
    main_qi = HIDDEN_STEMS[branch][0]
    return ten_god(day_stem, main_qi)


# ═══════════════════════════════════════════════════════════════════════
# 4. 空亡 (Kong Wang) — 旬空
# ═══════════════════════════════════════════════════════════════════════

# 六甲旬头表: 每个甲子的起始六十甲子序号
_XUN_HEADS = [
    (0, "戌亥"),    # 甲子旬 (甲子..癸酉) → 空戌亥
    (10, "申酉"),   # 甲戌旬 (甲戌..癸未) → 空申酉
    (20, "午未"),   # 甲申旬 (甲申..癸巳) → 空午未
    (30, "辰巳"),   # 甲午旬 (甲午..癸卯) → 空辰巳
    (40, "寅卯"),   # 甲辰旬 (甲辰..癸丑) → 空寅卯
    (50, "子丑"),   # 甲寅旬 (甲寅..癸亥) → 空子丑
]


def kong_wang(day_stem: str, day_branch: str) -> str:
    """根据日柱地支查旬空 (空亡) 的地支对。"""
    gz60 = _gz60_index_simple(day_stem, day_branch)
    xun_start = (gz60 // 10) * 10
    for head, kw in _XUN_HEADS:
        if head == xun_start:
            return kw
    return "未知"


# ═══════════════════════════════════════════════════════════════════════
# 5. 神煞 (Shen Sha)
# ═══════════════════════════════════════════════════════════════════════

# 天乙贵人 (以日干/年干查)
_TIANYI_GUIREN: dict[str, str] = {
    "甲": "丑未", "戊": "丑未", "庚": "丑未",
    "乙": "子申", "己": "子申",
    "丙": "亥酉", "丁": "亥酉",
    "辛": "午寅",
    "壬": "巳卯", "癸": "巳卯",
}

# 文昌贵人 (以日干查)
_WENCHANG: dict[str, str] = {
    "甲": "巳", "乙": "午", "丙": "申", "丁": "酉", "戊": "申",
    "己": "酉", "庚": "亥", "辛": "子", "壬": "寅", "癸": "卯",
}

# 桃花/咸池 (以年支或日支查, 三合局: 申子辰→酉, 寅午戌→卯, 巳酉丑→午, 亥卯未→子)
_TAOHUA: dict[str, str] = {
    "申": "酉", "子": "酉", "辰": "酉",
    "寅": "卯", "午": "卯", "戌": "卯",
    "巳": "午", "酉": "午", "丑": "午",
    "亥": "子", "卯": "子", "未": "子",
}

# 驿马 (以年支或日支查)
_YIMA: dict[str, str] = {
    "申": "寅", "子": "寅", "辰": "寅",
    "寅": "申", "午": "申", "戌": "申",
    "巳": "亥", "酉": "亥", "丑": "亥",
    "亥": "巳", "卯": "巳", "未": "巳",
}

# 华盖 (以年支或日支查: 申子辰→辰, 寅午戌→戌, 巳酉丑→丑, 亥卯未→未)
_HUAGAI: dict[str, str] = {
    "申": "辰", "子": "辰", "辰": "辰",
    "寅": "戌", "午": "戌", "戌": "戌",
    "巳": "丑", "酉": "丑", "丑": "丑",
    "亥": "未", "卯": "未", "未": "未",
}

# 羊刃 (以日干查)
_YANGREN: dict[str, str] = {
    "甲": "卯", "乙": "寅", "丙": "午", "丁": "巳", "戊": "午",
    "己": "巳", "庚": "酉", "辛": "申", "壬": "子", "癸": "亥",
}

# 天德 (以月支查)
_TIANDE: dict[str, str] = {
    "寅": "丁", "卯": "申", "辰": "壬", "巳": "辛", "午": "亥",
    "未": "甲", "申": "癸", "酉": "寅", "戌": "丙", "亥": "乙",
    "子": "巳", "丑": "庚",
}

# 月德 (以月支查)
_YUEDE: dict[str, str] = {
    "寅": "丙", "卯": "甲", "辰": "壬", "巳": "庚", "午": "丙",
    "未": "甲", "申": "壬", "酉": "庚", "戌": "丙", "亥": "甲",
    "子": "壬", "丑": "庚",
}

# 禄神 (以日干查: 甲禄寅, 乙禄卯, 丙戊禄巳, 丁己禄午, 庚禄申, 辛禄酉, 壬禄亥, 癸禄子)
_LUSHEN: dict[str, str] = {
    "甲": "寅", "乙": "卯", "丙": "巳", "丁": "午", "戊": "巳",
    "己": "午", "庚": "申", "辛": "酉", "壬": "亥", "癸": "子",
}

# 将星 (年支/日支三合局帝旺位: 申子辰→子, 亥卯未→卯, 寅午戌→午, 巳酉丑→酉)
_JIANGXING: dict[str, str] = {
    "申": "子", "子": "子", "辰": "子",
    "亥": "卯", "卯": "卯", "未": "卯",
    "寅": "午", "午": "午", "戌": "午",
    "巳": "酉", "酉": "酉", "丑": "酉",
}

# 劫煞 (年支/日支三合局绝地: 申子辰→巳, 亥卯未→申, 寅午戌→亥, 巳酉丑→寅)
_JIESHA: dict[str, str] = {
    "申": "巳", "子": "巳", "辰": "巳",
    "亥": "申", "卯": "申", "未": "申",
    "寅": "亥", "午": "亥", "戌": "亥",
    "巳": "寅", "酉": "寅", "丑": "寅",
}

# 灾煞 (年支/日支三合局胎地: 申子辰→午, 亥卯未→酉, 寅午戌→子, 巳酉丑→卯)
_ZAISHA: dict[str, str] = {
    "申": "午", "子": "午", "辰": "午",
    "亥": "酉", "卯": "酉", "未": "酉",
    "寅": "子", "午": "子", "戌": "子",
    "巳": "卯", "酉": "卯", "丑": "卯",
}

def season_group(branch: str) -> str:
    """地支→季节组: 寅卯辰→春, 巳午未→夏, 申酉戌→秋, 亥子丑→冬"""
    seasons: dict[str, str] = {
        "寅": "spring", "卯": "spring", "辰": "spring",
        "巳": "summer", "午": "summer", "未": "summer",
        "申": "autumn", "酉": "autumn", "戌": "autumn",
        "亥": "winter", "子": "winter", "丑": "winter",
    }
    return seasons.get(branch, "")

# 孤辰 (季节组: 春→巳, 夏→申, 秋→亥, 冬→寅)
_GUCHEN: dict[str, str] = {
    "spring": "巳", "summer": "申", "autumn": "亥", "winter": "寅",
}

# 寡宿 (季节组: 春→丑, 夏→辰, 秋→未, 冬→戌)
_GUASU: dict[str, str] = {
    "spring": "丑", "summer": "辰", "autumn": "未", "winter": "戌",
}

# 红鸾 (年支: 子→卯, 丑→寅, 寅→丑, 卯→子, 辰→亥, 巳→戌, 午→酉, 未→申, 申→未, 酉→午, 戌→巳, 亥→辰)
_HONGLUAN: dict[str, str] = {
    "子": "卯", "丑": "寅", "寅": "丑", "卯": "子",
    "辰": "亥", "巳": "戌", "午": "酉", "未": "申",
    "申": "未", "酉": "午", "戌": "巳", "亥": "辰",
}

# 天喜 (年支: 红鸾对冲, 子→酉, 丑→申, ...)
_TIANXI: dict[str, str] = {
    "子": "酉", "丑": "申", "寅": "未", "卯": "午",
    "辰": "巳", "巳": "辰", "午": "卯", "未": "寅",
    "申": "丑", "酉": "子", "戌": "亥", "亥": "戌",
}

# 金舆 (日干: 甲→辰, 乙→巳, 丙→未, 丁→申, 戊→未, 己→申, 庚→戌, 辛→亥, 壬→丑, 癸→寅)
_JINYU: dict[str, str] = {
    "甲": "辰", "乙": "巳", "丙": "未", "丁": "申", "戊": "未",
    "己": "申", "庚": "戌", "辛": "亥", "壬": "丑", "癸": "寅",
}

# 太极贵人 (日干: 甲乙→子午, 丙丁→卯酉, 戊己→辰戌丑未, 庚辛→寅亥, 壬癸→巳申)
_TAIJI_GUIREN: dict[str, str] = {
    "甲": "子午", "乙": "子午",
    "丙": "卯酉", "丁": "卯酉",
    "戊": "辰戌丑未", "己": "辰戌丑未",
    "庚": "寅亥", "辛": "寅亥",
    "壬": "巳申", "癸": "巳申",
}

# 福星贵人 (日干: 甲→寅, 乙→丑, 丙→寅, 丁→酉, 戊→申, 己→未, 庚→午, 辛→巳, 壬→辰, 癸→卯)
_FUXING_GUIREN: dict[str, str] = {
    "甲": "寅", "乙": "丑", "丙": "寅", "丁": "酉", "戊": "申",
    "己": "未", "庚": "午", "辛": "巳", "壬": "辰", "癸": "卯",
}

# 魁罡 (特定干支: 庚辰, 庚戌, 壬辰, 戊戌)
_KUIGANG: set[str] = {"庚辰", "庚戌", "壬辰", "戊戌"}

# 学堂 (日干: 甲→亥, 乙→午, 丙→寅, 丁→酉, 戊→寅, 己→酉, 庚→巳, 辛→子, 壬→申, 癸→卯)
_XUETANG: dict[str, str] = {
    "甲": "亥", "乙": "午", "丙": "寅", "丁": "酉", "戊": "寅",
    "己": "酉", "庚": "巳", "辛": "子", "壬": "申", "癸": "卯",
}

# 词馆 (日干, 学堂对冲: 甲→巳, 乙→子, 丙→申, 丁→卯, ...)
_CIGUAN: dict[str, str] = {
    "甲": "巳", "乙": "子", "丙": "申", "丁": "卯", "戊": "申",
    "己": "卯", "庚": "亥", "辛": "午", "壬": "寅", "癸": "酉",
}


def shen_sha(year_branch: str, month_branch: str, day_stem: str, day_branch: str, pillar_branch: str) -> list[str]:
    """计算一支柱上的常用神煞列表。

    参数:
        year_branch: 年柱地支
        month_branch: 月柱地支
        day_stem: 日干
        day_branch: 日支
        pillar_branch: 当前柱地支

    返回: 命中的神煞名称列表(中文)。
    """
    result: list[str] = []

    # 天乙贵人: 日干/年干查, 地支匹配
    tianyi = _TIANYI_GUIREN.get(day_stem, "")
    if pillar_branch in tianyi:
        result.append("天乙贵人")

    # 文昌贵人: 日干查
    if _WENCHANG.get(day_stem) == pillar_branch:
        result.append("文昌贵人")

    # 桃花: 年支 & 日支查
    if _TAOHUA.get(year_branch) == pillar_branch:
        result.append("桃花")
    elif _TAOHUA.get(day_branch) == pillar_branch:
        result.append("桃花")

    # 驿马: 年支 & 日支查
    if _YIMA.get(year_branch) == pillar_branch:
        result.append("驿马")
    elif _YIMA.get(day_branch) == pillar_branch:
        result.append("驿马")

    # 华盖: 年支 & 日支查
    if _HUAGAI.get(year_branch) == pillar_branch:
        result.append("华盖")
    elif _HUAGAI.get(day_branch) == pillar_branch:
        result.append("华盖")

    # 羊刃: 日干查
    if _YANGREN.get(day_stem) == pillar_branch:
        result.append("羊刃")

    # 禄神: 日干查 (甲禄寅, 乙禄卯, ...)
    if _LUSHEN.get(day_stem) == pillar_branch:
        result.append("禄神")

    # 将星: 年支/日支查 (三合局帝旺位: 申子辰→子, 亥卯未→卯, 寅午戌→午, 巳酉丑→酉)
    if _JIANGXING.get(year_branch) == pillar_branch:
        result.append("将星")
    elif _JIANGXING.get(day_branch) == pillar_branch:
        result.append("将星")

    # 劫煞: 年支/日支查 (三合局绝地: 申子辰→巳, 亥卯未→申, 寅午戌→亥, 巳酉丑→寅)
    if _JIESHA.get(year_branch) == pillar_branch:
        result.append("劫煞")
    elif _JIESHA.get(day_branch) == pillar_branch:
        result.append("劫煞")

    # 灾煞: 年支/日支查 (三合局胎地: 申子辰→午, 亥卯未→酉, 寅午戌→子, 巳酉丑→卯)
    if _ZAISHA.get(year_branch) == pillar_branch:
        result.append("灾煞")
    elif _ZAISHA.get(day_branch) == pillar_branch:
        result.append("灾煞")

    # 孤辰: 季节查 (寅卯辰→巳, 巳午未→申, 申酉戌→亥, 亥子丑→寅)
    if _GUCHEN.get(season_group(year_branch)) == pillar_branch:
        result.append("孤辰")
    elif _GUCHEN.get(season_group(day_branch)) == pillar_branch:
        result.append("孤辰")

    # 寡宿: 季节查 (寅卯辰→丑, 巳午未→辰, 申酉戌→未, 亥子丑→戌)
    if _GUASU.get(season_group(year_branch)) == pillar_branch:
        result.append("寡宿")
    elif _GUASU.get(season_group(day_branch)) == pillar_branch:
        result.append("寡宿")

    # 红鸾: 年支查
    if _HONGLUAN.get(year_branch) == pillar_branch:
        result.append("红鸾")

    # 天喜: 年支查 (红鸾对冲)
    if _TIANXI.get(year_branch) == pillar_branch:
        result.append("天喜")

    # 金舆: 日干查
    if _JINYU.get(day_stem) == pillar_branch:
        result.append("金舆")

    # 太极贵人: 日干+年干查
    if pillar_branch in _TAIJI_GUIREN.get(day_stem, ""):
        result.append("太极贵人")

    # 福星贵人: 日干查支
    if _FUXING_GUIREN.get(day_stem) == pillar_branch:
        result.append("福星贵人")

    # 学堂: 日干查
    if _XUETANG.get(day_stem) == pillar_branch:
        result.append("学堂")

    # 词馆: 日干查 (学堂对冲)
    if _CIGUAN.get(day_stem) == pillar_branch:
        result.append("词馆")

    return sorted(set(result))  # 去重排序


def shen_sha_for_pillar(
    year_branch: str, month_branch: str, day_stem: str, day_branch: str,
    pillar_stem: str, pillar_branch: str,
) -> list[str]:
    """完整版神煞: 包含需要天干匹配的神煞(天德/月德)。

    参数:
        year_branch, month_branch, day_stem, day_branch: 四柱参照
        pillar_stem: 当前柱天干(用于天德/月德匹配)
        pillar_branch: 当前柱地支

    返回: 命中的神煞名称列表(含天干相关)。
    """
    result = shen_sha(year_branch, month_branch, day_stem, day_branch, pillar_branch)

    # 天德: 月支定天干, 当前柱天干匹配
    tian_de_stem = _TIANDE.get(month_branch, "")
    if pillar_stem in tian_de_stem:
        result.append("天德")

    # 月德: 月支定天干, 当前柱天干匹配
    yue_de_stem = _YUEDE.get(month_branch, "")
    if pillar_stem in yue_de_stem:
        result.append("月德")

    # 魁罡: 特定干支组合 (庚辰/庚戌/壬辰/戊戌), 需天干+地支联合判断
    if pillar_stem + pillar_branch in _KUIGANG:
        result.append("魁罡")

    return sorted(set(result))
