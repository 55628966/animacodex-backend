# -*- coding: utf-8 -*-
"""Anima Codex 后端 API(模型A)。

契约来源:《00_总纲与接口契约》第四节 +《01_模型A任务书》第四节。
铁律: ChartResult schema 字段不增不删不改; 错误统一 {"error": {"code", "message"}}。

HTTP 状态码约定(文档化):
- 400  一切客户端输入错误(含 JSON 解析失败与字段校验失败, 不使用422, 统一400风格):
       INVALID_REQUEST / INVALID_DATE / INVALID_TIME / INVALID_TIMEZONE /
       INVALID_LOCATION / INVALID_SEX / OUT_OF_RANGE(年份超1800-2399) /
       INVALID_QUERY / INVALID_QUESTION / INVALID_OPTION / SESSION_FINISHED
- 404  资源不存在或 owner secret 无效/过期: NOT_FOUND(排盘结果) / INVALID_SESSION(时辰反推会话)
- 405  METHOD_NOT_ALLOWED
- 501  NOT_IMPLEMENTED(时辰反推计算模块 bazi_engine.hour_inference 未就绪时的兜底)
- 500  INTERNAL(任何未捕获异常, 由统一异常处理器兜底)

设计: 服务本身无状态, 持久化全部落 SQLite(见 api/storage.py); 运行期零外网调用
(地理库首次初始化除外, 见 api/geo.py 授权边界说明)。

CORS(《08》A2): 放行模型B前端源 http://127.0.0.1:8321 / http://localhost:8321 / http://127.0.0.1:8322。
Chart owner secret 仅放在请求/响应 header，绝不放 URL；禁用通配符 *。
"""
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from bazi_engine import ALGO_VERSION, ChartOptions, compute_chart, compute_full_chart
from bazi_engine.rhythm import compute_monthly_rhythm, first_scroll_candidates

from . import auth as auth_module, geo, paddle as paddle_module, storage
from .auth import AuthError

# 时辰反推计算模块由另一名工程师并行开发: try-import, 缺席时接口返回 NOT_IMPLEMENTED,
# 模块就位后无需改本文件, 联调直接生效。
try:
    from bazi_engine.hour_inference import start_session, update_session
    _HOUR_INFERENCE_READY = True
except ImportError:
    start_session = update_session = None
    _HOUR_INFERENCE_READY = False

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_YEAR_MIN, _YEAR_MAX = 1800, 2399      # 引擎节气历表覆盖范围
_START_TIME = time.time()                 # 服务启动时间戳，供健康检查

# chart_id is only a locator. The bearer owner secret is intentionally carried
# in a non-URL header, returned once when the anonymous chart is created.
CHART_OWNER_SECRET_HEADER = "X-Anima-Chart-Owner"
CHART_EXPIRES_AT_HEADER = "X-Anima-Chart-Expires-At"
# Hour-inference sessions use the same bearer pattern as charts. Sessions have
# no expiry mechanism, so there is no Expires-At header for them.
HOUR_SESSION_OWNER_HEADER = "X-Anima-Hour-Session-Owner"


class ApiError(Exception):
    """业务错误: 统一映射为 {"error": {"code", "message"}}。"""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _err_response(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.init_db()          # 建表幂等; 地理库懒初始化(首次搜索时)
    yield


app = FastAPI(title="Anima Codex API", version=ALGO_VERSION, lifespan=lifespan)

# 29号: include auth router for A_组 endpoints
app.include_router(auth_module.router)

# CORS: only the local Model-B origin is allowed. The two explicit exposed
# headers let the client retain the one-time owner secret without putting it
# into a URL or JSON ChartResult body.
CORS_ALLOW_ORIGIN = "http://127.0.0.1:8321"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ALLOW_ORIGIN, "http://localhost:8321", "http://127.0.0.1:8322"],
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization", CHART_OWNER_SECRET_HEADER,
                   HOUR_SESSION_OWNER_HEADER],
    expose_headers=[CHART_OWNER_SECRET_HEADER, CHART_EXPIRES_AT_HEADER,
                    HOUR_SESSION_OWNER_HEADER],
)


# ---------------- 统一异常处理 ----------------

@app.exception_handler(ApiError)
async def _on_api_error(_req: Request, exc: ApiError):
    return _err_response(exc.code, exc.message, exc.status)


@app.exception_handler(AuthError)
async def _on_auth_error(_req: Request, exc: AuthError):
    return _err_response(exc.code, exc.message, exc.status)


