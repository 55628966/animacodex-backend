"""
六爻 (Liu Yao) 占卜引擎 — 全部确定性计算

本模块实现六爻占卜的全部确定性计算层。
输出为机器可读结构，不生成面向用户的解读文本。
解读文本由人工/后续系统基于本模块输出补充。

核心链路：起卦 → 定卦名/宫/世应 → 纳甲 → 定六亲 → 安六兽 → 变卦 → 旬空 → 伏神 → 用神判定 → 旺衰分析

Author: Anima Codex core engine
"""

from dataclasses import dataclass, field
from enum import Enum
import random
from typing import Optional


# ══════════════════════════════════════════════
# 基础枚举
# ══════════════════════════════════════════════

class Wuxing(Enum):
    WOOD = "木"
    FIRE = "火"
    EARTH = "土"
    METAL = "金"
    WATER = "水"


class Stem(Enum):
    JIA = "甲"
    YI = "乙"
    BING = "丙"
    DING = "丁"
    WU = "戊"
    JI = "己"
    GENG = "庚"
    XIN = "辛"
    REN = "壬"
    GUI = "癸"


class Branch(Enum):
    ZI = "子"
    CHOU = "丑"
    YIN = "寅"
    MAO = "卯"
    CHEN = "辰"
    SI = "巳"
    WU = "午"
    WEI = "未"
    SHEN = "申"
    YOU = "酉"
    XU = "戌"
    HAI = "亥"


class Trigram(Enum):
    QIAN = "乾"
    DUI = "兑"
    LI = "离"
    ZHEN = "震"
    XUN = "巽"
    KAN = "坎"
    GEN = "艮"
    KUN = "坤"


class LineType(Enum):
    SHAO_YANG = "少阳"       # 阳爻，不变
    SHAO_YIN = "少阴"        # 阴爻，不变
    LAO_YANG = "老阳"        # 阳爻，变阴
    LAO_YIN = "老阴"         # 阴爻，变阳


class SixRelation(Enum):
    PARENTS = "父母"          # 生我者
    OFFICER = "官鬼"          # 克我者
    SIBLINGS = "兄弟"         # 同我者
    CHILDREN = "子孙"         # 我生者
    WEALTH = "妻财"           # 我克者


class SixAnimal(Enum):
    AZURE_DRAGON = "青龙"
    VERMILION_BIRD = "朱雀"
    HOOK_SERPENT = "勾陈"
    SOARING_SNAKE = "螣蛇"
    WHITE_TIGER = "白虎"
    BLACK_TORTOISE = "玄武"


# ══════════════════════════════════════════════
# 查表数据
# ══════════════════════════════════════════════

# 地支 → 五行
BRANCH_WUXING: dict[Branch, Wuxing] = {
    Branch.ZI: Wuxing.WATER,   Branch.CHOU: Wuxing.EARTH,
    Branch.YIN: Wuxing.WOOD,   Branch.MAO: Wuxing.WOOD,
    Branch.CHEN: Wuxing.EARTH, Branch.SI: Wuxing.FIRE,
    Branch.WU: Wuxing.FIRE,    Branch.WEI: Wuxing.EARTH,
    Branch.SHEN: Wuxing.METAL, Branch.YOU: Wuxing.METAL,
    Branch.XU: Wuxing.EARTH,   Branch.HAI: Wuxing.WATER,
}

# 八卦 → 五行（宫五行）
TRIGRAM_WUXING: dict[Trigram, Wuxing] = {
    Trigram.QIAN: Wuxing.METAL, Trigram.DUI: Wuxing.METAL,
    Trigram.LI: Wuxing.FIRE,    Trigram.ZHEN: Wuxing.WOOD,
    Trigram.XUN: Wuxing.WOOD,   Trigram.KAN: Wuxing.WATER,
    Trigram.GEN: Wuxing.EARTH,  Trigram.KUN: Wuxing.EARTH,
}

# 八卦 → 纳天干
TRIGRAM_STEM: dict[Trigram, list[Stem]] = {
    Trigram.QIAN: [Stem.JIA, Stem.REN],
    Trigram.KUN: [Stem.YI, Stem.GUI],
    Trigram.ZHEN: [Stem.GENG],
    Trigram.XUN: [Stem.XIN],
    Trigram.KAN: [Stem.WU],
    Trigram.LI: [Stem.JI],
    Trigram.GEN: [Stem.BING],
    Trigram.DUI: [Stem.DING],
}

