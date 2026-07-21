# -*- coding: utf-8 -*-
"""时辰反推——纯计算模块（模型A负责）。

职责边界（依《00_总纲》4.2 与《01_模型A任务书》第五节）：
- 本模块只做计算与置信度框架：均匀先验 + 逐答案贝叶斯乘法更新 + 归一化。
- 问题的用户文案归模型B；本模块只定义问题ID、语义（evidence/meaning）与判别力权重。
- 红线在本模块执行：最多 5 问后最高置信度 < 0.90 → locked=False，
  只允许前三柱排盘（partial=true）。前端/后端不许绕过此判断。

硬性约束：
- 纯计算：无网络、无IO、无随机数；同一 answers 序列永远得到同一结果。
- confidence 四舍五入到 4 位小数（锁定判断使用未舍入值，避免边界抖动）。

权重表版本：v1.0 判别力权重，待命理顾问校准签字。
"""

import math

# ---------------------------------------------------------------------------
# 基础常量
# ---------------------------------------------------------------------------

# 12地支时辰，固定顺序（子=23-01时, 丑=01-03, 寅=03-05, 卯=05-07, 辰=07-09,
# 巳=09-11, 午=11-13, 未=13-15, 申=15-17, 酉=17-19, 戌=19-21, 亥=21-23）
BRANCHES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

MAX_QUESTIONS = 5          # 红线：最多问 5 个问题
LOCK_THRESHOLD = 0.90      # 红线：最高置信度 >= 0.90 才允许锁定时辰

# ---------------------------------------------------------------------------
# 问题库（v1.0 判别力权重，待命理顾问校准签字）
#
# 结构说明：
# - id       : 问题唯一标识，模型B据此写文案，不许改语义。
# - evidence : 一句话语义（给模型B写文案用，本身不是面向用户的文案）。
# - options  : 每个选项一个 12 维似然向量 P(观察到该回答 | 出生于该时辰) 的相对值，
#              顺序与 BRANCHES 一致（子丑寅卯辰巳午未申酉戌亥）。
#              取值口径（保守量级）：符合的时辰 4~6，弱相关/过渡 2~3，对立时辰 1；
#              全表不出现 0（任何回答都不把某时辰置信度打成绝对零）；
#              "不确定/记不清"类选项恒为全 1（乘法更新后分布不变）。
# - 每个向量旁注释推理依据（传统问时辰的常识线索）。
# ---------------------------------------------------------------------------

# 问题库（v1.1 —— 从"出生瞬间观察"改为"人生经历/性格倾向"，
# 确保受访者本人能够基于自身感受回答。）
#
# 结构说明：
# - id       : 问题唯一标识，模型B据此写文案，不许改语义。
# - evidence : 一句话语义（给模型B写文案用，本身不是面向用户的文案）。
# - options  : 每个选项一个 12 维似然向量 P(观察到该回答 | 出生于该时辰) 的相对值，
#              顺序与 BRANCHES 一致（子丑寅卯辰巳午未申酉戌亥）。
#              取值口径（保守量级）：符合的时辰 4~6，弱相关/过渡 2~3，对立时辰 1；
#              全表不出现 0（任何回答都不把某时辰置信度打成绝对零）；
#              "不确定/记不清"类选项恒为全 1（乘法更新后分布不变）。
# - 每个向量旁注释推理依据（传统问时辰的常识线索）。
# ---------------------------------------------------------------------------

