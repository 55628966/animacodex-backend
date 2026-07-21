# -*- coding: utf-8 -*-
"""ReportSegment v1 的结构、溯源与高风险结论发布门测试。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bazi_engine.report_contract import (  # noqa: E402
    ClaimType,
    ReportContractError,
    ReportPolicyViolation,
    SegmentStatus,
    enforce_report_contract,
    make_report_segment,
)


def _traditional_kwargs(**overrides):
    data = {
        "segment_id": "core-day-master",
        "claim_type": ClaimType.TRADITIONAL_READING,
        "body": "Under this profile, this pattern is traditionally read as a theme for reflection.",
        "boundary": "Traditional context boundary: for reflection, not prediction.",
        "evidence": [{"kind": "chart_field", "ref": "day_master.element"}],
        "trace_refs": ["meta.calculation_trace.profile_id"],
        "source_refs": ["editorial:day-master-guide-v1"],
        "content_version": "2026-07-19",
    }
    data.update(overrides)
    return data


def test_valid_segment_has_stable_b_mapping_fields_and_default_boundary():
    """模型B 可只依赖这一稳定结构渲染报告，不需要猜测字段。"""
    output = make_report_segment(**_traditional_kwargs()).to_dict()
    assert set(output) == {
        "contract_version", "segment_id", "claim_type", "body", "boundary", "evidence",
        "trace_refs", "source_refs", "profile_id", "content_version", "risk_flags", "status",
    }
    assert output["contract_version"] == "report_segment_v1"
    assert output["claim_type"] == "traditional_reading"
    assert output["profile_id"] == "zi_ping_solar_v1"
    assert output["status"] == "published"
    assert len(output["boundary"]) >= 12
    assert output["evidence"] == [{"kind": "chart_field", "ref": "day_master.element"}]


def test_required_claim_types_are_supported_including_migration_alias():
    """宪章正式值 + 任务要求的 traditional_interpretation 迁移兼容值均可受约束。"""
    cases = [
        (ClaimType.CHART_FACT, {"evidence": [{"kind": "chart_field", "ref": "pillars.month.branch"}]}),
        (ClaimType.TRADITIONAL_INTERPRETATION, {
            "evidence": [{"kind": "traditional_rule", "ref": "zi_ping_solar_v1.ten-gods"}],
            "source_refs": ["editorial:ten-gods-guide-v1"],
        }),
        (ClaimType.REFLECTION_PROMPT, {"source_refs": ["editorial:reflection-prompts-v1"]}),
        (ClaimType.EDUCATIONAL_FACT, {"source_refs": ["classic:di-tian-sui.section-1"]}),
    ]
    for index, (claim_type, support) in enumerate(cases):
        segment = make_report_segment(
            segment_id=f"allowed-type-{index}",
            claim_type=claim_type,
            body="A bounded, non-directive report paragraph for the selected type.",
            content_version="2026-07-19",
            **support,
        )
        assert segment.claim_type == claim_type


@pytest.mark.parametrize(
    ("claim_type", "support", "expected"),
    [
        (ClaimType.CHART_FACT, {"source_refs": ["editorial:guide-v1"]}, "chart_fact"),
        (ClaimType.TRADITIONAL_READING, {
            "evidence": [{"kind": "chart_field", "ref": "day_master.element"}],
        }, "traditional_reading"),
        (ClaimType.EDUCATIONAL_FACT, {
            "evidence": [{"kind": "editorial_note", "ref": "glossary.ten-gods"}],
        }, "educational_fact"),
    ],
)
def test_claim_specific_evidence_requirements_fail_closed(claim_type, support, expected):
    with pytest.raises(ReportContractError, match=expected):
        make_report_segment(
            segment_id="missing-required-support",
            claim_type=claim_type,
            body="A bounded report paragraph that is deliberately missing required support.",
            content_version="2026-07-19",
            **support,
        )


def test_every_segment_requires_claim_type_support_and_boundary():
    raw = _traditional_kwargs()
    raw.pop("claim_type")
    raw["boundary"] = "A clear report boundary that is long enough."
    with pytest.raises(ReportContractError, match="claim_type"):
        enforce_report_contract([raw])

    raw = _traditional_kwargs(boundary="short")
    with pytest.raises(ReportContractError, match="boundary"):
        enforce_report_contract([raw])

    raw = _traditional_kwargs(evidence=[], trace_refs=[], source_refs=[])
    with pytest.raises(ReportContractError, match="evidence"):
        enforce_report_contract([raw])


def test_sensitive_personal_references_cannot_enter_trace_or_evidence():
    with pytest.raises(ReportContractError, match="不得引用"):
        make_report_segment(**_traditional_kwargs(
            evidence=[{"kind": "chart_field", "ref": "birth_date"}],
        ))


@pytest.mark.parametrize(
    ("category", "body"),
    [
        ("deterministic_fate", "Your fate is destined to fail."),
        ("pseudoscientific_claim", "BaZi is scientifically proven for every person."),
        ("medical_or_reproductive", "You will develop cancer next year."),
        ("financial_or_gambling", "You should invest in crypto immediately."),
        ("legal_directive", "You should sue your employer now."),
        ("harmful_action", "This reading tells you to self-harm."),
        ("discriminatory", "Women are inferior and cannot succeed."),
        ("deterministic_fate", "你命中注定会失败。"),
        ("medical_or_reproductive", "命盘显示你会患病。"),
        ("financial_or_gambling", "建议你买入股票。"),
        ("discriminatory", "女性天生不适合领导。"),
    ],
)
def test_prohibited_user_visible_conclusions_fail_closed(category, body):
    with pytest.raises(ReportPolicyViolation) as exc:
        make_report_segment(**_traditional_kwargs(body=body))
    assert exc.value.category == category


def test_policy_violation_can_be_degraded_without_echoing_harmful_body():
    raw = _traditional_kwargs(body="You should invest in crypto immediately.")
    segment = enforce_report_contract([raw], on_policy_violation="degrade")[0]
    output = segment.to_dict()
    assert segment.claim_type == ClaimType.UNSUPPORTED_OR_EXCLUDED
    assert segment.status == SegmentStatus.EXCLUDED
    assert output["degradation_reason"] == "financial_or_gambling"
    assert "crypto" not in output["body"].lower()
    assert output["source_refs"] == ["policy:report-contract-v1"]


def test_structural_errors_never_degrade_away():
    raw = _traditional_kwargs(body="You should invest in crypto immediately.")
    raw.pop("boundary", None)
    with pytest.raises(ReportContractError, match="boundary"):
        enforce_report_contract([raw], on_policy_violation="degrade")


def test_excluded_claim_type_requires_excluded_status_and_policy_source():
    with pytest.raises(ReportContractError, match="unsupported_or_excluded"):
        make_report_segment(
            segment_id="bad-excluded",
            claim_type=ClaimType.UNSUPPORTED_OR_EXCLUDED,
            body="This request is outside scope.",
            source_refs=["policy:report-contract-v1"],
            content_version="2026-07-19",
        )