# 八卦 → 纳地支（每条爻对应的地支，初爻到上爻）
# 阳卦：逆行（子寅辰午申戌循环，起点不同）
# 阴卦：顺行（未巳卯丑亥酉循环，起点不同）
TRIGRAM_BRANCHES: dict[Trigram, list[Branch]] = {
    # 阳卦（逆行，两爻一跳）
    Trigram.QIAN: [Branch.ZI, Branch.YIN, Branch.CHEN,
                   Branch.WU, Branch.SHEN, Branch.XU],
    Trigram.ZHEN: [Branch.ZI, Branch.YIN, Branch.CHEN,
                   Branch.WU, Branch.SHEN, Branch.XU],
    Trigram.KAN:  [Branch.YIN, Branch.CHEN, Branch.WU,
                   Branch.SHEN, Branch.XU, Branch.ZI],
    Trigram.GEN:  [Branch.CHEN, Branch.WU, Branch.SHEN,
                   Branch.XU, Branch.ZI, Branch.YIN],
    # 阴卦（顺行）
    Trigram.KUN:  [Branch.WEI, Branch.SI, Branch.MAO,
                   Branch.CHOU, Branch.HAI, Branch.YOU],
    Trigram.XUN:  [Branch.CHOU, Branch.HAI, Branch.YOU,
                   Branch.WEI, Branch.SI, Branch.MAO],
    Trigram.LI:   [Branch.MAO, Branch.CHOU, Branch.HAI,
                   Branch.YOU, Branch.WEI, Branch.SI],
    Trigram.DUI:  [Branch.SI, Branch.MAO, Branch.CHOU,
                   Branch.HAI, Branch.YOU, Branch.WEI],
}

