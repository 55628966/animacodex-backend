# -*- coding: utf-8 -*-
"""节气源: Swiss Ephemeris (pyswisseph), Moshier 模型。

节气 = 太阳视黄经到达 15° 整数倍的精确时刻, 直接以 UT(≈UTC) 求交越,
精度角秒级(时刻误差远小于1秒), 覆盖 1800-2399, 无网络与数据文件依赖。
序号约定: 冬至=0, 小寒=1, 大寒=2, 立春=3, ... 大雪=23 (黄经 = 270°+15°×idx)。

为何不用 sxtwl 做主源: 实测发现 sxtwl 输出的是"当时中国钟表时"——
1940年代含历史夏令时(如1944年小寒偏差整1小时, 已经瑞士星历仲裁确认),
不是统一 UTC+8, 作边界判定源有隐患。sxtwl 降级为交叉验证第三源。
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import swisseph as swe

SOLAR_TERMS_SOURCE = ("Swiss Ephemeris (pyswisseph, Moshier模型): "
                      "太阳视黄经15°倍数交越UT时刻, 秒级精度, 覆盖1800-2399")
UTC8 = timezone(timedelta(hours=8))
_FLAG = swe.FLG_MOSEPH


def _jd_to_utc(jd: float) -> datetime:
    y, m, d, ut = swe.revjul(jd)
    sec = round(ut * 3600.0)
    return (datetime(y, m, d, tzinfo=timezone.utc) + timedelta(seconds=sec))


@lru_cache(maxsize=1024)
def terms_of_year(year: int):
    """该公历年内全部24节气 [(idx, utc_datetime)], 按时间升序。

    年内首个节气为小寒(黄经285°, 1月上旬), 依次每15°求下一次交越。
    """
    out = []
    jd = swe.julday(year, 1, 1, 0.0)
    for step in range(24):
        lon = (285 + 15 * step) % 360
        jd = swe.solcross_ut(float(lon), jd, _FLAG)
        idx = ((lon - 270) // 15) % 24
        out.append((idx, _jd_to_utc(jd)))
    assert out[0][1].year == year and out[-1][1].year == year, f"{year}年节气跨界异常"
    return tuple(out)


def lichun_utc(year: int) -> datetime:
    """该公历年立春(idx=3)的UTC精确时刻。"""
    for idx, dt in terms_of_year(year):
        if idx == 3:
            return dt
    raise RuntimeError(f"{year}年未找到立春")


def prev_and_next_jie(instant_utc: datetime):
    """返回出生时刻(UTC)之前最近的节与之后最近的节: ((idx, dt), (idx, dt))。

    只看"节"(月界, 奇数idx), 不看中气。用于月柱判定与大运起运计算。
    """
    from .constants import JIE_INDICES
    y = instant_utc.year
    jies = []
    for yy in (y - 1, y, y + 1):
        jies += [(i, dt) for i, dt in terms_of_year(yy) if i in JIE_INDICES]
    jies.sort(key=lambda x: x[1])
    prev_jie, next_jie = None, None
    for item in jies:
        if item[1] <= instant_utc:
            prev_jie = item
        else:
            next_jie = item
            break
    assert prev_jie and next_jie
    return prev_jie, next_jie
