"""
全局互动引擎 (Global Interaction Engine) — 八字图计算

将八字从"两两关系枚举"升级为"全局图计算"。
节点: 天干/地支/藏干/十神
边: 生/克/冲/合/刑/害
输出: 净能量图 + 关键路径(制化链/通关链/连锁反应) + 全局诊断

Owner 2026-07-20 签发。不生成面向用户的文本，输出为机器可读结构。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ══════════════════════════════════════════════
# 基础枚举
# ══════════════════════════════════════════════

class NodeType(Enum):
    STEM = "坐天干"
    BRANCH = "坐地支"
    HIDDEN_STEM = "藏干"
    TEN_GOD = "十神"


class Wuxing(Enum):
    WOOD = "木"; FIRE = "火"; EARTH = "土"; METAL = "金"; WATER = "水"


class EdgeType(Enum):
    GENERATE = "生"
    CONTROL = "克"
    CLASH = "冲"
    COMBINE = "合"
    PUNISH = "刑"
    HARM = "害"
    MEDIATION = "通关"
    CHAIN = "连锁"


# 五行生克
GENERATES = {Wuxing.WOOD:Wuxing.FIRE, Wuxing.FIRE:Wuxing.EARTH, Wuxing.EARTH:Wuxing.METAL,
             Wuxing.METAL:Wuxing.WATER, Wuxing.WATER:Wuxing.WOOD}
CONTROLS = {Wuxing.WOOD:Wuxing.EARTH, Wuxing.EARTH:Wuxing.WATER, Wuxing.WATER:Wuxing.FIRE,
            Wuxing.FIRE:Wuxing.METAL, Wuxing.METAL:Wuxing.WOOD}

# 地支冲合
BRANCH_CLASH = {1:7, 7:1, 2:8, 8:2, 3:9, 9:3, 4:10, 10:4, 5:11, 11:5, 6:12, 12:6}
BRANCH_COMBINE = {1:2, 2:1, 3:12, 12:3, 4:11, 11:4, 5:10, 10:5, 6:9, 9:6, 7:8, 8:7}

# 地支五行
BRANCH_WX_MAP = {1:Wuxing.WATER, 2:Wuxing.EARTH, 3:Wuxing.WOOD, 4:Wuxing.WOOD,
                 5:Wuxing.EARTH, 6:Wuxing.FIRE, 7:Wuxing.FIRE, 8:Wuxing.EARTH,
                 9:Wuxing.METAL, 10:Wuxing.METAL, 11:Wuxing.EARTH, 12:Wuxing.WATER}

# 天干五行
STEM_WX_MAP = {1:Wuxing.WOOD, 2:Wuxing.WOOD, 3:Wuxing.FIRE, 4:Wuxing.FIRE,
               5:Wuxing.EARTH, 6:Wuxing.EARTH, 7:Wuxing.METAL, 8:Wuxing.METAL,
               9:Wuxing.WATER, 10:Wuxing.WATER}

# 凶神列表（需被制化）
FIERCE_GODS = {"七杀","伤官","劫财","偏印"}


# ══════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════

@dataclass
class GraphNode:
    id: str                          # "year_stem","month_branch_main", 等
    node_type: NodeType
    element: Wuxing
    pillar: str                      # "year"|"month"|"day"|"hour"
    ten_god: Optional[str] = None    # 十神中文名(仅天干/藏干)
    is_day_master: bool = False
    label_cn: str = ""               # 显示中文名

@dataclass
class GraphEdge:
    source: str                      # node id
    target: str                      # node id
    edge_type: EdgeType
    weight: float
    description_cn: str

@dataclass
class KeyPath:
    path_type: str                   # "制化"|"通关"|"连锁"
    nodes: list[str]                 # 路径上的节点ID序列
    description_cn: str
    result: str                      # "制化成功"|"生扶更凶"|"缓冲成立"|"冲被解开"

@dataclass
class GlobalInteractionGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    net_energy: dict[str, float]            # node_id → 净能量
    key_paths: list[KeyPath]
    dominant_flow: str                      # 主能量流向描述
    global_diagnosis: str                   # 全局诊断(中文)


# ══════════════════════════════════════════════
# 图构建
# ══════════════════════════════════════════════

def build_interaction_graph(chart_result: dict) -> GlobalInteractionGraph:
    """
    从 ChartResult (dict) 构建全局互动图。
    
    输入: chart_result['pillars'] + chart_result['meta']['ten_gods'] + chart_result['hidden_stems']
    输出: 完整图结构
    """
    nodes = []
    edges = []
    day_stem = chart_result.get('day_master_stem', '')
    
    # --- 提取数据 ---
    pillars = chart_result.get('pillars', {})
    hidden = chart_result.get('hidden_stems', {})
    ten_gods_map = chart_result.get('ten_gods', {})
    
    stem_wx_values = {'甲':Wuxing.WOOD, '乙':Wuxing.WOOD, '丙':Wuxing.FIRE, '丁':Wuxing.FIRE,
                      '戊':Wuxing.EARTH, '己':Wuxing.EARTH, '庚':Wuxing.METAL, '辛':Wuxing.METAL,
                      '壬':Wuxing.WATER, '癸':Wuxing.WATER}
    branch_wx_values = {'子':Wuxing.WATER, '丑':Wuxing.EARTH, '寅':Wuxing.WOOD, '卯':Wuxing.WOOD,
                        '辰':Wuxing.EARTH, '巳':Wuxing.FIRE, '午':Wuxing.FIRE, '未':Wuxing.EARTH,
                        '申':Wuxing.METAL, '酉':Wuxing.METAL, '戌':Wuxing.EARTH, '亥':Wuxing.WATER}
    branch_val_map = {'子':1, '丑':2, '寅':3, '卯':4, '辰':5, '巳':6,
                      '午':7, '未':8, '申':9, '酉':10, '戌':11, '亥':12}
    
    # --- 1. 构建节点 ---
    pillar_order = ['year', 'month', 'day', 'hour']
    for pillar in pillar_order:
        p = pillars.get(pillar) or {}  # partial 命例 hour 可能为 None
        stem = p.get('stem', '')
        branch = p.get('branch', '')
        is_dm = (pillar == 'day')
        
        if stem:
            wx = stem_wx_values.get(stem, Wuxing.EARTH)
            tg = ten_gods_map.get(f'{pillar}_stem', '')
            nodes.append(GraphNode(
                id=f'{pillar}_stem', node_type=NodeType.STEM,
                element=wx, pillar=pillar, ten_god=tg,
                is_day_master=is_dm, label_cn=f'{pillar}干{stem}'
            ))
        if branch:
            wx = branch_wx_values.get(branch, Wuxing.EARTH)
            nodes.append(GraphNode(
                id=f'{pillar}_branch', node_type=NodeType.BRANCH,
                element=wx, pillar=pillar, label_cn=f'{pillar}支{branch}'
            ))
        
        # 藏干
        hidden_list = hidden.get(pillar, [])
        for i, hs in enumerate(hidden_list):
            if isinstance(hs, dict):
                h_stem = hs.get('stem', '')
            else:
                h_stem = str(hs)
            if h_stem:
                wx = stem_wx_values.get(h_stem, Wuxing.EARTH)
                tg = ten_gods_map.get(f'{pillar}_hidden_{i}', '')
                nodes.append(GraphNode(
                    id=f'{pillar}_hidden_{i}', node_type=NodeType.HIDDEN_STEM,
                    element=wx, pillar=pillar, ten_god=tg,
                    label_cn=f'{pillar}藏{h_stem}'
                ))
    
    node_ids = {n.id for n in nodes}
    node_map = {n.id: n for n in nodes}
    
    # --- 2. 建边 ---
    for ni in nodes:
        for nj in nodes:
            if ni.id >= nj.id:
                continue  # 避免重复
            
            # 生克关系（天干之间、天干→地支、地支→藏干）
            if GENERATES.get(ni.element) == nj.element:
                edges.append(GraphEdge(ni.id, nj.id, EdgeType.GENERATE, 1.0,
                                       f'{ni.label_cn} 生 {nj.label_cn}'))
            elif GENERATES.get(nj.element) == ni.element:
                edges.append(GraphEdge(nj.id, ni.id, EdgeType.GENERATE, 1.0,
                                       f'{nj.label_cn} 生 {ni.label_cn}'))
            if CONTROLS.get(ni.element) == nj.element:
                edges.append(GraphEdge(ni.id, nj.id, EdgeType.CONTROL, -1.0,
                                       f'{ni.label_cn} 克 {nj.label_cn}'))
            elif CONTROLS.get(nj.element) == ni.element:
                edges.append(GraphEdge(nj.id, ni.id, EdgeType.CONTROL, -1.0,
                                       f'{nj.label_cn} 克 {ni.label_cn}'))
            
            # 冲合（仅地支之间）
            if ni.node_type in (NodeType.BRANCH, NodeType.HIDDEN_STEM) and \
               nj.node_type in (NodeType.BRANCH, NodeType.HIDDEN_STEM):
                # 尝试从label_cn提取地支值
                bi = _extract_branch_val(ni.label_cn, branch_val_map)
                bj = _extract_branch_val(nj.label_cn, branch_val_map)
                if bi and bj:
                    if BRANCH_CLASH.get(bi) == bj:
                        edges.append(GraphEdge(ni.id, nj.id, EdgeType.CLASH, -1.5,
                                               f'{ni.label_cn} 冲 {nj.label_cn}'))
                    if BRANCH_COMBINE.get(bi) == bj:
                        edges.append(GraphEdge(ni.id, nj.id, EdgeType.COMBINE, 1.5,
                                               f'{ni.label_cn} 合 {nj.label_cn}'))
    
    # --- 3. 净能量计算 ---
    net_energy = {}
    for n in nodes:
        inflow = sum(e.weight for e in edges if e.target == n.id and e.edge_type == EdgeType.GENERATE)
        outflow = sum(abs(e.weight) for e in edges if e.source == n.id and e.edge_type == EdgeType.CONTROL)
        net_energy[n.id] = inflow - outflow
    
    # 日主额外加权
    dm_node = next((n for n in nodes if n.is_day_master), None)
    if dm_node:
        net_energy[dm_node.id] += 2.0
    
    # --- 4. 关键路径 ---
    key_paths = _find_key_paths(nodes, edges, net_energy, node_map)
    
    # --- 5. 全局诊断 ---
    diagnosis = _generate_diagnosis(nodes, edges, net_energy, key_paths)
    
    return GlobalInteractionGraph(
        nodes=nodes, edges=edges, net_energy=net_energy,
        key_paths=key_paths, dominant_flow=_dominant_flow(net_energy, node_map),
        global_diagnosis=diagnosis
    )


def _extract_branch_val(label: str, val_map: dict) -> Optional[int]:
    """从 '年支午' 提取地支值 7"""
    for k, v in val_map.items():
        if k in label:
            return v
    return None


def _find_key_paths(nodes, edges, net_energy, node_map) -> list[KeyPath]:
    """识别制化链、通关链、连锁反应"""
    paths = []
    
    for n in nodes:
        if n.ten_god in FIERCE_GODS and n.node_type in (NodeType.STEM, NodeType.HIDDEN_STEM):
            # 查找克制此凶神的节点
            controllers = [e for e in edges if e.target == n.id and e.edge_type == EdgeType.CONTROL]
            for ctrl in controllers:
                ctrl_node = node_map[ctrl.source]
                if ctrl_node.ten_god in ('食神', '伤官', '正官', '正印'):
                    # 制化成功
                    paths.append(KeyPath(
                        path_type='制化',
                        nodes=[ctrl.source, n.id],
                        description_cn=f'{ctrl_node.label_cn}({ctrl_node.ten_god})克制{n.label_cn}({n.ten_god})',
                        result='制化成功'
                    ))
    
    # 通关：A克B → C生A → 缓冲。C必须是柱干/藏干（有十神的节点），不是地支
    for e in edges:
        if e.edge_type == EdgeType.CONTROL:
            A_id, B_id = e.source, e.target
            A_node = node_map.get(A_id)
            B_node = node_map.get(B_id)
            if not A_node or not B_node:
                continue
            # 只关心：A是凶神、B是关键节点（日主或有力十神）
            if A_node.ten_god not in FIERCE_GODS:
                continue
            for e2 in edges:
                if e2.edge_type == EdgeType.GENERATE and e2.target == A_id and e2.source != B_id:
                    C_node = node_map[e2.source]
                    # C必须是有十神的节点
                    if C_node and C_node.ten_god:
                        paths.append(KeyPath(
                            path_type='通关',
                            nodes=[C_node.id, A_id, B_id],
                            description_cn=f'{C_node.label_cn}({C_node.ten_god})生{A_node.label_cn}({A_node.ten_god})→{A_node.ten_god}克{B_node.label_cn}·缓冲',
                            result='缓冲成立'
                        ))
    
    # 连锁：A冲B → B合C → 冲被解开。仅地支节点
    clashes = [e for e in edges if e.edge_type == EdgeType.CLASH]
    for cl in clashes:
        A_id, B_id = cl.source, cl.target
        A_node = node_map.get(A_id)
        B_node = node_map.get(B_id)
        if not A_node or not B_node:
            continue
        if A_node.node_type not in (NodeType.BRANCH,) or B_node.node_type not in (NodeType.BRANCH,):
            continue
        combines = [e for e in edges if e.edge_type == EdgeType.COMBINE and
                    (e.source == B_id or e.target == B_id)]
        for cb in combines:
            other = cb.source if cb.target == B_id else cb.target
            if other != A_id:
                paths.append(KeyPath(
                    path_type='连锁',
                    nodes=[A_id, B_id, other],
                    description_cn=f'{A_node.label_cn}冲{B_node.label_cn}但{B_node.label_cn}合{node_map[other].label_cn if other in node_map else other}',
                    result='冲被解开'
                ))
    
    return paths


def _dominant_flow(net_energy: dict, node_map: dict) -> str:
    """主导能量流：找净能量绝对值最大的节点"""
    if not net_energy:
        return "无主导向"
    top = max(net_energy.items(), key=lambda x: abs(x[1]))
    node = node_map.get(top[0])
    if node:
        direction = "吸纳" if top[1] > 0 else "输出"
        return f'{node.label_cn}:{direction}能量({top[1]:.1f})'
    return "无法判定"


def _generate_diagnosis(nodes, edges, net_energy, key_paths) -> str:
    """生成全局诊断中文摘要"""
    parts = []
    
    # 日主强弱
    dm = next((n for n in nodes if n.is_day_master), None)
    if dm:
        dm_e = net_energy.get(dm.id, 0)
        if dm_e > 3: parts.append("日主偏强，喜克泄")
        elif dm_e < -1: parts.append("日主偏弱，喜生扶")
        else: parts.append("日主中和")
    
    # 制化总结
    zhihua = [p for p in key_paths if p.path_type == '制化']
    if zhihua:
        fierce = set(p.nodes[1] for p in zhihua)
        parts.append(f'凶神{len(fierce)}处被制')
    else:
        parts.append("凶神未见制化")
    
    # 通关
    mediation = [p for p in key_paths if p.path_type == '通关']
    if mediation:
        parts.append(f'{len(mediation)}处通关成立')
    
    # 连锁
    chains = [p for p in key_paths if p.path_type == '连锁']
    if chains:
        parts.append(f'{len(chains)}处连锁反应')
    
    return '；'.join(parts)


def graph_from_chart_result(chart_result: dict) -> GlobalInteractionGraph:
    """把 core.compute_chart 产出的真实 ChartResult 适配为引擎输入并建图。

    键映射（ChartResult → 引擎输入）:
      pillars.{year,month,day,hour}.stem/branch → pillars.{柱}.stem/branch
      pillars.{柱}.hidden_stems (list[str])     → hidden_stems.{柱}
      pillars.{柱}.ten_god_stem                 → ten_gods["{柱}_stem"]
      pillars.{柱}.ten_gods_hidden[i]           → ten_gods["{柱}_hidden_{i}"]
      day_master.stem                           → day_master_stem
    partial 命例 pillars.hour 为 None → 跳过，图只含三柱。
    """
    src_pillars = chart_result.get('pillars') or {}
    pillars, hidden, ten_gods = {}, {}, {}
    for name in ('year', 'month', 'day', 'hour'):
        p = src_pillars.get(name)
        if not p:
            continue  # partial 时辰未知
        stem, branch = p.get('stem'), p.get('branch')
        if not stem or not branch:
            continue
        pillars[name] = {'stem': stem, 'branch': branch}
        hs = p.get('hidden_stems') or []
        hidden[name] = [h.get('stem', '') if isinstance(h, dict) else str(h) for h in hs]
        tg_stem = p.get('ten_god_stem')
        if tg_stem:
            ten_gods[f'{name}_stem'] = tg_stem
        for i, tg in enumerate(p.get('ten_gods_hidden') or []):
            if tg:
                ten_gods[f'{name}_hidden_{i}'] = tg
    day_master = chart_result.get('day_master') or {}
    adapted = {
        'pillars': pillars,
        'hidden_stems': hidden,
        'ten_gods': ten_gods,
        'day_master_stem': day_master.get('stem', ''),
    }
    return build_interaction_graph(adapted)


def graph_to_dict(g: GlobalInteractionGraph) -> dict:
    """序列化图结构供 API 返回"""
    return {
        "nodes": [{"id": n.id, "type": n.node_type.value, "element": n.element.value,
                   "pillar": n.pillar, "ten_god": n.ten_god, "is_day_master": n.is_day_master,
                   "net_energy": round(g.net_energy.get(n.id, 0), 2)}
                  for n in g.nodes],
        "edges": [{"source": e.source, "target": e.target, "type": e.edge_type.value,
                   "weight": e.weight, "desc": e.description_cn}
                  for e in g.edges],
        "key_paths": [{"type": p.path_type, "nodes": p.nodes, "desc": p.description_cn,
                       "result": p.result}
                      for p in g.key_paths],
        "dominant_flow": g.dominant_flow,
        "global_diagnosis": g.global_diagnosis,
    }