QUESTIONS = [
    {
        "id": "q_mind_peak",
        "evidence": "顺其自然时，头脑最清醒的时间段（清晨/上午/午后/夜晚/深夜）",
        # 依据：阳气升降对应大脑活跃度 ——
        # 卯辰:日出阳气升→早起清醒(5~6); 巳午:阳气最盛→午前午后(5~6);
        # 申酉:日落倦意(2~3); 亥子丑:夜深安静型(4~6)
        "options": {
            #                 子  丑  寅  卯  辰  巳  午  未  申  酉  戌  亥
            "opt_dawn":      [2,  1,  3,  5,  6,  4,  2,  1,  1,  1,  1,  1],
            # 清晨(寅卯辰):寅=曙光初现(3),卯=日出清醒(5),辰=旭日晨间(6)
            "opt_morning":   [1,  1,  1,  2,  4,  5,  4,  2,  1,  1,  1,  1],
            # 上午(巳午):巳=巳时通明(5),午=盛午(4),辰未过渡(2~4)
            "opt_afternoon": [1,  1,  1,  1,  1,  2,  3,  4,  5,  4,  2,  1],
            # 午后(未申酉):未=午后慵懒(4),申=傍晚专注(5),酉=日落前(4)
            "opt_night":     [4,  5,  4,  2,  1,  1,  1,  1,  1,  2,  4,  6],
            # 夜晚(戌亥子丑):戌=初夜安静(4),亥=深夜效率(6),子=子时冥思(5),丑=深夜深思(4)
            "opt_no_pattern": [1, 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1],
        },
        "option_meanings": {
            "opt_dawn": "清晨（日出前后）",
            "opt_morning": "上午",
            "opt_afternoon": "午后至傍晚",
            "opt_night": "夜晚至深夜",
            "opt_no_pattern": "无明显规律",
        },
    },
    {
        "id": "q_response_style",
        "evidence": "面对突发挫折的第一反应模式（立刻行动/先分析/等待/另辟蹊径）",
        # 依据：时辰与先天性格倾向 ——
        # 子午卯酉"四正"：果断型(子午偏行动,卯酉偏谋略);
        # 寅申巳亥"四生"：开拓型(寅巳偏行动,申亥偏变通);
        # 辰戌丑未"四库"：稳妥型(偏等待/积蓄)
        "options": {
            #                 子  丑  寅  卯  辰  巳  午  未  申  酉  戌  亥
            "opt_act_immediate": [5, 1, 5, 2, 2, 5, 5, 1, 2, 1, 2, 2],
            # 立刻行动:子=果断(5),寅=开拓(5),巳=火性急(5),午=火性烈(5)
            "opt_analyze":     [2,  2,  2,  6,  3,  1,  1,  3,  1,  6,  2,  1],
            # 先分析:卯=谋略型(6),酉=精密型(6),辰未戌=库蓄(2~3)
            "opt_wait":        [1,  6,  1,  1,  6,  1,  1,  6,  2,  1,  6,  2],
            # 等待:丑=坚忍(6),辰=蓄势(6),未=柔韧(6),戌=固守(6)
            "opt_new_path":    [1,  2,  3,  2,  2,  3,  2,  2,  6,  2,  1,  6],
            # 另辟蹊径:申=变通(6),亥=灵变(6),寅巳=开拓(3)
            "opt_unknown":     [1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1],
        },
        "option_meanings": {
            "opt_act_immediate": "立刻行动，先做了再说",
            "opt_analyze": "先分析全局，再精准出手",
            "opt_wait": "静观其变，多数问题会自己解决",
            "opt_new_path": "转身另辟一条路",
            "opt_unknown": "说不好",
        },
    },
    {
        "id": "q_social_role",
        "evidence": "身边人最常因为什么来找你（决策/谋略/安稳/推动力）",
        # 依据：五行人格在时辰上的投影 ——
        # 子(水):谋略; 午(火):决断; 卯(木):推动; 酉(金):决断;
        # 寅(木):推动; 巳(火):决断; 申(金):谋略; 亥(水):谋略;
        # 辰戌丑未(土):安稳
        "options": {
            #                 子  丑  寅  卯  辰  巳  午  未  申  酉  戌  亥
            "opt_decide":    [3,  2,  3,  4,  2,  6,  6,  2,  4,  5,  2,  2],
            # 决断型:巳=炼金(6),午=烈火(6),酉=金断(5),申卯=辅决(3~4)
            "opt_counsel":   [6,  3,  3,  2,  2,  2,  1,  2,  6,  3,  2,  6],
            # 谋略型:子=玄水(6),申=智金(6),亥=渊水(6),丑辰未=土厚辅谋(2~3)
            "opt_steady":    [1,  6,  1,  2,  5,  1,  1,  6,  1,  1,  5,  1],
            # 安稳型:丑=坚土(6),未=柔土(6),辰戌=库土(5)
            "opt_push":      [2,  2,  6,  6,  3,  4,  3,  2,  2,  2,  2,  2],
            # 推动型:寅=生发(6),卯=舒张(6),巳=助燃(4),午辰=辅推(2~3)
            "opt_unknown":   [1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1],
        },
        "option_meanings": {
            "opt_decide": "求决断——我能一锤定音",
            "opt_counsel": "求谋略——我看得见全局",
            "opt_steady": "求安稳——我不动摇",
            "opt_push": "求推力——我能让事情动起来",
            "opt_unknown": "说不好",
        },
    },
    {
        "id": "q_turning_point",
        "evidence": "人生第一次重大转折（分水岭事件）发生在什么年龄段",
        # 依据：大运起运年龄内化为人格转折；早转折(童年/青少年)对应寅卯辰巳(生发早运)、
        # 中转折(成年早期)对应午未申(旺运)、晚转折对应戌亥子丑(秋冬收藏);
        # 选项简化为 age 区间而非精确年龄
        "options": {
            #                 子  丑  寅  卯  辰  巳  午  未  申  酉  戌  亥
            "opt_child":     [2,  2,  5,  5,  5,  4,  2,  1,  1,  1,  1,  1],
            # 童年(12岁前):寅卯辰=生发早(5),巳(4);其余递减
            "opt_teen":      [2,  2,  4,  5,  5,  5,  4,  2,  2,  1,  1,  1],
            # 青少年(13-18):寅卯辰巳午=蓬勃发育(4~5)
            "opt_young_adult":[3, 3,  3,  3,  3,  4,  6,  6,  5,  3,  2,  2],
            # 青年(19-25):午未申=壮旺(5~6),其余过渡
            "opt_adult":     [5,  5,  3,  2,  2,  2,  3,  3,  4,  6,  6,  5],
            # 25岁后:酉戌亥子丑=收藏(5~6)
            "opt_not_yet":   [1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1],
        },
        "option_meanings": {
            "opt_child": "童年（12岁前）",
            "opt_teen": "青少年（13-18岁）",
            "opt_young_adult": "青年（19-25岁）",
            "opt_adult": "25岁之后",
            "opt_not_yet": "尚未到来",
        },
    },
    {
        "id": "q_independence",
        "evidence": "第一次完全自主的重大人生决定发生在什么时机（离家/择业/新生）",
        # 依据：人生关键转折与时辰的节奏对应 ——
        # 卯寅:早出发; 辰巳午:稳步上升期; 未申:调整期; 酉戌:成熟期; 亥子丑:晚期大器
        "options": {
            #                 子  丑  寅  卯  辰  巳  午  未  申  酉  戌  亥
            "opt_early":     [1,  1,  6,  5,  4,  2,  1,  1,  1,  1,  1,  1],
            # 很早(18岁前):寅=早发(6),卯=早行(5),辰=早立(4)
            "opt_early_adult":[2, 2,  4,  5,  6,  5,  4,  2,  2,  1,  1,  1],
            # 成年早期(18-22):卯辰巳午=成长期(4~6)
            "opt_mid_adult": [3,  3,  2,  2,  3,  4,  5,  5,  5,  4,  2,  2],
            # 成年中期(23-28):午未申=成熟期(5)
            "opt_late":      [5,  5,  2,  1,  1,  1,  2,  2,  3,  6,  6,  5],
            # 较晚(28岁后):酉戌亥子丑=晚成(5~6)
            "opt_not_applied":[1, 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1],
        },
        "option_meanings": {
            "opt_early": "很早（18岁以前）",
            "opt_early_adult": "成年早期（18-22岁）",
            "opt_mid_adult": "成年中期（23-28岁）",
            "opt_late": "较晚（28岁以后）",
            "opt_not_applied": "尚未经历",
        },
    },
]


