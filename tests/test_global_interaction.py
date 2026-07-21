# -*- coding: utf-8 -*-
"""30号 A组 — GlobalInteractionEngine 完整测试 (≥30条)

测试对象为模块的真实 API:
- bazi_engine.global_interaction: GraphNode/GraphEdge/KeyPath/GlobalInteractionGraph,
  NodeType/Wuxing/EdgeType 枚举, BRANCH_CLASH/BRANCH_COMBINE/GENERATES/CONTROLS/FIERCE_GODS,
  build_interaction_graph(), graph_to_dict()
- bazi_engine.interaction_layers: origin_layer/first_scroll_layer/full_layer/oracle_layer

build_interaction_graph 的输入 chart_result 需要的键（照模块实际读取构造）:
- pillars: {"year"|"month"|"day"|"hour": {"stem": 干, "branch": 支}}
- hidden_stems: {柱名: [藏干...]}
- ten_gods: {"{柱}_stem": 十神, "{柱}_hidden_{i}": 十神}
- day_master_stem: 日主天干（当前实现读取后未使用，日主以 pillar=="day" 判定）

规格缺项 / 集成缺陷对应的测试以 @pytest.mark.xfail(strict=False) 标注，
逐条清单见测试文件末尾注释与最终报告。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bazi_engine.constants import HIDDEN_STEMS, STEMS, ten_god
from bazi_engine.core import compute_chart
from bazi_engine.global_interaction import (
    BRANCH_CLASH, BRANCH_COMBINE, CONTROLS, FIERCE_GODS, GENERATES,
    EdgeType, GlobalInteractionGraph, GraphEdge, GraphNode, KeyPath,
    NodeType, Wuxing,
    build_interaction_graph, graph_to_dict,
)
from bazi_engine.interaction_layers import (
    first_scroll_layer, full_layer, oracle_layer, origin_layer,
)

# ── 辅助 ──

GODS_CASE = (("丙", "午"), ("壬", "子"), ("庚", "申"), ("戊", "寅"))  # 日主庚金


def _make_chart(*gzs):
    """按 build_interaction_graph 实际读取的键构造 chart_result。
    gzs: (年,月,日,时) 四组 (天干, 地支)；某一柱传 None 表示该柱键缺失。"""
    names = ["year", "month", "day", "hour"]
    day_stem = gzs[2][0]
    pillars, hidden, tg = {}, {}, {}
    for name, gz in zip(names, gzs):
        if gz is None:
            continue
        stem, branch = gz
        pillars[name] = {"stem": stem, "branch": branch}
        hs = list(HIDDEN_STEMS[branch])
        hidden[name] = hs
        tg[f"{name}_stem"] = ten_god(day_stem, stem)
        for i, h in enumerate(hs):
            tg[f"{name}_hidden_{i}"] = ten_god(day_stem, h)
    return {
        "chart_id": "test",
        "pillars": pillars,
        "day_master_stem": day_stem,
        "hidden_stems": hidden,
        "ten_gods": tg,
    }


def _gods_graph():
    return build_interaction_graph(_make_chart(*GODS_CASE))


def _edges(g, edge_type):
    return [e for e in g.edges if e.edge_type == edge_type]


# ══ 1. 图构建：节点 = 四柱天干 + 地支 + 藏干 ══

def test_gods_case_node_count():
    """God's case: 4干 + 4支 + 9藏干(午2/子1/申3/寅3) = 17 节点。"""
    g = _gods_graph()
    assert len(g.nodes) == 17


def test_stem_nodes_count_and_type():
    g = _gods_graph()
    stems = [n for n in g.nodes if n.node_type == NodeType.STEM]
    assert len(stems) == 4
    assert {n.id for n in stems} == {"year_stem", "month_stem", "day_stem", "hour_stem"}


def test_branch_nodes_count_and_type():
    g = _gods_graph()
    branches = [n for n in g.nodes if n.node_type == NodeType.BRANCH]
    assert len(branches) == 4
    assert {n.id for n in branches} == {"year_branch", "month_branch", "day_branch", "hour_branch"}


