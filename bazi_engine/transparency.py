# -*- coding: utf-8 -*-
"""传统口径、可公开计算 Trace 与边界提示。

本模块只描述已经采用的计算约定；不输出叙事、不输出原始出生资料或坐标。
"""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from .constants import JIE_NAMES
from .solar_terms import prev_and_next_jie

PROFILE_ID = "zi_ping_solar_v1"
TRADITION_PROFILE = {
    "profile_id": PROFILE_ID,
    "year_boundary": "Li Chun exact instant",
    "month_boundary": "12 Jie exact instants",
    "civil_time": "IANA timezone with historical DST",
    "time_correction": "true solar time",
    "day_boundary": "23:00 true-solar late-Zi new-day convention",
    "five_elements_radar": "visible main stems/branches integer tally; not a full strength score",
    "luck_cycle_direction": "traditional year-stem yin-yang plus selected traditional convention",
}

# 边界提示是透明度提示，不是“命运不确定”的营销话术。
_BOUNDARY_MINUTES = 120


def public_tradition_profile() -> dict:
    """返回可安全展示的独立 profile 副本。"""
    return deepcopy(TRADITION_PROFILE)


def _minutes_to_hour_boundary(tst: datetime) -> float:
    """真太阳时距离最近二小时时支界的分钟数（子时以23:00起）。"""
    minutes = tst.hour * 60 + tst.minute + tst.second / 60
    boundaries = (23 * 60, 60, 180, 300, 420, 540, 660, 780, 900, 1020, 1140, 1260)
    return min(abs(minutes - point) for point in boundaries)


def calculation_transparency(clock_local: datetime, tz_name: str, tst: datetime,
                             total_correction: float, birth_utc: datetime,
                             partial: bool, late_zi_new_day: bool) -> tuple[dict, dict]:
    """返回 (calculation_trace, boundary_notice)，两者均不含出生日期/时间文本。"""
    aware = clock_local.replace(tzinfo=ZoneInfo(tz_name))
    dst = aware.dst()
    prev_jie, next_jie = prev_and_next_jie(birth_utc)
    jie_distance = min((birth_utc - prev_jie[1]).total_seconds(),
                       (next_jie[1] - birth_utc).total_seconds()) / 60
    if partial:
        notice = {
            "threshold_minutes": _BOUNDARY_MINUTES,
            "near_jie_boundary": jie_distance <= _BOUNDARY_MINUTES,
            "near_day_boundary": False,
            "near_hour_boundary": False,
            "time_unknown": True,
        }
    else:
        minute_of_day = tst.hour * 60 + tst.minute + tst.second / 60
        notice = {
            "threshold_minutes": _BOUNDARY_MINUTES,
            "near_jie_boundary": jie_distance <= _BOUNDARY_MINUTES,
            "near_day_boundary": min(minute_of_day, abs(minute_of_day - 23 * 60)) <= _BOUNDARY_MINUTES,
            "near_hour_boundary": _minutes_to_hour_boundary(tst) <= _BOUNDARY_MINUTES,
            "time_unknown": False,
        }
    trace = {
        "profile_id": PROFILE_ID,
        "civil_time_basis": "IANA timezone with historical DST",
        "timezone": tz_name,
        "dst_applied": bool(dst and dst.total_seconds()),
        "true_solar_time_applied": not partial,
        "true_solar_correction_minutes": int(round(total_correction)),
        "year_boundary": "立春精确时刻",
        "month_boundary": "十二节精确时刻",
        "day_boundary": "真太阳时23点换日" if late_zi_new_day else "真太阳时0点换日",
        "hour_pillar_basis": "真太阳时二小时地支",
        "nearest_jie": {"previous": JIE_NAMES[prev_jie[0]], "next": JIE_NAMES[next_jie[0]]},
    }
    return trace, notice
