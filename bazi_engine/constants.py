# -*- coding: utf-8 -*-
"""干支、五行、藏干、十神基础常量。

藏干表与十神表对齐已发布来源 lunar-python 1.4.8 (6tail/LunarUtil)，
顺序为 本气/中气/余气。该表属拍板项2范围，命理顾问签字前标注"待签字"。
"""

STEMS = "甲乙丙丁戊己庚辛壬癸"          # 天干,索引0-9
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"    # 地支,索引0-11

# 天干五行/阴阳 (索引对应 STEMS)
STEM_ELEMENT = ["wood", "wood", "fire", "fire", "earth",
                "earth", "metal", "metal", "water", "water"]
STEM_YANG = [True, False, True, False, True, False, True, False, True, False]

# 地支本气五行 (索引对应 BRANCHES)
BRANCH_ELEMENT = ["water", "earth", "wood", "wood", "earth", "fire",
                  "fire", "earth", "metal", "metal", "earth", "water"]

# 地支藏干表 (本气/中气/余气) —— 对齐 lunar-python LunarUtil.ZHI_HIDE_GAN
HIDDEN_STEMS = {
    "子": ["癸"],
    "丑": ["己", "癸", "辛"],
    "寅": ["甲", "丙", "戊"],
    "卯": ["乙"],
    "辰": ["戊", "乙", "癸"],
    "巳": ["丙", "庚", "戊"],
    "午": ["丁", "己"],
    "未": ["己", "丁", "乙"],
    "申": ["庚", "壬", "戊"],
    "酉": ["辛"],
    "戌": ["戊", "辛", "丁"],
    "亥": ["壬", "甲"],
}

# 五行相生: 生我者 (element -> 生它的element)
GENERATES = {"wood": "fire", "fire": "earth", "earth": "metal",
             "metal": "water", "water": "wood"}
# 五行相克: 我克者
CONTROLS = {"wood": "earth", "earth": "water", "water": "fire",
            "fire": "metal", "metal": "wood"}

ELEMENTS = ["wood", "fire", "earth", "metal", "water"]


def ten_god(day_stem: str, other_stem: str) -> str:
    """以日干为基准判定 other_stem 的十神(中文原术语)。"""
    di, oi = STEMS.index(day_stem), STEMS.index(other_stem)
    de, oe = STEM_ELEMENT[di], STEM_ELEMENT[oi]
    same_polarity = STEM_YANG[di] == STEM_YANG[oi]
    if oe == de:
        return "比肩" if same_polarity else "劫财"
    if GENERATES[de] == oe:          # 我生
        return "食神" if same_polarity else "伤官"
    if CONTROLS[de] == oe:           # 我克
        return "偏财" if same_polarity else "正财"
    if CONTROLS[oe] == de:           # 克我
        return "七杀" if same_polarity else "正官"
    # 生我
    return "偏印" if same_polarity else "正印"


# 十神 -> 五类功能组(以日主为参照的五行生克角色)。
# peer=同我(比劫) / output=我生(食伤) / wealth=我克(财) / authority=克我(官杀) / resource=生我(印)。
# 用于 career 五组计数与十神互动关系判定(09号 FullChartData, 选取/关系规则v1.0 待会签)。
TEN_GOD_CATEGORY = {
    "比肩": "peer", "劫财": "peer",
    "食神": "output", "伤官": "output",
    "偏财": "wealth", "正财": "wealth",
    "七杀": "authority", "正官": "authority",
    "偏印": "resource", "正印": "resource",
}

# 节(月界)在 sxtwl 节气序号(冬至=0)中的位置: 小寒1,立春3,惊蛰5...大雪23
JIE_INDICES = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23]
# 节 -> 月支: 立春(3)->寅(2), 惊蛰(5)->卯(3) ... 小寒(1)->丑(1)
JIE_TO_MONTH_BRANCH = {3: 2, 5: 3, 7: 4, 9: 5, 11: 6, 13: 7,
                       15: 8, 17: 9, 19: 10, 21: 11, 23: 0, 1: 1}
JIE_NAMES = {1: "小寒", 3: "立春", 5: "惊蛰", 7: "清明", 9: "立夏", 11: "芒种",
             13: "小暑", 15: "立秋", 17: "白露", 19: "寒露", 21: "立冬", 23: "大雪"}