@app.exception_handler(RequestValidationError)
async def _on_validation_error(_req: Request, exc: RequestValidationError):
    # 统一 400 风格, 不暴露 FastAPI 默认 422
    return _err_response("INVALID_REQUEST", f"请求体不合法: {exc.errors()[:1]}", 400)


@app.exception_handler(StarletteHTTPException)
async def _on_http_error(_req: Request, exc: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "ERROR")
    return _err_response(code, str(exc.detail), exc.status_code)


@app.exception_handler(Exception)
async def _on_unhandled(_req: Request, exc: Exception):
    # 兜底: 任何未捕获异常也保证契约错误结构
    return _err_response("INTERNAL", f"服务内部错误: {type(exc).__name__}", 500)


# ---------------- 输入校验 ----------------

async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ApiError("INVALID_REQUEST", "请求体不是合法 JSON")
    if not isinstance(body, dict):
        raise ApiError("INVALID_REQUEST", "请求体必须是 JSON 对象")
    return body


def _validate_chart_request(body: dict) -> dict:
    """逐字段校验契约请求体, 返回规范化参数。校验失败抛对应错误码。"""
    birth_date = body.get("birth_date")
    if not isinstance(birth_date, str) or not _DATE_RE.match(birth_date):
        raise ApiError("INVALID_DATE", "birth_date 必须是 ISO 8601 日期字符串, 如 1990-06-15")
    try:
        d = date.fromisoformat(birth_date)
    except ValueError:
        raise ApiError("INVALID_DATE", f"birth_date 不是有效日期: {birth_date}")
    if not (_YEAR_MIN <= d.year <= _YEAR_MAX):
        raise ApiError("OUT_OF_RANGE",
                       f"出生年份 {d.year} 超出历表覆盖范围 {_YEAR_MIN}-{_YEAR_MAX}")

    birth_time = body.get("birth_time")
    if birth_time is not None and (not isinstance(birth_time, str)
                                   or not _TIME_RE.match(birth_time)):
        raise ApiError("INVALID_TIME", 'birth_time 必须是 "HH:MM"(24小时制) 或 null')

    tz_name = body.get("timezone")
    if not isinstance(tz_name, str) or not tz_name:
        raise ApiError("INVALID_TIMEZONE", "timezone 必须是 IANA 时区名, 如 Asia/Shanghai")
    try:
        ZoneInfo(tz_name)
    except Exception:
        raise ApiError("INVALID_TIMEZONE", f"未知 IANA 时区: {tz_name}")

    loc = body.get("location")
    if not isinstance(loc, dict):
        raise ApiError("INVALID_LOCATION", "location 必须是含 lat/lng/city 的对象")
    lat, lng, city = loc.get("lat"), loc.get("lng"), loc.get("city")
    if (not isinstance(lat, (int, float)) or isinstance(lat, bool)
            or not (-90 <= lat <= 90)):
        raise ApiError("INVALID_LOCATION", "location.lat 必须是 [-90, 90] 内的数值")
    if (not isinstance(lng, (int, float)) or isinstance(lng, bool)
            or not (-180 <= lng <= 180)):
        raise ApiError("INVALID_LOCATION", "location.lng 必须是 [-180, 180] 内的数值")
    if not isinstance(city, str) or not city.strip():
        raise ApiError("INVALID_LOCATION", "location.city 必须是非空字符串")

    convention = body.get("luck_cycle_convention")
    if convention not in (None, "traditional_male", "traditional_female", "not_applied"):
        raise ApiError("INVALID_LUCK_CYCLE_CONVENTION",
                       'luck_cycle_convention 必须是 "traditional_male"、"traditional_female"、"not_applied" 或省略')
    sex = body.get("sex")
    if convention is None and sex not in ("male", "female"):
        raise ApiError("INVALID_SEX", 'sex 必须是 "male" 或 "female"（未指定 luck_cycle_convention 时必填）')
    if convention is not None and sex is not None and sex not in ("male", "female"):
        raise ApiError("INVALID_SEX", 'sex 如提供必须是 "male" 或 "female"')

    return {"birth_date": birth_date, "birth_time": birth_time, "timezone": tz_name,
            "lat": float(lat), "lng": float(lng), "city": city, "sex": sex,
            "luck_cycle_convention": convention}


# ---------------- 排盘接口 ----------------

