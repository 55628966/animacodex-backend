# -*- coding: utf-8 -*-
"""全卷数据 FullChartData 计算(09号 M3第一单 A组)。

纯函数: 输入已排好的 ChartResult dict, 输出 FullChartData dict。不重算命盘、
不触网、不落库、无随机——完全由 ChartResult 既有字段派生, 保证与 /chart 结果一致。
全部中文原术语, 零叙事文案(英文转码与叙事归模型B)。

口径规则(选取/关系/计数)见 docs/口径文档_排盘算法_待签字.md §11,
标注【v1.0, 命理顾问会签待补】, 与既有拍板项一并送签。
"""
from .constants import HIDDEN_STEMS, STEMS, BRANCHES, TEN_GOD_CATEGORY, ten_god

# 透出天干补入优先级(日干=自身, 不计); 藏干补入按地支出现先后。
_STEM_FILL_ORDER = ("month", "hour", "year")
_BRANCH_SCAN_ORDER = ("year", "month", "day", "hour")


def _pillar(chart, pos):
    return chart["pillars"].get(pos)


def key_ten_gods(chart: dict) -> list:
    """关键四十神, 恰4个(选取规则v1.0):
      rank1 = 月支主气十神(month_branch_main);
      再按 透出天干(月>时>年, 日干=自身不计) 去重补入;
      不足4个按 地支藏干出现频次(高→低, 同频按 年<月<日<时、支内本>中>余 先出现者优先) 补入。
    partial(无时辰)命例同规则, 天然仍可凑满4个(三柱含足够十神种类)。
    """
    day_stem = chart["day_master"]["stem"]
    chosen = []          # [(name, position)]
    seen = set()

    def add(name, position):
        if name not in seen:
            seen.add(name)
            chosen.append({"name": name, "position": position, "rank": len(chosen) + 1})

    # rank1: 月支本气十神
    month = _pillar(chart, "month")
    if month and month["hidden_stems"]:
        add(ten_god(day_stem, month["hidden_stems"][0]), "month_branch_main")

    # 透出天干补入(月>时>年), 日干为自身不计
    for pos in _STEM_FILL_ORDER:
        if len(chosen) >= 4:
            break
        p = _pillar(chart, pos)
        if p:
            add(p["ten_god_stem"], f"{pos}_stem")

    # 藏干按频次补入
    if len(chosen) < 4:
        freq, first_seen = {}, {}
        order = 0
        for pos in _BRANCH_SCAN_ORDER:
            p = _pillar(chart, pos)
            if not p:
                continue
            for h in p["hidden_stems"]:
                tg = ten_god(day_stem, h)
                freq[tg] = freq.get(tg, 0) + 1
                if tg not in first_seen:
                    first_seen[tg] = (order, pos)
                order += 1
        # 高频优先, 同频按首次出现顺序
        for tg in sorted(freq, key=lambda t: (-freq[t], first_seen[t][0])):
            if len(chosen) >= 4:
                break
            add(tg, f"{first_seen[tg][1]}_branch_hidden")

    return chosen[:4]