# 64卦 → (卦名, 卦宫, 宫位1-8, 内卦, 外卦)
# 宫位: 1=八纯, 2=一世, 3=二世, 4=三世, 5=四世, 6=五世, 7=游魂, 8=归魂
# 世爻位置: 宫1→6爻, 宫2→1爻, 宫3→2爻, 宫4→3爻, 宫5→4爻, 宫6→5爻, 宫7→4爻, 宫8→3爻
# 应爻: (世爻+2)%6+1 (间隔两位)
_HEXAGRAM_TABLE: dict[int, tuple[str, Trigram, int, Trigram, Trigram]] = {
    # 乾宫
    1:  ("乾为天", Trigram.QIAN, 1, Trigram.QIAN, Trigram.QIAN),
    44: ("天风姤", Trigram.QIAN, 2, Trigram.XUN, Trigram.QIAN),
    33: ("天山遁", Trigram.QIAN, 3, Trigram.GEN, Trigram.QIAN),
    12: ("天地否", Trigram.QIAN, 4, Trigram.KUN, Trigram.QIAN),
    20: ("风地观", Trigram.QIAN, 5, Trigram.KUN, Trigram.XUN),
    23: ("山地剥", Trigram.QIAN, 6, Trigram.KUN, Trigram.GEN),
    35: ("火地晋", Trigram.QIAN, 7, Trigram.KUN, Trigram.LI),
    14: ("火天大有", Trigram.QIAN, 8, Trigram.QIAN, Trigram.LI),
    # 兑宫
    58: ("兑为泽", Trigram.DUI, 1, Trigram.DUI, Trigram.DUI),
    47: ("泽水困", Trigram.DUI, 2, Trigram.KAN, Trigram.DUI),
    45: ("泽地萃", Trigram.DUI, 3, Trigram.KUN, Trigram.DUI),
    31: ("泽山咸", Trigram.DUI, 4, Trigram.GEN, Trigram.DUI),
    39: ("水山蹇", Trigram.DUI, 5, Trigram.GEN, Trigram.KAN),
    15: ("地山谦", Trigram.DUI, 6, Trigram.GEN, Trigram.KUN),
    62: ("雷山小过", Trigram.DUI, 7, Trigram.GEN, Trigram.ZHEN),
    54: ("雷泽归妹", Trigram.DUI, 8, Trigram.DUI, Trigram.ZHEN),
    # 离宫
    30: ("离为火", Trigram.LI, 1, Trigram.LI, Trigram.LI),
    56: ("火山旅", Trigram.LI, 2, Trigram.GEN, Trigram.LI),
    50: ("火风鼎", Trigram.LI, 3, Trigram.XUN, Trigram.LI),
    64: ("火水未济", Trigram.LI, 4, Trigram.KAN, Trigram.LI),
    4:  ("山水蒙", Trigram.LI, 5, Trigram.KAN, Trigram.GEN),
    59: ("风水涣", Trigram.LI, 6, Trigram.KAN, Trigram.XUN),
    6:  ("天水讼", Trigram.LI, 7, Trigram.KAN, Trigram.QIAN),
    13: ("天火同人", Trigram.LI, 8, Trigram.LI, Trigram.QIAN),
    # 震宫
    51: ("震为雷", Trigram.ZHEN, 1, Trigram.ZHEN, Trigram.ZHEN),
    16: ("雷地豫", Trigram.ZHEN, 2, Trigram.KUN, Trigram.ZHEN),
    40: ("雷水解", Trigram.ZHEN, 3, Trigram.KAN, Trigram.ZHEN),
    32: ("雷风恒", Trigram.ZHEN, 4, Trigram.XUN, Trigram.ZHEN),
    46: ("地风升", Trigram.ZHEN, 5, Trigram.XUN, Trigram.KUN),
    48: ("水风井", Trigram.ZHEN, 6, Trigram.XUN, Trigram.KAN),
    28: ("泽风大过", Trigram.ZHEN, 7, Trigram.XUN, Trigram.DUI),
    17: ("泽雷随", Trigram.ZHEN, 8, Trigram.ZHEN, Trigram.DUI),
    # 巽宫
    57: ("巽为风", Trigram.XUN, 1, Trigram.XUN, Trigram.XUN),
    9:  ("风天小畜", Trigram.XUN, 2, Trigram.QIAN, Trigram.XUN),
    37: ("风火家人", Trigram.XUN, 3, Trigram.LI, Trigram.XUN),
    42: ("风雷益", Trigram.XUN, 4, Trigram.ZHEN, Trigram.XUN),
    25: ("天雷无妄", Trigram.XUN, 5, Trigram.ZHEN, Trigram.QIAN),
    21: ("火雷噬嗑", Trigram.XUN, 6, Trigram.ZHEN, Trigram.LI),
    27: ("山雷颐", Trigram.XUN, 7, Trigram.ZHEN, Trigram.GEN),
    18: ("山风蛊", Trigram.XUN, 8, Trigram.XUN, Trigram.GEN),
    # 坎宫
    29: ("坎为水", Trigram.KAN, 1, Trigram.KAN, Trigram.KAN),
    60: ("水泽节", Trigram.KAN, 2, Trigram.DUI, Trigram.KAN),
    3:  ("水雷屯", Trigram.KAN, 3, Trigram.ZHEN, Trigram.KAN),
    63: ("水火既济", Trigram.KAN, 4, Trigram.LI, Trigram.KAN),
    49: ("泽火革", Trigram.KAN, 5, Trigram.LI, Trigram.DUI),
    55: ("雷火丰", Trigram.KAN, 6, Trigram.LI, Trigram.ZHEN),
    36: ("地火明夷", Trigram.KAN, 7, Trigram.LI, Trigram.KUN),
    7:  ("地水师", Trigram.KAN, 8, Trigram.KAN, Trigram.KUN),
    # 艮宫
    52: ("艮为山", Trigram.GEN, 1, Trigram.GEN, Trigram.GEN),
    22: ("山火贲", Trigram.GEN, 2, Trigram.LI, Trigram.GEN),
    26: ("山天大畜", Trigram.GEN, 3, Trigram.QIAN, Trigram.GEN),
    41: ("山泽损", Trigram.GEN, 4, Trigram.DUI, Trigram.GEN),
    38: ("火泽睽", Trigram.GEN, 5, Trigram.DUI, Trigram.LI),
    10: ("天泽履", Trigram.GEN, 6, Trigram.DUI, Trigram.QIAN),
    61: ("风泽中孚", Trigram.GEN, 7, Trigram.DUI, Trigram.XUN),
    53: ("风山渐", Trigram.GEN, 8, Trigram.GEN, Trigram.XUN),
    # 坤宫
    2:  ("坤为地", Trigram.KUN, 1, Trigram.KUN, Trigram.KUN),
    24: ("地雷复", Trigram.KUN, 2, Trigram.ZHEN, Trigram.KUN),
    19: ("地泽临", Trigram.KUN, 3, Trigram.DUI, Trigram.KUN),
    11: ("地天泰", Trigram.KUN, 4, Trigram.QIAN, Trigram.KUN),
    34: ("雷天大壮", Trigram.KUN, 5, Trigram.QIAN, Trigram.ZHEN),
    43: ("泽天夬", Trigram.KUN, 6, Trigram.QIAN, Trigram.DUI),
    5:  ("水天需", Trigram.KUN, 7, Trigram.QIAN, Trigram.KAN),
    8:  ("水地比", Trigram.KUN, 8, Trigram.KUN, Trigram.KAN),
}