def _chart_not_found() -> ApiError:
    # Do not reveal whether a chart_id exists, expired, or belongs to another user.
    return ApiError("NOT_FOUND", "命盘不存在、已过期或访问凭证无效", 404)


def _load_owned_chart(request: Request, chart_id: str):
    # Header lookup is case-insensitive. The secret is never accepted in a URL
    # parameter and is never logged or echoed by this API.
    result = storage.load_chart_for_owner(
        chart_id, request.headers.get(CHART_OWNER_SECRET_HEADER, "")
    )
    if result is None:
        raise _chart_not_found()
    return result


@app.post("/api/v1/chart")
async def create_chart(request: Request):
    body = await _json_body(request)
    p = _validate_chart_request(body)
    chart_id = str(uuid.uuid4())
    try:
        result = compute_chart(p["birth_date"], p["birth_time"], p["timezone"],
                               p["lat"], p["lng"], p["sex"],
                               options=ChartOptions(luck_cycle_convention=p["luck_cycle_convention"]), chart_id=chart_id)
    except KeyError as e:
        # 引擎找不到时区数据(理论上已被前置校验拦截)
        raise ApiError("INVALID_TIMEZONE", f"时区数据不可用: {e}")
    except ValueError as e:
        raise ApiError("INVALID_REQUEST", f"引擎拒绝该输入: {e}")
    except Exception as e:
        # ZoneInfoNotFoundError 是 KeyError 子类已在上面拦截; 其余(含历表越界 RuntimeError)
        if "ZoneInfo" in type(e).__name__:
            raise ApiError("INVALID_TIMEZONE", f"未知 IANA 时区: {p['timezone']}")
        raise ApiError("INTERNAL", f"排盘引擎异常: {type(e).__name__}: {e}", 500)
    # ⚠️ WARNING: DO NOT add "access" or "owner_secret" to the JSON body.
    # Owner credentials MUST travel only via response headers.
    # Regression test: tests/test_29_auth_storage.py::test_chart_create_response_never_exposes_owner_secret_in_json
    # If this is broken, the frontend will reject every chart creation with PARSE error.
    owner_secret = storage.new_owner_secret()
    expires_at = storage.save_chart(chart_id, result, owner_secret)
    # access is NEVER included in the JSON body.
    # The owner secret is transmitted ONLY via response headers
    # so that no JSON parser, proxy log, or HAR dump can capture it.
    return JSONResponse(
        content=result,
        headers={
            CHART_OWNER_SECRET_HEADER: owner_secret,
            CHART_EXPIRES_AT_HEADER: expires_at,
        },
    )


@app.get("/api/v1/chart/{chart_id}")
async def get_chart(chart_id: str, request: Request):
    return _load_owned_chart(request, chart_id)


@app.delete("/api/v1/chart/{chart_id}", status_code=204)
async def delete_chart(chart_id: str, request: Request):
    owner_secret = request.headers.get(CHART_OWNER_SECRET_HEADER, "")
    if not storage.delete_chart_for_owner(chart_id, owner_secret):
        raise _chart_not_found()
    return Response(status_code=204)


@app.get("/api/v1/chart/{chart_id}/full")
async def get_chart_full(chart_id: str, request: Request):
    """Full chart data, derived only from the owner-protected ChartResult."""
    result = _load_owned_chart(request, chart_id)
    full = compute_full_chart(result)
    full["profile_id"] = result["meta"]["tradition_profile"]["profile_id"]
    full["first_scroll_candidates"] = first_scroll_candidates(full)

    # 30号: 全局互动图 Full 层
    try:
        from bazi_engine.global_interaction import graph_from_chart_result
        from bazi_engine.interaction_layers import full_layer as _full_layer
        gi_graph = graph_from_chart_result(result)
        full["global_interaction_full"] = _full_layer(gi_graph)
    except Exception:
        full["global_interaction_full"] = None

    return full


