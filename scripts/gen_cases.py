# -*- coding: utf-8 -*-
"""回归命例库生成器（一次性工具, 产出即证据链）。

生成 tests/test_cases/cases.json 与 tests/test_cases/rejected.json:
- expected 全部由 bazi_engine 计算, 禁止手填干支;
- 凡可对照处逐例经 lunar-python(1.4.8, 独立实现) 按交叉验证协议核验,
  任何一处不一致的候选例不入库, 写入 rejected.json 附原因;
- 比较协议与 tests/test_cross_validation.py 完全一致:
    年/月柱: 把引擎 birth_utc 转 UTC+8 挂钟喂 lunar-python;
    日/时柱: 把引擎算出的真太阳时喂 lunar-python, sect1=晚子换日 / sect2=不换日;
    大运:   方向 + 起运折算命理分钟(容差24分钟, 吸收两库节气秒级源差) + 前6步干支;
    盲区:   距节气交接±120秒内不做跨库断言 —— 本库全部命例按 ≥150秒 安全边界构造,
            因此库内每一例都是完整双源核验过的。
- 中国命例避开 Asia/Shanghai 历史夏令时窗口(1919/1940-1949/1986-1991 的 3-11 月)。

用法(项目根目录): ./.venv/bin/python scripts/gen_cases.py
"""
import json
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lunar_python import Solar  # noqa: E402

from bazi_engine import ChartOptions, compute_chart  # noqa: E402
from bazi_engine.core import ALGO_VERSION, _add_ym  # noqa: E402
from bazi_engine.solar_terms import (lichun_utc, prev_and_next_jie,  # noqa: E402
                                     terms_of_year)
from bazi_engine.true_solar import true_solar  # noqa: E402

UTC8 = timezone(timedelta(hours=8))
NOW_UTC = datetime(2026, 7, 17, tzinfo=timezone.utc)  # 固定, 保证可复现
SOURCE = ("三层来源(已拍板 2026-07-17): 权威锚=紫金山天文台《中国天文年历》体系"
          "(含GB/T 33661-2017); 双源准入=Swiss Ephemeris × lunar-python 1.4.8; "
          "第三对照=sxtwl 2.0.7")
SAFE_GAP_S = 150  # 距最近节的安全边界(>盲区120s: 两库节气秒差≤94s + lunar分钟截断)

# Asia/Shanghai 历史夏令时年份(IANA), 构造中国命例避开这些年的3-11月
CN_DST_YEARS = {1919} | set(range(1940, 1950)) | set(range(1986, 1992))

JIE_NAME = {1: "小寒", 3: "立春", 5: "惊蛰", 7: "清明", 9: "立夏", 11: "芒种",
            13: "小暑", 15: "立秋", 17: "白露", 19: "寒露", 21: "立冬", 23: "大雪"}

cases, rejected = [], []
_seq = [0]


def next_id():
    _seq[0] += 1
    return f"case_{_seq[0]:03d}"


def lunar_pillars(dt, sect=2):
    """lunar-python 四柱。sect1=晚子时换日, sect2=不换日。"""
    ec = Solar.fromYmdHms(dt.year, dt.month, dt.day,
                          dt.hour, dt.minute, dt.second).getLunar().getEightChar()
    ec.setSect(sect)
    return ec.getYear(), ec.getMonth(), ec.getDay(), ec.getTime()


def gap_to_jie(inp):
    """出生时刻(UTC)距最近节的秒数。"""
    clock = datetime.fromisoformat(f"{inp['birth_date']}T{inp['birth_time'] or '12:00'}")
    _, _, _, birth_utc = true_solar(clock, inp["timezone"], inp["lng"])
    pj, nj = prev_and_next_jie(birth_utc)
    return min((birth_utc - pj[1]).total_seconds(), (nj[1] - birth_utc).total_seconds())