# 世爻位置: 宫位 → 世爻位置(1-6)
SHI_POSITION: dict[int, int] = {1: 6, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 4, 8: 3}

# 六兽顺序
ANIMAL_SEQUENCE = [
    SixAnimal.AZURE_DRAGON,
    SixAnimal.VERMILION_BIRD,
    SixAnimal.HOOK_SERPENT,
    SixAnimal.SOARING_SNAKE,
    SixAnimal.WHITE_TIGER,
    SixAnimal.BLACK_TORTOISE,
]

# 日干 → 初爻起始神兽
DAY_STEM_ANIMAL_START: dict[Stem, int] = {
    Stem.JIA: 0, Stem.YI: 0,      # 甲乙日 → 青龙起
    Stem.BING: 1, Stem.DING: 1,    # 丙丁日 → 朱雀起
    Stem.WU: 2,                    # 戊日 → 勾陈起
    Stem.JI: 3,                    # 己日 → 螣蛇起
    Stem.GENG: 4, Stem.XIN: 4,    # 庚辛日 → 白虎起
    Stem.REN: 5, Stem.GUI: 5,     # 壬癸日 → 玄武起
}

# 60甲子表
SEXAGENARY: list[tuple[Stem, Branch]] = [
    (Stem.JIA, Branch.ZI), (Stem.YI, Branch.CHOU), (Stem.BING, Branch.YIN),
    (Stem.DING, Branch.MAO), (Stem.WU, Branch.CHEN), (Stem.JI, Branch.SI),
    (Stem.GENG, Branch.WU), (Stem.XIN, Branch.WEI), (Stem.REN, Branch.SHEN),
    (Stem.GUI, Branch.YOU), (Stem.JIA, Branch.XU), (Stem.YI, Branch.HAI),
    (Stem.BING, Branch.ZI), (Stem.DING, Branch.CHOU), (Stem.WU, Branch.YIN),
    (Stem.JI, Branch.MAO), (Stem.GENG, Branch.CHEN), (Stem.XIN, Branch.SI),
    (Stem.REN, Branch.WU), (Stem.GUI, Branch.WEI), (Stem.JIA, Branch.SHEN),
    (Stem.YI, Branch.YOU), (Stem.BING, Branch.XU), (Stem.DING, Branch.HAI),
    (Stem.WU, Branch.ZI), (Stem.JI, Branch.CHOU), (Stem.GENG, Branch.YIN),
    (Stem.XIN, Branch.MAO), (Stem.REN, Branch.CHEN), (Stem.GUI, Branch.SI),
    (Stem.JIA, Branch.WU), (Stem.YI, Branch.WEI), (Stem.BING, Branch.SHEN),
    (Stem.DING, Branch.YOU), (Stem.WU, Branch.XU), (Stem.JI, Branch.HAI),
    (Stem.GENG, Branch.ZI), (Stem.XIN, Branch.CHOU), (Stem.REN, Branch.YIN),
    (Stem.GUI, Branch.MAO), (Stem.JIA, Branch.CHEN), (Stem.YI, Branch.SI),
    (Stem.BING, Branch.WU), (Stem.DING, Branch.WEI), (Stem.WU, Branch.SHEN),
    (Stem.JI, Branch.YOU), (Stem.GENG, Branch.XU), (Stem.XIN, Branch.HAI),
    (Stem.REN, Branch.ZI), (Stem.GUI, Branch.CHOU), (Stem.JIA, Branch.YIN),
    (Stem.YI, Branch.MAO), (Stem.BING, Branch.CHEN), (Stem.DING, Branch.SI),
    (Stem.WU, Branch.WU), (Stem.JI, Branch.WEI), (Stem.GENG, Branch.SHEN),
    (Stem.XIN, Branch.YOU), (Stem.REN, Branch.XU), (Stem.GUI, Branch.HAI),
]

# 地支六合
BRANCH_COMBINE: dict[Branch, Branch] = {
    Branch.ZI: Branch.CHOU, Branch.CHOU: Branch.ZI,
    Branch.YIN: Branch.HAI, Branch.HAI: Branch.YIN,
    Branch.MAO: Branch.XU, Branch.XU: Branch.MAO,
    Branch.CHEN: Branch.YOU, Branch.YOU: Branch.CHEN,
    Branch.SI: Branch.SHEN, Branch.SHEN: Branch.SI,
    Branch.WU: Branch.WEI, Branch.WEI: Branch.WU,
}