def test_hidden_stem_nodes_count_and_type():
    g = _gods_graph()
    hidden = [n for n in g.nodes if n.node_type == NodeType.HIDDEN_STEM]
    assert len(hidden) == 9  # 午藏丁己 / 子藏癸 / 申藏庚壬戊 / 寅藏甲丙戊
    assert "year_hidden_0" in {n.id for n in hidden}


def test_day_master_marked_on_day_stem():
    g = _gods_graph()
    dm = [n for n in g.nodes if n.is_day_master]
    assert len(dm) == 1
    assert dm[0].id == "day_stem"
    assert dm[0].node_type == NodeType.STEM


def test_node_elements_correct():
    """丙=火 壬=水 庚=金 戊=土；午=火 子=水 申=金 寅=木。"""
    g = _gods_graph()
    nm = {n.id: n for n in g.nodes}
    assert nm["year_stem"].element == Wuxing.FIRE
    assert nm["month_stem"].element == Wuxing.WATER
    assert nm["day_stem"].element == Wuxing.METAL
    assert nm["hour_stem"].element == Wuxing.EARTH
    assert nm["year_branch"].element == Wuxing.FIRE
    assert nm["month_branch"].element == Wuxing.WATER
    assert nm["day_branch"].element == Wuxing.METAL
    assert nm["hour_branch"].element == Wuxing.WOOD


def test_node_ten_gods_wired():
    """庚日主: 丙=七杀 壬=食神 戊=偏印 庚=比肩。"""
    g = _gods_graph()
    nm = {n.id: n for n in g.nodes}
    assert nm["year_stem"].ten_god == "七杀"
    assert nm["month_stem"].ten_god == "食神"
    assert nm["hour_stem"].ten_god == "偏印"
    assert nm["day_stem"].ten_god == "比肩"
    assert nm["year_branch"].ten_god is None  # 地支节点无十神


def test_node_labels_contain_ganzhi():
    g = _gods_graph()
    nm = {n.id: n for n in g.nodes}
    assert "丙" in nm["year_stem"].label_cn
    assert "子" in nm["month_branch"].label_cn
    assert "癸" in nm["month_hidden_0"].label_cn


def test_partial_chart_missing_hour_key():
    """缺时柱（hour 键不存在）: 引擎容错，仅 14 节点（寅3藏/辰3藏/午2藏）。"""
    g = build_interaction_graph(_make_chart(("甲", "寅"), ("丙", "辰"), ("戊", "午"), None))
    assert len(g.nodes) == 14
    assert all(n.pillar != "hour" for n in g.nodes)


def test_partial_chart_hour_none_tolerated():
    """真实 ChartResult（core.compute_chart）缺时柱时 pillars['hour']=None，引擎不应崩溃。"""
    chart = _make_chart(("甲", "寅"), ("丙", "辰"), ("戊", "午"), None)
    chart["pillars"]["hour"] = None
    g = build_interaction_graph(chart)
    assert len(g.nodes) == 14


# ══ 2. 边生成：生/克/冲/合（刑/害/天干五合/三合为规格缺项，见 xfail） ══

def test_generate_edge_exists():
    """木生火: 甲(年干)→丙(月干)，weight=+1.0。"""
    g = build_interaction_graph(_make_chart(("甲", "寅"), ("丙", "辰"), ("戊", "午"), ("庚", "申")))
    gen = _edges(g, EdgeType.GENERATE)
    assert any(e.source == "year_stem" and e.target == "month_stem" and e.weight == 1.0
               for e in gen)


def test_generate_edge_reverse_direction():
    """生者→被生者单向: 丙不生甲，故无 month_stem→year_stem 的生边。"""
    g = build_interaction_graph(_make_chart(("甲", "寅"), ("丙", "辰"), ("戊", "午"), ("庚", "申")))
    gen = _edges(g, EdgeType.GENERATE)
    assert not any(e.source == "month_stem" and e.target == "year_stem" for e in gen)


def test_control_edge_exists():
    """火克金: 丙(年干)→庚(日干)，weight=-1.0。"""
    g = _gods_graph()
    ctrl = _edges(g, EdgeType.CONTROL)
    assert any(e.source == "year_stem" and e.target == "day_stem" and e.weight == -1.0
               for e in ctrl)


