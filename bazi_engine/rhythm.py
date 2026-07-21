# -*- coding: utf-8 -*-
"""个人节律的纯计算结构（21号 A1/A2）。

只输出节气月、十神和既有规则关系；所有叙事归模型B。
"""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from .constants import JIE_NAMES, ten_god
from .core import month_pillar, year_pillar
from .full_chart import _relation, key_ten_gods
from .solar_terms import prev_and_next_jie
from .transparency import PROFILE_ID


def _local_iso(instant_utc: datetime, viewer_timezone: str) -> str:
    return instant_utc.astimezone(ZoneInfo(viewer_timezone)).replace(microsecond=0).isoformat()


def compute_monthly_rhythm(chart: dict, at: date, viewer_timezone: str) -> dict:
    """以查看者时区的当地正午确定所属节气月，保证日期入参可稳定回归。"""
    local_noon = datetime.combine(at, time(12), tzinfo=ZoneInfo(viewer_timezone))
    instant_utc = local_noon.astimezone(timezone.utc)
    current_jie, next_jie = prev_and_next_jie(instant_utc)
    _, year_stem, _ = year_pillar(instant_utc)
    month_stem, month_branch = month_pillar(instant_utc, year_stem)
    month_ten_god = ten_god(chart["day_master"]["stem"], month_stem)

    links = [{"kind": "ten_god", "source": "solar_month", "value": month_ten_god}]
    for item in key_ten_gods(chart):
        relation, note_cn = _relation(month_ten_god, item["name"])
        links.append({
            "kind": "interaction",
            "relation": relation,
            "note_cn": note_cn,
            "with": item["name"],
            "source_rank": item["rank"],
        })

    return {
        "chart_id": chart["chart_id"],
        "profile_id": chart.get("meta", {}).get("tradition_profile", {}).get("profile_id", PROFILE_ID),
        "solar_month": {
            "term_anchor": JIE_NAMES[current_jie[0]],
            "starts_at": _local_iso(current_jie[1], viewer_timezone),
            "ends_at": _local_iso(next_jie[1], viewer_timezone),
            "stem": month_stem,
            "branch": month_branch,
            "ten_god": month_ten_god,
        },
        "next_boundary": {"term_anchor": JIE_NAMES[next_jie[0]], "at": _local_iso(next_jie[1], viewer_timezone)},
        "natal_links": links,
        "limitations": ["traditional_reading_only", "not_a_prediction"],
    }


def first_scroll_candidates(full: dict) -> list[dict]:
    """固定的三个付费样章入口；只给 B 指针，不做叙事或重要性宣判。"""
    return [
        {"slot": 1, "kind": "key_ten_god", "source_path": "key_ten_gods[0]"},
        {"slot": 2, "kind": "interaction", "source_path": "interactions[0]"},
        {"slot": 3, "kind": "annual_theme", "source_path": "annual_next3[0]"},
    ]