def verify_with_lunar(inp, late_zi, r):
    """按交叉验证协议对照 lunar-python。返回 (是否一致, notes, 不一致原因)。"""
    birth_time = inp["birth_time"]
    clock = datetime.fromisoformat(f"{inp['birth_date']}T{birth_time or '12:00'}")
    tst, _, _, birth_utc = true_solar(clock, inp["timezone"], inp["lng"])
    pj, nj = prev_and_next_jie(birth_utc)
    gap = min((birth_utc - pj[1]).total_seconds(), (nj[1] - birth_utc).total_seconds())
    if gap < SAFE_GAP_S:
        return False, "", f"距最近节仅{gap:.0f}秒(<安全边界{SAFE_GAP_S}秒), 属跨库盲区, 不入库"

    problems = []
    p = r["pillars"]
    got = {k: (p[k]["stem"] + p[k]["branch"]) if p[k] else None
           for k in ("year", "month", "day", "hour")}

    # 年/月柱: 喂 UTC+8 挂钟(归一化消除夏令时/非东八区干扰)
    cn_wall = birth_utc.astimezone(UTC8).replace(tzinfo=None)
    ly, lm, _, _ = lunar_pillars(cn_wall)
    if got["year"] != ly:
        problems.append(f"年柱不一致 engine={got['year']} lunar={ly}")
    if got["month"] != lm:
        problems.append(f"月柱不一致 engine={got['month']} lunar={lm}")

    # 日/时柱
    if birth_time is None:
        # 时辰未知: 引擎日柱=公历日, 按该日正午喂 lunar(正午无子时边界干扰)
        _, _, ld, _ = lunar_pillars(datetime(clock.year, clock.month, clock.day, 12, 0))
        if got["day"] != ld:
            problems.append(f"日柱不一致(公历日正午对照) engine={got['day']} lunar={ld}")
        day_note = "时辰未知: 日柱按公历日正午对照; 时柱=null不对照"
    else:
        sect = 1 if late_zi else 2
        _, _, ld, lh = lunar_pillars(tst, sect)
        if got["day"] != ld:
            problems.append(f"日柱不一致(TST={tst}) engine={got['day']} lunar={ld}")
        if got["hour"] != lh:
            problems.append(f"时柱不一致(TST={tst}) engine={got['hour']} lunar={lh}")
        day_note = f"日/时柱按真太阳时{tst.replace(microsecond=0).isoformat()}对照(sect{sect})"

    # 大运: 方向 + 起运命理分钟(容差24) + 前6步干支 (lunar 以 UTC+8 挂钟时刻计, 流派2)
    ec = Solar.fromYmdHms(cn_wall.year, cn_wall.month, cn_wall.day,
                          cn_wall.hour, cn_wall.minute, cn_wall.second) \
        .getLunar().getEightChar()
    yun = ec.getYun(1 if inp["sex"] == "male" else 0, 2)
    lc = r["luck_cycles"]
    if (lc["direction"] == "forward") != yun.isForward():
        problems.append(f"大运顺逆不一致 engine={lc['direction']} lunar_forward={yun.isForward()}")
    ya, ma = lc["start_age"]["years"], lc["start_age"]["months"]
    extra_days = (date.fromisoformat(lc["start_date"]) - _add_ym(clock.date(), ya, ma, 0)).days
    eng_min = ya * 4320 + ma * 360 + extra_days * 12
    lun_min = (yun.getStartYear() * 4320 + yun.getStartMonth() * 360
               + yun.getStartDay() * 12)
    if abs(eng_min - lun_min) > 24:
        problems.append(f"起运不一致 engine={ya}年{ma}月{extra_days}天 "
                        f"lunar={yun.getStartYear()}年{yun.getStartMonth()}月{yun.getStartDay()}天")
    lunar_dy = [d.getGanZhi() for d in yun.getDaYun()[1:7]]
    got_dy = [c["stem"] + c["branch"] for c in lc["cycles"][:6]]
    if got_dy != lunar_dy:
        problems.append(f"大运干支不一致 engine={got_dy} lunar={lunar_dy}")

    if problems:
        return False, "", "; ".join(problems)
    notes = (f"四柱/大运方向/前6步大运干支与lunar-python一致; {day_note}; "
             f"距最近节{gap:.0f}秒(盲区外); 起运两库差{abs(eng_min - lun_min)}命理分钟(容差24)")
    return True, notes, ""