def test_clash_edge_zi_wu():
    """子午冲: 年支午 ↔ 月支子，weight=-1.5。"""
    g = _gods_graph()
    clash = _edges(g, EdgeType.CLASH)
    assert any({e.source, e.target} == {"year_branch", "month_branch"} and e.weight == -1.5
               for e in clash)


def test_clash_edge_yin_shen():
    """寅申冲: 日支申 ↔ 时支寅（God's case 第二条冲）。"""
    g = _gods_graph()
    clash = _edges(g, EdgeType.CLASH)
    assert any({e.source, e.target} == {"day_branch", "hour_branch"} for e in clash)


def test_clash_edges_unique_per_pair():
    """同一对地支只生成一条冲边（无双向重复）。"""
    g = _gods_graph()
    pairs = [frozenset((e.source, e.target)) for e in _edges(g, EdgeType.CLASH)]
    assert len(pairs) == len(set(pairs))


def test_combine_edge_liu_he():
    """地支六合: 午未合（日支配午 / 年支未），weight=+1.5。"""
    g = build_interaction_graph(_make_chart(("己", "未"), ("丁", "丑"), ("庚", "午"), ("壬", "寅")))
    comb = _edges(g, EdgeType.COMBINE)
    assert any({e.source, e.target} == {"year_branch", "day_branch"} and e.weight == 1.5
               for e in comb)


def test_edges_only_between_related_elements():
    """生/克边仅存在于五行有生克关系的节点对（不产生同五行生克边）。"""
    g = _gods_graph()
    nm = {n.id: n for n in g.nodes}
    for e in g.edges:
        if e.edge_type == EdgeType.GENERATE:
            assert GENERATES[nm[e.source].element] == nm[e.target].element
        elif e.edge_type == EdgeType.CONTROL:
            assert CONTROLS[nm[e.source].element] == nm[e.target].element


def test_no_self_loop_edges():
    g = _gods_graph()
    assert all(e.source != e.target for e in g.edges)


def test_all_edge_types_valid_enum():
    g = _gods_graph()
    for e in g.edges:
        assert isinstance(e.edge_type, EdgeType)
        assert e.source and e.target and e.description_cn


@pytest.mark.xfail(reason="30号规格缺项：刑(Punishment)边未生成——EdgeType.PUNISH 枚举存在，"
                          "但建边逻辑只实现六冲/六合，无地支相刑规则（§2.2 边类型表）",
                   strict=False)
def test_punish_edge_yin_si_shen():
    """寅巳申三刑: 命例含寅、申，应生成刑边（weight=-0.5）。"""
    g = build_interaction_graph(_make_chart(("丙", "寅"), ("壬", "子"), ("庚", "申"), ("戊", "午")))
    pun = _edges(g, EdgeType.PUNISH)
    assert any({e.source, e.target} == {"year_branch", "day_branch"} for e in pun)


@pytest.mark.xfail(reason="30号规格缺项：害(Harm)边未生成——EdgeType.HARM 枚举存在，"
                          "但建边逻辑无地支相害规则（§2.2 边类型表，如子未害）",
                   strict=False)
def test_harm_edge_zi_wei():
    """子未害: 命例含子、未，应生成害边（weight=-0.5）。"""
    g = build_interaction_graph(_make_chart(("甲", "子"), ("丙", "未"), ("戊", "午"), ("庚", "申")))
    har = _edges(g, EdgeType.HARM)
    assert any({e.source, e.target} == {"year_branch", "month_branch"} for e in har)


@pytest.mark.xfail(reason="30号规格缺项：天干五合未生成——合(Combine)仅实现地支六合，"
                          "缺 §2.2 要求的天干五合（如甲己合）",
                   strict=False)
def test_stem_combine_jia_ji():
    """甲己合: 年干甲、月干己应生成合边。"""
    g = build_interaction_graph(_make_chart(("甲", "寅"), ("己", "巳"), ("戊", "午"), ("庚", "申")))
    comb = _edges(g, EdgeType.COMBINE)
    assert any({e.source, e.target} == {"year_stem", "month_stem"} for e in comb)


@pytest.mark.xfail(reason="30号规格缺项：地支三合/三会未生成——合(Combine)仅实现六合，"
                          "缺 §2.2 要求的三合局（如申子辰）与三会",
                   strict=False)
