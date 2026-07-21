# Full Codex V1：内容生产、审校与发布手册

> 状态：**内部生产包；不是用户报告，也不是已获会签的传统结论。**
>
> 适用范围：`$19.99 Full Codex` 的全部用户可见文案、Trace 索引、导出、邮件样张与人工交付引用。本文不授权任何人上线收费，也不替代 `bazi_engine.report_contract` 的运行时校验。
>
> 对应文件：
>
> - `AnimaCodex_模型B/narrative/full_codex_v1_segment_schema.json`
> - `AnimaCodex_模型B/narrative/full_codex_v1_module_manifest.json`
> - `AnimaCodex_模型B/narrative/full_codex_v1_source_registry_template.json`
> - `AnimaCodex_模型B/narrative/full_codex_v1_signoff_register.csv`
> - `AnimaCodex_模型A/docs/Full_Codex_V1_降级矩阵.json`

## 1. 生产目标与不可跨越的边界

Full 不是“付款后更准”的排盘。它交付的是：在明确 `zi_ping_solar_v1` 口径下，对本次命盘**可见结构**做出的更完整、可展开、可审校的传统阅读与反思材料。

它不交付或暗示：确定人生结果、改命方法、疾病/心理/生育判断、投资/借贷/买卖建议、法律判断、婚恋最终决定、性别或身份角色规定。每一条用户可见文本必须通过 `ReportSegment v1`；不得直接渲染未结构化字符串。

### 1.1 事实、阅读与反思必须拆开

| 内容 | 可写什么 | 必须有 | 不能写什么 |
|---|---|---|---|
| `chart_fact` | 可由本次引擎结果复算的字段、计算口径、可用性状态 | evidence 或 trace；段落边界 | 人生后果、人格定论、预测 |
| `traditional_reading` | 明示为本产品采用子平口径下的象征性解释 | evidence + trace 或 source；段落边界；会签 | 唯一真理、科学证明、确定性/恐惧话术 |
| `reflection_prompt` | 用户可选的开放问题、观察点、私密笔记提示 | 一条依据、trace 或 source；段落边界 | 命令、唯一解、重大决定指令 |
| `educational_fact` | 术语或来源的解释 | 可核对的 source；段落边界 | 把典籍当科学验证 |
| `unsupported_or_excluded` | 被排除的高风险内容与安全转向 | policy 依据；`status=excluded` | 回显高风险原问题、变相预测 |

`traditional_interpretation` 仅是兼容类型；新内容统一使用 `traditional_reading`。

## 2. 内容包的使用顺序

1. **工程先取数。** 只取被 manifest 列出的脱敏字段和 Trace 路径；不得把原始生日、出生时间、地点、经纬度、真太阳时原值、chart ID、owner secret、邮箱放进任何内容记录、source、导出或截图。
2. **内容编辑建立 draft。** 每个草稿先选择模块、`content_role`、`claim_type`、证据、Trace、来源占位和边界；没有来源或规则就不写传统阅读。
3. **命理顾问校规则。** 只核对术语、适用前提、例外和来源范围，不将传统包装为科学。
4. **安全编辑校风险。** 把直白或隐晦的决定论、医疗化、金融化、法律化、伤害、歧视、恐惧营销与依赖诱导全部拒绝或重写。
5. **英语编辑校表达。** 使英文自然、准确、克制；不得用诗意或神谕腔吞掉边界。
6. **工程生成 release candidate。** 先按降级矩阵决定哪些模块/段落可显示，再把每段交给 `enforce_report_contract(..., on_policy_violation="raise")`。
7. **签字后才发布。** 三角色会签、运行时校验、Trace/source 解析、敏感数据扫描、移动端和导出检查缺一不可。

草稿文本可以存在隔离的编辑系统；草稿**绝不能**通过 API、页面、邮件、分享图、PDF 或人工回复发给用户。

## 3. 14 模块的最小交付

完整细则是 `full_codex_v1_module_manifest.json`；此表是发布前人工核对的简明索引。`必需`指模块被显示时必须包含；`条件`指只有 manifest 所列条件满足、且规则已会签才允许出现；`禁止`指 V1 不得生成。

