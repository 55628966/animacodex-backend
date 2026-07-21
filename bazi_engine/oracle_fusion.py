"""
神谕所融合层 (Oracle Fusion) — 八字 × 六爻 × 大六壬

将三套计算引擎的输出在一张五行图上融合。
输出为机器可读结构，不生成面向用户的解读文本。
解读文本由 Owner/后续系统基于本模块输出补充。

Owner 2026-07-20 签发。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ══════════════════════════════════════════════
# 基础
# ══════════════════════════════════════════════

class Wuxing(Enum):
    WOOD = "木"; FIRE = "火"; EARTH = "土"; METAL = "金"; WATER = "水"


GENERATES = {Wuxing.WOOD:Wuxing.FIRE, Wuxing.FIRE:Wuxing.EARTH, Wuxing.EARTH:Wuxing.METAL,
             Wuxing.METAL:Wuxing.WATER, Wuxing.WATER:Wuxing.WOOD}
CONTROLS = {Wuxing.WOOD:Wuxing.EARTH, Wuxing.EARTH:Wuxing.WATER, Wuxing.WATER:Wuxing.FIRE,
            Wuxing.FIRE:Wuxing.METAL, Wuxing.METAL:Wuxing.WOOD}

STEM_WX = {'甲':Wuxing.WOOD, '乙':Wuxing.WOOD, '丙':Wuxing.FIRE, '丁':Wuxing.FIRE,
           '戊':Wuxing.EARTH, '己':Wuxing.EARTH, '庚':Wuxing.METAL, '辛':Wuxing.METAL,
           '壬':Wuxing.WATER, '癸':Wuxing.WATER}

BRANCH_WX_MAP = {'子':Wuxing.WATER, '丑':Wuxing.EARTH, '寅':Wuxing.WOOD, '卯':Wuxing.WOOD,
                 '辰':Wuxing.EARTH, '巳':Wuxing.FIRE, '午':Wuxing.FIRE, '未':Wuxing.EARTH,
                 '申':Wuxing.METAL, '酉':Wuxing.METAL, '戌':Wuxing.EARTH, '亥':Wuxing.WATER}

TEN_GOD_WU = {
    '正官':Wuxing.METAL, '七杀':Wuxing.FIRE, '正印':Wuxing.EARTH, '偏印':Wuxing.WATER,
    '比肩':Wuxing.METAL, '劫财':Wuxing.METAL, '食神':Wuxing.WOOD, '伤官':Wuxing.FIRE,
    '正财':Wuxing.WOOD, '偏财':Wuxing.WOOD,
}
# 修正：十神 → 五行 映射取决于日主。土日主：食神=金，伤官=水, 正财=水...
# 简化：用十神本身推断日主五行，再对应用神五行。


@dataclass
class FusionReport:
    """八字×占卜融合报告"""
    # 八字侧
    day_master_stem: str = ""           # 日主天干
    day_master_wx: str = ""             # 日主五行
    chart_balance: str = ""             # "身强"/"身弱"/"中和"
    xiji: str = ""                      # 喜用神五行 "木火"/"金水"/...

    # 卦爻侧（六爻）
    hexagram_name: Optional[str] = None    # 卦名
    shi_element: Optional[str] = None      # 世爻五行
    yongshen: Optional[str] = None         # 用神六亲
    yongshen_wx: Optional[str] = None      # 用神五行
    yongshen_strength: Optional[str] = None  # 用神旺衰

    # 课式侧（大六壬）
    liuren_ke_name: Optional[str] = None   # "克"/"贼"/"比用"/...
    sanchuan_wx: Optional[str] = None      # 三传主五行

    # 融合结果
    day_master_vs_shi: str = ""    # 日主↔世爻对齐
    yongshen_vs_xiji: str = ""     # 用神-喜忌交互
    dayun_echo: str = ""           # 大运时序呼应
    global_flag: str = ""          # "吉"/"平"/"凶"


def _balance_from_chart(chart: dict) -> tuple[str, str]:
    """从 ChartResult 推断身强身弱和喜用神"""
    dm = chart.get('day_master_stem', '')
    dm_wx = STEM_WX.get(dm, Wuxing.EARTH)

    # 简化的身强身弱：通过 pillar 五行统计
    pillars = chart.get('pillars', {})
    supports = 0
    controls = 0
    for p in ['year', 'month', 'day', 'hour']:
        pl = pillars.get(p, {})
        for field in ['stem', 'branch']:
            ch = pl.get(field, '')
            wx = STEM_WX.get(ch) if field == 'stem' else BRANCH_WX_MAP.get(ch)
            if wx:
                if GENERATES.get(wx) == dm_wx: supports += 1
                elif CONTROLS.get(wx) == dm_wx: controls += 1

    if supports >= controls + 2: balance = '身强'
    elif controls >= supports + 2: balance = '身弱'
    else: balance = '中和'

    # 喜用神
    if balance == '身强':
        xiji = '金水' if dm_wx in (Wuxing.WOOD, Wuxing.FIRE) else ('水木' if dm_wx in (Wuxing.EARTH, Wuxing.METAL) else '木火')
    elif balance == '身弱':
        xiji = '木火' if dm_wx == Wuxing.WOOD else ('火土' if dm_wx == Wuxing.FIRE else ('土金' if dm_wx == Wuxing.EARTH else ('金水' if dm_wx == Wuxing.METAL else '水木')))
    else:
        xiji = '调候需要'

    return balance, xiji


def _map_yongshen_wx(yongshen_str: str, chart_wx: Wuxing) -> Wuxing:
    """用神六亲 → 五行映射（相对于日主）"""
    # 十神 → 相对于日主的五行关系 → 用神实际五行
    mapping = {
        '父母': GENERATES.get(chart_wx, chart_wx),  # 生我者
        '官鬼': CONTROLS.get(chart_wx, chart_wx),   # 克我者
        '兄弟': chart_wx,                             # 同我者
        '子孙': chart_wx,                             # 我生者
        '妻财': chart_wx,                             # 我克者
    }
    # 修正：子孙=我生者，妻财=我克者
    for k, v in list(GENERATES.items()):
        if v == chart_wx: mapping['子孙'] = k
    for k, v in list(CONTROLS.items()):
        if v == chart_wx: mapping['妻财'] = k

    return mapping.get(yongshen_str, chart_wx)


def fuse_liuyao_with_chart(chart: dict, liuyao: dict) -> FusionReport:
    """八字 + 六爻 融合"""
    dm_stem = chart.get('day_master_stem', '')
    dm_wx = STEM_WX.get(dm_stem, Wuxing.EARTH)
    chart_wx = dm_wx
    balance, xiji = _balance_from_chart(chart)

    report = FusionReport(
        day_master_stem=dm_stem,
        day_master_wx=dm_wx.value,
        chart_balance=balance,
        xiji=xiji,
    )

    if liuyao:
        report.hexagram_name = liuyao.get('name_cn', '')
        report.yongshen = liuyao.get('yongshen', '')
        report.yongshen_strength = liuyao.get('yongshen_strength', '')

        # 世爻五行
        for line in liuyao.get('lines', []):
            if line.get('is_shi'):
                report.shi_element = line.get('branch_wuxing', '')
                break

        # 日主↔世爻对齐
        if report.shi_element and report.day_master_wx:
            shi_wx = Wuxing(report.shi_element)
            dm_wx = Wuxing(report.day_master_wx)
            if CONTROLS.get(shi_wx) == dm_wx:
                report.day_master_vs_shi = f"世爻{report.shi_element}克日主{report.day_master_wx}·外在压力感"
            elif CONTROLS.get(dm_wx) == shi_wx:
                report.day_master_vs_shi = f"日主{report.day_master_wx}克世爻{report.shi_element}·主动掌控"
            elif GENERATES.get(shi_wx) == dm_wx:
                report.day_master_vs_shi = f"世爻{report.shi_element}生日主{report.day_master_wx}·外来生扶"
            elif GENERATES.get(dm_wx) == shi_wx:
                report.day_master_vs_shi = f"日主{report.day_master_wx}生世爻{report.shi_element}·能量输出"
            elif shi_wx == dm_wx:
                report.day_master_vs_shi = f"世爻与日主同{report.shi_element}·本位一致"
            else:
                report.day_master_vs_shi = f"世爻{report.shi_element}·日主{report.day_master_wx}·无直接生克"

        # 用神↔喜忌
        if report.yongshen:
            ys_map = {
                '官鬼': CONTROLS.get(chart_wx, Wuxing.EARTH).value,
                '妻财': next((k.value for k,v in CONTROLS.items() if v==chart_wx), '不明'),
                '父母': GENERATES.get(chart_wx, Wuxing.EARTH).value,
                '子孙': next((k.value for k,v in GENERATES.items() if v==chart_wx), '不明'),
                '兄弟': report.day_master_wx,
            }
            report.yongshen_wx = ys_map.get(report.yongshen, '不明')

            xiji = report.xiji
            if report.yongshen_wx in xiji:
                report.yongshen_vs_xiji = f"用神{report.yongshen}({report.yongshen_wx})为喜神·根基稳固"
            else:
                report.yongshen_vs_xiji = f"用神{report.yongshen}({report.yongshen_wx})非喜用·需察动爻补救"

        # 全局判
        if report.yongshen_strength == '旺' and '为喜神' in report.yongshen_vs_xiji:
            report.global_flag = '吉'
        elif report.yongshen_strength == '衰' and '非喜用' in report.yongshen_vs_xiji:
            report.global_flag = '凶'
        else:
            report.global_flag = '平'

    return report


def fuse_daliuren_with_chart(chart: dict, daliuren: dict) -> FusionReport:
    """八字 + 大六壬 融合"""
    dm_stem = chart.get('day_master_stem', '')
    dm_wx = STEM_WX.get(dm_stem, Wuxing.EARTH)
    chart_wx = dm_wx
    balance, xiji = _balance_from_chart(chart)

    report = FusionReport(
        day_master_stem=dm_stem,
        day_master_wx=dm_wx.value,
        chart_balance=balance,
        xiji=xiji,
    )

    if daliuren:
        report.liuren_ke_name = daliuren.get('sanchuan_method', '')
        sc = daliuren.get('sanchuan', {})
        if sc:
            chu = sc.get('chu', '')
            zhong = sc.get('zhong', '')
            mo = sc.get('mo', '')
            # 三传主五行：取末传（事之终结）为主
            mo_wx = BRANCH_WX_MAP.get(mo, Wuxing.EARTH)
            report.sanchuan_wx = mo_wx.value
            report.day_master_vs_shi = f"三传{chu}→{zhong}→{mo}(末{mo_wx.value})·日主{report.day_master_wx}"

            # 日干↔四课第一课上神
            lessons = daliuren.get('lessons', [])
            if lessons:
                l1 = lessons[0]
                upper_br = l1['upper']['branch']
                upper_wx = BRANCH_WX_MAP.get(upper_br, Wuxing.EARTH)
                if CONTROLS.get(upper_wx) == chart_wx:
                    report.day_master_vs_shi += f"·上神{upper_br}({upper_wx.value})克日干·临危"
                elif GENERATES.get(upper_wx) == chart_wx:
                    report.day_master_vs_shi += f"·上神{upper_br}({upper_wx.value})生日干·得益"

            # 三传末传 ↔ 日主
            if CONTROLS.get(mo_wx) == chart_wx:
                report.global_flag = '凶'
                report.yongshen_vs_xiji = f"末传{mo}({mo_wx.value})克日主{report.day_master_wx}·事态不利"
            elif GENERATES.get(mo_wx) == chart_wx:
                report.global_flag = '吉'
                report.yongshen_vs_xiji = f"末传{mo}({mo_wx.value})生日主{report.day_master_wx}·事态有利"
            else:
                report.global_flag = '平'
                report.yongshen_vs_xiji = f"末传{mo}({mo_wx.value})·日主{report.day_master_wx}·待观变爻"

    return report


def fusion_to_dict(r: FusionReport) -> dict:
    return {
        "day_master": {"stem": r.day_master_stem, "wuxing": r.day_master_wx},
        "chart_balance": r.chart_balance,
        "xiji": r.xiji,
        "hexagram_name": r.hexagram_name,
        "shi_element": r.shi_element,
        "yongshen": r.yongshen,
        "yongshen_wx": r.yongshen_wx,
        "yongshen_strength": r.yongshen_strength,
        "liuren_ke": r.liuren_ke_name,
        "sanchuan_wx": r.sanchuan_wx,
        "alignment": r.day_master_vs_shi,
        "yongshen_xiji": r.yongshen_vs_xiji,
        "dayun_echo": r.dayun_echo,
        "global_flag": r.global_flag,
    }
