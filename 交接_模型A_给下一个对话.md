# Anima Codex · 模型A 工作交接（给下一个对话）

> 写于 2026-07-18。本文件是模型A（排盘引擎与后端）的完整交接，力求零遗漏。
> 接手前**必读顺序**：本文件 → `桌面/AnimaCodex_执行任务书/00_总纲与接口契约` → `01_模型A任务书` → `docs/拍板项报告_给Owner.md`（末尾有Owner决议表）。
> 一句话现状：**M1 全部交付 + M2 的 A 组（A1/A2/A3）全部完成并真机验证；A 侧就绪，等模型B切 api 模式联调与总工程师终验。**

---

## 0. 我是谁 / 分工墙（铁律，越权即打回）

- 我 = **模型A**：排盘算法、后端API、数据库、时辰反推的**计算与置信度**、回归测试、Mock数据。
- 模型B = 叙事引擎、双层结构渲染、前端Web、可视化、内容安全、时辰反推的**问答交互文案**。
- **铁律**：前端和叙事引擎中**不允许任何命理计算**；所有干支/十神/五行/大运的唯一来源是我的API。
- **我禁止**：写任何面向用户的叙事文案；改术语转码表；碰前端。
- 四条宪法（《00》第二节）：①严谨第一（排盘错一切皆错，命例必须100%）②神秘在前逻辑在后（双层结构）③选择在人不在命（伦理红线）④文化自信（术语只用速查表）。

---

## 1. 项目位置与环境

- **项目根**：`/home/user/桌面/AnimaCodex_模型A`
- **任务书目录**：`/home/user/桌面/AnimaCodex_执行任务书/`
  - `00_总纲与接口契约_两个模型都必须先读.md` —— 最高依据，契约schema
  - `01_模型A_排盘引擎与后端_任务书.md` —— 我的职责总纲
  - `03_模型A_拍板后续指令.md` —— 拍板固化4项（已完成）
  - `07_验收打回通知_两模型.md` —— 见 §9 虚报事件说明
  - `08_M2合并联调指令_两模型.md` —— A组已完成，B组归模型B
- **Python**：系统 3.12.3；项目自带 venv `./.venv`
- **依赖**（`requirements.txt`）：
  - `pyswisseph` —— **节气主源**（瑞士星历表，太阳视黄经交越）
  - `lunar-python==1.4.8` —— **交叉验证副源**（独立万年历，版本锁定保可复现）
  - `sxtwl==2.0.7` —— 第三对照源（**注意：1940年代含历史时制，仅对照不作基准**，见 §8-坑1）
  - `fastapi` / `uvicorn` / `pytest` / `httpx`（httpx 仅测试用，testclient 依赖）
- 跑任何命令用 `./.venv/bin/python`（不要用系统 python3）。

---

## 2. 文件清单（3451行，全部我写/我的团队写，无一行叙事文案）

```
bazi_engine/            纯算法库(无网络无Web依赖)
  __init__.py           导出 ALGO_VERSION, ChartOptions, compute_chart
  constants.py   (69)   干支/五行/藏干/十神表 + ten_god() + 节→月支映射
  solar_terms.py (73)   节气源(瑞士星历) terms_of_year/lichun_utc/prev_and_next_jie
  true_solar.py  (49)   真太阳时: 均时差(NOAA/Spencer) + 经度修正
  core.py       (215)   四柱/十神/五行/大运/compute_chart 总装
  hour_inference.py(376) 时辰反推贝叶斯置信度框架(7问库)
api/
  __init__.py
  main.py       (275)   FastAPI 6端点 + 统一错误 + CORS
  storage.py    (115)   SQLite 持久化(charts/hour_sessions 表)
  geo.py        (220)   GeoNames cities5000 城市→经纬度(69476条入库)+68城兜底
  启动服务.sh    (5)     uvicorn 127.0.0.1:8901
tests/
  test_cross_validation.py(160) 双源模糊交叉验证(~3500例)
  test_regression.py     (122)  命例库回归(逐字段深比对)
  test_api.py            (369)  API契约+CORS+P95+时辰反推
  test_hour_inference.py (221)  贝叶斯确定性/锁定/红线
  test_cases/
    cases.json                  114命例(8类边界)
    rejected.json               被拒候选(当前0例)
scripts/
  gen_cases.py   (387)  命例库生成器(引擎算+lunar核验才入库,种子20260717)
  gen_mock.py    (95)   Mock生成器(3例+双源核验)
  gen_test_report.py(121) 生成 docs/测试报告.md
docs/
  口径文档_排盘算法_待签字.md      口径全集(已拍板固化)
  拍板项报告_给Owner.md            4拍板项+4附加项+Owner决议表
  时辰反推置信度算法.md            贝叶斯公式/7问12维似然表/给B的语义清单
  测试报告.md                      自动生成,114逐例明细
  Mock交付说明_给模型B.md          渲染注意事项
  联调基线_A组_20260717_改动前.txt A组改动前基线留底
mock_chart_result.json            第2周末交付物(3命例,供B)
run_tests.sh                      一键全量测试(4步)
requirements.txt / README.md
```

