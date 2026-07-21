# -*- coding: utf-8 -*-
"""双源交叉验证: bazi_engine(节气源=sxtwl) vs lunar-python(独立实现)。

比较协议(消除真太阳时/夏令时干扰, 保证同一有效时刻对比):
- 年柱/月柱: 以绝对时刻为准。把 birth_utc 转成 UTC+8 挂钟表示喂给 lunar-python,
  与引擎的 UTC 精确节气比较结果对齐。
- 日柱/时柱: 引擎按真太阳时判定, 故把引擎算出的真太阳时直接喂给 lunar-python,
  两边判定同一时刻。晚子时用 lunar 的 sect1(换日)/sect2(不换日) 分别对照
  引擎 late_zi_new_day=True/False。
- 大运: 方向、起运(年/月/天)、前6步干支对照 lunar 的 Yun。
任何一处不一致即断言失败并打印完整上下文。
"""
import random
from datetime import datetime, timedelta, timezone

import pytest
from lunar_python import Solar

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bazi_engine import compute_chart, ChartOptions
from bazi_engine.core import day_and_hour_pillar, year_pillar, month_pillar
from bazi_engine.true_solar import true_solar
from bazi_engine.solar_terms import terms_of_year

UTC8 = timezone(timedelta(hours=8))
rng = random.Random(20260717)  # 固定种子, 可复现


def lunar_pillars(dt_naive, sect=2):
    ec = Solar.fromYmdHms(dt_naive.year, dt_naive.month, dt_naive.day,
                          dt_naive.hour, dt_naive.minute, dt_naive.second) \
        .getLunar().getEightChar()
    ec.setSect(sect)
    return ec.getYear(), ec.getMonth(), ec.getDay(), ec.getTime()


def engine_vs_lunar_one(clock_naive, sex="male"):
    """单例全字段对照。出生地固定东经120/Asia/Shanghai(挂钟即UTC+8*)。
    *1986-1991夏令时期间 IANA 为UTC+9, 协议自动通过 birth_utc 归一化。"""
    r = compute_chart(clock_naive.date().isoformat(),
                      clock_naive.strftime("%H:%M"),
                      "Asia/Shanghai", 31.23, 120.0, sex,
                      now_utc=datetime(2026, 7, 17, tzinfo=timezone.utc))
    tst, _, _, birth_utc = true_solar(clock_naive, "Asia/Shanghai", 120.0)

    # 年/月柱: 喂 UTC+8 挂钟表示。
    # 盲区: 距节±120秒内不做跨库断言(两库节气秒差≤94s+lunar分钟截断),
    # 该区间的精确性由 test_engine_internal_term_boundary 秒级保证。
    from bazi_engine.solar_terms import prev_and_next_jie
    pj, nj = prev_and_next_jie(birth_utc)
    near_jie = min((birth_utc - pj[1]).total_seconds(),
                   (nj[1] - birth_utc).total_seconds()) < 120
    cn_wall = birth_utc.astimezone(UTC8).replace(tzinfo=None)
    ly, lm, _, _ = lunar_pillars(cn_wall)
    p = r["pillars"]
    got_y = p["year"]["stem"] + p["year"]["branch"]
    got_m = p["month"]["stem"] + p["month"]["branch"]
    if not near_jie:
        assert got_y == ly and got_m == lm, \
            f"{clock_naive} 年/月柱不一致: engine={got_y},{got_m} lunar={ly},{lm}"

    # 日/时柱: 喂真太阳时, 两种晚子时流派都验
    for late_zi, sect in ((True, 1), (False, 2)):
        ds, db, hs, hb = day_and_hour_pillar(tst, late_zi)
        _, _, ld, lh = lunar_pillars(tst, sect)
        assert ds + db == ld and hs + hb == lh, \
            f"{clock_naive} TST={tst} sect{sect} 日/时柱不一致: " \
            f"engine={ds+db},{hs+hb} lunar={ld},{lh}"

    # 大运: 方向+起运年月天+前6步干支 (lunar 以挂钟UTC+8时刻计)。
    # 距节±120秒盲区内两库对"上一节/下一节"认定可差一秒级, 跳过跨库断言。
    if near_jie:
        return
    ec = Solar.fromYmdHms(cn_wall.year, cn_wall.month, cn_wall.day,
                          cn_wall.hour, cn_wall.minute, cn_wall.second) \
        .getLunar().getEightChar()
    yun = ec.getYun(1 if sex == "male" else 0, 2)  # 流派2=分钟级精确换算
    lc = r["luck_cycles"]
    assert (lc["direction"] == "forward") == yun.isForward(), f"{clock_naive} 大运顺逆不一致"
    # 起运: 折算成总命理分钟比较, 容差24分钟(=2命理天), 吸收两库节气秒级源差(实测≤52s)
    from datetime import date as _date
    from bazi_engine.core import _add_ym
    ya, ma = lc["start_age"]["years"], lc["start_age"]["months"]
    eng_extra_days = (_date.fromisoformat(lc["start_date"])
                      - _add_ym(clock_naive.date(), ya, ma, 0)).days
    eng_min = ya * 4320 + ma * 360 + eng_extra_days * 12
    lun_min = yun.getStartYear() * 4320 + yun.getStartMonth() * 360 + yun.getStartDay() * 12
    assert abs(eng_min - lun_min) <= 24, \
        f"{clock_naive} 起运不一致: engine={ya}年{ma}月{eng_extra_days}天 " \
        f"lunar={yun.getStartYear()}年{yun.getStartMonth()}月{yun.getStartDay()}天"
    lunar_dy = [d.getGanZhi() for d in yun.getDaYun()[1:7]]
    got_dy = [c["stem"] + c["branch"] for c in lc["cycles"][:6]]
    assert got_dy == lunar_dy, f"{clock_naive} 大运干支不一致: {got_dy} vs {lunar_dy}"


