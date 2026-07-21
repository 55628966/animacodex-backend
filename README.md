# Anima Codex | 模型A —— 排盘引擎与后端

依据《00_总纲与接口契约》《01_模型A任务书》。**只含算法/API/测试，无任何叙事文案与前端。**

## 目录

- `bazi_engine/` —— 排盘核心算法库（纯计算，无网络无Web依赖）：节气(瑞士星历)、真太阳时、四柱、十神、五行、大运、时辰反推置信度
- `api/` —— FastAPI 后端（《00》第四节契约）+ SQLite 持久化 + 城市地理查询
- `tests/` —— 双源交叉验证 + 命例回归库 + API契约测试
- `docs/` —— 口径文档（待签字）、拍板项报告、测试报告、算法文档
- `mock_chart_result.json` —— 第2周末交付物（3命例，供模型B）
- `run_tests.sh` —— 一键全量测试
- `api/启动服务.sh` —— 启动后端（127.0.0.1:8901）

## 快速开始（Owner 实机复现）

```bash
cd AnimaCodex_模型A
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt   # 已建好可跳过
./run_tests.sh          # 全量测试(交叉验证+回归+报告)
./api/启动服务.sh        # 启动API
curl -s http://127.0.0.1:8901/api/v1/health
```

## 纪律遵守状态

- 契约 schema 零增删改；中文原术语传输；无叙事内容
- 拍板项1/2/4 已按"可配置+文档化"实现，默认值待签字（见 docs/拍板项报告_给Owner.md）
- 拍板项3：命例来源清单候选已列，**Owner 确认前回归通过不构成最终验收**