---

## 3. 排盘引擎口径（核心，改动必须全量重跑）

**algo_version = "1.0.0"**（写入每个结果 `meta.algo_version`，供追溯）。

### 3.1 节气源（solar_terms.py）
- **主源 = 瑞士星历表**（pyswisseph，`FLG_MOSEPH` Moshier模型）。节气=太阳视黄经到 15°整数倍的交越时刻，直接以 UT 求，秒级精度，覆盖1800–2399，零外网零数据文件。
- 序号约定：**冬至=0，小寒=1，…立春=3，…大雪=23**，黄经 = `(270 + 15*idx) % 360`。`terms_of_year(year)` 返回该公历年24节气 `[(idx, utc_datetime)]`。
- **年柱以立春精确时刻为界**（`lichun_utc`）；**月柱以十二"节"（奇数idx）为界**（`prev_and_next_jie`，只看节不看中气）。比较一律在 **UTC 绝对时刻**下做，与出生地经度无关。

### 3.2 真太阳时（true_solar.py）
- 公式：`真太阳时 = 钟表时间 + 经度修正 + 均时差`；`经度修正 = 经度×4分钟 − 时区偏移(分钟)`；均时差 = NOAA/Spencer 级数（±30秒内）。
- 返回 `(tst, total_correction_min, eot_min, birth_utc)`。契约字段：`correction_minutes`=总修正、`equation_of_time_minutes`=均时差分量。
- **历史时制如实处理**：IANA 含中国1986–1991夏令时（UTC+9）→ 1990夏 14:00 真太阳时=12:45（午时）。这是特性不是bug（见 §8-坑2）。

### 3.3 四柱与时辰（core.py）
- 日柱、时辰以**真太阳时**判定；日界=真太阳时 00:00。
- **日柱锚点：1990-06-15 = 辛亥日**（六十甲子序47，甲子=0），按日序推算。
- **晚子时开关** `late_zi_new_day`（拍板项1）：`true`=换日派(日柱取次日)/`false`=不换日派。两派下时柱天干均按次日日干五鼠遁。**正式默认=true**（Owner拍板）。

### 3.4 十神/藏干/五行
- 十神 `ten_god(day_stem, other_stem)`：标准子平（同我比劫/我生食伤/我克财/克我官杀/生我印枭，阴阳同异分正偏），全部中文原术语。
- 藏干表 `HIDDEN_STEMS`：本气/中气/余气（与lunar-python发布表一致，"午藏丁己"）。
- 五行 `five_element_mode`（拍板项2）：**`main`=正式默认**（八字逐字计1，地支按本气，整数，总和8；时辰未知为6）；`hidden_weighted`=保留内部能力（天干1.0，地支按藏干拆0.6/0.3/0.1）。**藏干不进雷达图，但保留在API `hidden_stems` 供叙事层用**。