# 地支六冲
BRANCH_CLASH: dict[Branch, Branch] = {
    Branch.ZI: Branch.WU, Branch.WU: Branch.ZI,
    Branch.CHOU: Branch.WEI, Branch.WEI: Branch.CHOU,
    Branch.YIN: Branch.SHEN, Branch.SHEN: Branch.YIN,
    Branch.MAO: Branch.YOU, Branch.YOU: Branch.MAO,
    Branch.CHEN: Branch.XU, Branch.XU: Branch.CHEN,
    Branch.SI: Branch.HAI, Branch.HAI: Branch.SI,
}

# 五行生克关系
WUXING_GENERATES: dict[Wuxing, Wuxing] = {
    Wuxing.WOOD: Wuxing.FIRE, Wuxing.FIRE: Wuxing.EARTH,
    Wuxing.EARTH: Wuxing.METAL, Wuxing.METAL: Wuxing.WATER,
    Wuxing.WATER: Wuxing.WOOD,
}

WUXING_CONTROLS: dict[Wuxing, Wuxing] = {
    Wuxing.WOOD: Wuxing.EARTH, Wuxing.EARTH: Wuxing.WATER,
    Wuxing.WATER: Wuxing.FIRE, Wuxing.FIRE: Wuxing.METAL,
    Wuxing.METAL: Wuxing.WOOD,
}

# 六亲判定：（爻五行，宫五行）→ 六亲
def _determine_relation(line_wx: Wuxing, palace_wx: Wuxing) -> SixRelation:
    """根据爻五行和宫五行的生克关系判定六亲"""
    if line_wx == palace_wx:
        return SixRelation.SIBLINGS  # 同我者兄弟
    if WUXING_GENERATES.get(line_wx) == palace_wx:
        return SixRelation.PARENTS   # 生我者父母
    if WUXING_CONTROLS.get(line_wx) == palace_wx:
        return SixRelation.OFFICER   # 克我者官鬼
    if WUXING_GENERATES.get(palace_wx) == line_wx:
        return SixRelation.CHILDREN  # 我生者子孙
    return SixRelation.WEALTH        # 我克者妻财


# ══════════════════════════════════════════════
# 核心数据结构
# ══════════════════════════════════════════════

@dataclass
class YaoLine:
    """一条爻"""
    position: int           # 1-6，初爻=1，上爻=6
    branch: Branch          # 纳甲地支
    stem: Stem              # 纳甲天干
    relation: SixRelation   # 六亲
    animal: SixAnimal       # 六兽
    line_type: LineType     # 爻的类型
    is_shi: bool = False    # 是世爻
    is_ying: bool = False   # 是应爻
    is_void: bool = False   # 旬空
    hidden_relation: Optional[SixRelation] = None  # 伏神六亲
    changed_to: Optional['YaoLine'] = None  # 变卦对应爻

    @property
    def is_moving(self) -> bool:
        return self.line_type in (LineType.LAO_YANG, LineType.LAO_YIN)

    @property
    def is_yang(self) -> bool:
        return self.line_type in (LineType.SHAO_YANG, LineType.LAO_YANG)

    @property
    def is_yin(self) -> bool:
        return not self.is_yang

    @property
    def element(self) -> Wuxing:
        return BRANCH_WUXING[self.branch]


@dataclass
class LiuYaoResult:
    """六爻占卜完整结果"""
    number: int                     # 卦序号 1-64
    name_cn: str                    # 卦名
    palace: Trigram                 # 卦宫
    palace_wx: Wuxing              # 宫五行
    lines: list[YaoLine]            # 本卦六爻
    bian_gua_lines: list[YaoLine] | None  # 变卦六爻（无动爻则为None）
    shi_position: int               # 世爻位置
    ying_position: int              # 应爻位置
    day_stem: Stem                  # 起卦日天干
    day_branch: Branch              # 起卦日地支
    yongshen: Optional[SixRelation]  # 用神
    yongshen_strength: Optional[str] = None  # 用神旺衰："旺"/"平"/"衰"

    # 旬空
    void_branches: list[Branch] = field(default_factory=list)

    # 本宫纯卦伏神
    hidden_lines: list[Optional[SixRelation]] = field(default_factory=list)

    # 起卦元数据
    cast_method: str = "coin"       # coin | manual | time
    question_domain: Optional[str] = None  # wealth/career/health/relationship...


