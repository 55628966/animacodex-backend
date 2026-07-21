# -*- coding: utf-8 -*-
"""运行回归命例库并生成 docs/测试报告.md(《01》第三节交付物)。

- 逐例重算引擎, 与 cases.json 的 expected 深度比对(复用 tests/test_regression.py 的比对逻辑);
- 报告含: 总数/通过/失败、按类别分布表、逐例明细表(id/类别/输入/期望四柱/实际四柱/结果/来源);
- 任何一例失败: 报告标红明细, 脚本退出码非0(供 run_tests.sh 汇总)。

用法(项目根目录): ./.venv/bin/python scripts/gen_test_report.py
"""
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from bazi_engine.core import ALGO_VERSION  # noqa: E402
from test_regression import CASES, DATA, NOW_UTC, compare_case, run_case  # noqa: E402

CAT_ZH = {"lichun_boundary": "立春边界(跨年柱)", "jie_boundary": "节交接边界(跨月柱)",
          "zi_hour": "早/晚子时(两流派)", "extreme_geo": "极端地理(真太阳时)",
          "luck_quadrant": "大运顺逆四象限", "start_age_extreme": "起运年龄极端值",
          "hour_unknown": "时辰未知(前三柱)", "random_regular": "随机常规"}


def fmt_pillars(pd):
    """四柱 dict -> '庚午 壬午 辛亥 甲午'(时柱null显示'—')。"""
    return " ".join(pd[k] if pd[k] else "—" for k in ("year", "month", "day", "hour"))


def fmt_input(case):
    i, o = case["input"], case["options"]
    return (f"{i['birth_date']} {i['birth_time'] or '时辰未知'} {i['timezone']} "
            f"({i['lat']},{i['lng']}) {'男' if i['sex'] == 'male' else '女'} "
            f"晚子{'换日' if o.get('late_zi_new_day', True) else '不换日'}")


def main():
    rows, fail_details = [], []
    passed = 0
    for case in CASES:
        exp_str = fmt_pillars(case["expected"]["pillars"])
        try:
            r = run_case(case)
            p = r["pillars"]
            got = {k: (p[k]["stem"] + p[k]["branch"]) if p[k] else None
                   for k in ("year", "month", "day", "hour")}
            got_str = fmt_pillars(got)
            diffs = compare_case(case, r)
        except Exception as e:  # 运行异常同样计失败
            got_str, diffs = "(运行异常)", [f"运行异常: {e!r}"]
        ok = not diffs
        passed += ok
        rows.append((case["id"], case["category"], fmt_input(case),
                     exp_str, got_str, "通过" if ok else "**失败**", case["source"]))
        if not ok:
            fail_details.append((case["id"], diffs))

    total = len(CASES)
    counts = {}
    for c in CASES:
        counts[c["category"]] = counts.get(c["category"], 0) + 1

    md = []
    md.append("# Anima Codex 排盘引擎 · 回归测试报告\n")
    md.append("> **命例来源清单已Owner拍板（2026-07-17，拍板项3）：紫金山天文台《中国天文年历》体系权威锚 / Swiss Ephemeris × lunar-python 双源准入 / sxtwl 第三对照。命理顾问对拍板项1/2的会签待补。**\n")
    md.append(f"- 引擎 algo_version: `{ALGO_VERSION}`")
    md.append(f"- 命例库: `tests/test_cases/cases.json`(共 {total} 例, "
              f"expected=引擎计算+lunar-python {DATA['meta']['lunar_python_version']} 双源核验一致; "
              f"双源不一致候选例见 `tests/test_cases/rejected.json`)")
    md.append(f"- 盲区规则: {DATA['meta']['blind_zone_rule']}")
    md.append(f"- 固定 now_utc: `{NOW_UTC.isoformat()}`(保证可复现)")
    md.append("- 生成命令: `./run_tests.sh` 或 `./.venv/bin/python scripts/gen_test_report.py`")
    md.append(f"- 报告生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    md.append(f"## 一、总览\n")
    md.append(f"- 命例总数: **{total}**")
    md.append(f"- 通过/失败: **{passed}/{total - passed}**"
              + ("（全部通过）" if passed == total else "（存在失败, 整体不通过）") + "\n")

    md.append("## 二、按类别分布\n")
    md.append("| 类别 | 说明 | 数量 | 通过 |")
    md.append("|---|---|---:|---:|")
    cat_pass = {}  # 类别 -> [总数, 通过数]
    for r in rows:
        cat_pass.setdefault(r[1], [0, 0])
        cat_pass[r[1]][0] += 1
        cat_pass[r[1]][1] += (r[5] == "通过")
    for cat in sorted(counts):
        n, p_ = cat_pass[cat]
        md.append(f"| {cat} | {CAT_ZH.get(cat, '')} | {n} | {p_} |")
    md.append(f"| **合计** | | **{total}** | **{passed}** |\n")

    md.append("## 三、逐例明细\n")
    md.append("| id | 类别 | 输入 | 期望四柱 | 实际四柱 | 结果 | 来源 |")
    md.append("|---|---|---|---|---|---|---|")
    for r in rows:
        md.append("| " + " | ".join(str(x) for x in r) + " |")
    md.append("")

    if fail_details:
        md.append("## 四、失败明细\n")
        for cid, diffs in fail_details:
            md.append(f"### {cid}\n")
            for d in diffs:
                md.append(f"- {d}")
            md.append("")

    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    out = os.path.join(ROOT, "docs", "测试报告.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"报告已生成: {out}")
    print(f"回归: {passed}/{total} 通过")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