### 3.5 大运（core.py luck_cycles）
- 顺逆：阳年男/阴年女顺排，阴年男/阳年女逆排（年干阴阳，立春界定）。
- 起运：顺排取出生→下一节、逆排取上一节→出生的精确差，**取整到分钟**后：`4320分钟(3天)=1岁`、`360分钟=1月`、`12分钟=1天`，逐级下取整（对齐 lunar-python "流派2/分钟法"）。
- 输出8步，每步含干支/对日主十神/起止年。`end_year = start_year + 10`（左闭右开，对齐《00》示例）。

### 3.6 时辰未知（partial）
- `birth_time=None` → `partial:true`，`hour=null`，`true_solar_time=null`，五行6字口径，日柱按公历出生日。

---

## 4. 后端API（api/main.py，端口 8901）

| 端点 | 说明 |
|---|---|
| `POST /api/v1/chart` | 排盘，生成uuid chart_id，持久化，返回契约 ChartResult |
| `GET /api/v1/chart/{chart_id}` | 取回历史结果（溯源），不存在→404 NOT_FOUND |
| `POST /api/v1/hour-inference/start` | 时辰反推开始，返回12候选+session_id |
| `POST /api/v1/hour-inference/answer` | 传答案，服务端存序列全量重算，锁定判断只在后端 |
| `GET /api/v1/geo/search?q=` | 城市→经纬度（含IANA时区回填），≤10条按人口降序 |
| `GET /api/v1/health` | `{"status":"ok","algo_version":"1.0.0"}` |

- **错误统一** `{"error":{"code","message"}}`。状态码约定（main.py头部文档化）：400=一切输入错误（不用422）；404=NOT_FOUND/INVALID_SESSION；405=METHOD_NOT_ALLOWED；501=NOT_IMPLEMENTED（时辰反推模块缺席兜底，现已就位）；500=INTERNAL（统一异常处理器兜底任何未捕获异常）。
- **CORS（《08》A2）**：`allow_origins=["http://127.0.0.1:8321"]`、`allow_methods=["GET","POST"]`、`allow_headers=["Content-Type"]`，**禁用通配符**。常量 `CORS_ALLOW_ORIGIN`。
- **持久化**（storage.py）：SQLite `data/anima.db`，`charts`表（chart_id/request_json/result_json/algo_version/created_at）+ `hour_sessions`表（session_id/answers_json/时间戳）。无状态服务，状态全落库。
- **地理**（geo.py）：GeoNames cities5000（CC-BY 4.0），**已实际入库 69476 条**；下载失败时用68城内置兜底。**授权边界：只下载 geonames.org 这一个文件，运行期API零外网**。
- **P95 实测 8.9ms**（红线500ms）。

---

## 5. 时辰反推框架（hour_inference.py）

- `start_session()` / `update_session(answers)` 两个纯函数（无网络无IO无随机，完全可复现）。`answers=[{"question_id","option_key"},...]`。
- 均匀先验(1/12) → 每答案乘法贝叶斯更新 → 归一化；`confidence` 四舍五入4位。
- **7问库**（ID顺序）：`q_sky_light`(天色) / `q_family_asleep`(作息) / `q_meal`(饭点) / `q_rooster_sun`(鸡鸣日出) / `q_work`(劳作) / `q_sun_position`(日位) / `q_night_watch`(更次)。每问带12维似然向量，含全1"不确定"选项。选题用期望信息增益EIG。
- **红线**（`LOCK_THRESHOLD=0.90`, `MAX_QUESTIONS=5`，判断只在后端）：
  - `max_conf≥0.90` → `locked=True`，`next_question_id=None`（可第5问前提前锁定）
  - `asked_count≥5` 且未达0.90 → `locked=False`，`next_question_id=None`（**问尽锁死，上层只允许前三柱**）
- **`locked_branch` 字段（《00》4.2 v1.1，拍板2026-07-17增补）**：`locked=True` 时状态**必须**含 `"locked_branch":"<地支>"`（未舍入后验最大项）；未锁定不得出现。API answer 原样透传。
- 问题**文案归模型B**（doc里给的是 evidence 语义清单，B据此写文案，不许改语义）。权重表标注"v1.0，命理顾问会签待补"。