def _relation(a: str, b: str):
    """两十神互动关系(对称, 与a/b顺序无关)。返回 (relation, note_cn)。
    词表限定 生/克/化/竞(09号要求):
      同类别 → 竞(同占一功能位, 相互竞立);
      官杀×印 → 化(杀印/官印相生, 化克为生护身, 特判先于'生');
      生克循环相邻(生) → 生; 相克循环相邻 → 克。
    note_cn 为经典简称(2-4字), 非叙事。"""
    ca, cb = TEN_GOD_CATEGORY[a], TEN_GOD_CATEGORY[b]
    if ca == cb:
        return "竞", "同气并立"
    pair = {ca, cb}
    # 官杀 + 印: 化(杀印相生 / 官印相生)
    if pair == {"authority", "resource"}:
        note = "杀印相生" if "七杀" in (a, b) else "官印相生"
        return "化", note
    # 相生循环: resource->peer->output->wealth->authority->resource
    gen_next = {"resource": "peer", "peer": "output", "output": "wealth",
                "wealth": "authority", "authority": "resource"}
    if gen_next[ca] == cb or gen_next[cb] == ca:
        note = {
            frozenset({"peer", "output"}): "比劫生食伤",
            frozenset({"output", "wealth"}): "食伤生财",
            frozenset({"wealth", "authority"}): "财官相生",
            frozenset({"resource", "peer"}): "印生身",
        }[frozenset(pair)]
        return "生", note
    # 相克循环: peer->wealth->resource->output->authority->peer
    ctl_next = {"peer": "wealth", "wealth": "resource", "resource": "output",
                "output": "authority", "authority": "peer"}
    note_ctl = {
        frozenset({"peer", "wealth"}): "比劫夺财",
        frozenset({"wealth", "resource"}): "财破印",
        frozenset({"resource", "output"}): "枭神夺食" if "偏印" in (a, b) else "印制食伤",
        frozenset({"output", "authority"}): "伤官见官" if "伤官" in (a, b) else "食神制杀",
        frozenset({"authority", "peer"}): "官杀攻身",
    }
    if ctl_next[ca] == cb or ctl_next[cb] == ca:
        return "克", note_ctl[frozenset(pair)]
    return "克", "相制"  # 兜底(五类间必为生或克, 不应到达)


def interactions(key_gods: list) -> list:
    """key_ten_gods 两两互动关系(去重无序对, 恰 C(n,2) 条, n=4→6条)。对称。"""
    names = [g["name"] for g in key_gods]
    out = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            rel, note = _relation(names[i], names[j])
            out.append({"a": names[i], "b": names[j], "relation": rel, "note_cn": note})
    return out


def annual_next3(chart: dict) -> list:
    """自当前流年(current.annual.year)起连续3个干支流年 + 对日主十神。"""
    day_stem = chart["day_master"]["stem"]
    y0 = chart["current"]["annual"]["year"]
    out = []
    for y in (y0, y0 + 1, y0 + 2):
        stem = STEMS[(y - 4) % 10]
        branch = BRANCHES[(y - 4) % 12]
        out.append({"year": y, "stem": stem, "branch": branch,
                    "ten_god": ten_god(day_stem, stem)})
    return out


def relationship(chart: dict) -> dict:
    """夫妻宫 = 日支; hidden_ten_gods = 日支藏干十神(供叙事层, 禁确定性预言)。"""
    day = _pillar(chart, "day")
    return {"spouse_palace": {"branch": day["branch"],
                              "hidden_ten_gods": list(day["ten_gods_hidden"])}}


def career(chart: dict) -> dict:
    """五组计数(官杀/财/印/食伤/比劫), 与五行main口径同基: 逐字(天干+地支本气)各计1,
    日干=自身(比肩→peer)。满盘8字, partial(无时辰)6字。"""
    counts = {"authority": 0, "wealth": 0, "resource": 0, "output": 0, "peer": 0}
    day_stem = chart["day_master"]["stem"]
    for pos in _BRANCH_SCAN_ORDER:
        p = _pillar(chart, pos)
        if not p:
            continue
        counts[TEN_GOD_CATEGORY[p["ten_god_stem"]]] += 1               # 天干
        counts[TEN_GOD_CATEGORY[ten_god(day_stem, p["hidden_stems"][0])]] += 1  # 地支本气
    return counts


def compute_full_chart(chart: dict) -> dict:
    """由 ChartResult 派生 FullChartData(纯函数, 与命盘结果强一致)。"""
    kg = key_ten_gods(chart)
    return {
        "key_ten_gods": kg,
        "interactions": interactions(kg),
        "annual_next3": annual_next3(chart),
        "relationship": relationship(chart),
        "career": career(chart),
    }
