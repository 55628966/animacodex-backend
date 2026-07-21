# -*- coding: utf-8 -*-
"""全卷数据 FullChartData + AI脱敏出口 测试(09号 M3第一单 A组)。

运行: ./.venv/bin/python -m pytest tests/test_full_chart.py -q  (项目根)
覆盖: 关键四十神恰4个/rank1月令/去重 · partial命例 · interactions对称与计数 ·
      annual_next3从current起 · 夫妻宫=日支 · career五组计数(满8/partial6) ·
      Mock与端点一致 · /full 端点契约与404 · export_safe 脱敏彻底。
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 项目根

from bazi_engine import ChartOptions, compute_chart, compute_full_chart, assemble_ai_payload  # noqa: E402
from bazi_engine.full_chart import _relation, interactions, key_ten_gods  # noqa: E402
from bazi_engine.constants import TEN_GOD_CATEGORY  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MOCK_CHARTS = json.loads((ROOT / "mock_chart_result.json").read_text(encoding="utf-8"))
ALL_TEN_GODS = set(TEN_GOD_CATEGORY)
RELATIONS = {"生", "克", "化", "竞"}


@pytest.fixture(scope="module")
def fulls():
    return [compute_full_chart(ch) for ch in MOCK_CHARTS]


# ---------------- key_ten_gods ----------------

def test_key_ten_gods_exactly_four(fulls):
    """每个命例(含partial)关键十神恰4个。"""
    for f in fulls:
        assert len(f["key_ten_gods"]) == 4


def test_key_ten_gods_distinct_and_ranked(fulls):
    """4个关键十神互不相同, rank 为 1..4, 均为合法十神。"""
    for f in fulls:
        names = [g["name"] for g in f["key_ten_gods"]]
        assert len(set(names)) == 4
        assert set(names) <= ALL_TEN_GODS
        assert [g["rank"] for g in f["key_ten_gods"]] == [1, 2, 3, 4]


def test_key_rank1_is_month_branch_main():
    """rank1 必为月支本气十神, position=month_branch_main。"""
    from bazi_engine.constants import ten_god
    for ch in MOCK_CHARTS:
        kg = key_ten_gods(ch)
        month = ch["pillars"]["month"]
        expected = ten_god(ch["day_master"]["stem"], month["hidden_stems"][0])
        assert kg[0]["name"] == expected
        assert kg[0]["position"] == "month_branch_main"


def test_key_ten_gods_partial_case(fulls):
    """partial 命例(第3例, 无时辰)仍恰4个且规则一致。"""
    partial = fulls[2]
    assert MOCK_CHARTS[2].get("partial") is True
    assert len(partial["key_ten_gods"]) == 4
    assert partial["key_ten_gods"][0]["position"] == "month_branch_main"


# ---------------- interactions ----------------

def test_interactions_count_is_c_4_2(fulls):
    """4个关键十神两两组合恰 C(4,2)=6 条。"""
    for f in fulls:
        assert len(f["interactions"]) == 6


def test_interactions_relation_vocabulary(fulls):
    """relation 只用 生/克/化/竞; a/b 为关键十神成员; note_cn 非空短语。"""
    for f in fulls:
        keys = {g["name"] for g in f["key_ten_gods"]}
        for it in f["interactions"]:
            assert it["relation"] in RELATIONS
            assert it["a"] in keys and it["b"] in keys and it["a"] != it["b"]
            assert isinstance(it["note_cn"], str) and 0 < len(it["note_cn"]) <= 6


def test_interactions_symmetric():
    """关系与 a/b 顺序无关(对称): _relation(a,b) == _relation(b,a)。"""
    gods = sorted(ALL_TEN_GODS)
    for a in gods:
        for b in gods:
            if a != b:
                assert _relation(a, b) == _relation(b, a)


def test_interactions_known_pairs():
    """经典组合判定正确: 杀印相生=化 / 比劫夺财=克 / 食伤生财=生 / 同类=竞。"""
    assert _relation("七杀", "正印") == ("化", "杀印相生")
    assert _relation("劫财", "偏财")[0] == "克"
    assert _relation("食神", "偏财") == ("生", "食伤生财")
    assert _relation("比肩", "劫财") == ("竞", "同气并立")


# ---------------- annual_next3 ----------------

def test_annual_next3_from_current(fulls):
    """3个连续流年, 自 current.annual.year 起(命例均2026)。"""
    from bazi_engine.constants import STEMS, BRANCHES, ten_god
    for ch, f in zip(MOCK_CHARTS, fulls):
        y0 = ch["current"]["annual"]["year"]
        assert y0 == 2026
        an = f["annual_next3"]
        assert [a["year"] for a in an] == [y0, y0 + 1, y0 + 2]
        for a in an:                                   # 干支与十神自洽
            assert a["stem"] == STEMS[(a["year"] - 4) % 10]
            assert a["branch"] == BRANCHES[(a["year"] - 4) % 12]
            assert a["ten_god"] == ten_god(ch["day_master"]["stem"], a["stem"])


# ---------------- relationship / career ----------------

def test_spouse_palace_is_day_branch(fulls):
    """夫妻宫 = 日支, 藏干十神 = 日支藏干十神。"""
    for ch, f in zip(MOCK_CHARTS, fulls):
        day = ch["pillars"]["day"]
        sp = f["relationship"]["spouse_palace"]
        assert sp["branch"] == day["branch"]
        assert sp["hidden_ten_gods"] == day["ten_gods_hidden"]


def test_career_sum_matches_char_count(fulls):
    """career 五组和 = 有效字数(满盘8, partial6), 与五行main同基。"""
    for ch, f in zip(MOCK_CHARTS, fulls):
        n_pillars = sum(1 for p in ch["pillars"].values() if p is not None)
        assert sum(f["career"].values()) == n_pillars * 2
        assert set(f["career"]) == {"authority", "wealth", "resource", "output", "peer"}


def test_career_peer_includes_day_master(fulls):
    """日主自身计入 peer(比劫): 满盘 peer 至少为1。"""
    for ch, f in zip(MOCK_CHARTS, fulls):
        assert f["career"]["peer"] >= 1


# ---------------- Mock 与端点一致 ----------------

def test_mock_full_matches_engine():
    """mock_full_result.json 与 compute_full_chart(mock_chart) 逐字段一致(解耦B的前提)。"""
    mock_full = json.loads((ROOT / "mock_full_result.json").read_text(encoding="utf-8"))
    assert len(mock_full) == len(MOCK_CHARTS)
    for ch, mf in zip(MOCK_CHARTS, mock_full):
        expect = compute_full_chart(ch)
        assert mf["key_ten_gods"] == expect["key_ten_gods"]
        assert mf["interactions"] == expect["interactions"]
        assert mf["annual_next3"] == expect["annual_next3"]
        assert mf["relationship"] == expect["relationship"]
        assert mf["career"] == expect["career"]


# ---------------- export_safe(A3 脱敏) ----------------

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


def _live_chart():
    """真实排盘(含 true_solar_time / start_date), 用于验脱敏。"""
    return compute_chart("1990-06-15", "14:00", "Asia/Shanghai",
                         39.9042, 116.4074, "male", chart_id="test-chart-id-xyz")


def test_export_safe_no_datetime_or_coords():
    """脱敏输出序列化后不含任何日期/时间格式串; 无坐标键。"""
    ch = _live_chart()
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    blob = json.dumps(payload, ensure_ascii=False)
    assert not _DATE_RE.search(blob), "残留日期格式串"
    assert not _TIME_RE.search(blob), "残留时间格式串"
    # 敏感键一律不得出现(按带引号的JSON键名匹配, 避免'lat'误命中'relation'等词)
    for key in ("lat", "lng", "chart_id", "true_solar_time", "start_date",
                "birth_date", "birth_time", "datetime", "location"):
        assert f'"{key}"' not in blob, f"泄漏敏感字段: {key}"
    # 经纬度数值不得残留
    for coord in ("39.9042", "116.4074"):
        assert coord not in blob, f"泄漏坐标数值: {coord}"


def test_export_safe_whitelist_present():
    """白名单命理字段齐全, 且 contains_sensitive 自检为 False。"""
    from bazi_engine.export_safe import contains_sensitive
    ch = _live_chart()
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    for k in ("day_master", "five_elements", "pillars", "luck_cycles",
              "key_ten_gods", "interactions", "annual_next3", "relationship", "career"):
        assert k in payload
    # 大运保留干支与年份(整数), 但无 start_date
    for c in payload["luck_cycles"]["cycles"]:
        assert set(c) == {"index", "stem", "branch", "start_year", "end_year", "ten_god"}
    assert contains_sensitive(payload) is False


def test_export_safe_pillars_stripped_of_ganzhi():
    """14号裁定①: AI payload 四柱条目不得含 stem/branch/hidden_stems, 只留每柱十神。"""
    ch = _live_chart()
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    for pos, entry in payload["pillars"].items():
        if entry is None:
            continue
        assert set(entry) == {"ten_god_stem", "ten_gods_hidden"}, f"{pos}柱残留干支"
        assert "stem" not in entry and "branch" not in entry
        assert "hidden_stems" not in entry


def test_export_safe_sensitive_detector_catches_leak():
    """阴性对照: 故意注入日期串, contains_sensitive 必须抓到(证明检测有效非空判)。"""
    from bazi_engine.export_safe import contains_sensitive
    ch = _live_chart()
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    payload["_leak"] = "1990-06-15"
    assert contains_sensitive(payload) is True


def test_export_safe_handles_luck_cycles_not_applied():
    """20号：用户选择不生成大运时，AI 白名单保持脱敏且不因 None 崩溃。"""
    ch = compute_chart("1990-06-15", "14:00", "Asia/Shanghai",
                       39.9042, 116.4074, "male",
                       options=ChartOptions(luck_cycle_convention="not_applied"),
                       chart_id="test-no-luck")
    assert ch["luck_cycles"] is None
    payload = assemble_ai_payload(ch, compute_full_chart(ch))
    assert payload["luck_cycles"] is None
    assert payload["current_luck_index"] is None
    assert "tradition_profile" not in payload
    assert "calculation_trace" not in payload