---

## 6. 测试体系（run_tests.sh 一键，全绿退出0）

| 测试文件 | 计数 | 覆盖 |
|---|---|---|
| test_cross_validation.py | **5 passed**(~18s) | 双源模糊~3500例：随机2000(1902-2098)+节气边界探针+早晚子时双流派+大运四象限+**引擎自身±1秒内部边界** |
| test_regression.py | **116 passed** | 114命例逐字段深比对 + 2元测试(配额/双源标记) |
| test_api.py | **19 passed,1 skipped** | 契约字段/partial/全错误码/持久化取回/geo/P95/**3条CORS**/时辰反推全流程 |
| test_hour_inference.py | **16 passed** | 确定性/归一化/锁定/红线/locked_branch/非法输入/单调性 |

- **命例库 cases.json = 114例8类**：lichun_boundary16 / jie_boundary22 / zi_hour16 / extreme_geo10 / luck_quadrant16 / start_age_extreme8 / hour_unknown8 / random_regular18。rejected.json 当前0例（全部候选双源一致）。
- **1 skipped** 是"时辰反推模块缺席兜底"用例——模块已就位故自动跳过兜底路径，属正常。
- **关键护栏——盲区规则 ±120秒**：距节气交接±120秒内**不做跨库断言**（两库节气源秒差实测≤94s + lunar分钟截断），该区间由引擎内部±1秒秒级测试(`test_engine_internal_term_boundary`)独立保证。命例库全部按"距节≥150秒"安全构造，无一例依赖盲区豁免。
- **改算法后必须** `./run_tests.sh` 全量重跑；改默认口径后必须 `./.venv/bin/python scripts/gen_cases.py` 重生成命例库再跑。

---

## 7. 拍板决议（2026-07-17，已全部固化，见 docs/拍板项报告 末尾决议表）

| 项 | 决议（已固化） |
|---|---|
| 拍板1 | `late_zi_new_day=true`（23点换日）为正式默认；不换日开关保留不对用户暴露 |
| 拍板2 | `five_element_mode="main"`（本气计数整数）为正式默认；藏干不进雷达图但保留API；`hidden_weighted` 内部能力 |
| 拍板3 | 三层来源：**紫金山天文台《中国天文年历》体系(GB/T 33661-2017)权威锚** / SwissEph×lunar-python双源准入 / sxtwl第三对照；人工锚点暂不强制，上线前主流工具人工抽查 |
| 拍板4 | GeoNames cities5000 报备通过 |
| 附加A | **不加**忽略夏令时开关，维持严谨；修正明细由B在确认页/溯源层展示 |
| 附加B | 1940年代时制风险，知悉，M1不处理 |
| 附加C | 时辰反推权重表随1、2一并交命理顾问会签 |
| 附加D | 《00》示例日柱笔误(丙子→辛亥)已由总工程师修正契约文件 |
| **待补** | 命理顾问对 1/2/C 的会签（Owner已批依据，走过场）；**会签若改默认值 → 重跑 gen_cases.py** |

固化动作（03指令）已全部落地：口径文档"待签字"→"已拍板2026-07-17"，cases.json 三层来源，locked_branch字段+测试。

---

## 8. 关键坑与技术决策（务必知悉，别踩回去）

1. **sxtwl 被弃为主源**：实测其1940年代输出混历史时制（1944小寒差整1小时），已用瑞士星历表独立仲裁（1944-01-06小寒=10:39:15.6 UT）确认。sxtwl 只作第三对照，节气主源认瑞士星历表。
2. **夏令时是特性不是bug**：IANA 如实含中国1986–1991夏令时。构造中国命例必须**避开 1919 / 1940-1949 / 1986-1991 的3-11月**（gen_cases.py `CN_DST_YEARS` 已处理）；境外夏令时例经 birth_utc 归一化协议核验。
3. **盲区±120秒**（见§6）——别把它当成引擎不精确；引擎自身秒级精确，盲区只是"不拿两个秒级源互相较真"。
4. **大运对照用 lunar 流派2**（`getYun(gender, 2)` 分钟法），不是流派1。
5. **契约示例笔误**：《00》4.1 示例标 1990-06-15 日柱"丙子"，实际"辛亥"（双源一致），已由总工程师修正契约，按schema结构实现即可。