def test_three_way_combine_shen_zi_chen():
    """申子辰三合水局: 三支同盘应产生合关系。"""
    g = build_interaction_graph(_make_chart(("庚", "申"), ("壬", "子"), ("甲", "辰"), ("丙", "寅")))
    comb = _edges(g, EdgeType.COMBINE)
    trio = {"year_branch", "month_branch", "day_branch"}
    hit = [e for e in comb if {e.source, e.target} <= trio]
    assert len(hit) >= 2  # 三合至少应连成两条合边才成局


# ══ 3. 关系表/枚举一致性 ══

def test_branch_clash_symmetric():
    for k, v in BRANCH_CLASH.items():
        assert BRANCH_CLASH[v] == k


def test_branch_clash_six_pairs():
    """六冲: 子午/丑未/寅申/卯酉/辰戌/巳亥。"""
    assert len(BRANCH_CLASH) == 12
    assert BRANCH_CLASH[1] == 7 and BRANCH_CLASH[3] == 9 and BRANCH_CLASH[6] == 12


def test_branch_combine_symmetric():
    for k, v in BRANCH_COMBINE.items():
        assert BRANCH_COMBINE[v] == k


def test_generate_cycle_consistent():
    """相生环: 木→火→土→金→水→木。"""
    assert GENERATES[Wuxing.WOOD] == Wuxing.FIRE
    assert GENERATES[Wuxing.FIRE] == Wuxing.EARTH
    assert GENERATES[Wuxing.EARTH] == Wuxing.METAL
    assert GENERATES[Wuxing.METAL] == Wuxing.WATER
    assert GENERATES[Wuxing.WATER] == Wuxing.WOOD


def test_control_cycle_consistent():
    """相克环: 木→土→水→火→金→木；且相克目标≠相生目标。"""
    assert CONTROLS[Wuxing.WOOD] == Wuxing.EARTH
    assert CONTROLS[Wuxing.EARTH] == Wuxing.WATER
    assert CONTROLS[Wuxing.WATER] == Wuxing.FIRE
    assert CONTROLS[Wuxing.FIRE] == Wuxing.METAL
    assert CONTROLS[Wuxing.METAL] == Wuxing.WOOD
    for e in Wuxing:
        assert CONTROLS[e] != GENERATES[e]


def test_fierce_gods_complete():
    assert FIERCE_GODS == {"七杀", "伤官", "劫财", "偏印"}


# ══ 4. 净能量计算 ══

def test_net_energy_all_nodes_present():
    g = _gods_graph()
    for n in g.nodes:
        assert n.id in g.net_energy


def test_net_energy_matches_documented_formula():
    """净能量 = Σ生入边权重 − Σ克出边|权重| (+2.0 日主加权)，逐节点验证。"""
    g = _gods_graph()
    for n in g.nodes:
        inflow = sum(e.weight for e in g.edges
                     if e.target == n.id and e.edge_type == EdgeType.GENERATE)
        outflow = sum(abs(e.weight) for e in g.edges
                      if e.source == n.id and e.edge_type == EdgeType.CONTROL)
        expected = inflow - outflow + (2.0 if n.is_day_master else 0.0)
        assert g.net_energy[n.id] == pytest.approx(expected), n.id


def test_day_master_bonus_applied():
    """日主额外 +2.0: 庚(生入2·克出0) + 2.0 = 4.0。"""
    g = _gods_graph()
    inflow = sum(e.weight for e in g.edges
                 if e.target == "day_stem" and e.edge_type == EdgeType.GENERATE)
    outflow = sum(abs(e.weight) for e in g.edges
                  if e.source == "day_stem" and e.edge_type == EdgeType.CONTROL)
    assert inflow - outflow == 2.0
    assert g.net_energy["day_stem"] == pytest.approx(4.0)


def test_controlled_fierce_god_energy_negative():
    """被壬癸水围克又泄于金的丙(七杀): 净能量 -1.0（生入2·克出3）。"""
    g = _gods_graph()
    assert g.net_energy["year_stem"] == pytest.approx(-1.0)
    assert g.net_energy["year_stem"] < 0