def add_case(category, birth_date, birth_time, tz, lat, lng, sex,
             late_zi=True, cid=None, extra_note=""):
    """引擎计算 expected -> lunar 核验 -> 一致入库, 不一致进 rejected。"""
    inp = {"birth_date": birth_date, "birth_time": birth_time, "timezone": tz,
           "lat": lat, "lng": lng, "sex": sex}
    r = compute_chart(birth_date, birth_time, tz, lat, lng, sex,
                      options=ChartOptions(late_zi_new_day=late_zi), now_utc=NOW_UTC)
    p = r["pillars"]
    lc = r["luck_cycles"]
    expected = {
        "pillars": {k: (p[k]["stem"] + p[k]["branch"]) if p[k] else None
                    for k in ("year", "month", "day", "hour")},
        "day_master": dict(r["day_master"]),
        "five_elements": dict(r["five_elements"]),
        "direction": lc["direction"],
        "start_age": dict(lc["start_age"]),
        "start_date": lc["start_date"],
        "first_cycles": [c["stem"] + c["branch"] for c in lc["cycles"][:3]],
        "partial": bool(r.get("partial", False)),
    }
    ok, notes, reason = verify_with_lunar(inp, late_zi, r)
    rec = {"id": cid or next_id(), "category": category, "input": inp,
           "options": {"late_zi_new_day": late_zi}, "expected": expected,
           "source": SOURCE,
           "verification": {"lunar_python_agrees": ok,
                            "notes": (extra_note + "; " if extra_note else "") + notes}}
    if ok:
        cases.append(rec)
        return rec
    rejected.append({"id": rec["id"], "category": category, "input": inp,
                     "options": rec["options"], "reason": reason})
    return None


def wall_near(t_utc, offset_min):
    """节气UTC时刻±offset分钟 -> UTC+8挂钟(秒截断, 供 birth_time 分钟精度输入)。"""
    return (t_utc + timedelta(minutes=offset_min)).astimezone(UTC8) \
        .replace(second=0, microsecond=0, tzinfo=None)


def jie_utc_of(year, idx):
    for i, t in terms_of_year(year):
        if i == idx:
            return t
    raise RuntimeError(f"{year}年未找到节idx={idx}")


# ---------- 1. lichun_boundary ≥16: 立春前后, 跨年柱 ----------
def gen_lichun():
    specs = [(1907, 4), (1929, 10), (1950, 60), (1968, 300),
             (1985, 25), (2024, 4), (2057, 90), (2091, 240)]
    for y, off in specs:
        t = lichun_utc(y)
        pair = {}
        for sign in (-1, 1):
            w = wall_near(t, sign * off)
            rec = add_case("lichun_boundary", w.date().isoformat(), w.strftime("%H:%M"),
                           "Asia/Shanghai", 31.23, 120.0,
                           "male" if sign < 0 else "female",
                           extra_note=f"{y}年立春{'前' if sign < 0 else '后'}约{off}分钟")
            pair[sign] = rec
        # 跨年柱/跨月柱自检: 立春两侧年柱与月柱必须都切换
        if pair[-1] and pair[1]:
            assert pair[-1]["expected"]["pillars"]["year"] != pair[1]["expected"]["pillars"]["year"], \
                f"{y}立春两侧年柱未切换"
            assert pair[-1]["expected"]["pillars"]["month"] != pair[1]["expected"]["pillars"]["month"], \
                f"{y}立春两侧月柱未切换"


# ---------- 2. jie_boundary ≥22: 其余11节前后, 跨月柱 ----------
def gen_jie():
    specs = [(1955, 5, 6), (1963, 7, 15), (1972, 9, 45), (1980, 11, 8),
             (1995, 13, 120), (2001, 15, 5), (2010, 17, 30), (2018, 19, 10),
             (2030, 21, 20), (2050, 23, 6), (2066, 1, 60)]
    for y, idx, off in specs:
        t = jie_utc_of(y, idx)
        pair = {}
        for sign in (-1, 1):
            w = wall_near(t, sign * off)
            rec = add_case("jie_boundary", w.date().isoformat(), w.strftime("%H:%M"),
                           "Asia/Shanghai", 31.23, 120.0,
                           "male" if sign < 0 else "female",
                           extra_note=f"{y}年{JIE_NAME[idx]}{'前' if sign < 0 else '后'}约{off}分钟")
            pair[sign] = rec
        if pair[-1] and pair[1]:
            assert pair[-1]["expected"]["pillars"]["month"] != pair[1]["expected"]["pillars"]["month"], \
                f"{y}{JIE_NAME[idx]}两侧月柱未切换"


