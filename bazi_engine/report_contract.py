# -*- coding: utf-8 -*-
"""用户可见报告段落的强制契约（ReportSegment v1）。

本模块不撰写命理叙事，也不判断某条传统解释是否得到命理顾问会签；它只负责
把《16_传统内核与商业伦理宪章》中可由代码执行的发布前条件变成硬约束：

* 每个用户可见段落必须有 ``claim_type``、可追溯依据和边界文本；
* 传统解释必须同时指向盘面/规则依据及术语或编辑来源；
* 宿命绝对化、伪科学、医疗、金融、法律、伤害及歧视性结论不可发布；
* 调用方可以选择严格失败，或把命中的单段降级为明确的 ``unsupported_or_excluded``。

这不是内容安全的唯一防线。模型B 的 UI/推送/支付页、人工审校和产品发布门仍需
调用同一校验器；新增传统规则仍须命理顾问会签，不能因为结构合法就被视为校勘完成。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Iterable, Mapping, Sequence

from .transparency import PROFILE_ID


REPORT_CONTRACT_VERSION = "report_segment_v1"


class ClaimType(str, Enum):
    """可发布的结论类型。

    ``traditional_reading`` 是《16》宪章的正式名称。
    ``traditional_interpretation`` 保留为迁移兼容名：它与前者同属传统解释，
    但在新模板中优先使用 ``traditional_reading``。保留该值是为了使历史内容
    迁移时不会绕开校验器。
    """

    CHART_FACT = "chart_fact"
    TRADITIONAL_READING = "traditional_reading"
    TRADITIONAL_INTERPRETATION = "traditional_interpretation"
    REFLECTION_PROMPT = "reflection_prompt"
    EDUCATIONAL_FACT = "educational_fact"
    UNSUPPORTED_OR_EXCLUDED = "unsupported_or_excluded"


class SegmentStatus(str, Enum):
    PUBLISHED = "published"
    EXCLUDED = "excluded"


class ReportContractError(ValueError):
    """段落结构、溯源或内容策略不符合发布契约。"""


class ReportPolicyViolation(ReportContractError):
    """段落正文命中不可发布的结论或措辞。"""

    def __init__(self, category: str, detail: str):
        self.category = category
        super().__init__(detail)


@dataclass(frozen=True)
class EvidenceRef:
    """一条可展示、不可含出生隐私的证据/规则引用。"""

    kind: str
    ref: str
    label: str = ""

    def to_dict(self) -> dict[str, str]:
        data = {"kind": self.kind, "ref": self.ref}
        if self.label:
            data["label"] = self.label
        return data


@dataclass(frozen=True)
class ReportSegment:
    """唯一允许进入用户可见报告、导出、推送或付费样章的段落结构。"""

    segment_id: str
    claim_type: ClaimType | str
    body: str
    boundary: str
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)
    trace_refs: tuple[str, ...] = field(default_factory=tuple)
    source_refs: tuple[str, ...] = field(default_factory=tuple)
    profile_id: str = PROFILE_ID
    content_version: str = "unversioned"
    risk_flags: tuple[str, ...] = field(default_factory=tuple)
    status: SegmentStatus | str = SegmentStatus.PUBLISHED
    degradation_reason: str | None = None

    def __post_init__(self) -> None:
        # frozen dataclass 仍可在初始化期标准化 Enum；错误会在此处阻断对象生成。
        object.__setattr__(self, "claim_type", _coerce_claim_type(self.claim_type))
        object.__setattr__(self, "status", _coerce_status(self.status))
        object.__setattr__(self, "evidence", tuple(_coerce_evidence(item) for item in self.evidence))
        object.__setattr__(self, "trace_refs", tuple(self.trace_refs))
        object.__setattr__(self, "source_refs", tuple(self.source_refs))
        object.__setattr__(self, "risk_flags", tuple(self.risk_flags))
        validate_report_segment(self)

    def to_dict(self) -> dict[str, Any]:
        """稳定、JSON 可序列化的输出；不暴露 dataclass/Enum 实现细节。"""
        data: dict[str, Any] = {
            "contract_version": REPORT_CONTRACT_VERSION,
            "segment_id": self.segment_id,
            "claim_type": self.claim_type.value,
            "body": self.body,
            "boundary": self.boundary,
            "evidence": [item.to_dict() for item in self.evidence],
            "trace_refs": list(self.trace_refs),
            "source_refs": list(self.source_refs),
            "profile_id": self.profile_id,
            "content_version": self.content_version,
            "risk_flags": list(self.risk_flags),
            "status": self.status.value,
        }
        if self.degradation_reason:
            data["degradation_reason"] = self.degradation_reason
        return data


# 这些是默认边界，而不是“免责即安全”。正文本身仍须通过禁语校验。
DEFAULT_BOUNDARIES: dict[ClaimType, str] = {
    ClaimType.CHART_FACT: (
        "This is a reproducible calculation result under the stated calculation profile; "
        "it is not a life prediction."
    ),
    ClaimType.TRADITIONAL_READING: (
        "This is one symbolic traditional reading under the stated profile, not a proven "
        "fact, prediction, or professional advice."
    ),
    ClaimType.TRADITIONAL_INTERPRETATION: (
        "This is one symbolic traditional interpretation under the stated profile, not a "
        "proven fact, prediction, or professional advice."
    ),
    ClaimType.REFLECTION_PROMPT: (
        "This is an optional reflection prompt, not a directive or professional advice."
    ),
    ClaimType.EDUCATIONAL_FACT: (
        "This is educational context; editions and traditional schools can differ."
    ),
    ClaimType.UNSUPPORTED_OR_EXCLUDED: (
        "No personal conclusion is provided because this request is outside this product's "
        "safe scope."
    ),
}


# 输出正文的保守拦截词。只扫描 body，不扫描 boundary：边界需要能够写出
# “not medical/financial/legal advice” 等否定说明。规则覆盖的是发布门，不替代人工复核。
_POLICY_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("deterministic_fate", (
        re.compile(r"\b(?:destined|fated|inevitable|guaranteed|cannot\s+avoid|will\s+definitely)\b", re.I),
        re.compile(r"(?:命中注定|注定|必然会|一定会|绝对会|百分之百|不可避免)"),
    )),
    ("pseudoscientific_claim", (
        re.compile(r"\b(?:scientifically\s+proven|proven\s+by\s+science|science\s+proves)\b", re.I),
        re.compile(r"(?:科学证明|已被科学证实).{0,12}(?:八字|命理|bazi)", re.I),
    )),
    ("medical_or_reproductive", (
        re.compile(r"\b(?:you\s+(?:have|will\s+get|will\s+develop)|diagnos(?:e|is|ed)|cure|treat)\b.{0,36}\b(?:disease|illness|cancer|depression|pregnan(?:t|cy)|infertil(?:e|ity))\b", re.I),
        re.compile(r"(?:你会|你将|命盘显示你).{0,20}(?:生病|患病|得病|怀孕|流产|不孕|抑郁|癌症)"),
        re.compile(r"(?:诊断|治疗|治愈|处方).{0,20}(?:疾病|病情|怀孕|生育)"),
    )),
    ("financial_or_gambling", (
        re.compile(r"\b(?:buy|sell|invest(?:ment)?|borrow|loan|bet|gambl(?:e|ing))\b.{0,40}\b(?:stock|crypto|property|house|money|return|profit|lottery)\b", re.I),
        re.compile(r"(?:买入|卖出|投资|借贷|购房|彩票|博彩|保证收益|稳赚)"),
    )),
    ("legal_directive", (
        re.compile(r"\b(?:legal\s+advice|sue|lawsuit|sign\s+(?:this|the)\s+contract)\b", re.I),
        re.compile(r"(?:法律建议|起诉|诉讼|签订合同|一定胜诉)"),
    )),
    ("harmful_action", (
        re.compile(r"\b(?:self[- ]harm|suicide|kill\s+yourself|hurt\s+them|revenge)\b", re.I),
        re.compile(r"(?:自杀|自残|伤害他人|报复)"),
    )),
    ("discriminatory", (
        re.compile(r"\b(?:women|men|female|male|gay|lesbian|trans(?:gender)?|disabled|black|white|asian)\b.{0,48}\b(?:inferior|superior|unfit|should\s+obey|cannot\s+succeed|not\s+suited)\b", re.I),
        re.compile(r"(?:女性|男性|女人|男人|同性恋|跨性别|残疾人|某种族).{0,24}(?:天生不适合|低人一等|劣等|应该服从|注定失败|不配)"),
    )),
)

_SEGMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-\[\]]{1,255}$")
_RISK_FLAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_SENSITIVE_REF_PARTS = frozenset({
    "birth_date", "birth_time", "location", "lat", "lng", "true_solar_time", "chart_id",
})
_EVIDENCE_KINDS = frozenset({
    "chart_field", "derived_field", "calculation_trace", "traditional_rule", "editorial_note", "policy",
})


def _coerce_claim_type(value: ClaimType | str) -> ClaimType:
    try:
        return value if isinstance(value, ClaimType) else ClaimType(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in ClaimType)
        raise ReportContractError(f"claim_type 必须为以下之一: {allowed}") from exc


def _coerce_status(value: SegmentStatus | str) -> SegmentStatus:
    try:
        return value if isinstance(value, SegmentStatus) else SegmentStatus(value)
    except (TypeError, ValueError) as exc:
        raise ReportContractError("status 必须为 published 或 excluded") from exc


def _coerce_evidence(value: EvidenceRef | Mapping[str, Any]) -> EvidenceRef:
    if isinstance(value, EvidenceRef):
        return value
    if not isinstance(value, Mapping):
        raise ReportContractError("evidence 的每项必须为 EvidenceRef 或 {kind, ref} 对象")
    unknown = set(value) - {"kind", "ref", "label"}
    missing = {"kind", "ref"} - set(value)
    if unknown or missing:
        raise ReportContractError("evidence 每项仅允许 kind/ref/label，且 kind/ref 必填")
    return EvidenceRef(kind=value["kind"], ref=value["ref"], label=value.get("label", ""))


def _require_text(name: str, value: Any, *, min_length: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < min_length:
        raise ReportContractError(f"{name} 必须为至少 {min_length} 个字符的非空文本")
    return value.strip()


def _validate_ref(ref: str, field_name: str) -> None:
    _require_text(field_name, ref, min_length=2)
    if not _REF_RE.fullmatch(ref):
        raise ReportContractError(f"{field_name} 格式不合法；只允许稳定的非敏感引用标识")
    if any(part in ref.lower().split(".") for part in _SENSITIVE_REF_PARTS):
        raise ReportContractError(f"{field_name} 不得引用出生资料、地点、真太阳时或 chart_id")


def _validate_evidence(item: EvidenceRef) -> None:
    if item.kind not in _EVIDENCE_KINDS:
        raise ReportContractError(f"evidence.kind 不支持: {item.kind}")
    _validate_ref(item.ref, "evidence.ref")
    if item.label:
        _require_text("evidence.label", item.label)


def policy_category_for_text(text: str) -> str | None:
    """返回命中的首个禁止类别；仅用于用户可见正文。"""
    for category, patterns in _POLICY_PATTERNS:
        if any(pattern.search(text) for pattern in patterns):
            return category
    return None


def validate_report_segment(segment: ReportSegment) -> None:
    """严格校验一个已构造段落；任一失败均不可发布。"""
    _require_text("segment_id", segment.segment_id, min_length=3)
    if not _SEGMENT_ID_RE.fullmatch(segment.segment_id):
        raise ReportContractError("segment_id 必须为 3–128 位小写字母、数字、._- 的稳定标识")
    _require_text("body", segment.body, min_length=3)
    _require_text("boundary", segment.boundary, min_length=12)
    _require_text("profile_id", segment.profile_id, min_length=3)
    _require_text("content_version", segment.content_version, min_length=1)

    for item in segment.evidence:
        _validate_evidence(item)
    for ref in segment.trace_refs:
        _validate_ref(ref, "trace_refs")
    for ref in segment.source_refs:
        _validate_ref(ref, "source_refs")
    for flag in segment.risk_flags:
        if not isinstance(flag, str) or not _RISK_FLAG_RE.fullmatch(flag):
            raise ReportContractError("risk_flags 必须为小写稳定标识")

    has_evidence = bool(segment.evidence)
    has_trace = bool(segment.trace_refs)
    has_source = bool(segment.source_refs)
    if not (has_evidence or has_trace or has_source):
        raise ReportContractError("每个报告段落必须至少包含 evidence、trace_refs 或 source_refs")

    if segment.claim_type == ClaimType.CHART_FACT and not (has_evidence or has_trace):
        raise ReportContractError("chart_fact 必须指向可复算的 evidence 或 trace_refs")
    if segment.claim_type in {ClaimType.TRADITIONAL_READING, ClaimType.TRADITIONAL_INTERPRETATION}:
        if not has_evidence:
            raise ReportContractError("traditional_reading 必须指向盘面/规则 evidence")
        if not (has_trace or has_source):
            raise ReportContractError("traditional_reading 必须同时包含 trace_refs 或 source_refs")
    if segment.claim_type == ClaimType.EDUCATIONAL_FACT and not has_source:
        raise ReportContractError("educational_fact 必须包含 source_refs")
    if segment.claim_type == ClaimType.UNSUPPORTED_OR_EXCLUDED:
        if segment.status != SegmentStatus.EXCLUDED:
            raise ReportContractError("unsupported_or_excluded 必须使用 excluded 状态")
    elif segment.status != SegmentStatus.PUBLISHED:
        raise ReportContractError("只有 unsupported_or_excluded 可以使用 excluded 状态")

    category = policy_category_for_text(segment.body)
    if category:
        raise ReportPolicyViolation(category, f"报告正文命中不可发布类别: {category}")


def make_report_segment(
    *,
    segment_id: str,
    claim_type: ClaimType | str,
    body: str,
    evidence: Sequence[EvidenceRef | Mapping[str, Any]] = (),
    trace_refs: Sequence[str] = (),
    source_refs: Sequence[str] = (),
    profile_id: str = PROFILE_ID,
    content_version: str = "unversioned",
    risk_flags: Sequence[str] = (),
    boundary: str | None = None,
) -> ReportSegment:
    """构造并校验可发布段落；缺失/违规时立即抛错，不产生半成品。"""
    normalized_claim_type = _coerce_claim_type(claim_type)
    return ReportSegment(
        segment_id=segment_id,
        claim_type=normalized_claim_type,
        body=body,
        boundary=boundary or DEFAULT_BOUNDARIES[normalized_claim_type],
        evidence=tuple(_coerce_evidence(item) for item in evidence),
        trace_refs=tuple(trace_refs),
        source_refs=tuple(source_refs),
        profile_id=profile_id,
        content_version=content_version,
        risk_flags=tuple(risk_flags),
    )


def excluded_segment(
    *,
    segment_id: str,
    category: str,
    profile_id: str = PROFILE_ID,
    content_version: str = "unversioned",
) -> ReportSegment:
    """生成可安全显示的降级段落，绝不回显原始高风险正文。"""
    return ReportSegment(
        segment_id=segment_id,
        claim_type=ClaimType.UNSUPPORTED_OR_EXCLUDED,
        body=(
            "This requested conclusion is outside Anima Codex's scope, so no personal "
            "conclusion is provided."
        ),
        boundary=DEFAULT_BOUNDARIES[ClaimType.UNSUPPORTED_OR_EXCLUDED],
        source_refs=("policy:report-contract-v1",),
        profile_id=profile_id,
        content_version=content_version,
        risk_flags=(category,),
        status=SegmentStatus.EXCLUDED,
        degradation_reason=category,
    )


def enforce_report_contract(
    segments: Iterable[ReportSegment | Mapping[str, Any]], *, on_policy_violation: str = "raise"
) -> list[ReportSegment]:
    """批量发布门。

    ``on_policy_violation='raise'`` 是默认且推荐的编辑/测试模式；``'degrade'``
    只会把命中正文策略的单段转为安全排除说明。结构性错误永远失败，不能靠降级掩盖。
    """
    if on_policy_violation not in {"raise", "degrade"}:
        raise ValueError("on_policy_violation 必须为 raise 或 degrade")

    published: list[ReportSegment] = []
    for raw in segments:
        try:
            segment = raw if isinstance(raw, ReportSegment) else _segment_from_mapping(raw)
            # dataclass 初始化已校验；这里再跑一次以防未来传入可变/子类对象。
            validate_report_segment(segment)
        except ReportPolicyViolation as exc:
            if on_policy_violation != "degrade":
                raise
            raw_id = raw.segment_id if isinstance(raw, ReportSegment) else raw.get("segment_id") if isinstance(raw, Mapping) else None
            raw_profile = raw.profile_id if isinstance(raw, ReportSegment) else raw.get("profile_id", PROFILE_ID) if isinstance(raw, Mapping) else PROFILE_ID
            raw_version = raw.content_version if isinstance(raw, ReportSegment) else raw.get("content_version", "unversioned") if isinstance(raw, Mapping) else "unversioned"
            # 无法识别 id 的输入仍应因结构错误失败；这里不会泄漏其正文。
            if not isinstance(raw_id, str):
                raise ReportContractError("策略降级前仍需要合法 segment_id") from exc
            published.append(excluded_segment(
                segment_id=raw_id,
                category=exc.category,
                profile_id=raw_profile if isinstance(raw_profile, str) else PROFILE_ID,
                content_version=raw_version if isinstance(raw_version, str) else "unversioned",
            ))
        else:
            published.append(segment)
    return published


def _segment_from_mapping(raw: Mapping[str, Any]) -> ReportSegment:
    if not isinstance(raw, Mapping):
        raise ReportContractError("报告段落必须为 ReportSegment 或 mapping")
    allowed = {
        "segment_id", "claim_type", "body", "boundary", "evidence", "trace_refs", "source_refs",
        "profile_id", "content_version", "risk_flags", "status", "degradation_reason", "contract_version",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ReportContractError(f"报告段落存在未知字段: {', '.join(sorted(unknown))}")
    required = {"segment_id", "claim_type", "body", "boundary"}
    missing = required - set(raw)
    if missing:
        raise ReportContractError(f"报告段落缺少必填字段: {', '.join(sorted(missing))}")
    return ReportSegment(
        segment_id=raw["segment_id"],
        claim_type=raw["claim_type"],
        body=raw["body"],
        boundary=raw["boundary"],
        evidence=tuple(raw.get("evidence", ())),
        trace_refs=tuple(raw.get("trace_refs", ())),
        source_refs=tuple(raw.get("source_refs", ())),
        profile_id=raw.get("profile_id", PROFILE_ID),
        content_version=raw.get("content_version", "unversioned"),
        risk_flags=tuple(raw.get("risk_flags", ())),
        status=raw.get("status", SegmentStatus.PUBLISHED),
        degradation_reason=raw.get("degradation_reason"),
    )
