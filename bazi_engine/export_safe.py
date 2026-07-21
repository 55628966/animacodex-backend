# -*- coding: utf-8 -*-
"""AI 入参脱敏装配(06号发布规划·安全修正1落地; 09号A3)。

铁律: 一切 AI 调用只准以本函数输出为入参。绝不把可回推真实生辰/居所的字段喂给模型。

剥除(白名单外一律不出):
- true_solar_time(其 datetime ≈ 生辰本身)
- birth_date / birth_time / 任何出生时刻(本就只在 request_json, 不在 ChartResult)
- location / lat / lng / 经纬度坐标
- chart_id(可关联落库记录)
- luck_cycles.start_date、start_age(可回推出生日附近)、meta.solar_terms_source 等无关字段
- **四柱 stem/branch/hidden_stems 干支**(14号裁定①, 2026-07-18): 四柱干支 + 大运 start_year
  可联合把生辰反推至 2 小时窗 ≈ 泄漏 birth_*。故每柱只保留【十神】(ten_god_stem/
  ten_gods_hidden), 不出干支符号。

保留白名单(命理语义, 不含个人可识别信息):
- 日主(日干/五行/阴阳)、五行计数
- 四柱【十神】(每柱 ten_god_stem/ten_gods_hidden, 无干支)
- 大运: 序号/干支/对日主十神/起止【年份】(整数年, 非日期串)、顺逆(09号A3明批, 14号未挑战)
- 当前流年、annual_next3(流年干支为公开历法, 非个人标识)
- 关键四十神/互动/夫妻宫十神/事业五组计数
"""
import re

# 日期时间格式串探测(用于自检断言): YYYY-MM-DD 或 HH:MM
_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\b\d{1,2}:\d{2}\b")


def assemble_ai_payload(chart: dict, full: dict) -> dict:
    """输入 ChartResult + FullChartData, 输出白名单脱敏 AI 入参 dict。"""
    def clean_pillar(p):
        # 14号裁定①: 剥四柱干支(stem/branch/hidden_stems), 每柱只留十神。
        if p is None:
            return None
        return {
            "ten_god_stem": p["ten_god_stem"],
            "ten_gods_hidden": list(p["ten_gods_hidden"]),
        }

    lc = chart["luck_cycles"]
    payload = {
        "algo_version": chart["meta"]["algo_version"],
        "partial": bool(chart.get("partial", False)),
        "day_master": dict(chart["day_master"]),
        "five_elements": dict(chart["five_elements"]),
        "pillars": {pos: clean_pillar(chart["pillars"].get(pos))
                    for pos in ("year", "month", "day", "hour")},
        "luck_cycles": None if lc is None else {
            "direction": lc["direction"],
            "cycles": [{"index": c["index"], "stem": c["stem"], "branch": c["branch"],
                        "start_year": c["start_year"], "end_year": c["end_year"],
                        "ten_god": c["ten_god"]}
                       for c in lc["cycles"]],
        },
        "current_luck_index": chart["current"]["luck_cycle_index"],
        "current_annual": dict(chart["current"]["annual"]),
        # FullChartData 全部为命理语义, 直接并入
        "key_ten_gods": full["key_ten_gods"],
        "interactions": full["interactions"],
        "annual_next3": full["annual_next3"],
        "relationship": full["relationship"],
        "career": full["career"],
    }
    return payload


def contains_sensitive(payload: dict) -> bool:
    """自检: 序列化后是否残留日期时间格式串(坐标为浮点, 白名单已无 lat/lng 键)。
    用于单测断言脱敏彻底(True=有泄漏)。"""
    import json
    blob = json.dumps(payload, ensure_ascii=False)
    return bool(_DATETIME_RE.search(blob))