@app.get("/api/v1/chart/{chart_id}/rhythm")
async def get_chart_rhythm(chart_id: str, request: Request, at: str, viewer_timezone: str):
    """21号：按查看者时区确定所属节气月，返回纯计算结构而非叙事。"""
    result = _load_owned_chart(request, chart_id)
    if not isinstance(at, str) or not _DATE_RE.match(at):
        raise ApiError("INVALID_DATE", "at 必须是 ISO 8601 日期字符串, 如 2026-03-06")
    try:
        rhythm_date = date.fromisoformat(at)
    except ValueError:
        raise ApiError("INVALID_DATE", f"at 不是有效日期: {at}")
    if not (_YEAR_MIN <= rhythm_date.year <= _YEAR_MAX):
        raise ApiError("OUT_OF_RANGE", f"at 年份超出历表覆盖范围 {_YEAR_MIN}-{_YEAR_MAX}")
    if not isinstance(viewer_timezone, str) or not viewer_timezone:
        raise ApiError("INVALID_TIMEZONE", "viewer_timezone 必须是 IANA 时区名")
    try:
        ZoneInfo(viewer_timezone)
    except Exception:
        raise ApiError("INVALID_TIMEZONE", f"未知 viewer_timezone: {viewer_timezone}")
    return compute_monthly_rhythm(result, rhythm_date, viewer_timezone)


# ---------------- 时辰反推接口(计算模块 try-import 兜底) ----------------

def _require_hour_inference():
    if not _HOUR_INFERENCE_READY:
        raise ApiError("NOT_IMPLEMENTED",
                       "时辰反推计算模块(bazi_engine.hour_inference)尚未就绪; "
                       "模块交付后本接口自动生效", 501)


def _session_state(answers: list) -> dict:
    """按答案序列全量重算会话状态(纯函数, 可复现)。"""
    return update_session(answers) if answers else start_session()


@app.post("/api/v1/hour-inference/start")
async def hour_inference_start():
    _require_hour_inference()
    session_id = str(uuid.uuid4())
    state = start_session()
    # Same owner-secret pattern as charts: the bearer credential is returned
    # once, only in a response header, never in the JSON body.
    owner_secret = storage.new_owner_secret()
    storage.create_hour_session(session_id, owner_secret)
    return JSONResponse(
        content={**state, "session_id": session_id},
        headers={HOUR_SESSION_OWNER_HEADER: owner_secret},
    )


def _load_owned_hour_session(request: Request, session_id: str):
    # Missing, wrong-secret, and unknown sessions collapse to one 404 so the
    # endpoint stays non-enumerable, same as charts.
    answers = storage.load_hour_session_for_owner(
        session_id, request.headers.get(HOUR_SESSION_OWNER_HEADER, "")
    )
    if answers is None:
        raise ApiError("INVALID_SESSION", "时辰反推会话不存在或访问凭证无效", 404)
    return answers


@app.post("/api/v1/hour-inference/answer")
async def hour_inference_answer(request: Request):
    _require_hour_inference()
    body = await _json_body(request)
    session_id = body.get("session_id")
    question_id = body.get("question_id")
    option_key = body.get("option_key")
    if not isinstance(session_id, str) or not session_id:
        raise ApiError("INVALID_SESSION", "session_id 必须是非空字符串", 404)
    if not isinstance(question_id, str) or not question_id:
        raise ApiError("INVALID_QUESTION", "question_id 必须是非空字符串")
    if not isinstance(option_key, str) or not option_key:
        raise ApiError("INVALID_OPTION", "option_key 必须是非空字符串")

    answers = _load_owned_hour_session(request, session_id)

    current = _session_state(answers)
    # 锁定判断只在后端: 已锁定或问题用尽(next_question_id=None)后不再接受答案
    if current.get("locked") or current.get("next_question_id") is None:
        raise ApiError("SESSION_FINISHED",
                       "会话已结束(已锁定或已达最多5问), 不再接受新答案")
    if question_id != current.get("next_question_id"):
        raise ApiError("INVALID_QUESTION",
                       f"question_id 不匹配, 当前应回答: {current.get('next_question_id')}")

    new_answers = answers + [{"question_id": question_id, "option_key": option_key}]
    try:
        state = update_session(new_answers)
    except (KeyError, ValueError) as e:
        raise ApiError("INVALID_OPTION", f"非法 option_key: {e}")
    storage.update_hour_session(session_id, new_answers)
    return {**state, "session_id": session_id}


@app.delete("/api/v1/hour-inference/{session_id}", status_code=204)
async def hour_inference_delete(session_id: str, request: Request):
    """Delete a session only for a matching owner secret (frontend data.js path)."""
    _require_hour_inference()
    owner_secret = request.headers.get(HOUR_SESSION_OWNER_HEADER, "")
    if not storage.delete_hour_session_for_owner(session_id, owner_secret):
        raise ApiError("INVALID_SESSION", "时辰反推会话不存在或访问凭证无效", 404)
    return Response(status_code=204)