# ══════════════════════════════════════════════
# 计算函数
# ══════════════════════════════════════════════

def _hexagram_number_from_lines(line_types: list[LineType]) -> int:
    """六条爻 → 卦序号（六位二进制）"""
    # 初爻=bit0, 上爻=bit5; 阳=1, 阴=0
    num = 0
    for i, lt in enumerate(line_types):
        if lt in (LineType.SHAO_YANG, LineType.LAO_YANG):
            num |= (1 << i)
    return num + 1  # 1-based


def _cast_coins() -> list[LineType]:
    """铜钱起卦：三枚铜钱掷六次"""
    # 概率分布: 老阳1/8, 少阴3/8, 少阳3/8, 老阴1/8
    # heads=0: 三反→老阳, heads=1: 一反两正→少阴
    # heads=2: 一正两反→少阳, heads=3: 三正→老阴
    def throw():
        h = sum(1 for _ in range(3) if random.random() < 0.5)
        if h == 0: return LineType.LAO_YANG
        if h == 1: return LineType.SHAO_YIN
        if h == 2: return LineType.SHAO_YANG
        return LineType.LAO_YIN

    return [throw() for _ in range(6)]


def _get_trigram(line_types: list[LineType], is_outer: bool) -> Trigram:
    """三条爻 → 八卦"""
    start = 3 if is_outer else 0
    num = 0
    for i in range(3):
        lt = line_types[start + i]
        if lt in (LineType.SHAO_YANG, LineType.LAO_YANG):
            num |= (1 << i)
    mapping = {
        0: Trigram.KUN, 1: Trigram.ZHEN, 2: Trigram.KAN, 3: Trigram.DUI,
        4: Trigram.GEN, 5: Trigram.LI, 6: Trigram.XUN, 7: Trigram.QIAN,
    }
    return mapping[num]


def _compute_void_branches(day_stem: Stem, day_branch: Branch) -> list[Branch]:
    """日干支 → 旬空二支"""
    # 找到日干支在60甲子中的位置
    for idx, (s, b) in enumerate(SEXAGENARY):
        if s == day_stem and b == day_branch:
            dec = idx // 10  # 旬序
            void_idx = (dec + 1) * 10 - 1
            if void_idx >= 60: void_idx -= 60
            # 旬空是甲子旬中缺的两个地支
            start = dec * 10
            present = {SEXAGENARY[i][1] for i in range(start, start + 10)}
            all_branches = list(Branch)
            return [b for b in all_branches if b not in present][:2]
    return []


def _compute_hidden_lines(lines: list[YaoLine], palace: Trigram) -> list[Optional[SixRelation]]:
    """伏神：本宫纯卦中，本卦缺失的六亲"""
    present_relations = {line.relation for line in lines}
    pure_branches = TRIGRAM_BRANCHES[palace]
    pure_wx = TRIGRAM_WUXING[palace]
    result: list[Optional[SixRelation]] = []
    for i, branch in enumerate(pure_branches):
        wx = BRANCH_WUXING[branch]
        relation = _determine_relation(wx, pure_wx)
        result.append(relation if relation not in present_relations else None)
    return result


def _determine_yongshen(question_domain: Optional[str]) -> SixRelation:
    """根据问题域判定用神"""
    if not question_domain:
        return SixRelation.OFFICER
    domain = question_domain.lower()
    if any(w in domain for w in ['money', 'wealth', 'finance', 'investment', 'financial', '财']):
        return SixRelation.WEALTH
    if any(w in domain for w in ['career', 'job', 'work', 'promotion', '事业', '工作']):
        return SixRelation.OFFICER
    if any(w in domain for w in ['health', 'study', 'exam', 'school', '学业', '考试', '健康']):
        return SixRelation.PARENTS
    if any(w in domain for w in ['relationship', 'love', 'marriage', 'partner', '感情', '婚姻']):
        return SixRelation.WEALTH
    if any(w in domain for w in ['children', 'creative', 'start', 'project', '子嗣', '创意']):
        return SixRelation.CHILDREN
    if any(w in domain for w in ['partner', 'business', 'collaboration', '合作']):
        return SixRelation.SIBLINGS
    return SixRelation.OFFICER


