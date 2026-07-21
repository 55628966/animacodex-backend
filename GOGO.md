# GOGO — 模型A 启动指令 2026-07-19

## 状态确认
- A2 mock_full_result.json ✅ 已交付已验schema
- A1 `/api/v1/chart/{id}/full` ✅ 端点已实装（curl验证通过）
- 待做：A3 export_safe.py / A4 基线 / 20号A组 / 21号A组

## 执行顺序

### 1. 基线留底（先跑）
```bash
cd /home/user/桌面/AnimaCodex_模型A && ./run_tests.sh
```
全绿才继续。失败停工上报。

### 2. A3: export_safe.py
在 `bazi_engine/export_safe.py` 实现：
- 输入 ChartResult + FullChartData
- 输出白名单字段：十神/五行计数/大运干支年份/流年/日主
- 剥除：true_solar_time、birth_*、经纬度、chart_id
- 单测断言：序列化输出不含日期时间格式串和坐标数字
- 后续一切AI调用只准走此出口

验收：pytest test_export_safe.py 全绿

### 3. A4: 终验
`./run_tests.sh` — 旧测试+新增全绿

### 4. 20号A组
前置必读：16/17/18/19号任务书
- A1: tradition_profile → ChartResult.meta
- A2: luck_cycle_convention 可选参数
详见：`../AnimaCodex_执行任务书/20_M3_5_传统透明与高级定制基础_两模型任务书.md`

### 5. 21号A组
- A1: MonthlyRhythmData 端点 `GET /chart/{id}/rhythm?at=YYYY-MM-DD&viewer_timezone=IANA`
- A2: first_scroll_candidates 已在full端点返回，确认格式
详见：`../AnimaCodex_执行任务书/21_M3_6_商业漏斗与个人节律基础_两模型任务书.md`

## 纪律
- 五件套生效（《00》v1.3）
- 每完成一项交作业：改了什么:行号 / 验收命令+输出 / 证据路径
- 不改旧字段旧命例结果
- 不懂先问，不猜不做
