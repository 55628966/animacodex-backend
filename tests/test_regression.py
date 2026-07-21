# -*- coding: utf-8 -*-
"""回归命例库 pytest(《01》第三节: 验收的生死线)。

逐例重算引擎并与 tests/test_cases/cases.json 的 expected 深度比对:
四柱 / 日主 / 五行分布 / 大运方向 / 起运年龄 / 起运日期 / 前若干步大运干支 / partial。
任何一例任一字段不一致即失败, 并打印差异明细与完整输入。

命例来源: expected 由 bazi_engine 计算并经 lunar-python(1.4.8) 按交叉验证协议
逐例核验一致后入库(生成器: scripts/gen_cases.py, 双源不一致的候选例在
tests/test_cases/rejected.json)。命例来源三层清单已Owner拍板(2026-07-17, 拍板项3)。
now_utc 固定为 2026-07-17T00:00:00Z, 保证 current 块不随运行日期漂移、结果可复现。
"""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bazi_engine import ChartOptions, compute_chart  # noqa: E402

NOW_UTC = datetime(2026, 7, 17, tzinfo=timezone.utc)  # 与生成时一致, 固定可复现
CASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "test_cases", "cases.json")
with open(CASES_PATH, encoding="utf-8") as _f:
    DATA = json.load(_f)
CASES = DATA["cases"]

# 类别配额(任务书要求), 总数≥110
QUOTAS = {"lichun_boundary": 16, "jie_boundary": 22, "zi_hour": 12, "extreme_geo": 10,
          "luck_quadrant": 16, "start_age_extreme": 8, "hour_unknown": 8}


def run_case(case):
    """按命例输入与 options 重算引擎。"""
    inp, opt = case["input"], case.get("options", {})
    options = ChartOptions(
        late_zi_new_day=opt.get("late_zi_new_day", True),
        five_element_mode=opt.get("five_element_mode", "main"))
    return compute_chart(inp["birth_date"], inp["birth_time"], inp["timezone"],
                         inp["lat"], inp["lng"], inp["sex"],
                         options=options, now_utc=NOW_UTC)


def compare_case(case, r):
    """深度比对 expected 全部字段, 返回差异明细列表(空=完全一致)。"""
    diffs = []
    exp = case["expected"]

    # 四柱(时柱可为 null)
    p = r["pillars"]
    for k in ("year", "month", "day", "hour"):
        got = (p[k]["stem"] + p[k]["branch"]) if p[k] else None
        if got != exp["pillars"][k]:
            diffs.append(f"pillars.{k}: 期望={exp['pillars'][k]} 实际={got}")

    # 日主
    dm = r["day_master"]
    for k in ("stem", "element", "yin_yang"):
        if dm[k] != exp["day_master"][k]:
            diffs.append(f"day_master.{k}: 期望={exp['day_master'][k]} 实际={dm[k]}")

    # 五行分布(逐元素)
    for e in ("wood", "fire", "earth", "metal", "water"):
        if r["five_elements"].get(e) != exp["five_elements"].get(e):
            diffs.append(f"five_elements.{e}: 期望={exp['five_elements'].get(e)} "
                         f"实际={r['five_elements'].get(e)}")

    # 大运: 方向 / 起运年龄 / 起运日期 / 前若干步干支
    lc = r["luck_cycles"]
    if lc["direction"] != exp["direction"]:
        diffs.append(f"direction: 期望={exp['direction']} 实际={lc['direction']}")
    for k in ("years", "months"):
        if lc["start_age"][k] != exp["start_age"][k]:
            diffs.append(f"start_age.{k}: 期望={exp['start_age'][k]} 实际={lc['start_age'][k]}")
    if lc["start_date"] != exp["start_date"]:
        diffs.append(f"start_date: 期望={exp['start_date']} 实际={lc['start_date']}")
    got_cycles = [c["stem"] + c["branch"] for c in lc["cycles"][:len(exp["first_cycles"])]]
    if got_cycles != exp["first_cycles"]:
        diffs.append(f"first_cycles: 期望={exp['first_cycles']} 实际={got_cycles}")

    # partial 标志(时辰未知模式)
    got_partial = bool(r.get("partial", False))
    if got_partial != exp["partial"]:
        diffs.append(f"partial: 期望={exp['partial']} 实际={got_partial}")
    return diffs


def test_case_count_and_quota():
    """命例总数≥110 且各类别满足配额。"""
    assert len(CASES) >= 110, f"命例总数不足110: {len(CASES)}"
    counts = {}
    for c in CASES:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    for cat, quota in QUOTAS.items():
        assert counts.get(cat, 0) >= quota, \
            f"类别{cat}配额不足: {counts.get(cat, 0)}/{quota}"


def test_all_cases_lunar_verified():
    """入库命例必须全部带双源核验标记(盲区例需在notes注明)。"""
    for c in CASES:
        v = c["verification"]
        assert v["lunar_python_agrees"] or "盲区" in v.get("notes", ""), \
            f"{c['id']} 未经lunar-python核验且未注明盲区"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_regression_case(case):
    """逐例重算并深度比对; 不一致打印全部差异与输入上下文。"""
    r = run_case(case)
    diffs = compare_case(case, r)
    assert not diffs, (
        f"\n命例 {case['id']} ({case['category']}) 与期望不一致:\n  "
        + "\n  ".join(diffs)
        + f"\n输入: {case['input']}\noptions: {case['options']}"
        + f"\n来源: {case['source']}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