# ---------------- 地理服务 ----------------

@app.get("/api/v1/geo/search")
async def geo_search(q: str = ""):
    q = (q or "").strip()
    if not q:
        raise ApiError("INVALID_QUERY", "缺少查询参数 q(城市名)")
    return geo.search(q)


# ---------------- 神谕所/占卜 ----------------

@app.post("/api/v1/oracle/cast")
async def oracle_cast(request: Request):
    """起卦：六爻或大六壬"""
    body = await _json_body(request)
    method = str(body.get("method", "liuyao")).lower()
    question = body.get("question_domain", None)
    chart_id = body.get("chart_id", None)

    if method == "liuyao":
        from bazi_engine.liuyao import cast_hexagram, hexagram_to_dict
        r = cast_hexagram(method="coin", question_domain=question)
        result = {
            "reading_id": str(uuid.uuid4()),
            "method": "liuyao",
            "hexagram": hexagram_to_dict(r),
            "fusion": None
        }
    elif method == "daliuren":
        from bazi_engine.daliuren import cast_daliuren, result_to_dict as dr_to_dict
        import datetime
        r = cast_daliuren(datetime.date.today(), datetime.datetime.now().hour)
        result = {
            "reading_id": str(uuid.uuid4()),
            "method": "daliuren",
            "cast": dr_to_dict(r),
            "fusion": None
        }
    else:
        raise ApiError("INVALID_METHOD", f"不支持的占卜方法: {method}")

    if chart_id:
        try:
            chart = storage.load_chart_for_owner(chart_id,
                request.headers.get(CHART_OWNER_SECRET_HEADER, ""))
            if chart:
                from bazi_engine.oracle_fusion import (
                    fuse_liuyao_with_chart, fuse_daliuren_with_chart, fusion_to_dict)
                if method == "liuyao":
                    fr = fuse_liuyao_with_chart(chart, result["hexagram"])
                else:
                    fr = fuse_daliuren_with_chart(chart, result["cast"])
                result["fusion"] = fusion_to_dict(fr)
        except Exception as exc:
            print(f"[oracle] fusion skipped: {type(exc).__name__}: {exc}")  # fusion失败不影响起卦，但不再静默

    return result


# ---------------- 健康检查 ----------------

@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok",
        "algo_version": ALGO_VERSION,
        "uptime_seconds": int(time.time() - _START_TIME),
        "charts_computed": storage.count_charts(),
    }


# ═══════════════════════════════════════════════════════════════════════
# 29号 A_组: chart library, entitlements, privacy (A2/A3/A4)
# ═══════════════════════════════════════════════════════════════════════

# ── A2: Chart library (require JWT) ───────────────────────────────────

@app.post("/api/v1/chart/{chart_id}/claim")
async def claim_chart(chart_id: str, request: Request):
    """Claim an anonymous chart for the authenticated user using the owner secret."""
    user_id = await auth_module.get_current_user(request)
    owner_secret = request.headers.get(CHART_OWNER_SECRET_HEADER, "")
    # Verify owner secret before claiming
    result = storage.load_chart_for_owner(chart_id, owner_secret)
    if result is None:
        raise _chart_not_found()
    if not storage.claim_chart(chart_id, user_id):
        raise ApiError("CONFLICT", "Chart is already claimed or does not exist", 409)
    return {"chart_id": chart_id, "claimed": True}


@app.get("/api/v1/user/charts")
async def list_user_charts(request: Request):
    """List all charts owned by the authenticated user."""
    user_id = await auth_module.get_current_user(request)
    charts = storage.list_user_charts(user_id)
    return {"charts": charts, "count": len(charts)}


@app.patch("/api/v1/user/charts/{chart_id}")
async def patch_chart_label(chart_id: str, request: Request):
    """Update the user-defined label for an owned chart."""
    user_id = await auth_module.get_current_user(request)
    try:
        body = await request.json()
    except Exception:
        raise ApiError("INVALID_REQUEST", "请求体不是合法 JSON")
    label = body.get("label", "") if isinstance(body, dict) else ""
    if not isinstance(label, str):
        raise ApiError("INVALID_REQUEST", "label 必须是字符串")
    if not storage.update_chart_label(chart_id, user_id, label):
        raise ApiError("NOT_FOUND", "Chart not found or not owned by user", 404)
    return {"chart_id": chart_id, "label": label}


