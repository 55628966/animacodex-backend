# -*- coding: utf-8 -*-
"""时辰反推模块（bazi_engine.hour_inference）回归测试。

覆盖：确定性 / 归一化 / 锁定语义 / 红线（5问未达90%锁死；4问达90%提前锁定）/
非法输入 / 单调性冒烟。
"""

import pytest

from bazi_engine.hour_inference import (
    BRANCHES,
    LOCK_THRESHOLD,
    MAX_QUESTIONS,
    QUESTIONS,
    start_session,
    update_session,
)

# 强证据序列：天色大亮 + 午饭前后 + 日头正顶 + 大人午间打盹 → 应锁定"午"
STRONG_NOON = [
    {"question_id": "q_sky_light", "option_key": "opt_bright"},
    {"question_id": "q_meal", "option_key": "opt_lunch"},
    {"question_id": "q_sun_position", "option_key": "opt_overhead"},
    {"question_id": "q_family_asleep", "option_key": "opt_noon_nap"},
]

# 5 个不同问题全答"不确定"
FIVE_UNSURE = [
    {"question_id": qid, "option_key": "opt_unknown"}
    for qid in ["q_sky_light", "q_family_asleep", "q_meal", "q_rooster_sun", "q_work"]
]

# 5 问弱证据（互相不聚焦，达不到 0.90）
FIVE_WEAK = [
    {"question_id": "q_sky_light", "option_key": "opt_dim"},
    {"question_id": "q_family_asleep", "option_key": "opt_unknown"},
    {"question_id": "q_meal", "option_key": "opt_no_meal"},
    {"question_id": "q_rooster_sun", "option_key": "opt_none"},
    {"question_id": "q_work", "option_key": "opt_unknown"},
]


def _conf_map(state):
    """candidates 列表 → {地支: 置信度} 字典。"""
    return {c["branch"]: c["confidence"] for c in state["candidates"]}


# ---------------------------------------------------------------------------
# 结构与初始状态
# ---------------------------------------------------------------------------

def test_start_session_structure():
    """start_session：均匀先验、12候选按固定地支序、未锁定且给出首问。"""
    s = start_session()
    assert [c["branch"] for c in s["candidates"]] == BRANCHES
    for c in s["candidates"]:
        assert c["confidence"] == round(1.0 / 12.0, 4)  # 0.0833
    assert s["asked_count"] == 0
    assert s["max_questions"] == MAX_QUESTIONS == 5
    assert s["locked"] is False
    assert s["next_question_id"] in {q["id"] for q in QUESTIONS}


def test_question_bank_sanity():
    """问题库自检：6-8问、向量12维且无0、每问含全1的不确定类选项。"""
    assert 6 <= len(QUESTIONS) <= 8
    for q in QUESTIONS:
        has_all_ones = False
        for okey, vec in q["options"].items():
            assert len(vec) == 12
            assert all(v > 0 for v in vec)          # 不许出现0
            if all(v == 1 for v in vec):
                has_all_ones = True
        assert has_all_ones, f"{q['id']} 缺少全1的不确定选项"


# ---------------------------------------------------------------------------
# 确定性
# ---------------------------------------------------------------------------

def test_determinism_same_answers_same_result():
    """同一答案序列两次调用，结果逐位相同。"""
    for answers in ([], STRONG_NOON, FIVE_UNSURE, FIVE_WEAK):
        r1 = update_session(answers)
        r2 = update_session(answers)
        assert r1 == r2
    assert start_session() == start_session()


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

def test_normalization_sums_to_one():
    """任何状态下 12 个 confidence 求和 ≈ 1（容忍4位舍入误差）。"""
    for answers in ([], STRONG_NOON, FIVE_UNSURE, FIVE_WEAK,
                    [{"question_id": "q_sky_light", "option_key": "opt_dark"}]):
        s = update_session(answers)
        total = sum(c["confidence"] for c in s["candidates"])
        assert abs(total - 1.0) < 0.005


# ---------------------------------------------------------------------------
# 锁定语义与红线
# ---------------------------------------------------------------------------

def test_strong_evidence_locks_near_noon():
    """强证据序列锁定到午/未附近，locked=True 且不再给问题。"""
    s = update_session(STRONG_NOON)
    conf = _conf_map(s)
    best = max(conf, key=conf.get)
    assert best in ("午", "未")
    assert conf[best] >= LOCK_THRESHOLD
    assert s["locked"] is True
    assert s["next_question_id"] is None


