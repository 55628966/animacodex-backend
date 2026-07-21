# -*- coding: utf-8 -*-
"""生成 mock_chart_result.json (第2周末交付物, 供模型B前端开发)。

《01》第六节要求: 3个真实可验证命例, 不同日主、不同五行分布、一男一女、
其中1例时辰未知; 逐字段符合契约schema, 正确性按100%标准。
本脚本: 引擎计算 + lunar-python 独立核验(四柱/顺逆/起运), 全部通过才写文件。
current 字段以固定基准日 2026-07-17 计算(写入说明供B知悉)。
避开1986-1991历史夏令时年份, 免去B在Mock阶段理解时制修正。
"""
import json
import sys
import os
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bazi_engine import compute_chart
from bazi_engine.true_solar import true_solar
from lunar_python import Solar

NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)
UTC8 = timezone(timedelta(hours=8))

CASES = [
    # (chart_id固定, 出生日期, 时间, 时区, 纬度, 经度, 城市, 性别)
    ("6f1a2b3c-0001-4a01-9a01-000000000001",
     "1988-03-25", "06:30", "Asia/Shanghai", 39.9042, 116.4074, "Beijing", "male"),
    ("6f1a2b3c-0002-4a02-9a02-000000000002",
     "1995-11-08", "21:15", "Asia/Shanghai", 30.5728, 104.0668, "Chengdu", "female"),
    ("6f1a2b3c-0003-4a03-9a03-000000000003",
     "2001-07-22", None, "Asia/Shanghai", 23.1291, 113.2644, "Guangzhou", "male"),
]


def verify_against_lunar(res, birth_date, birth_time, tz, lng, sex):
    """独立核验: 年/月柱(UTC+8挂钟), 日/时柱(真太阳时), 大运顺逆+起运。"""
    clock = datetime.fromisoformat(f"{birth_date}T{birth_time or '12:00'}")
    tst, _, _, birth_utc = true_solar(clock, tz, lng)
    cn = birth_utc.astimezone(UTC8).replace(tzinfo=None)

    ec = Solar.fromYmdHms(cn.year, cn.month, cn.day, cn.hour, cn.minute, cn.second) \
        .getLunar().getEightChar()
    p = res["pillars"]
    assert p["year"]["stem"] + p["year"]["branch"] == ec.getYear(), "年柱核验失败"
    assert p["month"]["stem"] + p["month"]["branch"] == ec.getMonth(), "月柱核验失败"

    if birth_time is not None:
        ec2 = Solar.fromYmdHms(tst.year, tst.month, tst.day, tst.hour, tst.minute,
                               tst.second).getLunar().getEightChar()
        ec2.setSect(1)  # 引擎默认 late_zi_new_day=True 对应流派1
        assert p["day"]["stem"] + p["day"]["branch"] == ec2.getDay(), "日柱核验失败"
        assert p["hour"]["stem"] + p["hour"]["branch"] == ec2.getTime(), "时柱核验失败"
    else:
        # 时辰未知: 日柱按公历日直接对照(lunar以12:00计不影响日柱, 该日无跨日争议)
        ecd = Solar.fromYmdHms(clock.year, clock.month, clock.day, 12, 0, 0) \
            .getLunar().getEightChar()
        assert p["day"]["stem"] + p["day"]["branch"] == ecd.getDay(), "日柱核验失败(partial)"
        assert res.get("partial") is True and p["hour"] is None, "partial口径核验失败"

    yun = ec.getYun(1 if sex == "male" else 0, 2)
    lc = res["luck_cycles"]
    assert (lc["direction"] == "forward") == yun.isForward(), "大运顺逆核验失败"
    assert lc["start_age"]["years"] == yun.getStartYear(), "起运岁数核验失败"
    lunar_dy = [d.getGanZhi() for d in yun.getDaYun()[1:4]]
    got = [c["stem"] + c["branch"] for c in lc["cycles"][:3]]
    assert got == lunar_dy, f"大运干支核验失败 {got} vs {lunar_dy}"


def main():
    out = []
    day_masters = set()
    for cid, bd, bt, tz, lat, lng, city, sex in CASES:
        res = compute_chart(bd, bt, tz, lat, lng, sex, chart_id=cid, now_utc=NOW)
        verify_against_lunar(res, bd, bt, tz, lng, sex)
        day_masters.add(res["day_master"]["stem"])
        out.append(res)
        p = res["pillars"]
        hour_str = (p["hour"]["stem"] + p["hour"]["branch"]) if p["hour"] else "时辰未知"
        print(f"√ {bd} {bt or 'null':>5} {city:9s} {sex:6s} 日主{res['day_master']['stem']}"
              f"({res['day_master']['element']}) 四柱: "
              f"{p['year']['stem']}{p['year']['branch']} {p['month']['stem']}{p['month']['branch']} "
              f"{p['day']['stem']}{p['day']['branch']} {hour_str} 五行{res['five_elements']}")
    assert len(day_masters) == 3, f"日主未做到各不相同: {day_masters}"
    fe = [json.dumps(r["five_elements"], sort_keys=True) for r in out]
    assert len(set(fe)) == 3, "五行分布未做到各不相同"

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "mock_chart_result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 {path} (3例, 全部通过双源核验)")


if __name__ == "__main__":
    main()