@pytest.mark.xfail(reason="30号规格缺项：净能量未按 §2.3 计入克/冲等负权入边"
                          "（实现只算生入边−克出边），受六重金克的甲日主净能量+4.0 且误诊'日主偏强'",
                   strict=False)
def test_weak_day_master_diagnosed_weak():
    """庚申 辛酉 甲寅 壬子(甲日主): 六节点克日主，应判偏弱而非偏强。"""
    g = build_interaction_graph(_make_chart(("庚", "申"), ("辛", "酉"), ("甲", "寅"), ("壬", "子")))
    assert "偏弱" in g.global_diagnosis


# ══ 5. 关键路径：制化 / 通关 / 连锁 ══

def test_gods_case_zhihua_food_god_controls_seven_killings():
    """食神制杀: 壬(食神)克丙(七杀)，路径制化成功。"""
    g = _gods_graph()
    zh = [p for p in g.key_paths if p.path_type == "制化"]
    assert any(p.nodes == ["month_stem", "year_stem"] and p.result == "制化成功"
               and "食神" in p.description_cn and "七杀" in p.description_cn
               for p in zh)


def test_gods_case_zhihua_count_three_fierce_controlled():
    """God's case: 3 个凶神被制（丙×2 + 癸），诊断含'凶神3处被制'。"""
    g = _gods_graph()
    zh = [p for p in g.key_paths if p.path_type == "制化"]
    fierce_controlled = {p.nodes[1] for p in zh}
    assert fierce_controlled == {"year_stem", "month_hidden_0", "hour_hidden_1"}
    assert "凶神3处被制" in g.global_diagnosis


def test_gods_case_tongguan_identified():
    """通关链: 甲(偏财)生丙(七杀)→七杀克庚(日主)·缓冲成立。"""
    g = _gods_graph()
    tg = [p for p in g.key_paths if p.path_type == "通关"]
    assert len(tg) >= 1
    assert any(p.nodes == ["hour_hidden_0", "year_stem", "day_stem"]
               and p.result == "缓冲成立" for p in tg)


def test_tongguan_path_structure():
    """通关路径恒为 [通关者C, 凶神A, 被克者B] 三节，C 必带十神。"""
    g = _gods_graph()
    nm = {n.id: n for n in g.nodes}
    for p in g.key_paths:
        if p.path_type == "通关":
            assert len(p.nodes) == 3
            assert nm[p.nodes[0]].ten_god  # C 有十神
            assert nm[p.nodes[1]].ten_god in FIERCE_GODS  # A 是凶神


def test_chain_reaction_identified():
    """连锁反应: 丑冲未 但 未合午 → 冲被解开。"""
    g = build_interaction_graph(_make_chart(("己", "未"), ("丁", "丑"), ("庚", "午"), ("壬", "寅")))
    chains = [p for p in g.key_paths if p.path_type == "连锁"]
    assert any(p.nodes == ["month_branch", "year_branch", "day_branch"]
               and p.result == "冲被解开" for p in chains)


def test_key_path_fields_complete():
    """每条关键路径: path_type 合法、nodes≥2、描述与结果非空。"""
    g = _gods_graph()
    assert len(g.key_paths) > 0
    for p in g.key_paths:
        assert p.path_type in ("制化", "通关", "连锁")
        assert len(p.nodes) >= 2
        assert p.description_cn
        assert p.result in ("制化成功", "生扶更凶", "缓冲成立", "冲被解开")


@pytest.mark.xfail(reason="30号规格缺项：生扶链未实现——§2.3 步骤3b 要求识别"
                          "'凶神被生/合→能量为正=被生旺(更凶)'，实现仅输出制化/通关/连锁",
                   strict=False)
def test_support_chain_for_fostered_fierce_god():
    """戊(偏印,凶神)得丙火生扶 → 应识别生扶链并判'生扶更凶'。"""
    g = _gods_graph()
    support = [p for p in g.key_paths if p.path_type == "生扶"]
    assert any(p.result == "生扶更凶" for p in support)


# ══ 6. God's case（丙午 壬子 庚申 戊寅，日主庚金）完整演算 ══