# ---------- 3. zi_hour ≥12: 真太阳时子时窗口, 每例两种流派 _a/_b ----------
def gen_zi():
    specs = [("1975-03-08", "23:30", "male"), ("1984-10-01", "23:40", "female"),
             ("2000-12-31", "23:25", "male"), ("1958-06-21", "23:35", "female"),
             ("2012-07-15", "00:30", "male"), ("2025-01-01", "00:20", "female"),
             ("2040-04-15", "00:40", "male"), ("1995-09-09", "00:25", "female")]
    for d, hm, sex in specs:
        clock = datetime.fromisoformat(f"{d}T{hm}")
        tst, _, _, _ = true_solar(clock, "Asia/Shanghai", 120.0)
        assert tst.hour in (23, 0), f"{d} {hm} 真太阳时{tst}不在子时窗口, 需换时刻"
        window = "晚子时23:00-24:00" if tst.hour == 23 else "早子时00:00-01:00"
        base = next_id()
        for suffix, lz in (("_a", True), ("_b", False)):
            add_case("zi_hour", d, hm, "Asia/Shanghai", 31.23, 120.0, sex,
                     late_zi=lz, cid=base + suffix,
                     extra_note=f"真太阳时{tst.strftime('%H:%M:%S')}({window}); "
                                f"流派: late_zi_new_day={'true换日' if lz else 'false不换日'}")


# ---------- 4. extreme_geo ≥10: 真太阳时修正量大或跨日 ----------
def gen_geo():
    specs = [
        ("喀什", 39.47, 75.99, "Asia/Shanghai", "1970-05-10", "08:30", "male"),
        ("喀什(真太阳时跨日回前一天)", 39.47, 75.99, "Asia/Shanghai", "2018-01-01", "01:30", "female"),
        ("乌鲁木齐", 43.83, 87.62, "Asia/Shanghai", "2005-11-20", "21:00", "male"),
        ("拉萨", 29.65, 91.13, "Asia/Shanghai", "1999-08-18", "06:10", "female"),
        ("雷克雅未克(高纬)", 64.15, -21.94, "Atlantic/Reykjavik", "1988-06-15", "14:00", "male"),
        ("雷克雅未克(真太阳时跨日)", 64.15, -21.94, "Atlantic/Reykjavik", "2020-12-21", "00:10", "female"),
        ("惠灵顿(南半球+夏令时)", -41.29, 174.78, "Pacific/Auckland", "2003-02-10", "03:00", "male"),
        ("纽约(夏令时)", 40.71, -74.01, "America/New_York", "1969-07-20", "22:56", "female"),
        ("伦敦", 51.51, -0.13, "Europe/London", "1961-01-15", "09:45", "male"),
        ("圣保罗(南半球+夏令时)", -23.55, -46.63, "America/Sao_Paulo", "1990-12-25", "23:30", "female"),
    ]
    for city, lat, lng, tz, d, hm, sex in specs:
        clock = datetime.fromisoformat(f"{d}T{hm}")
        tst, corr, _, _ = true_solar(clock, tz, lng)
        add_case("extreme_geo", d, hm, tz, lat, lng, sex,
                 extra_note=f"{city}; 真太阳时修正{corr:+.1f}分钟, TST={tst.replace(microsecond=0).isoformat()}")


# ---------- 5. luck_quadrant ≥16: 阳/阴年 × 男/女 × 多年代 ----------
def gen_luck():
    specs = [("1924-06-15", "10:30", "甲子·阳年"), ("1937-10-20", "08:00", "丁丑·阴年"),
             ("1956-03-18", "16:20", "丙申·阳年"), ("1967-12-01", "21:15", "丁未·阴年"),
             ("1988-11-20", "06:45", "戊辰·阳年"), ("1999-06-30", "13:05", "己卯·阴年"),
             ("2008-05-18", "18:40", "戊子·阳年"), ("2021-07-07", "09:55", "辛丑·阴年")]
    for d, hm, tag in specs:
        for sex in ("male", "female"):
            add_case("luck_quadrant", d, hm, "Asia/Shanghai", 31.23, 120.0, sex,
                     extra_note=f"{tag} × {'男' if sex == 'male' else '女'}: 验大运顺逆与干支序列")


# ---------- 6. start_age_extreme ≥8: 距节3-30分钟 / 距下节仅几分钟 ----------
def gen_start_age():
    specs = [(1953, 11, 5), (1978, 19, 12), (2015, 21, -6), (2062, 7, -20)]
    for y, idx, off in specs:
        t = jie_utc_of(y, idx)
        w = wall_near(t, off)
        side = (f"{JIE_NAME[idx]}后约{off}分钟(逆排起运趋近0岁, 顺排趋近满值)" if off > 0
                else f"{JIE_NAME[idx]}前约{-off}分钟(顺排起运趋近0岁, 逆排趋近满值)")
        for sex in ("male", "female"):
            add_case("start_age_extreme", w.date().isoformat(), w.strftime("%H:%M"),
                     "Asia/Shanghai", 31.23, 120.0, sex,
                     extra_note=f"{y}年{side}")


