# -*- coding: utf-8 -*-
"""生成 mock_full_result.json(09号A2): 为 mock_chart_result.json 的3个命例
构造 FullChartData。规则与 A1 /full 端点【同一函数】compute_full_chart 派生,
保证 Mock 与真实端点逐字段一致(解耦模型B开发, 48h先行交付物)。

用法: ./.venv/bin/python scripts/gen_mock_full.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bazi_engine import compute_full_chart

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "mock_chart_result.json"
OUT = ROOT / "mock_full_result.json"


def main():
    charts = json.loads(SRC.read_text(encoding="utf-8"))
    out = []
    for ch in charts:
        full = compute_full_chart(ch)
        out.append({"chart_id": ch["chart_id"],
                    "partial": bool(ch.get("partial", False)),
                    **full})
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 交付自检打印(供人工核对)
    for o in out:
        kg = "/".join(g["name"] for g in o["key_ten_gods"])
        print(f'{o["chart_id"][-4:]} partial={o["partial"]} '
              f'key=[{kg}] interactions={len(o["interactions"])} '
              f'annual={[a["year"] for a in o["annual_next3"]]} '
              f'spouse={o["relationship"]["spouse_palace"]["branch"]} '
              f'career={o["career"]}')
    print(f"已写出: {OUT}")


if __name__ == "__main__":
    main()
