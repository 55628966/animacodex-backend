#!/usr/bin/env bash
# Anima Codex 模型A · 一键测试(《01》第三节交付物)
# 用法: 在项目目录直接 ./run_tests.sh
# 步骤: [1] 双源交叉验证  [2] 回归命例库  [3] API契约+时辰反推 pytest
#       [4] 全卷数据FullChartData+AI脱敏  [5] 生成 docs/测试报告.md
# 任一步失败, 退出码非0。
set -u
cd "$(dirname "$0")" || exit 1
PY=./.venv/bin/python

echo "== [1/4] 双源交叉验证 (tests/test_cross_validation.py) =="
"$PY" -m pytest tests/test_cross_validation.py -q
CV=$?

echo ""
echo "== [2/4] 回归命例库 (tests/test_regression.py) =="
"$PY" -m pytest tests/test_regression.py -q
RG=$?

echo ""
echo "== [3/5] API契约 + 时辰反推 + 29号账号存储 + 30号全局互动/Paddle支付 =="
"$PY" -m pytest tests/test_api.py tests/test_hour_inference.py tests/test_29_auth_storage.py tests/test_global_interaction.py tests/test_30_paddle.py -q
AP=$?

echo ""
echo "== [4/5] 全卷数据 + AI脱敏 + 报告契约 + 个人节律 =="
"$PY" -m pytest tests/test_full_chart.py tests/test_export_safe.py tests/test_report_contract.py tests/test_rhythm.py -q
FC=$?

echo ""
echo "== [5/5] 生成测试报告 (scripts/gen_test_report.py -> docs/测试报告.md) =="
REPORT_OUT=$("$PY" scripts/gen_test_report.py)
RP=$?
echo "$REPORT_OUT"
# 从报告脚本输出提取 "回归: x/y 通过" 汇总行
SUMMARY_LINE=$(echo "$REPORT_OUT" | grep "^回归:" | tail -1)

echo ""
echo "================ 汇总 ================"
[ $CV -eq 0 ] && echo "交叉验证: 通过" || echo "交叉验证: 失败"
[ $RG -eq 0 ] && [ $RP -eq 0 ] && echo "${SUMMARY_LINE:-回归: 失败}" || echo "${SUMMARY_LINE:-回归: 失败} (存在失败)"
[ $AP -eq 0 ] && echo "API契约+时辰反推+29号+30号: 通过" || echo "API契约+时辰反推+29号+30号(含Paddle支付): 失败"
[ $FC -eq 0 ] && echo "全卷数据+AI脱敏+报告契约+节律: 通过" || echo "全卷数据+AI脱敏+报告契约+节律: 失败"
echo "测试报告: docs/测试报告.md (来源三层清单已拍板2026-07-17, 命理顾问会签待补)"
echo "======================================"

[ $CV -eq 0 ] && [ $RG -eq 0 ] && [ $RP -eq 0 ] && [ $AP -eq 0 ] && [ $FC -eq 0 ]
exit $?
