# -*- coding: utf-8 -*-
"""四柱、十神、五行、大运主计算 + ChartResult 总装。

口径要点(详见 docs/口径文档, 待命理顾问签字项均已标注):
- 年柱以立春精确时刻为界; 月柱以十二节精确时刻为界(均为绝对时刻UTC比较)。
- 日柱、时辰以出生地【真太阳时】判定; 日界为真太阳时 00:00,
  晚子时(23:00-24:00)归属由 late_zi_new_day 开关控制(拍板项1, 默认值待签字):
    True  = 换日派: 日柱取次日
    False = 不换日派: 日柱留当日
  两派下晚子时的时柱天干均按次日日干五鼠遁(对齐 lunar-python 已发布流派语义)。
- 大运: 阳年男/阴年女顺排, 阴年男/阳年女逆排; 起运按 3天=1岁、1天=4个月、
  1时辰=10天 精确换算(即实际天数×120=命理天数, 360命理天=1岁)。
- 大运 end_year = start_year + 10 (左闭右开, 即下一步起始年), 对齐《00》示例。
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .constants import (STEMS, BRANCHES, STEM_ELEMENT, STEM_YANG, BRANCH_ELEMENT,
                        HIDDEN_STEMS, JIE_TO_MONTH_BRANCH, ten_god)
from .pillar_extras import nayin, star_fortune, zi_zuo, kong_wang, shen_sha_for_pillar
from .solar_terms import (SOLAR_TERMS_SOURCE, lichun_utc, prev_and_next_jie)
from .transparency import calculation_transparency, public_tradition_profile
from .true_solar import true_solar

ALGO_VERSION = "1.0.0"

# 日柱锚点: 1990-06-15 为 辛亥 日(六十甲子序47, 甲子=0)。已双源核验(sxtwl/lunar-python)。
_ANCHOR_ORD = date(1990, 6, 15).toordinal()
_ANCHOR_GZ = 47


@dataclass
class ChartOptions:
    late_zi_new_day: bool = True       # 拍板项1: 晚子时换日流派, 默认值待命理顾问签字
    five_element_mode: str = "main"    # 拍板项2: main=八字本气计数(契约示例口径) | hidden_weighted
    # None=沿用 legacy sex；其余为《16》约定的传统大运计算选择，不是性别身份判断。
    luck_cycle_convention: str | None = None


def _gz(idx60):
    return STEMS[idx60 % 10], BRANCHES[idx60 % 12]


def day_gz_index(d: date) -> int:
    return (d.toordinal() - _ANCHOR_ORD + _ANCHOR_GZ) % 60


def year_pillar(birth_utc: datetime):
    """立春精确时刻为界。返回(干支年数字, stem, branch)。"""
    y = birth_utc.year
    sui = y if birth_utc >= lichun_utc(y) else y - 1
    return sui, STEMS[(sui - 4) % 10], BRANCHES[(sui - 4) % 12]


def month_pillar(birth_utc: datetime, year_stem: str):
    """节界(精确时刻)。五虎遁月。"""
    (jie_idx, _), _ = prev_and_next_jie(birth_utc)
    branch_idx = JIE_TO_MONTH_BRANCH[jie_idx]
    offset = (branch_idx - 2) % 12                       # 距寅月
    stem_idx = ((STEMS.index(year_stem) % 5) * 2 + 2 + offset) % 10
    return STEMS[stem_idx], BRANCHES[branch_idx]


def day_and_hour_pillar(tst: datetime, late_zi_new_day: bool):
    """由真太阳时定日柱与时柱。返回 (day_stem, day_branch, hour_stem, hour_branch)。"""
    d = tst.date()
    is_late_zi = tst.hour == 23
    day_date = d + timedelta(days=1) if (is_late_zi and late_zi_new_day) else d
    day_idx = day_gz_index(day_date)
    day_stem, day_branch = _gz(day_idx)

    hour_branch_idx = ((tst.hour + 1) // 2) % 12
    # 时干所用日干: 晚子时一律按次日日干遁(两派一致, 见模块注释)
    zi_day = d + timedelta(days=1) if is_late_zi else day_date
    zi_day_stem_idx = day_gz_index(zi_day) % 10
    hour_stem_idx = ((zi_day_stem_idx % 5) * 2 + hour_branch_idx) % 10
    return day_stem, day_branch, STEMS[hour_stem_idx], BRANCHES[hour_branch_idx]


def pillar_dict(stem, branch, day_stem, day_branch="",
                year_branch="", month_branch="", pillar_kong_wang=""):
    p = {
        "stem": stem, "branch": branch,
        "hidden_stems": list(HIDDEN_STEMS[branch]),
        "ten_god_stem": ten_god(day_stem, stem),
        "ten_gods_hidden": [ten_god(day_stem, h) for h in HIDDEN_STEMS[branch]],
        "nayin": nayin(stem, branch),
        "star_fortune": star_fortune(stem, branch),
        "zi_zuo": ten_god(day_stem, HIDDEN_STEMS[branch][0]),
        "kong_wang": pillar_kong_wang,
        "shen_sha": shen_sha_for_pillar(
            year_branch or branch, month_branch or branch,
            day_stem, day_branch or branch, stem, branch,
        ),
    }
    return p


def five_elements(pillars, mode="main"):
    """五行分布。mode=main: 八字逐字按本气计1(契约示例口径, 整数);
    mode=hidden_weighted: 天干各1.0, 地支1.0按藏干拆分(1藏[1.0]/2藏[0.7,0.3]/3藏[0.6,0.3,0.1])。
    两种口径均属拍板项2, 待命理顾问签字。"""
    counts = {e: 0.0 for e in ("wood", "fire", "earth", "metal", "water")}
    weights = {1: [1.0], 2: [0.7, 0.3], 3: [0.6, 0.3, 0.1]}
    for p in pillars:
        if p is None:
            continue
        counts[STEM_ELEMENT[STEMS.index(p["stem"])]] += 1
        if mode == "main":
            counts[BRANCH_ELEMENT[BRANCHES.index(p["branch"])]] += 1
        else:
            hs = HIDDEN_STEMS[p["branch"]]
            for h, w in zip(hs, weights[len(hs)]):
                counts[STEM_ELEMENT[STEMS.index(h)]] += w
    if mode == "main":
        return {k: int(v) for k, v in counts.items()}
    return {k: round(v, 2) for k, v in counts.items()}


def _add_ym(d: date, years: int, months: int, days: int) -> date:
    y = d.year + years + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    dd = min(d.day, [31, 29 if m == 2 and (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, dd) + timedelta(days=days)


def luck_cycles(birth_utc: datetime, birth_local_date: date, year_stem: str,
                month_stem: str, month_branch: str, day_stem: str, sex: str,
                n_cycles: int = 8):
    """大运。顺逆以年干阴阳×性别; 起运距离取到分钟级。"""
    yang_year = STEM_YANG[STEMS.index(year_stem)]
    forward = (yang_year and sex == "male") or (not yang_year and sex == "female")

    prev_jie, next_jie = prev_and_next_jie(birth_utc)
    diff = (next_jie[1] - birth_utc) if forward else (birth_utc - prev_jie[1])
    # 分钟级精确换算: 3天=1岁 → 4320分钟=1岁; 1天=4月 → 360分钟=1月;
    # 1时辰=10天 → 12分钟=1天。距离取整到分钟(契约精度), 逐级下取整。
    minutes = int(diff.total_seconds() // 60)
    years = minutes // 4320
    rem = minutes % 4320
    months = rem // 360
    days = (rem % 360) // 12
    start_date = _add_ym(birth_local_date, years, months, days)

    month_gz60 = next(i for i in range(60)
                      if STEMS[i % 10] == month_stem and BRANCHES[i % 12] == month_branch)
    step = 1 if forward else -1
    cycles = []
    for k in range(1, n_cycles + 1):
        s, b = _gz((month_gz60 + step * k) % 60)
        sy = start_date.year + 10 * (k - 1)
        cycles.append({"index": k, "stem": s, "branch": b,
                       "start_year": sy, "end_year": sy + 10,
                       "ten_god": ten_god(day_stem, s)})
    return {"direction": "forward" if forward else "backward",
            "start_age": {"years": years, "months": months},
            "start_date": start_date.isoformat(),
            "cycles": cycles}


def current_block(now_utc: datetime, lc: dict | None):
    """当前所处大运序号(0=尚未起运)与流年(立春界)。"""
    sui = now_utc.year if now_utc >= lichun_utc(now_utc.year) else now_utc.year - 1
    if lc is None:
        return {"luck_cycle_index": None,
                "annual": {"year": sui, "stem": STEMS[(sui - 4) % 10],
                           "branch": BRANCHES[(sui - 4) % 12]}}
    start = date.fromisoformat(lc["start_date"])
    today = now_utc.date()
    idx = 0
    for c in lc["cycles"]:
        if today >= _add_ym(start, 10 * (c["index"] - 1), 0, 0):
            idx = c["index"]
    return {"luck_cycle_index": idx,
            "annual": {"year": sui, "stem": STEMS[(sui - 4) % 10],
                       "branch": BRANCHES[(sui - 4) % 12]}}


def compute_chart(birth_date: str, birth_time, tz_name: str, lat: float, lng: float,
                  sex: str, options: ChartOptions = None, chart_id: str = None,
                  now_utc: datetime = None):
    """总装, 返回契约 ChartResult dict(不含叙事, 全部中文原术语)。

    birth_time 为 None 时: 前三柱模式, partial=true, 起运距离按当地12:00估算,
    true_solar_time 为 null。
    """
    opt = options or ChartOptions()
    now_utc = now_utc or datetime.now(timezone.utc)
    partial = birth_time is None
    clock = datetime.fromisoformat(f"{birth_date}T{birth_time or '12:00'}")

    tst, total_corr, eot, birth_utc = true_solar(clock, tz_name, lng)

    sui, y_stem, y_branch = year_pillar(birth_utc)
    m_stem, m_branch = month_pillar(birth_utc, y_stem)
    if partial:
        d_stem, d_branch = _gz(day_gz_index(clock.date()))
        h_stem = h_branch = None
    else:
        d_stem, d_branch, h_stem, h_branch = day_and_hour_pillar(tst, opt.late_zi_new_day)

    kw = kong_wang(d_stem, d_branch)
    day_p = pillar_dict(d_stem, d_branch, d_stem,
                        day_branch=d_branch, year_branch=y_branch,
                        month_branch=m_branch, pillar_kong_wang=kw)
    day_p["note"] = "day_master"
    pillars = {
        "year": pillar_dict(y_stem, y_branch, d_stem,
                            day_branch=d_branch, year_branch=y_branch,
                            month_branch=m_branch, pillar_kong_wang=kw),
        "month": pillar_dict(m_stem, m_branch, d_stem,
                             day_branch=d_branch, year_branch=y_branch,
                             month_branch=m_branch, pillar_kong_wang=kw),
        "day": day_p,
        "hour": None if partial else pillar_dict(h_stem, h_branch, d_stem,
                                                  day_branch=d_branch,
                                                  year_branch=y_branch,
                                                  month_branch=m_branch,
                                                  pillar_kong_wang=kw),
    }
    di = STEMS.index(d_stem)
    convention = opt.luck_cycle_convention
    convention_sex = {
        "traditional_male": "male",
        "traditional_female": "female",
    }
    if convention not in (None, "traditional_male", "traditional_female", "not_applied"):
        raise ValueError(f"未知 luck_cycle_convention: {convention}")
    if convention == "not_applied":
        lc = None
        effective_convention = "not_applied"
    else:
        effective_sex = convention_sex.get(convention, sex)
        lc = luck_cycles(birth_utc, clock.date(), y_stem, m_stem, m_branch, d_stem, effective_sex)
        effective_convention = convention or ("traditional_male" if sex == "male" else "traditional_female")
    trace, boundary_notice = calculation_transparency(
        clock, tz_name, tst, total_corr, birth_utc, partial, opt.late_zi_new_day)

    result = {
        "chart_id": chart_id,
        "true_solar_time": None if partial else {
            "datetime": tst.replace(microsecond=0).isoformat(),
            "correction_minutes": int(round(total_corr)),
            "equation_of_time_minutes": int(round(eot)),
        },
        "pillars": pillars,
        "day_master": {"stem": d_stem, "element": STEM_ELEMENT[di],
                       "yin_yang": "yang" if STEM_YANG[di] else "yin"},
        "five_elements": five_elements(
            [pillars["year"], pillars["month"], pillars["day"], pillars["hour"]],
            opt.five_element_mode),
        "luck_cycles": lc,
        "current": current_block(now_utc, lc),
        "meta": {
            "algo_version": ALGO_VERSION,
            "solar_terms_source": SOLAR_TERMS_SOURCE,
            "tradition_profile": public_tradition_profile(),
            "luck_cycle_convention": effective_convention,
            "calculation_trace": trace,
            "boundary_notice": boundary_notice,
        },
    }
    if partial:
        result["partial"] = True

    # 30号: 全局互动图（免费层仅节点清单）
    try:
        from .global_interaction import graph_from_chart_result
        from .interaction_layers import origin_layer as _origin_layer
        gi_graph = graph_from_chart_result(result)
        result["global_interaction"] = _origin_layer(gi_graph)
    except Exception:
        result["global_interaction"] = None

    return result