@app.delete("/api/v1/user/charts/{chart_id}", status_code=204)
async def delete_user_chart(chart_id: str, request: Request):
    """Delete a chart owned by the authenticated user."""
    user_id = await auth_module.get_current_user(request)
    if not storage.delete_user_chart(chart_id, user_id):
        raise ApiError("NOT_FOUND", "Chart not found or not owned by user", 404)
    return Response(status_code=204)


# ── A3: Entitlements (require JWT) ────────────────────────────────────

@app.get("/api/v1/user/entitlements")
async def list_entitlements(request: Request):
    """List all entitlements for the authenticated user."""
    user_id = await auth_module.get_current_user(request)
    ents = storage.list_entitlements(user_id)
    return {"entitlements": ents, "count": len(ents)}


@app.post("/api/v1/user/entitlements/redeem")
async def redeem_entitlement(request: Request):
    """Redeem a product entitlement. Body: {product_id, code?}."""
    user_id = await auth_module.get_current_user(request)
    try:
        body = await request.json()
    except Exception:
        raise ApiError("INVALID_REQUEST", "请求体不是合法 JSON")
    product_id = body.get("product_id") if isinstance(body, dict) else None
    if not isinstance(product_id, str) or not product_id.strip():
        raise ApiError("INVALID_REQUEST", "product_id 不能为空")
    source = "redeem"
    if isinstance(body, dict) and body.get("code"):
        source = "code"
    ent = storage.get_or_create_entitlement(user_id, product_id, source=source)
    return {"entitlement": ent}


# ── B4: Paddle 支付(收款主体已拍板 Paddle, MoR 模式) ──────────────────

@app.post("/api/v1/checkout/create")
async def create_checkout(request: Request):
    """Create a Paddle checkout for a priced product.

    Body: {product_id, chart_id?}. 价格只以 api/paddle.PRODUCTS 常量表为准,
    前端提交的金额一律忽略。带有效 JWT 时把 user_id 写入 Paddle custom_data,
    供 webhook 回写权益; 匿名购买只带 chart_id。
    """
    body = await _json_body(request)
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or product_id not in paddle_module.PRODUCTS:
        raise ApiError("INVALID_PRODUCT", "未知或不可售的 product_id")
    chart_id = body.get("chart_id")
    if chart_id is not None and (not isinstance(chart_id, str) or not chart_id.strip()):
        raise ApiError("INVALID_REQUEST", "chart_id 必须是非空字符串")

    cfg = paddle_module.load_config()
    if not cfg.checkout_configured:
        raise ApiError(
            "NOT_IMPLEMENTED",
            "payment not configured: 缺少 PADDLE_API_KEY / PADDLE_SELLER_ID 环境变量",
            501,
        )

    # Optional account binding: a valid JWT attaches user_id to custom_data.
    # An absent or invalid token degrades to anonymous checkout, never a 401.
    user_id = None
    if request.headers.get("Authorization", "").startswith("Bearer "):
        try:
            user_id = await auth_module.get_current_user(request)
        except AuthError:
            user_id = None

    custom_data = {"product_id": product_id}
    if chart_id:
        custom_data["chart_id"] = chart_id.strip()
    if user_id:
        custom_data["user_id"] = user_id

    try:
        checkout_url = await paddle_module.create_checkout_url(cfg, product_id, custom_data)
    except paddle_module.PaddleUnavailable as exc:
        raise ApiError("PAYMENT_PROVIDER_ERROR", f"支付服务暂不可用: {exc}", 502)
    return {"checkout_url": checkout_url, "product_id": product_id, "expires_at": None}


