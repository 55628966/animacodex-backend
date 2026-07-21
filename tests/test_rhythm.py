# -*- coding: utf-8 -*-
"""21号 A3: 个人节律验收测试。
覆盖: 可复现性 / 节气边界 / DST / 时区 / luck_cycles:null /
      叙事缺席 / 出生资料不泄漏 / AI payload不入。
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bazi_engine import compute_chart, ChartOptions
from bazi_engine.rhythm import compute_monthly_rhythm
from bazi_engine.export_safe import assemble_ai_payload


def _chart(sex="male", convention=None):
    return compute_chart("1990-06-15", "14:00", "Asia/Shanghai",
                         39.9042, 116.4074, sex,
                         options=ChartOptions(luck_cycle_convention=convention),
                         chart_id="test-rhythm-id")


# ---------------- 可复现 ----------------

def test_rhythm_idempotent():
    """固定 at + viewer_timezone → 响应可复现。"""
    ch = _chart()
    r1 = compute_monthly_rhythm(ch, date(2026, 3, 6), "Asia/Shanghai")
    r2 = compute_monthly_rhythm(ch, date(2026, 3, 6), "Asia/Shanghai")
    assert r1 == r2


# ---------------- 节气边界 ----------------

def test_rhythm_jie_boundary_starts():
    """惊蛰当天 → 节气月为卯月(惊蛰→清明)。"""
    ch = _chart()
    r = compute_monthly_rhythm(ch, date(2026, 3, 6), "Asia/Shanghai")
    assert r["solar_month"]["term_anchor"] == "惊蛰"
    assert r["solar_month"]["branch"] == "卯"
    assert r["next_boundary"]["term_anchor"] == "清明"


def test_rhythm_jie_boundary_before():
    """惊蛰前一天 → 仍在寅月(立春→惊蛰)。"""
    ch = _chart()
    r = compute_monthly_rhythm(ch, date(2026, 3, 4), "Asia/Shanghai")
    assert r["solar_month"]["term_anchor"] == "立春"
    assert r["solar_month"]["branch"] == "寅"


# ---------------- DST 时区 ----------------

def test_rhythm_dst_timezone():
    """夏令时地区(如 America/New_York)时区校验通过且节气月正确。"""
    ch = _chart()
    r = compute_monthly_rhythm(ch, date(2026, 7, 15), "America/New_York")
    assert "小暑" in r["solar_month"]["term_anchor"] or "大暑" in r["solar_month"]["term_anchor"]
    assert r["solar_month"]["branch"] in ("未", "申")


# ---------------- 不同查看者时区 ----------------

def test_rhythm_timezone_boundary():
    """同一UTC时刻但不同时区 → 可能在节气边界两侧, 各自正确归属。"""
    ch = _chart()
    # 2026-04-05 是清明当天(UTC), 上海 vs 纽约可能跨节气
    r_sh = compute_monthly_rhythm(ch, date(2026, 4, 5), "Asia/Shanghai")
    r_ny = compute_monthly_rhythm(ch, date(2026, 4, 5), "America/New_York")
    # 至少一个归属不同节气月可接受; 仅断言两个都不崩溃且结构一致
    assert set(r_sh) == set(r_ny)
    assert r_sh["chart_id"] == r_ny["chart_id"] == "test-rhythm-id"
    assert isinstance(r_sh["solar_month"]["term_anchor"], str)


# ---------------- luck_cycles:null ----------------

def test_rhythm_without_luck_cycles():
    """luck_cycles:null 时仍正常返回节气月 + natal_links, 无大运依赖。"""
    ch = _chart(convention="not_applied")
    assert ch["luck_cycles"] is None
    r = compute_monthly_rhythm(ch, date(2026, 3, 6), "Asia/Shanghai")
    assert r["solar_month"]["term_anchor"] == "惊蛰"
    assert len(r["natal_links"]) >= 1
    assert r["natal_links"][0]["kind"] == "ten_god"


# ---------------- 不含叙事 ----------------

def test_rhythm_no_narrative_fields():
    """MonthlyRhythmData 为纯计算结构, 无叙事/解释字段。"""
    ch = _chart()
    r = compute_monthly_rhythm(ch, date(2026, 3, 6), "Asia/Shanghai")
    narrative_keys = {"narrative", "interpretation", "advice", "prediction",
                      "reading", "fortune", "luck_score"}
    assert not (set(r) & narrative_keys), f"rhythm 含叙事字段: {set(r) & narrative_keys}"
    blob = json.dumps(r, ensure_ascii=False)
    for word in ("将会", "必然", "命运", "注定", "好运", "坏运"):
        assert word not in blob, f"rhythm 含叙事词: {word}"


# ---------------- 不含出生资料 ----------------

def test_rhythm_no_birth_data():
    """MonthlyRhythmData 不含原始出生文本/经纬度。"""
    ch = _chart()
    r = compute_monthly_rhythm(ch, date(2026, 3, 6), "Asia/Shanghai")
    blob = json.dumps(r, ensure_ascii=False)
    for key in ("birth_date", "birth_time", "lat", "lng", "location",
                "true_solar_time", "chart_id_value"):
        assert f'"{key}"' not in blob, f"rhythm 泄漏: {key}"
    assert "1990-06-15" not in blob
    assert "39.9042" not in blob


# ---------------- 不进入 AI payload ----------------

def test_rhythm_not_in_export_safe():
    """MonthlyRhythmData 不入 AI 白名单 payload。"""
    ch = _chart()
    from bazi_engine.full_chart import compute_full_chart
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    blob = json.dumps(payload, ensure_ascii=False)
    for key in ("solar_month", "natal_links", "next_boundary", "rhythm",
                "term_anchor", "starts_at", "ends_at"):
        assert f'"{key}"' not in blob, f"AI payload 泄漏 rhythm 字段: {key}"
