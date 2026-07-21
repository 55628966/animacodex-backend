# -*- coding: utf-8 -*-
"""A3: export_safe 独立验收测试。
GOGO.md 验收：pytest test_export_safe.py 全绿
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bazi_engine import compute_chart, compute_full_chart, assemble_ai_payload
from bazi_engine.export_safe import contains_sensitive

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


def _live_chart():
    return compute_chart("1990-06-15", "14:00", "Asia/Shanghai",
                         39.9042, 116.4074, "male", chart_id="test-chart-id-xyz")


# ---------------- 脱敏彻底 ----------------

def test_export_safe_no_datetime_or_coords():
    """序列化输出不含任何日期/时间格式串；无坐标键。"""
    ch = _live_chart()
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    blob = json.dumps(payload, ensure_ascii=False)
    assert not _DATE_RE.search(blob), "残留日期格式串"
    assert not _TIME_RE.search(blob), "残留时间格式串"
    for key in ("lat", "lng", "chart_id", "true_solar_time", "start_date",
                "birth_date", "birth_time", "datetime", "location"):
        assert f'"{key}"' not in blob, f"泄漏敏感字段: {key}"
    for coord in ("39.9042", "116.4074"):
        assert coord not in blob, f"泄漏坐标数值: {coord}"


def test_export_safe_whitelist_present():
    """白名单命理字段齐全, contains_sensitive 为 False。"""
    ch = _live_chart()
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    for k in ("day_master", "five_elements", "pillars", "luck_cycles",
              "key_ten_gods", "interactions", "annual_next3", "relationship", "career"):
        assert k in payload
    for c in payload["luck_cycles"]["cycles"]:
        assert set(c) == {"index", "stem", "branch", "start_year", "end_year", "ten_god"}
    assert contains_sensitive(payload) is False


def test_export_safe_pillars_stripped():
    """14号裁定: 四柱条目只含十神, 无干支。"""
    ch = _live_chart()
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    for pos, entry in payload["pillars"].items():
        if entry is None:
            continue
        assert set(entry) == {"ten_god_stem", "ten_gods_hidden"}, f"{pos}柱残留干支"
        assert "stem" not in entry and "branch" not in entry
        assert "hidden_stems" not in entry


def test_export_safe_sensitive_detector():
    """阴性对照: 注入日期串 → contains_sensitive 必须 True。"""
    ch = _live_chart()
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    payload["_leak"] = "1990-06-15"
    assert contains_sensitive(payload) is True


# ---------------- 20号A4: profile/trace 不可入 AI payload ----------------

def test_export_safe_excludes_profile_and_trace():
    """20号A4: AI payload 不得含 tradition_profile / calculation_trace / boundary_notice / meta。"""
    ch = _live_chart()
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    blob = json.dumps(payload, ensure_ascii=False)
    for key in ("tradition_profile", "calculation_trace", "boundary_notice",
                "meta", "solar_terms_source"):
        assert f'"{key}"' not in blob, f"AI payload 泄漏元数据字段: {key}"


def test_export_safe_trace_no_leak_raw_birth():
    """20号A3: calculation_trace 不含出生日期文本/经纬度 (trace 不出现在 AI payload,
    但即使 meta 被意外序列化也不应泄漏)。"""
    ch = _live_chart()
    trace = ch["meta"]["calculation_trace"]
    blob = json.dumps(trace, ensure_ascii=False)
    assert "1990" not in blob, "trace 含年份"
    assert "06" not in blob, "trace 含月份数字"
    assert "39.9042" not in blob and "116.4074" not in blob, "trace 含坐标"