def _assess_strength(result: LiuYaoResult) -> str:
    """用神旺衰分析——传统六爻标准"""
    if result.yongshen is None:
        return "平"

    # 找到用神爻（优先不用神的爻）
    ys_line = None
    for line in result.lines:
        if line.relation == result.yongshen:
            ys_line = line
            if not line.is_void:
                break  # 优先取不旬空的爻
    if ys_line is None:
        return "衰"  # 用神不上卦

    score = 0
    ys_wx = ys_line.element
    moon_wx = BRANCH_WUXING[result.day_branch]  # 简化：日用月
    day_wx = BRANCH_WUXING[result.day_branch]

    # 月建：同我者当令最旺
    if moon_wx == ys_wx:
        score += 3  # 当令
    elif WUXING_GENERATES.get(moon_wx) == ys_wx:
        score += 2  # 月生
    elif WUXING_CONTROLS.get(moon_wx) == ys_wx:
        score -= 2  # 月克

    # 日辰：生扶或同五行
    if day_wx == ys_wx:
        score += 2  # 临日
    elif WUXING_GENERATES.get(day_wx) == ys_wx:
        score += 1  # 日生

    # 动爻生克
    for line in result.lines:
        if line.is_moving and line != ys_line:
            if WUXING_GENERATES.get(line.element) == ys_wx:
                score += 1  # 动爻来生
            elif WUXING_CONTROLS.get(line.element) == ys_wx:
                score -= 1  # 动爻来克

    # 旬空（空亡）
    if ys_line.is_void:
        score -= 4  # 旬空大凶

    # 月破（月冲）
    if BRANCH_CLASH.get(ys_line.branch) == result.day_branch:
        score -= 3

    # 日冲暗动：静爻被日辰冲 → 暗动（小吉）
    if not ys_line.is_moving and BRANCH_CLASH.get(ys_line.branch) == result.day_branch:
        score += 1

    if score >= 3:
        return "旺"
    if score <= -2:
        return "衰"
    return "平"


# ══════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════