# 索引：question_id -> 问题定义（构建一次，便于校验与查表）
_QUESTION_INDEX = {q["id"]: q for q in QUESTIONS}


# ---------------------------------------------------------------------------
# 内部纯函数
# ---------------------------------------------------------------------------

def _validate_and_dedup(answers):
    """校验答案列表并去重（同一问题重复回答以最后一次为准）。

    返回 (有效答案字典 question_id->option_key, 按首次出现排序的已问ID列表)。
    非法 question_id / option_key 抛 ValueError。
    """
    if not isinstance(answers, list):
        raise ValueError("UNKNOWN_QUESTION")
    effective = {}      # question_id -> option_key（后答覆盖先答）
    asked_order = []    # 已问问题ID（按首次出现顺序，用于 asked_count）
    for item in answers:
        if not isinstance(item, dict):
            raise ValueError("UNKNOWN_QUESTION")
        qid = item.get("question_id")
        okey = item.get("option_key")
        if qid not in _QUESTION_INDEX:
            raise ValueError("UNKNOWN_QUESTION")
        if okey not in _QUESTION_INDEX[qid]["options"]:
            raise ValueError("UNKNOWN_OPTION")
        if qid not in effective:
            asked_order.append(qid)
        effective[qid] = okey
    return effective, asked_order