def test_random_fuzz_2000():
    """1902-2098 随机2000例, 男女各半。"""
    for i in range(2000):
        y = rng.randint(1902, 2098)
        dt = datetime(y, 1, 1) + timedelta(days=rng.randint(0, 364),
                                           minutes=rng.randint(0, 1439))
        engine_vs_lunar_one(dt, "male" if i % 2 == 0 else "female")


def test_solar_term_boundaries():
    """每8年取样, 全部12节交接时刻 ±1分钟 / ±1小时 各测: 跨月柱/年柱边界。"""
    from bazi_engine.constants import JIE_INDICES
    for y in range(1904, 2097, 8):
        for idx, t_utc in terms_of_year(y):
            if idx not in JIE_INDICES:
                continue
            wall = t_utc.astimezone(UTC8).replace(tzinfo=None)
            # ±2分钟起步: 两库节气源存在秒级差(实测最大52s), ±1分钟内不做跨库断言;
            # 引擎自身的秒级边界精确性由 test_engine_internal_term_boundary 保证
            for dm in (-60, -2, 2, 60):
                engine_vs_lunar_one(wall + timedelta(minutes=dm))


def test_zi_hour_boundaries():
    """早/晚子时边界: 22:59/23:00/23:59/00:00/00:59/01:00, 两流派均在单例内验证。"""
    for y in (1924, 1955, 1984, 2000, 2024, 2060):
        for m, d in ((1, 10), (6, 20), (12, 31)):
            for hh, mm in ((22, 59), (23, 0), (23, 59), (0, 0), (0, 59), (1, 0)):
                engine_vs_lunar_one(datetime(y, m, d, hh, mm))


def test_engine_internal_term_boundary():
    """引擎自身边界自洽: 对自己的节气源必须精确到秒。
    立春前1秒→旧年柱/丑月, 立春后1秒→新年柱/寅月; 各节前后1秒月柱必须切换。"""
    from bazi_engine.constants import JIE_INDICES, JIE_TO_MONTH_BRANCH, BRANCHES, STEMS
    from bazi_engine.solar_terms import lichun_utc
    for y in range(1901, 2100, 13):
        for idx, t_utc in terms_of_year(y):
            if idx not in JIE_INDICES:
                continue
            before, after = t_utc - timedelta(seconds=1), t_utc + timedelta(seconds=1)
            _, ys_b, _ = year_pillar(before)
            _, ys_a, _ = year_pillar(after)
            _, mb_b = month_pillar(before, ys_b)
            _, mb_a = month_pillar(after, ys_a)
            assert mb_a == BRANCHES[JIE_TO_MONTH_BRANCH[idx]], \
                f"{y}节{idx}后1秒月支应切换, got {mb_a}"
            assert mb_b != mb_a, f"{y}节{idx}前后1秒月支未切换"
            if idx == 3:  # 立春: 年柱切换
                sui_b, _, _ = year_pillar(before)
                sui_a, _, _ = year_pillar(after)
                assert sui_a == sui_b + 1 == y, f"{y}立春年柱切换错误"


def test_luck_quadrants():
    """阳年男/阳年女/阴年男/阴年女 四象限大运方向。"""
    for y, expect_yang in ((1990, True), (1991, False), (2000, True), (2015, False)):
        for sex in ("male", "female"):
            engine_vs_lunar_one(datetime(y, 6, 15, 10, 30), sex)


if __name__ == "__main__":
    import pytest as _p
    raise SystemExit(_p.main([__file__, "-x", "-q"]))