def cast_hexagram(
    method: str = "coin",
    question_domain: Optional[str] = None,
    day_stem: Optional[Stem] = None,
    day_branch: Optional[Branch] = None,
    manual_lines: Optional[list[LineType]] = None,
) -> LiuYaoResult:
    """
    起卦并完成全部确定性计算。

    Args:
        method: 起卦方式 "coin" | "manual" | "time"
        question_domain: 问题域（用于用神判定）
        day_stem: 起卦日天干（默认用今日）
        day_branch: 起卦日地支（默认用今日）
        manual_lines: 手动指定的六爻（仅 method="manual" 时有效）

    Returns:
        LiuYaoResult: 完整的卦象数据
    """

    # 1. 起卦
    if method == "manual" and manual_lines and len(manual_lines) == 6:
        line_types = list(manual_lines)
    else:
        line_types = _cast_coins()

    # 2. 日干支（默认用今天）
    if day_stem is None or day_branch is None:
        import datetime
        today = datetime.date.today()
        # 简化的日干支计算（使用已知基准：2026-07-20 = 乙未日）
        # 实际项目应使用 lunar-python 或 sxtwl 获取精确日干支
        ref_date = datetime.date(2026, 7, 20)
        ref_sb = SEXAGENARY.index((Stem.YI, Branch.WEI))
        diff = (today - ref_date).days
        idx = (ref_sb + diff) % 60
        day_stem, day_branch = SEXAGENARY[idx]

    # 3. 定卦名/宫/世应
    number = _hexagram_number_from_lines(line_types)
    name_cn, palace, palace_pos, inner_t, outer_t = _HEXAGRAM_TABLE[number]
    palace_wx = TRIGRAM_WUXING[palace]
    shi_pos = SHI_POSITION[palace_pos]
    ying_pos = ((shi_pos - 1 + 3) % 6) + 1

    # 4. 纳甲 + 六亲 + 六兽
    day_animal_start = DAY_STEM_ANIMAL_START.get(day_stem, 0)
    lines = []
    for pos in range(6):
        # 确定内卦还是外卦
        trigram = inner_t if pos < 3 else outer_t
        # 纳地支
        branch = TRIGRAM_BRANCHES[trigram][pos]
        # 纳天干
        stems = TRIGRAM_STEM[trigram]
        stem = stems[0] if pos < 3 or len(stems) < 2 else stems[1]
        # 六亲
        wx = BRANCH_WUXING[branch]
        relation = _determine_relation(wx, palace_wx)
        # 六兽
        animal_idx = (day_animal_start + pos) % 6
        animal = ANIMAL_SEQUENCE[animal_idx]
        # 爻类型
        lt = line_types[pos]

        line = YaoLine(
            position=pos + 1,
            branch=branch,
            stem=stem,
            relation=relation,
            animal=animal,
            line_type=lt,
            is_shi=(pos + 1 == shi_pos),
            is_ying=(pos + 1 == ying_pos),
        )
        lines.append(line)

    # 5. 旬空
    void_branches = _compute_void_branches(day_stem, day_branch)
    for line in lines:
        if line.branch in void_branches:
            line.is_void = True

    # 6. 变卦
    moving_positions = [i for i, lt in enumerate(line_types)
                        if lt in (LineType.LAO_YANG, LineType.LAO_YIN)]
    bian_gua_lines = None
    if moving_positions:
        # 生成本卦动爻翻转变卦
        changed_line_types = []
        for lt in line_types:
            if lt == LineType.LAO_YANG:
                changed_line_types.append(LineType.SHAO_YIN)
            elif lt == LineType.LAO_YIN:
                changed_line_types.append(LineType.SHAO_YANG)
            else:
                changed_line_types.append(lt)

        # 变卦使用本卦卦宫
        bg_number = _hexagram_number_from_lines(changed_line_types)
        _, _, bg_pos, bg_inner, bg_outer = _HEXAGRAM_TABLE[bg_number]
        bg_lines = []
        for pos in range(6):
            trigram = bg_inner if pos < 3 else bg_outer
            branch = TRIGRAM_BRANCHES[trigram][pos]
            stems = TRIGRAM_STEM[trigram]
            stem = stems[0] if pos < 3 or len(stems) < 2 else stems[1]
            wx = BRANCH_WUXING[branch]
            relation = _determine_relation(wx, palace_wx)
            animal_idx = (day_animal_start + pos) % 6
            bg_line = YaoLine(
                position=pos + 1,
                branch=branch, stem=stem,
                relation=relation,
                animal=ANIMAL_SEQUENCE[animal_idx],
                line_type=changed_line_types[pos],
            )
            bg_lines.append(bg_line)

        # 关联变卦
        for i in moving_positions:
            lines[i].changed_to = bg_lines[i]

        bian_gua_lines = bg_lines

    # 7. 伏神
    hidden_lines = _compute_hidden_lines(lines, palace)

    # 8. 用神
    yongshen = _determine_yongshen(question_domain)

    result = LiuYaoResult(
        number=number,
        name_cn=name_cn,
        palace=palace,
        palace_wx=palace_wx,
        lines=lines,
        bian_gua_lines=bian_gua_lines,
        shi_position=shi_pos,
        ying_position=ying_pos,
        day_stem=day_stem,
        day_branch=day_branch,
        yongshen=yongshen,
        void_branches=void_branches,
        hidden_lines=hidden_lines,
        cast_method=method,
        question_domain=question_domain,
    )

    # 9. 旺衰
    result.yongshen_strength = _assess_strength(result)

    return result


def hexagram_to_dict(result: LiuYaoResult) -> dict:
    """将 LiuYaoResult 序列化为可用于 API 返回的 dict"""
    def line_dict(line: YaoLine) -> dict:
        d = {
            "position": line.position,
            "branch": line.branch.value,
            "branch_wuxing": line.element.value,
            "stem": line.stem.value,
            "relation": line.relation.value,
            "animal": line.animal.value,
            "line_type": line.line_type.value,
            "is_yang": line.is_yang,
            "is_moving": line.is_moving,
            "is_shi": line.is_shi,
            "is_ying": line.is_ying,
            "is_void": line.is_void,
        }
        if line.hidden_relation:
            d["hidden_relation"] = line.hidden_relation.value
        if line.changed_to:
            d["changed_to"] = line_dict(line.changed_to)
        return d

    return {
        "hexagram_number": result.number,
        "name_cn": result.name_cn,
        "palace": result.palace.value,
        "palace_wuxing": result.palace_wx.value,
        "shi_position": result.shi_position,
        "ying_position": result.ying_position,
        "lines": [line_dict(l) for l in result.lines],
        "bian_gua_lines": [line_dict(l) for l in result.bian_gua_lines] if result.bian_gua_lines else None,
        "day_stem": result.day_stem.value,
        "day_branch": result.day_branch.value,
        "yongshen": result.yongshen.value if result.yongshen else None,
        "yongshen_strength": result.yongshen_strength,
        "void_branches": [b.value for b in result.void_branches],
        "hidden_lines": [r.value if r else None for r in result.hidden_lines],
        "cast_method": result.cast_method,
        "question_domain": result.question_domain,
    }