| # | 模块 | 事实 | 传统阅读 | 反思问题 | 必须显示的边界 | 证据/来源最低要求 |
|---:|---|---|---|---|---|---|
| 01 | Calculation Profile | 必需 | 不适用 | 不适用 | 口径是公开选择，非唯一标准 | profile + Trace |
| 02 | Four Pillars Record | 必需 | 不适用 | 不适用 | 未知柱/边界不补写 | 四柱字段 + Trace |
| 03 | Day Master Lens | 必需 | 必需 | 必需 | 日主不是整个人或整张盘 | 日主字段 + Trace + 会签来源 |
| 04 | Seasonal Context | 必需 | 必需 | 必需 | 节气边界和月令的有限作用 | 月柱 + profile Trace + 会签来源 |
| 05 | Five-Element Map | 必需 | 条件 | 必需 | 可见八字计数不是完整强弱评分 | 元素计数 + 口径 Trace；阅读另需来源 |
| 06 | Key Ten-God Vocabulary | 必需 | 必需 | 必需 | 选中的术语不代表完整判断 | 十神及位置 + Trace + 会签来源 |
| 07 | Relation Map | 必需 | 条件 | 必需 | 结构关系不预示关系事件 | interaction + Trace；阅读另需来源 |
| 08 | Cycles, If Chosen | 条件 | 条件 | 条件 | 约定、未应用状态、估算状态 | convention/cycles + Trace；阅读另需来源 |
| 09 | Solar-Month Context | 必需 | 条件 | 必需 | 节气月不是每日吉凶或行动命令 | rhythm/natal links + Trace；阅读另需来源 |
| 10 | Work & Craft Reflection | 必需 | V1 不适用 | 至少 2 条 | 不决定职业、合同、收入或投资 | career 计数 + Trace |
| 11 | Relationship Reflection | 必需 | V1 不适用 | 至少 2 条 | 不决定对象、婚姻或去留 | spouse-palace 字段 + Trace |
| 12 | Boundaries & Unknowns | 必需 | 禁止 | 条件 | 所有 active limitation 必须逐项显露 | partial/convention/boundary notice + policy 来源 |
| 13 | Trace & Source Index | 必需 | 不适用 | 不适用 | Trace 不展示个人原始输入或密钥 | 每个已显示 Segment 的 evidence/trace/source |
| 14 | Reader’s Closing Notes | 条件 | 禁止 | 3–5 条 | 报告是反思材料，不是人生权威 | 已显示模块标识 + profile Trace + policy 来源 |

**硬性规则：** 模块 03、04、06 的传统阅读在没有已验证的来源记录和三角色会签前，模块只可显示它的事实、边界与合规反思问题；不能用旧模板、AI 草稿或“常识性”描述补足。所有模块不得出现“缺某元素”等贬损性标签，也不得把视觉色彩、饰品、饮食、精油、风水或消费推荐伪装成命盘建议。

## 4. 段落生产模板（供编辑系统实现）

每个用户可见段落按照下面的骨架录入。`{{...}}` 是**仅限内部草稿**的占位；发布时必须替换，并经过契约、来源和会签校验。

```json
{
  "contract_version": "report_segment_v1",
  "module_id": "full.XX.module-name",
  "segment_id": "full.module-name.specific-rule.v1",
  "content_role": "fact | traditional_reading | reflection | boundary | source_index | excluded",
  "claim_type": "chart_fact | traditional_reading | reflection_prompt | educational_fact | unsupported_or_excluded",
  "body": "{{approved user-visible English body}}",
  "boundary": "{{approved segment-specific boundary}}",
  "evidence": [{"kind": "chart_field", "ref": "{{non-sensitive-field-path}}"}],
  "trace_refs": ["{{non-sensitive-trace-path}}"],
  "source_refs": ["{{verified registry ref only}}"],
  "profile_id": "zi_ping_solar_v1",
  "content_version": "full-v1.0.0-YYYYMMDD",
  "risk_flags": ["{{applicable controlled flag}}"],
  "status": "published"
}
```

发布校验：

- `segment_id` 在一个发行版本内唯一，不可因英文文案微调而复用到不同含义；
- `evidence.ref`、`trace_refs`、`source_refs` 都是稳定、脱敏的标识符；
- 传统阅读至少有 1 条 evidence，且至少再有 Trace 或来源；教育性事实必须有来源；
- `boundary` 是该段的限制，不是统一免责声明的复制品；
- `status=excluded` 只可用于 `unsupported_or_excluded`，并且不能回显用户的危险问题；
- 所有 `TODO`、`TBD`、`SOURCE_REF_REQUIRED` 和 `{{...}}` 都是发布阻断项。

## 5. 三角色会签与否决

会签表模板是 `full_codex_v1_signoff_register.csv`。首版按 14 个 module bundle 预置了 42 行；实际生成的每一个用户可见 segment 都必须有可追溯的关联会签记录。若某个 module bundle 内出现新规则、新来源、新风险类别或实质性重写，必须新增对应行，不能继承旧签字。

| 角色 | 必须确认 | 可作出的决定 | 不能做的事 |
|---|---|---|---|
| 命理顾问 / `traditional_consultant` | 术语、规则、前提、反例、经典/编辑来源的适用范围 | `approve` / `revise` / `reject` | 宣称科学验证，或放行医疗、金融、法律、关系结论 |
| 安全编辑 / `safety_editor` | claim 标签、边界、歧视与伤害、隐私、付费话术整体印象 | `approve` / `revise` / `reject`；对风险有一票否决 | 以“传统”名义放行禁区 |
| 英语编辑 / `english_editor` | 术语英译、自然度、克制感、边界是否可理解 | `approve` / `revise` / `reject` | 为流畅删除边界，或把阅读写成神谕 |

签字必须记下：release ID、content version、module/segment ID、来源版本、角色、姓名、UTC 时间、决定、修改摘要及后续工单。`pending`、空姓名、空日期、`revise` 或 `reject` 都是发布阻断项。