def test_gods_case_clash_edges_exactly_two():
    """两条冲边: 子午冲 + 寅申冲。"""
    g = _gods_graph()
    clash_pairs = {frozenset((e.source, e.target)) for e in _edges(g, EdgeType.CLASH)}
    assert clash_pairs == {frozenset(("year_branch", "month_branch")),
                           frozenset(("day_branch", "hour_branch"))}


def test_gods_case_no_combine_edges():
    """God's case 无六合关系 → 0 条合边。"""
    g = _gods_graph()
    assert len(_edges(g, EdgeType.COMBINE)) == 0


def test_gods_case_edge_type_counts():
    """完整演算回归: 生56 / 克58 / 冲2，共 116 条边。"""
    g = _gods_graph()
    assert len(_edges(g, EdgeType.GENERATE)) == 56
    assert len(_edges(g, EdgeType.CONTROL)) == 58
    assert len(_edges(g, EdgeType.CLASH)) == 2
    assert len(g.edges) == 116


def test_gods_case_dominant_flow():
    """主导能量流向: 日主庚金吸纳 4.0。"""
    g = _gods_graph()
    assert g.dominant_flow == "day干庚:吸纳能量(4.0)"


def test_gods_case_global_diagnosis():
    """全局诊断: 日主偏强 + 凶神3处被制 + 通关成立（含'七杀'制的语义）。"""
    g = _gods_graph()
    assert "日主偏强" in g.global_diagnosis
    assert "凶神3处被制" in g.global_diagnosis
    assert "通关成立" in g.global_diagnosis


def test_gods_case_seven_killings_controlled_by_food_god_path():
    """Owner 例题核心结论: 丙七杀被壬食神克制，凶转吉有据。"""
    g = _gods_graph()
    paths = {(p.path_type, tuple(p.nodes)) for p in g.key_paths}
    assert ("制化", ("month_stem", "year_stem")) in paths
    # 壬水通关缓冲: 甲生丙→丙克庚 的缓冲链亦成立
    assert ("通关", ("hour_hidden_0", "year_stem", "day_stem")) in paths


def test_gods_case_day_master_strongest_node():
    """日主庚金净能量 4.0，为全图最高（吸纳主导）。"""
    g = _gods_graph()
    top = max(g.net_energy.items(), key=lambda x: x[1])
    assert top[0] == "day_stem"
    assert top[1] == pytest.approx(4.0)


# ══ 7. 不同日主不同视角 ══

def test_different_day_master_different_ten_gods():
    """同一丙火: 甲日主→食神，庚日主→七杀。"""
    g_jia = build_interaction_graph(_make_chart(("丙", "午"), ("壬", "子"), ("甲", "申"), ("戊", "寅")))
    g_geng = _gods_graph()
    s_jia = next(n for n in g_jia.nodes if n.id == "year_stem")
    s_geng = next(n for n in g_geng.nodes if n.id == "year_stem")
    assert s_jia.ten_god == "食神"
    assert s_geng.ten_god == "七杀"
    assert s_jia.ten_god != s_geng.ten_god


def test_strong_day_master_high_energy():
    """戊日主得丁丙双印生: 净能量显著为正。"""
    g = build_interaction_graph(_make_chart(("丁", "巳"), ("丙", "午"), ("戊", "辰"), ("己", "未")))
    assert g.net_energy["day_stem"] >= 2.0
    assert "日主偏强" in g.global_diagnosis


def test_day_master_has_incoming_control_edges():
    """甲日主遇庚辛官杀: 至少一条克边指向日主。"""
    g = build_interaction_graph(_make_chart(("庚", "申"), ("辛", "酉"), ("甲", "寅"), ("壬", "子")))
    ctrl = [e for e in g.edges if e.target == "day_stem" and e.edge_type == EdgeType.CONTROL]
    assert len(ctrl) >= 1


# ══ 8. 序列化 ══

def test_graph_to_dict_json_serializable():
    g = _gods_graph()
    d = graph_to_dict(g)
    assert set(d.keys()) == {"nodes", "edges", "key_paths", "dominant_flow", "global_diagnosis"}
    blob = json.dumps(d, ensure_ascii=False)
    assert len(blob) > 100


