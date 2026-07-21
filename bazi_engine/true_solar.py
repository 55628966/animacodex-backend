# -*- coding: utf-8 -*-
"""真太阳时计算。

公式(《01》2.2): 真太阳时 = 当地钟表时间 + 经度修正 + 均时差
- 经度修正 = 出生地经度×4分钟 − 时区偏移(即当地平太阳时与钟表时之差)
- 均时差(Equation of Time): NOAA/Spencer 傅里叶级数实现, 精度约±30秒,
  满足契约"分钟级"要求。来源: NOAA Solar Calculator (Spencer 1971)。

契约字段口径:
- correction_minutes         = 总修正(经度修正+均时差), 即 真太阳时−钟表时
- equation_of_time_minutes   = 其中均时差分量
(与《00》示例吻合: 14:00 + (-18) = 13:42, 其中均时差 -2)
"""
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def equation_of_time_minutes(dt_utc: datetime) -> float:
    """均时差(分钟), NOAA/Spencer公式。正值=真太阳快于平太阳。"""
    doy = dt_utc.timetuple().tm_yday
    hour = dt_utc.hour + dt_utc.minute / 60.0
    year_len = 366 if _is_leap(dt_utc.year) else 365
    gamma = 2.0 * math.pi / year_len * (doy - 1 + (hour - 12) / 24.0)
    return 229.18 * (0.000075
                     + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                     - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))


def _is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def true_solar(clock_local: datetime, tz_name: str, lng: float):
    """由当地钟表时间求真太阳时。

    返回 (tst_naive_datetime, total_correction_min, eot_min, birth_utc)。
    tst 为出生地真太阳时(无时区语义的本地天文时刻)。
    """
    tz = ZoneInfo(tz_name)
    aware = clock_local.replace(tzinfo=tz)
    utc_offset_min = aware.utcoffset().total_seconds() / 60.0
    birth_utc = aware.astimezone(ZoneInfo("UTC"))

    lng_corr = lng * 4.0 - utc_offset_min          # 经度修正(分钟)
    eot = equation_of_time_minutes(birth_utc)       # 均时差(分钟)
    total = lng_corr + eot
    tst = clock_local + timedelta(minutes=total)
    return tst, total, eot, birth_utc