# ---------- 7. hour_unknown ≥8: birth_time=null, 前三柱口径 ----------
def gen_hour_unknown():
    specs = [("1912-02-20", "male"), ("1935-07-15", "female"),
             ("1976-08-08", "male"), ("1993-01-10", "female"),
             ("2003-04-18", "male"), ("2027-09-30", "female"),
             ("2055-06-16", "male"), ("2088-12-12", "female")]
    for d, sex in specs:
        rec = add_case("hour_unknown", d, None, "Asia/Shanghai", 39.9042, 116.4074, sex,
                       extra_note="时辰未知: 验 partial=true / hour=null / 五行按6字口径")
        if rec:
            assert rec["expected"]["partial"] is True and rec["expected"]["pillars"]["hour"] is None
            assert sum(rec["expected"]["five_elements"].values()) == 6, "6字口径五行总数应为6"


# ---------- 8. random_regular: 1902-2098 随机补足 ----------
def gen_random(n_target=18):
    rng = random.Random(20260717)  # 固定种子, 可复现
    n = 0
    while n < n_target:
        y = rng.randint(1902, 2098)
        dt = datetime(y, 1, 1) + timedelta(days=rng.randint(0, 364),
                                           minutes=rng.randint(0, 1439))
        if y in CN_DST_YEARS and 3 <= dt.month <= 11:
            continue  # 避开中国历史夏令时窗口
        inp = {"birth_date": dt.date().isoformat(), "birth_time": dt.strftime("%H:%M"),
               "timezone": "Asia/Shanghai", "lng": 120.0}
        if gap_to_jie(inp) < SAFE_GAP_S:
            continue  # 随机撞进盲区安全边界则重抽(非双源不一致, 不计rejected)
        sex = "male" if n % 2 == 0 else "female"
        if add_case("random_regular", dt.date().isoformat(), dt.strftime("%H:%M"),
                    "Asia/Shanghai", 31.23, 120.0, sex,
                    extra_note="随机常规例(种子20260717)"):
            n += 1


QUOTAS = {"lichun_boundary": 16, "jie_boundary": 22, "zi_hour": 12, "extreme_geo": 10,
          "luck_quadrant": 16, "start_age_extreme": 8, "hour_unknown": 8}


def main():
    gen_lichun()
    gen_jie()
    gen_zi()
    gen_geo()
    gen_luck()
    gen_start_age()
    gen_hour_unknown()
    gen_random(18)

    counts = {}
    for c in cases:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    for cat, q in QUOTAS.items():
        assert counts.get(cat, 0) >= q, f"类别{cat}配额不足: {counts.get(cat, 0)}/{q}"
    assert len(cases) >= 110, f"总数不足110: {len(cases)}"

    out_dir = os.path.join(ROOT, "tests", "test_cases")
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "meta": {
            "description": "Anima Codex 排盘引擎回归命例库(《01》第三节)。expected由bazi_engine计算并经lunar-python双源核验一致后入库。",
            "engine_algo_version": ALGO_VERSION,
            "lunar_python_version": "1.4.8",
            "generated_by": "scripts/gen_cases.py (随机部分种子20260717)",
            "generated_at": "2026-07-17",
            "now_utc_fixed": "2026-07-17T00:00:00+00:00",
            "blind_zone_rule": "距节气交接±120秒内不做跨库断言; 本库全部命例按距节≥150秒构造, 均为完整双源核验",
            "source_confirmation": ("来源清单已Owner拍板(2026-07-17, 拍板项3): "
                                    "紫金山天文台《中国天文年历》体系为权威锚 / "
                                    "SwissEph×lunar-python双源准入 / sxtwl第三对照"),
            "total": len(cases),
            "category_counts": counts,
        },
        "cases": cases,
    }
    with open(os.path.join(out_dir, "cases.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "rejected.json"), "w", encoding="utf-8") as f:
        json.dump({"description": "双源核验不一致而被拒的候选命例(不入库)",
                   "rejected_count": len(rejected), "rejected": rejected},
                  f, ensure_ascii=False, indent=1)

    print(f"入库 {len(cases)} 例, 被拒 {len(rejected)} 例")
    for cat in sorted(counts):
        print(f"  {cat}: {counts[cat]}")
    if rejected:
        print("被拒明细:")
        for rj in rejected:
            print(f"  {rj['id']} {rj['category']}: {rj['reason']}")


if __name__ == "__main__":
    main()