## 6. 部分命盘、未应用大运与边界情况

机器可读矩阵见《Full Codex V1 降级矩阵》。工程侧先按它生成 `availability`，再让前端按数组顺序渲染：**条件说明 → 事实 → 已允许的阅读 → 反思问题**。不得把限制放在长文末尾、折叠进默认关闭的区域或留给客服解释。

关键口径：

- `partial=true`：显示已知三柱及其明确边界；任何依赖时柱的数据只能显示“未生成/不完整”，绝不将缺失当作 0、无或负面标签。
- `luck_cycle_convention=not_applied`：模块 08 显示“未生成大运”的事实与原因；不得要求用户选择传统性别约定、不得暗示付费可换取确定性。
- 已知时刻临近节气、真太阳日界或时辰边界：如果引擎提供该状态，相关模块必须先显示边界；若尚未提供可复算的替代结果，只能说明存在边界敏感性，不能杜撰另一张盘。
- 历史时制/地点解析不确定：只保留可复算事实与不确定性，暂停所有依赖该不确定字段的阅读。
- 多个条件同时命中时，**逐条保留**，不合并成一句笼统免责声明。

## 7. 版本命名与发布流程

### 7.1 命名

发行版格式：`full-vMAJOR.MINOR.PATCH-YYYYMMDD`，例如 `full-v1.0.0-20260719`（示例，不代表已发布）。

| 变化 | 版本规则 | 额外要求 |
|---|---|---|
| 计算口径、字段语义、claim 类型、降级逻辑发生不兼容变化 | 升 `MAJOR` | 新 `profile_id` 或迁移说明；旧报告不可静默覆盖；全量重签与回归 |
| 新增已会签模块/规则、实质扩展已售内容 | 升 `MINOR` | 受影响模块重签；更新 source index、产品范围和测试样例 |
| 文案修正、来源定位修正、边界澄清、无语义变化的排版修复 | 升 `PATCH` | 受影响 segment 重签；保留变更摘要 |

`content_version` 与 `profile_id` 必须一起存入每份交付。内容版本不同的历史报告只读保存；需要重新生成必须由用户主动发起，并展示新旧差异说明。

### 7.2 发布 gate

1. 创建 release ID、冻结 manifest、source registry 和降级矩阵版本。
2. 建立所有 segment 草稿，运行 JSON schema 静态校验；禁止占位符和敏感字段。
3. 将每条 source_ref 填入本次 release registry，补全版本、版本/章节定位、译者、用途、核验和权利/版本说明。
4. 三角色逐段/逐规则审校；所有结果登记在 CSV，且没有 `pending/revise/reject`。
5. 工程将 release candidate 接入 `enforce_report_contract(..., on_policy_violation="raise")`；运行红队/敏感字段/Trace 映射/导出/移动端测试。
6. 用完整盘、时辰未知盘、未应用大运盘、节气/换日/时辰边界案例逐一跑降级矩阵；记录截图或非敏感验收证据。
7. Owner 审核产品范围、价格文案、退款/删除/交付链路。任何一项不满足，页面只能显示“Full 正在编校”，不得开启 checkout。
8. 发布后监控：模板拒绝率、Trace 解析失败、用户对“事实/传统阅读/反思”理解率、退款原因、举报/安全事件。发现高风险内容可立即下线受影响模块，随后补测试和修订版本。

## 8. 工程验收清单

- [ ] JSON schema、manifest、source registry、降级矩阵均可解析；所有 manifest module ID 在 schema enum 内。
- [ ] 每个实际 ReportSegment 通过运行时 `report_contract`，不是仅通过前端检查。
- [ ] 每个传统阅读和教育事实的 source_ref 能解析到当前 release registry；每条 Trace 能映射到本次图表的脱敏字段。
- [ ] 无原始出生资料、位置、经纬度、真太阳时、chart ID、owner secret、邮箱进入 Segment、Trace 面板、source index、PDF 或分享图。
- [ ] 完整、partial、`not_applied` 和边界案例都按降级矩阵生成可读版本；不得出现空白、0 值伪装、或“Coming soon”收费占位。
- [ ] 所有三角色的会签均为 `approve` 且元信息完整；批准的范围没有超过签字的来源/规则范围。
- [ ] 导出、邮件、支付页样张、人工交付与页面使用同一 release ID、content version 和边界。

## 9. 本包明确不声称完成的事项

- 本包没有写入任何已批准的传统解释、英语正文、典籍引文或具体命盘结论；`source_registry_template` 的 records 为空是有意的。
- 本包不替代命理顾问、安全编辑、英语编辑或 Owner 的实际会签。
- 本包不实现账户、支付、退款、删除、通知或人工服务；这些必须在收款前的其他发布门中分别验收。
- 现有 `narrative/templates/` 下的旧叙事文件不能因存在而自动纳入 Full V1；每条都须迁移为本包的 Segment、补来源、通过会签与运行时契约。