def test_graph_to_dict_content_consistent():
    """序列化结果与图对象一致（节点数/边数/日主净能量）。"""
    g = _gods_graph()
    d = graph_to_dict(g)
    assert len(d["nodes"]) == len(g.nodes)
    assert len(d["edges"]) == len(g.edges)
    assert len(d["key_paths"]) == len(g.key_paths)
    dm = next(n for n in d["nodes"] if n["is_day_master"])
    assert dm["net_energy"] == pytest.approx(4.0)
    assert d["dominant_flow"] == g.dominant_flow


# ══ 9. 分层输出 ══

def test_origin_layer_nodes_only():
    """origin 免费层: 仅节点清单，无边。"""
    g = _gods_graph()
    layer = origin_layer(g)
    assert layer["tier"] == "origin"
    assert layer["node_count"] == len(g.nodes) == 17
    assert len(layer["nodes"]) == len(g.nodes)
    assert "edges" not in layer
    # 节点序列化口径与 graph_to_dict 一致
    dm = next(n for n in layer["nodes"] if n["is_day_master"])
    assert dm["id"] == "day_stem" and dm["net_energy"] == pytest.approx(4.0)


def test_first_scroll_layer_core_edges_and_one_path():
    """first_scroll 层: 核心边（生克冲合） + 1 条关键路径。"""
    g = _gods_graph()
    layer = first_scroll_layer(g)
    assert layer["tier"] == "first_scroll"
    assert "edges" in layer and "sample_key_path" in layer
    assert layer["edge_count"] == len(layer["edges"])
    assert 0 < layer["edge_count"] <= len(g.edges)  # 仅核心边子集
    # 核心边只剩生/克/冲/合
    assert {e["type"] for e in layer["edges"]} <= {"生", "克", "冲", "合"}
    assert layer["sample_key_path"] is not None
    assert set(layer["sample_key_path"]) == {"type", "nodes", "desc", "result"}


def test_full_layer_has_everything():
    """full 层: 全部边 + 全部关键路径 + 全局诊断 + 主导流向。"""
    g = _gods_graph()
    layer = full_layer(g)
    assert layer["tier"] == "full"
    assert layer["edge_count"] == len(g.edges) == 116
    assert len(layer["key_paths"]) == len(g.key_paths)
    assert layer["global_diagnosis"] == g.global_diagnosis
    assert layer["dominant_flow"] == g.dominant_flow


def test_oracle_layer_falls_back_with_context():
    """oracle 层: 当前返回 full 数据 + 占位说明；cycle 参数预留。"""
    g = _gods_graph()
    layer = oracle_layer(g)
    assert layer["tier"] == "oracle"
    assert "oracle_context" in layer
    assert layer["edge_count"] == len(g.edges)  # full 数据兜底
    layer2 = oracle_layer(g, cycle={"year": 2026, "stem": "丙", "branch": "午"})
    assert layer2["oracle_context"]["cycle"]["year"] == 2026


# ══ 10. API 集成契约 ══

def test_api_main_expected_entrypoints_exist():
    """api/main.py 与 core.py 期望的引擎入口（graph_from_chart_result + 分层函数）存在。"""
    from bazi_engine import global_interaction
    assert callable(getattr(global_interaction, "graph_from_chart_result", None))
    assert callable(getattr(global_interaction, "build_interaction_graph", None))
    assert callable(getattr(global_interaction, "graph_to_dict", None))


def test_adapter_from_real_chart_result():
    """适配器: 真实 ChartResult 键结构 → 完整图（含藏干节点与十神）。"""
    from bazi_engine.global_interaction import graph_from_chart_result
    chart = compute_chart("1990-06-15", "14:00", "Asia/Shanghai",
                          39.9042, 116.4074, "male", chart_id="adapter-test")
    g = graph_from_chart_result(chart)
    assert len(g.nodes) >= 16  # 4干+4支+藏干
    assert any(n.node_type == NodeType.HIDDEN_STEM for n in g.nodes)
    assert any(n.ten_god for n in g.nodes if n.node_type == NodeType.STEM)
    assert len(g.edges) > 0
    dm = [n for n in g.nodes if n.is_day_master]
    assert len(dm) == 1