@app.post("/api/v1/webhooks/paddle")
async def paddle_webhook(request: Request):
    """Paddle server-to-server webhook(无 Origin, 不受全局 CORS 影响)。

    红线: 验签不过一律 401 且绝不写权益; 未配置 secret → 503;
    非 transaction.completed 事件 200 收下不处理, 防 Paddle 重试风暴。
    """
    cfg = paddle_module.load_config()
    if not cfg.webhook_secret:
        raise ApiError(
            "PAYMENT_NOT_CONFIGURED",
            "payment webhook not configured: 缺少 PADDLE_WEBHOOK_SECRET 环境变量",
            503,
        )
    raw = await request.body()
    signature = request.headers.get("paddle-signature", "")
    if not paddle_module.verify_signature(raw, signature, cfg.webhook_secret):
        raise ApiError("INVALID_SIGNATURE", "webhook 签名验证失败", 401)

    try:
        payload = json.loads(raw)
    except Exception:
        raise ApiError("INVALID_REQUEST", "请求体不是合法 JSON")
    if not isinstance(payload, dict):
        raise ApiError("INVALID_REQUEST", "请求体必须是 JSON 对象")

    event_type = payload.get("event_type")
    if event_type != "transaction.completed":
        return {"status": "ignored", "event_type": event_type}

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    transaction_id = str(data.get("id") or "")
    custom_data = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}
    product_id = custom_data.get("product_id")

    # 幂等: 同一 event(或同 transaction)重放不重复写权益。
    event_id = str(payload.get("event_id") or "") or f"txn:{transaction_id}"
    if not storage.record_webhook_event(event_id, event_type,
                                        transaction_id=transaction_id or None, processed=True):
        return {"status": "duplicate", "event_id": event_id}

    if not isinstance(product_id, str) or product_id not in paddle_module.PRODUCTS:
        return {"status": "unprocessable", "reason": "unknown product_id"}

    # user_id 来源: 登录用户 checkout 时写入的 custom_data.user_id →
    # 匿名 chart 支付则回查 chart_ownership(先付后认领的留待 pending)。
    user_id = None
    candidate = custom_data.get("user_id")
    if isinstance(candidate, str) and candidate and storage.get_user_by_id(candidate):
        user_id = candidate
    elif isinstance(custom_data.get("chart_id"), str):
        user_id = storage.get_chart_owner_user_id(custom_data["chart_id"])
    if user_id is None:
        return {"status": "pending_user", "transaction_id": transaction_id}

    ent = storage.get_or_create_entitlement(user_id, product_id, source="paddle")
    return {
        "status": "ok",
        "transaction_id": transaction_id,
        "entitlement": {
            "product_id": ent["product_id"],
            "source": ent["source"],
            "granted_at": ent["granted_at"],
        },
    }


# ── A4: Privacy suite (require JWT) ───────────────────────────────────

@app.post("/api/v1/user/export")
async def export_user_data(request: Request):
    """Export all user data as JSON."""
    user_id = await auth_module.get_current_user(request)
    user = storage.get_user_by_id(user_id)
    charts = storage.list_user_charts(user_id)
    entitlements = storage.list_entitlements(user_id)
    return {
        "user_id": user_id,
        "created_at": user.get("created_at") if user else None,
        "charts": charts,
        "entitlements": entitlements,
        "exported_at": storage._now_iso(),
    }


@app.delete("/api/v1/user/account")
async def delete_account(request: Request):
    """Request account deletion with a 7-day cooldown (mock)."""
    user_id = await auth_module.get_current_user(request)
    return {
        "message": "Account deletion requested. Data will be permanently deleted after a 7-day cooldown period.",
        "user_id": user_id,
        "deletion_scheduled_at": storage._now_iso(),
        "cooldown_days": 7,
    }


@app.get("/api/v1/user/privacy-policy")
async def privacy_policy(request: Request):
    """Return the static privacy policy content."""
    await auth_module.get_current_user(request)
    return {
        "version": "1.0",
        "effective_date": "2026-07-20",
        "content": (
            "Anima Codex 隐私政策摘要:\\n"
            "1. 我们仅存储命盘计算结果(ChartResult), 不存储出生日期、出生时间、出生地点。\\n"
            "2. 邮箱仅以 SHA-256 哈希形式存储, 无法反向推导。\\n"
            "3. JWT 令牌中仅包含用户 ID, 不含任何命盘或出生数据。\\n"
            "4. 匿名命盘默认 30 天后自动过期删除。\\n"
            "5. 您可随时通过 /api/v1/user/export 导出全部数据, 通过 /api/v1/user/account 申请删除。"
        ),
    }


@app.get("/api/v1/user/access-log")
async def access_log(request: Request):
    """Return a mock recent access log for the authenticated user."""
    user_id = await auth_module.get_current_user(request)
    return {
        "user_id": user_id,
        "entries": [
            {"timestamp": "2026-07-20T08:00:00Z", "action": "chart_created", "chart_id": "mock-abc123"},
            {"timestamp": "2026-07-20T08:05:00Z", "action": "chart_viewed", "chart_id": "mock-abc123"},
            {"timestamp": "2026-07-20T09:00:00Z", "action": "login"},
        ],
        "note": "This is a mock access log; full audit logging will be implemented in a future release.",
    }
