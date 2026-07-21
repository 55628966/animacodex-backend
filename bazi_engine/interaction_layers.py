# -*- coding: utf-8 -*-
"""分层输出函数 — 按付费层级筛选 GlobalInteractionGraph 内容（30号 A2）。

origin:      免费层 → 仅节点清单
first_scroll: $5.99 → 核心边（生/克/冲/合） + 1条关键路径
full:         $19.99 → 全部边 + 全部关键路径 + 全局诊断
oracle:       订阅 → 动态图（预留接口，当前返回 full层 + 占位说明）

所有函数输入均为 GlobalInteractionGraph，输出为机器可读 dict。
节点/边/关键路径的序列化口径与 graph_to_dict 一致。
"""
from __future__ import annotations

from typing import Any

from .global_interaction import EdgeType, GlobalInteractionGraph, graph_to_dict

# 核心关系边（first_scroll 层可见）：生/克/冲/合
_CORE_EDGE_TYPES = frozenset({
    EdgeType.GENERATE, EdgeType.CONTROL, EdgeType.CLASH, EdgeType.COMBINE,
})


def _serialize(graph: GlobalInteractionGraph) -> dict[str, Any]:
    return graph_to_dict(graph)


def origin_layer(graph: GlobalInteractionGraph) -> dict[str, Any]:
    """免费层：仅节点清单（四柱干支十神如已有的盘面展示）。"""
    data = _serialize(graph)
    return {
        "tier": "origin",
        "nodes": data["nodes"],
        "node_count": len(data["nodes"]),
    }


def first_scroll_layer(graph: GlobalInteractionGraph) -> dict[str, Any]:
    """First Scroll 层：核心边（生克冲合） + 第一条关键路径。"""
    data = _serialize(graph)
    core_pairs = {(e.source, e.target, e.edge_type.value)
                  for e in graph.edges if e.edge_type in _CORE_EDGE_TYPES}
    core_edges = [e for e in data["edges"]
                  if (e["source"], e["target"], e["type"]) in core_pairs]
    first_path = data["key_paths"][0] if data["key_paths"] else None

    return {
        "tier": "first_scroll",
        "nodes": data["nodes"],
        "edges": core_edges,
        "edge_count": len(core_edges),
        "sample_key_path": first_path,
    }


def full_layer(graph: GlobalInteractionGraph) -> dict[str, Any]:
    """Full Codex 层：全部边 + 全部关键路径 + 全局诊断。"""
    data = _serialize(graph)
    return {
        "tier": "full",
        "nodes": data["nodes"],
        "edges": data["edges"],
        "edge_count": len(data["edges"]),
        "key_paths": data["key_paths"],
        "dominant_flow": data["dominant_flow"],
        "global_diagnosis": data["global_diagnosis"],
    }


def oracle_layer(graph: GlobalInteractionGraph,
                 cycle: dict | None = None) -> dict[str, Any]:
    """Oracle/Sanctum 层：动态图（当前预留接口）。

    参数 cycle 为大运或流年节点数据（M4后启用）。
    当前返回 full 层数据 + 占位说明。
    """
    result = full_layer(graph)
    result["tier"] = "oracle"
    if cycle:
        result["oracle_context"] = {
            "cycle": cycle,
            "note": "动态图计算尚未启用；当前返回全量静态交互图。M4后加入流年/大运节点重算。",
        }
    else:
        result["oracle_context"] = {
            "note": "Oracle/Sanctum 动态图计算预留。当前返回全量静态交互图。",
        }
    return result