def test_adapter_partial_chart_result():
    """适配器: partial（无时辰）ChartResult → 三柱图，无 hour 节点，不崩溃。"""
    from bazi_engine.global_interaction import graph_from_chart_result
    chart = compute_chart("1990-06-15", None, "Asia/Shanghai",
                          39.9042, 116.4074, "male", chart_id="adapter-partial")
    assert chart["pillars"]["hour"] is None  # 真实 partial 形态
    g = graph_from_chart_result(chart)
    assert len(g.nodes) > 0
    assert all(n.pillar != "hour" for n in g.nodes)
    assert not any(n.is_day_master is False and n.pillar == "hour" for n in g.nodes)


# ══ 11. API 端到端集成（TestClient，隔离 DB） ══

@pytest.fixture(scope="module")
def api_client(tmp_path_factory):
    """与 test_api.py 同口径的隔离 DB + TestClient。"""
    import os
    db_file = tmp_path_factory.mktemp("gi-api-db") / "anima-gi-test.db"
    previous = {name: os.environ.get(name)
                for name in ("ANIMA_DB_PATH", "ANIMA_OWNER_SECRET_PEPPER")}
    os.environ["ANIMA_DB_PATH"] = str(db_file)
    os.environ["ANIMA_OWNER_SECRET_PEPPER"] = "test-only-owner-pepper"
    try:
        from fastapi.testclient import TestClient
        import api.main as main
        with TestClient(main.app, raise_server_exceptions=False) as c:
            yield c, main
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


_BASE_REQ = {
    "birth_date": "1990-06-15",
    "birth_time": "14:00",
    "timezone": "Asia/Shanghai",
    "location": {"lat": 39.9042, "lng": 116.4074, "city": "Beijing"},
    "sex": "male",
}


def _post(client, main, **overrides):
    resp = client.post("/api/v1/chart", json={**_BASE_REQ, **overrides})
    assert resp.status_code == 200, resp.text
    secret = resp.headers.get(main.CHART_OWNER_SECRET_HEADER)
    return resp.json(), {main.CHART_OWNER_SECRET_HEADER: secret}


def test_api_post_chart_global_interaction(api_client):
    """POST /chart（活体例）: global_interaction 非 None、节点>0、为 origin 层。"""
    client, _main = api_client
    body, _headers = _post(client, _main)
    gi = body["global_interaction"]
    assert gi is not None
    assert gi["tier"] == "origin"
    assert gi["node_count"] > 0
    assert len(gi["nodes"]) == gi["node_count"]
    assert "edges" not in gi  # 免费层仅节点清单（30号 A3）
    # 完整时辰: 四柱干/支节点齐全
    ids = {n["id"] for n in gi["nodes"]}
    assert {"year_stem", "month_stem", "day_stem", "hour_stem"} <= ids


def test_api_full_global_interaction(api_client):
    """GET /chart/{id}/full: global_interaction_full 非 None、edges>0、含 key_paths。"""
    client, _main = api_client
    body, headers = _post(client, _main)
    resp = client.get(f"/api/v1/chart/{body['chart_id']}/full", headers=headers)
    assert resp.status_code == 200, resp.text
    gif = resp.json()["global_interaction_full"]
    assert gif is not None
    assert gif["tier"] == "full"
    assert gif["edge_count"] > 0
    assert len(gif["edges"]) == gif["edge_count"]
    assert "key_paths" in gif
    assert "global_diagnosis" in gif and gif["global_diagnosis"]
    assert "dominant_flow" in gif and gif["dominant_flow"]


def test_api_partial_chart_global_interaction(api_client):
    """partial（birth_time=None）: 两端点不 500，global_interaction 正常、无 hour 节点。"""
    client, _main = api_client
    body, headers = _post(client, _main, birth_time=None)
    gi = body["global_interaction"]
    assert gi is not None
    assert gi["node_count"] > 0
    assert all(n["pillar"] != "hour" for n in gi["nodes"])

    resp = client.get(f"/api/v1/chart/{body['chart_id']}/full", headers=headers)
    assert resp.status_code == 200, resp.text
    gif = resp.json()["global_interaction_full"]
    assert gif is not None
    assert len(gif["nodes"]) > 0
    assert all(n["pillar"] != "hour" for n in gif["nodes"])