def test_early_lock_at_four_questions():
    """红线：4问已达90% → 提前锁定（不必问满5问）。"""
    s = update_session(STRONG_NOON)
    assert s["asked_count"] == 4
    assert s["locked"] is True
    assert s["next_question_id"] is None


def test_locked_branch_field_on_lock():
    """《00》4.2 v1.1(拍板2026-07-17): locked=True 时必须返回 locked_branch,
    且等于置信度最高的时辰地支。"""
    s = update_session(STRONG_NOON)
    assert s["locked"] is True
    conf = _conf_map(s)
    assert s["locked_branch"] == max(conf, key=conf.get)


def test_locked_branch_absent_when_not_locked():
    """未锁定状态(初始/问尽未达标)不得出现 locked_branch 字段。"""
    assert "locked_branch" not in start_session()
    s = update_session(FIVE_WEAK)
    assert s["locked"] is False and "locked_branch" not in s
    s2 = update_session(FIVE_UNSURE)
    assert s2["locked"] is False and "locked_branch" not in s2


def test_five_unsure_exhausted_not_locked():
    """全"不确定"5问：分布仍均匀，locked=False 且 next_question_id=None。"""
    s = update_session(FIVE_UNSURE)
    assert s["asked_count"] == 5
    assert s["locked"] is False
    assert s["next_question_id"] is None
    # 全1似然不更新分布 → 仍为均匀先验
    for c in s["candidates"]:
        assert c["confidence"] == round(1.0 / 12.0, 4)


def test_redline_five_questions_below_threshold_locks_out():
    """红线：5问后最高置信度<90% → 必然 locked=False 且不再给问题。"""
    s = update_session(FIVE_WEAK)
    assert s["asked_count"] == 5
    assert max(c["confidence"] for c in s["candidates"]) < LOCK_THRESHOLD
    assert s["locked"] is False
    assert s["next_question_id"] is None


def test_unlocked_midway_gives_unasked_question():
    """未锁定且未问尽时：next_question_id 必须是未问过的合法问题。"""
    answers = [{"question_id": "q_sky_light", "option_key": "opt_dark"}]
    s = update_session(answers)
    assert s["locked"] is False
    assert s["next_question_id"] is not None
    assert s["next_question_id"] != "q_sky_light"
    assert s["next_question_id"] in {q["id"] for q in QUESTIONS}


def test_repeated_question_last_answer_wins():
    """同一问题重复回答：以最后一次为准，且 asked_count 只计一次。"""
    twice = [
        {"question_id": "q_sky_light", "option_key": "opt_dark"},
        {"question_id": "q_sky_light", "option_key": "opt_bright"},
    ]
    once = [{"question_id": "q_sky_light", "option_key": "opt_bright"}]
    r_twice = update_session(twice)
    r_once = update_session(once)
    assert r_twice["candidates"] == r_once["candidates"]
    assert r_twice["asked_count"] == 1


# ---------------------------------------------------------------------------
# 非法输入
# ---------------------------------------------------------------------------

def test_unknown_question_raises():
    """非法 question_id → ValueError('UNKNOWN_QUESTION')。"""
    with pytest.raises(ValueError, match="UNKNOWN_QUESTION"):
        update_session([{"question_id": "q_不存在", "option_key": "opt_unknown"}])


def test_unknown_option_raises():
    """非法 option_key → ValueError('UNKNOWN_OPTION')。"""
    with pytest.raises(ValueError, match="UNKNOWN_OPTION"):
        update_session([{"question_id": "q_sky_light", "option_key": "opt_不存在"}])


def test_missing_fields_raise():
    """缺字段的答案项同样按非法输入处理。"""
    with pytest.raises(ValueError, match="UNKNOWN_QUESTION"):
        update_session([{"option_key": "opt_unknown"}])
    with pytest.raises(ValueError, match="UNKNOWN_OPTION"):
        update_session([{"question_id": "q_sky_light"}])


# ---------------------------------------------------------------------------
# 单调性冒烟
# ---------------------------------------------------------------------------

def test_monotonic_dark_favors_night_branches():
    """只答"天色黑"：夜间时辰(戌亥子丑寅)置信度之和 > 白昼时辰之和。"""
    s = update_session([{"question_id": "q_sky_light", "option_key": "opt_dark"}])
    conf = _conf_map(s)
    night = sum(conf[b] for b in ("戌", "亥", "子", "丑", "寅"))
    day = sum(conf[b] for b in ("卯", "辰", "巳", "午", "未", "申", "酉"))
    assert night > day