def _posterior(effective_answers):
    """从均匀先验出发，按问题-证据似然表做乘法贝叶斯更新并归一化。

    effective_answers: question_id -> option_key（已去重）。
    返回未舍入的 12 维后验概率列表（顺序与 BRANCHES 一致）。
    完全确定性：只做乘法与归一化，无随机数。
    """
    # 均匀先验：各 1/12
    post = [1.0 / 12.0] * 12
    for qid, okey in effective_answers.items():
        likelihood = _QUESTION_INDEX[qid]["options"][okey]
        post = [p * l for p, l in zip(post, likelihood)]
        total = sum(post)
        # 似然表不含0且先验为正，total 恒为正，无需防零分支
        post = [p / total for p in post]
    return post


def _entropy(probs):
    """香农熵（自然对数）。p=0 的项按 0 计（本模块中概率恒为正）。"""
    return -sum(p * math.log(p) for p in probs if p > 0.0)


def _expected_information_gain(question, post):
    """某问题在当前后验下的期望信息增益（下一问选择的判别力指标）。

    回答生成模型：P(选项o | 时辰b) = L[o][b] / Σ_o' L[o'][b]
    （把该问题各选项的似然按时辰列归一化，作为该时辰下用户选各选项的条件概率）。
    EIG = H(当前后验) - Σ_o P(o) * H(回答o后的后验)。
    该指标非负、确定性，"不确定"占比高的问题增益自然偏低。
    """
    option_keys = list(question["options"].keys())
    # 各时辰列的似然总和（用于列归一化）
    col_sum = [0.0] * 12
    for okey in option_keys:
        vec = question["options"][okey]
        for b in range(12):
            col_sum[b] += vec[b]
    h_now = _entropy(post)
    expected_h = 0.0
    for okey in option_keys:
        vec = question["options"][okey]
        # P(o|b) 列归一化后与后验相乘 → 联合分布，再归一化得回答o后的后验
        joint = [post[b] * vec[b] / col_sum[b] for b in range(12)]
        p_o = sum(joint)
        if p_o <= 0.0:
            continue
        cond_post = [j / p_o for j in joint]
        expected_h += p_o * _entropy(cond_post)
    return h_now - expected_h


def _next_question_id(post, asked_ids):
    """在未问问题中选期望信息增益最大者；并列时取问题库中靠前者（确定性）。"""
    best_id = None
    best_gain = -1.0
    for q in QUESTIONS:                     # 固定遍历顺序保证确定性
        if q["id"] in asked_ids:
            continue
        gain = _expected_information_gain(q, post)
        if gain > best_gain:                # 严格大于 → 并列时保留靠前问题
            best_gain = gain
            best_id = q["id"]
    return best_id


def _build_state(post, asked_ids):
    """按接口契约组装会话状态。红线判定在此执行，前端不许绕过。"""
    max_conf = max(post)                    # 锁定判断用未舍入值，避免边界抖动
    asked_count = len(asked_ids)
    if max_conf >= LOCK_THRESHOLD:
        # 达到 0.90 → 锁定时辰，不再提问
        locked = True
        next_qid = None
    elif asked_count >= MAX_QUESTIONS:
        # 红线：问尽 5 问仍 < 0.90 → 永不锁定，不再给问题；
        # 上层据此只允许前三柱排盘（partial=true）
        locked = False
        next_qid = None
    else:
        locked = False
        next_qid = _next_question_id(post, asked_ids)
    state = {
        "candidates": [
            {"branch": b, "confidence": round(p, 4)}
            for b, p in zip(BRANCHES, post)
        ],
        "next_question_id": next_qid,
        "asked_count": asked_count,
        "max_questions": MAX_QUESTIONS,
        "locked": locked,
    }
    if locked:
        # 《00》4.2 v1.1 增补(拍板 2026-07-17): 锁定时必须返回锁定时辰地支,
        # 取未舍入后验的最大项(index取首个, 纯确定性)
        state["locked_branch"] = BRANCHES[post.index(max_conf)]
    return state


# ---------------------------------------------------------------------------
# 对外接口（后端工程师按此对接，签名与返回结构不许改）
# ---------------------------------------------------------------------------

def start_session():
    """开启时辰反推会话：返回均匀先验(各1/12)与第一个建议问题。"""
    return update_session([])


def update_session(answers):
    """按答案序列全量重算会话状态（无状态设计，天然可复现）。

    answers: [{"question_id": "...", "option_key": "..."}, ...] 按提问顺序。
    - 同一问题重复回答以最后一次为准（按序覆盖后重算）。
    - 非法 question_id → ValueError("UNKNOWN_QUESTION")；
      非法 option_key  → ValueError("UNKNOWN_OPTION")。
    - 同一 answers 序列永远得到同一结果（纯计算、无随机数）。
    """
    effective, asked_order = _validate_and_dedup(answers)
    post = _posterior(effective)
    return _build_state(post, asked_order)