---

## 9. 里程碑进度 & §07虚报事件（必读）

- **第2周末**：Mock 3命例 ✓（提前交付）
- **M1（第2月末）**：全API上线 + 114命例回归 + 一键脚本 ✓（总工程师复核过：sxtwl独立复核114/114、契约逐字段、红线实测、P95、Mock逐字节）
- **M2 A组（《08》）**：A1清03欠账(四条验收命令全过) + A2 CORS(真机curl验证`access-control-allow-origin: http://127.0.0.1:8321`) + A3基线保护(新旧全绿) ✓
- **§07打回事件澄清**：07号通知称"模型A虚报03完成"。经查，那次虚报**出自另一个并行Claude窗口**（这台机器多开过会话，见记忆"设备·没坏是多开"）；**本会话线此前从未收到03、也没发过03完成汇报**。03的四项是本会话线在收到07后**真实做完并四样取证**的。→ **接手第一件事：`ps` 查有没有其他Claude窗口在写同一批文件，让用户关掉，避免再撞车。**

---

## 10. 待办（交给下一个模型A）

1. **M2终验**（总工程师执行，**需模型B先完成B组**：geo接入/错误态/切api模式/e2e新增5场景/联调启动脚本）：盲测完整流程、B5场景抽查复跑、Mock三命例在api模式下逐字节比对、前端控制台零报错、断网重连错误态实测。A侧配合复跑即可。
2. **命理顾问会签**（Owner侧，不阻塞A）——一旦会签改了默认流派/口径，**必须重跑 `gen_cases.py` 重生成命例库并 `run_tests.sh` 全绿**。
3. **M3 尚未下发**——《01》里程碑表止于M2；付费全卷/合盘/订阅/神谕所等后续里程碑再说，现在不许提前做（《00》一）。
4. 长期：上线前按拍板3补"主流工具人工抽查"作为人工锚点。

---

## 11. 一键复现命令（Owner实机可跑）

```bash
cd /home/user/桌面/AnimaCodex_模型A
./run_tests.sh                                   # 全量测试(交叉验证+回归+API+时辰反推+报告),末尾有汇总
./api/启动服务.sh                                 # 起后端(127.0.0.1:8901)
curl -s http://127.0.0.1:8901/api/v1/health      # 健康检查
./.venv/bin/python scripts/gen_mock.py           # 重生成mock(含双源核验断言)
./.venv/bin/python scripts/gen_cases.py          # 重生成命例库(改默认口径后必跑)
# CORS验收(需先起服务):
curl -si -H "Origin: http://127.0.0.1:8321" http://127.0.0.1:8901/api/v1/health | grep -i access-control-allow-origin
```

---

## 12. 纪律铁律（继承，别破）

- **"完成"= Owner实机可复现 + 附证据（命令/输出/截图），只在自己环境跑通不算完成。虚报比做不完更严重（§9）。**
- 交作业逐项列 **做了 / 没做 / 部分（列清单）+ 证据**（《08》五件套）。
- 遇《00》第七节拍板项/未覆盖决策 → **停下上报，不许自行决定**流派或口径。
- 每周三行汇报：一句话进展 / 两个数字(完成度%、阻塞数) / 一个需Owner的动作(无就写"无")。
- 契约 schema 字段**不增不删不改**；中文原术语传输，英文转码归B；**不写任何叙事文案，不碰前端**。
- 指令边界内**不顺手改**任何东西（03教训）；改坏旧断言整单打回（08纪律）。
- 用简体中文交流（用户长期要求）。

---

**A侧联调入口：`./api/启动服务.sh`（8901端口）。终验与B6联调启动脚本归模型B和总工程师，A侧随时配合复跑。**
