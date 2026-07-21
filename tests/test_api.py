import json
import os
import sqlite3
# -*- coding: utf-8 -*-
"""后端 API 契约测试(pytest + fastapi.testclient)。

运行: ./.venv/bin/python -m pytest tests/test_api.py -q  (在项目根目录)
覆盖: 契约字段逐一断言 / partial 语义 / 全部错误码 / 持久化取回 /
      geo 搜索 / P95 延迟冒烟 / 时辰反推(模块缺席时测兜底)。
"""
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 项目根

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api import storage  # noqa: E402

try:
    import bazi_engine.hour_inference  # noqa: F401, E402
    HAS_HOUR_INFERENCE = True
except ImportError:
    HAS_HOUR_INFERENCE = False

# 契约示例命例: 1990-06-15 14:00 北京 male
BASE_REQ = {
    "birth_date": "1990-06-15",
    "birth_time": "14:00",
    "timezone": "Asia/Shanghai",
    "location": {"lat": 39.9042, "lng": 116.4074, "city": "Beijing"},
    "sex": "male",
}

PILLAR_KEYS = {"stem", "branch", "hidden_stems", "ten_god_stem", "ten_gods_hidden",
               "nayin", "star_fortune", "zi_zuo", "kong_wang", "shen_sha"}
STEMS = set("甲乙丙丁戊己庚辛壬癸")
BRANCHES = set("子丑寅卯辰巳午未申酉戌亥")
_CHART_OWNER_SECRETS = {}


@pytest.fixture(scope="module")
def isolated_chart_db(tmp_path_factory):
    """Keep API tests away from any developer chart database and set a stable HMAC key."""
    db_file = tmp_path_factory.mktemp("api-chart-db") / "anima-test.db"
    previous = {
        name: os.environ.get(name)
        for name in ("ANIMA_DB_PATH", "ANIMA_OWNER_SECRET_PEPPER", "ANIMA_CHART_TTL_SECONDS")
    }
    os.environ["ANIMA_DB_PATH"] = str(db_file)
    os.environ["ANIMA_OWNER_SECRET_PEPPER"] = "test-only-owner-pepper"
    os.environ["ANIMA_CHART_TTL_SECONDS"] = "2592000"
    try:
        yield db_file
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture(scope="module")
def client(isolated_chart_db):
    # raise_server_exceptions=False: 让统一异常处理器兜底 INTERNAL 也能被测试到
    _CHART_OWNER_SECRETS.clear()
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


def _post_chart(client, **overrides):
    req = {**BASE_REQ, **overrides}
    response = client.post("/api/v1/chart", json=req)
    if response.status_code == 200:
        chart_id = response.json()["chart_id"]
        secret = response.headers.get(main.CHART_OWNER_SECRET_HEADER)
        assert secret, "successful chart creation must return one owner secret header"
        body = response.json()
        assert "access" not in body and "owner_secret" not in body, \
            "owner secret travels only via the response header, never the JSON body"
        _CHART_OWNER_SECRETS[chart_id] = secret
    return response


def _chart_headers(chart_or_id):
    chart_id = chart_or_id if isinstance(chart_or_id, str) else chart_or_id["chart_id"]
    secret = _CHART_OWNER_SECRETS.get(chart_id)
    assert secret, f"missing test owner secret for chart {chart_id}"
    return {main.CHART_OWNER_SECRET_HEADER: secret}


def _assert_error(resp, status, code):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


# ---------------- CORS(《08》A2) ----------------

def test_cors_allows_frontend_origin(client):
    """放行模型B前端源 http://127.0.0.1:8321, 且回显该源(非通配符 *)。"""
    origin = "http://127.0.0.1:8321"
    resp = client.get("/api/v1/health", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin


def test_cors_preflight_methods(client):
    """Preflight explicitly permits the owner header and DELETE, never a wildcard."""
    resp = client.options("/api/v1/chart/example", headers={
        "Origin": "http://127.0.0.1:8321",
        "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "Content-Type, X-Anima-Chart-Owner",
    })
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:8321"
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "POST" in allow_methods and "DELETE" in allow_methods
    allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
    assert "x-anima-chart-owner" in allow_headers


def test_cors_rejects_other_origin(client):
    """非白名单源不得被回显(不使用通配符)。"""
    resp = client.get("/api/v1/health",
                      headers={"Origin": "http://evil.example.com"})
    # 请求本身仍 200(CORS 是浏览器侧强制), 但不得回显该非法源或 *
    acao = resp.headers.get("access-control-allow-origin")
    assert acao != "*"
    assert acao != "http://evil.example.com"


# ---------------- 契约字段逐一断言 ----------------

def test_chart_contract_fields(client):
    resp = _post_chart(client)
    assert resp.status_code == 200, resp.text
    r = resp.json()

    # 顶层键集合(契约 ChartResult, 完整时辰时不含 partial; 30号新增 global_interaction)
    assert set(r.keys()) == {"chart_id", "true_solar_time", "pillars", "day_master",
                             "five_elements", "luck_cycles", "current", "meta",
                             "global_interaction"}
    uuid.UUID(r["chart_id"])  # 合法 uuid
    # owner_secret 仅经响应头一次性下发(29号安全口径), 不落 JSON body
    assert "access" not in r and "owner_secret" not in r
    secret = resp.headers.get(main.CHART_OWNER_SECRET_HEADER)
    assert isinstance(secret, str) and len(secret) >= 32

    # true_solar_time
    tst = r["true_solar_time"]
    assert set(tst.keys()) == {"datetime", "correction_minutes", "equation_of_time_minutes"}
    assert isinstance(tst["datetime"], str) and tst["datetime"].startswith("1990-06-15")
    assert isinstance(tst["correction_minutes"], int)
    assert isinstance(tst["equation_of_time_minutes"], int)

    # pillars 四键
    assert set(r["pillars"].keys()) == {"year", "month", "day", "hour"}
    for key in ("year", "month", "hour"):
        p = r["pillars"][key]
        assert PILLAR_KEYS <= set(p.keys()), key
        assert p["stem"] in STEMS and p["branch"] in BRANCHES
        assert isinstance(p["hidden_stems"], list) and all(s in STEMS for s in p["hidden_stems"])
        assert isinstance(p["ten_god_stem"], str)
        assert isinstance(p["ten_gods_hidden"], list)
    day_p = r["pillars"]["day"]
    assert day_p["note"] == "day_master"
    assert day_p["stem"] in STEMS and day_p["branch"] in BRANCHES

    # day_master
    dm = r["day_master"]
    assert set(dm.keys()) == {"stem", "element", "yin_yang"}
    assert dm["stem"] == day_p["stem"]
    assert dm["element"] in {"wood", "fire", "earth", "metal", "water"}
    assert dm["yin_yang"] in {"yin", "yang"}

    # five_elements: 五键全, 值为数值
    fe = r["five_elements"]
    assert set(fe.keys()) == {"wood", "fire", "earth", "metal", "water"}
    assert all(isinstance(v, (int, float)) for v in fe.values())

    # luck_cycles
    lc = r["luck_cycles"]
    assert set(lc.keys()) == {"direction", "start_age", "start_date", "cycles"}
    assert lc["direction"] in {"forward", "backward"}
    assert set(lc["start_age"].keys()) == {"years", "months"}
    assert isinstance(lc["start_age"]["years"], int) and isinstance(lc["start_age"]["months"], int)
    date.fromisoformat(lc["start_date"])
    assert isinstance(lc["cycles"], list) and len(lc["cycles"]) >= 8
    for c in lc["cycles"]:
        assert set(c.keys()) == {"index", "stem", "branch", "start_year", "end_year", "ten_god"}
        assert c["stem"] in STEMS and c["branch"] in BRANCHES
        assert isinstance(c["ten_god"], str)  # 中文原术语

    # current
    cur = r["current"]
    assert set(cur.keys()) == {"luck_cycle_index", "annual"}
    assert isinstance(cur["luck_cycle_index"], int)
    assert set(cur["annual"].keys()) == {"year", "stem", "branch"}

    # 20号：版本化传统口径、脱敏 Trace 和边界提示必须随盘持久化。
    meta = r["meta"]
    assert set(meta.keys()) == {"algo_version", "solar_terms_source", "tradition_profile",
                                "luck_cycle_convention", "calculation_trace", "boundary_notice"}
    assert isinstance(meta["algo_version"], str) and meta["algo_version"]
    assert meta["tradition_profile"]["profile_id"] == "zi_ping_solar_v1"
    assert meta["luck_cycle_convention"] == "traditional_male"
    assert meta["calculation_trace"]["timezone"] == "Asia/Shanghai"
    assert "1990-06-15" not in str(meta["calculation_trace"])
    assert set(meta["boundary_notice"]) == {"threshold_minutes", "near_jie_boundary",
                                              "near_day_boundary", "near_hour_boundary", "time_unknown"}


def test_chart_partial_when_birth_time_null(client):
    resp = _post_chart(client, birth_time=None)
    assert resp.status_code == 200, resp.text
    r = resp.json()
    assert r.get("partial") is True
    assert r["pillars"]["hour"] is None
    assert r["true_solar_time"] is None


# ---------------- 错误码 ----------------

def test_invalid_date(client):
    _assert_error(_post_chart(client, birth_date="1990-13-40"), 400, "INVALID_DATE")
    _assert_error(_post_chart(client, birth_date="15/06/1990"), 400, "INVALID_DATE")
    req = dict(BASE_REQ)
    del req["birth_date"]
    _assert_error(client.post("/api/v1/chart", json=req), 400, "INVALID_DATE")


def test_invalid_time(client):
    _assert_error(_post_chart(client, birth_time="25:00"), 400, "INVALID_TIME")
    _assert_error(_post_chart(client, birth_time="1400"), 400, "INVALID_TIME")
    _assert_error(_post_chart(client, birth_time="14:60"), 400, "INVALID_TIME")


def test_invalid_timezone(client):
    _assert_error(_post_chart(client, timezone="Mars/Olympus"), 400, "INVALID_TIMEZONE")
    _assert_error(_post_chart(client, timezone=""), 400, "INVALID_TIMEZONE")


def test_invalid_location(client):
    _assert_error(_post_chart(client, location={"lat": 91, "lng": 116.4, "city": "X"}),
                  400, "INVALID_LOCATION")
    _assert_error(_post_chart(client, location={"lat": 39.9, "lng": -181, "city": "X"}),
                  400, "INVALID_LOCATION")
    _assert_error(_post_chart(client, location={"lat": 39.9, "lng": 116.4, "city": ""}),
                  400, "INVALID_LOCATION")
    req = dict(BASE_REQ)
    del req["location"]
    _assert_error(client.post("/api/v1/chart", json=req), 400, "INVALID_LOCATION")


def test_invalid_sex(client):
    _assert_error(_post_chart(client, sex="other"), 400, "INVALID_SEX")
    req = dict(BASE_REQ)
    del req["sex"]
    _assert_error(client.post("/api/v1/chart", json=req), 400, "INVALID_SEX")


def test_out_of_range_year(client):
    _assert_error(_post_chart(client, birth_date="1799-12-31"), 400, "OUT_OF_RANGE")
    _assert_error(_post_chart(client, birth_date="2400-01-01"), 400, "OUT_OF_RANGE")


def test_invalid_request_body(client):
    resp = client.post("/api/v1/chart", content=b"not json",
                       headers={"Content-Type": "application/json"})
    _assert_error(resp, 400, "INVALID_REQUEST")
    _assert_error(client.post("/api/v1/chart", json=[1, 2, 3]), 400, "INVALID_REQUEST")


def test_internal_error_envelope(client, monkeypatch):
    """任何未捕获异常也必须返回统一错误结构 INTERNAL。"""
    def boom(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(main, "compute_chart", boom)
    _assert_error(_post_chart(client), 500, "INTERNAL")


# ---------------- 持久化取回 ----------------

def test_chart_persist_and_retrieve(client):
    r1 = _post_chart(client, birth_date="1988-02-04").json()
    resp = client.get(f"/api/v1/chart/{r1['chart_id']}", headers=_chart_headers(r1))
    assert resp.status_code == 200
    assert "access" not in resp.json()
    assert resp.json() == {key: value for key, value in r1.items() if key != "access"}

    _assert_error(client.get(f"/api/v1/chart/{uuid.uuid4()}"), 404, "NOT_FOUND")


def test_chart_owner_secret_guards_all_chart_reads_and_deletion(client):
    """chart_id alone never grants chart, full, rhythm, or deletion access."""
    created = _post_chart(client, birth_date="1988-02-05").json()
    chart_id = created["chart_id"]
    good_headers = _chart_headers(created)
    wrong_headers = {main.CHART_OWNER_SECRET_HEADER: "not-the-owner"}

    # Missing and wrong credentials intentionally collapse to the same 404.
    for headers in ({}, wrong_headers):
        _assert_error(client.get(f"/api/v1/chart/{chart_id}", headers=headers), 404, "NOT_FOUND")
        _assert_error(client.get(f"/api/v1/chart/{chart_id}/full", headers=headers), 404, "NOT_FOUND")
        _assert_error(client.get(f"/api/v1/chart/{chart_id}/rhythm", headers=headers, params={
            "at": "2026-03-06", "viewer_timezone": "Asia/Shanghai"}), 404, "NOT_FOUND")
        _assert_error(client.delete(f"/api/v1/chart/{chart_id}", headers=headers), 404, "NOT_FOUND")

    owned = client.get(f"/api/v1/chart/{chart_id}", headers=good_headers)
    assert owned.status_code == 200
    assert "access" not in owned.json(), "owner secret must not be echoed by later reads"
    assert client.get(f"/api/v1/chart/{chart_id}/full", headers=good_headers).status_code == 200
    assert client.get(f"/api/v1/chart/{chart_id}/rhythm", headers=good_headers, params={
        "at": "2026-03-06", "viewer_timezone": "Asia/Shanghai"}).status_code == 200

    deleted = client.delete(f"/api/v1/chart/{chart_id}", headers=good_headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    _assert_error(client.get(f"/api/v1/chart/{chart_id}", headers=good_headers), 404, "NOT_FOUND")


def test_expired_chart_is_unreadable_and_purged(client, isolated_chart_db):
    """Expiry is enforced on access and removes the row, rather than just hiding it."""
    created = _post_chart(client, birth_date="1988-02-06").json()
    chart_id = created["chart_id"]
    with sqlite3.connect(isolated_chart_db) as conn:
        conn.execute("UPDATE charts SET expires_at = ? WHERE chart_id = ?", (
            "2000-01-01T00:00:00+00:00", chart_id))
    _assert_error(
        client.get(f"/api/v1/chart/{chart_id}", headers=_chart_headers(created)),
        404,
        "NOT_FOUND",
    )
    with sqlite3.connect(isolated_chart_db) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM charts WHERE chart_id = ?", (chart_id,)
        ).fetchone()[0]
    assert remaining == 0


def test_chart_storage_excludes_raw_request_and_keeps_only_secret_digest(client, isolated_chart_db):
    """The database has no request_json column and never retains the bearer secret."""
    created = _post_chart(client, birth_date="1988-02-07").json()
    chart_id = created["chart_id"]
    secret = _CHART_OWNER_SECRETS[chart_id]
    with sqlite3.connect(isolated_chart_db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(charts)").fetchall()}
        row = conn.execute(
            "SELECT owner_secret_hash, result_json FROM charts WHERE chart_id = ?", (chart_id,)
        ).fetchone()
    assert columns == {
        "chart_id", "result_json", "algo_version", "owner_secret_hash",
        "created_at", "expires_at",
    }
    assert row is not None
    owner_secret_hash, result_json = row
    assert secret not in owner_secret_hash
    assert '"birth_date"' not in result_json
    assert '"birth_time"' not in result_json
    assert '"location"' not in result_json
    assert "Beijing" not in result_json


def test_legacy_raw_request_schema_is_fail_closed_not_migrated(tmp_path, monkeypatch):
    """Any residual request_json column is intentionally purged on migration."""
    legacy_db = tmp_path / "legacy-anima.db"
    with sqlite3.connect(legacy_db) as conn:
        conn.execute(
            "CREATE TABLE charts (chart_id TEXT PRIMARY KEY, result_json TEXT NOT NULL, "
            "algo_version TEXT NOT NULL, owner_secret_hash TEXT NOT NULL, created_at TEXT NOT NULL, "
            "expires_at TEXT NOT NULL, request_json TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO charts VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-id",
                "{}",
                "legacy",
                "obsolete-owner-digest",
                "2026-01-01T00:00:00+00:00",
                "2026-12-01T00:00:00+00:00",
                '{"birth_date":"1990-06-15","birth_time":"14:00","location":{"city":"Beijing"}}',
            ),
        )
    monkeypatch.setenv("ANIMA_DB_PATH", str(legacy_db))
    monkeypatch.setenv("ANIMA_OWNER_SECRET_PEPPER", "test-only-owner-pepper")
    monkeypatch.setenv("ANIMA_CHART_TTL_SECONDS", "2592000")
    storage.init_db()
    with sqlite3.connect(legacy_db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(charts)").fetchall()}
        count = conn.execute("SELECT COUNT(*) FROM charts").fetchone()[0]
    assert "request_json" not in columns
    assert columns == {
        "chart_id", "result_json", "algo_version", "owner_secret_hash",
        "created_at", "expires_at",
    }
    assert count == 0


# ---------------- 全卷数据 /full(09号 A1) ----------------

def test_chart_full_schema(client):
    """/full 返回 FullChartData: 恰4关键十神/6互动/3流年从2026/夫妻宫/五组计数。"""
    r = _post_chart(client).json()
    resp = client.get(f"/api/v1/chart/{r['chart_id']}/full", headers=_chart_headers(r))
    assert resp.status_code == 200, resp.text
    f = resp.json()
    assert set(f) == {"key_ten_gods", "interactions", "annual_next3",
                      "relationship", "career", "profile_id", "first_scroll_candidates",
                      "global_interaction_full"}
    assert f["profile_id"] == r["meta"]["tradition_profile"]["profile_id"]
    assert [c["source_path"] for c in f["first_scroll_candidates"]] == [
        "key_ten_gods[0]", "interactions[0]", "annual_next3[0]"]
    assert len(f["key_ten_gods"]) == 4
    for g in f["key_ten_gods"]:
        assert set(g) == {"name", "position", "rank"}
        assert g["name"] in "".join(("比肩劫财食神伤官偏财正财七杀正官偏印正印"))
    assert f["key_ten_gods"][0]["position"] == "month_branch_main"
    assert len(f["interactions"]) == 6                      # C(4,2)
    for it in f["interactions"]:
        assert set(it) == {"a", "b", "relation", "note_cn"}
        assert it["relation"] in {"生", "克", "化", "竞"}
    assert [a["year"] for a in f["annual_next3"]] == [2026, 2027, 2028]
    assert f["relationship"]["spouse_palace"]["branch"] in BRANCHES
    assert set(f["career"]) == {"authority", "wealth", "resource", "output", "peer"}
    assert sum(f["career"].values()) == 8                   # 满盘8字


def test_chart_full_partial(client):
    """partial(无时辰)命例 /full 仍恰4关键十神, 五组计数和为6。"""
    r = _post_chart(client, birth_time=None).json()
    assert r.get("partial") is True
    f = client.get(f"/api/v1/chart/{r['chart_id']}/full", headers=_chart_headers(r)).json()
    assert len(f["key_ten_gods"]) == 4
    assert sum(f["career"].values()) == 6                   # 6字


def test_chart_full_consistent_with_chart(client):
    """/full 与 /chart 强一致: 夫妻宫地支 == 日支。"""
    r = _post_chart(client).json()
    f = client.get(f"/api/v1/chart/{r['chart_id']}/full", headers=_chart_headers(r)).json()
    assert f["relationship"]["spouse_palace"]["branch"] == r["pillars"]["day"]["branch"]


def test_chart_full_not_found(client):
    """未知 chart_id → 404 NOT_FOUND。"""
    _assert_error(client.get(f"/api/v1/chart/{uuid.uuid4()}/full"), 404, "NOT_FOUND")


# ---------------- 20号传统透明 / 21号节气月 ----------------

def test_luck_cycle_conventions_and_legacy_compatibility(client):
    """旧 sex 结果不变；传统约定可覆盖排列方向或选择不生成大运。"""
    legacy = _post_chart(client).json()
    assert legacy["luck_cycles"]["direction"] == "forward"

    female_req = dict(BASE_REQ)
    female_req.pop("sex")
    female_req["luck_cycle_convention"] = "traditional_female"
    female = client.post("/api/v1/chart", json=female_req)
    assert female.status_code == 200, female.text
    assert female.json()["luck_cycles"]["direction"] == "backward"
    assert female.json()["meta"]["luck_cycle_convention"] == "traditional_female"

    omitted_req = dict(BASE_REQ)
    omitted_req.pop("sex")
    omitted_req["luck_cycle_convention"] = "not_applied"
    omitted = client.post("/api/v1/chart", json=omitted_req)
    assert omitted.status_code == 200, omitted.text
    body = omitted.json()
    assert body["luck_cycles"] is None
    assert body["current"]["luck_cycle_index"] is None
    assert body["meta"]["luck_cycle_convention"] == "not_applied"
    assert body["pillars"] == legacy["pillars"]


def test_invalid_luck_cycle_convention(client):
    _assert_error(_post_chart(client, luck_cycle_convention="invented"),
                  400, "INVALID_LUCK_CYCLE_CONVENTION")


def test_monthly_rhythm_contract_and_validation(client):
    chart = _post_chart(client).json()
    resp = client.get(f"/api/v1/chart/{chart['chart_id']}/rhythm", headers=_chart_headers(chart), params={
        "at": "2026-03-06", "viewer_timezone": "Asia/Shanghai"})
    assert resp.status_code == 200, resp.text
    rhythm = resp.json()
    assert set(rhythm) == {"chart_id", "profile_id", "solar_month", "next_boundary",
                           "natal_links", "limitations"}
    assert rhythm["chart_id"] == chart["chart_id"]
    assert rhythm["profile_id"] == "zi_ping_solar_v1"
    assert rhythm["solar_month"]["term_anchor"] == "惊蛰"
    assert set(rhythm["solar_month"]) == {"term_anchor", "starts_at", "ends_at", "stem", "branch", "ten_god"}
    assert rhythm["next_boundary"]["term_anchor"] == "清明"
    assert rhythm["limitations"] == ["traditional_reading_only", "not_a_prediction"]
    blob = json.dumps(rhythm, ensure_ascii=False)
    for forbidden in ("birth_date", "birth_time", "lat", "lng", "location"):
        assert f'"{forbidden}"' not in blob

    _assert_error(client.get(f"/api/v1/chart/{chart['chart_id']}/rhythm", headers=_chart_headers(chart), params={
        "at": "not-a-date", "viewer_timezone": "Asia/Shanghai"}), 400, "INVALID_DATE")
    _assert_error(client.get(f"/api/v1/chart/{chart['chart_id']}/rhythm", headers=_chart_headers(chart), params={
        "at": "2026-03-06", "viewer_timezone": "Mars/Olympus"}), 400, "INVALID_TIMEZONE")
    _assert_error(client.get(f"/api/v1/chart/{uuid.uuid4()}/rhythm", params={
        "at": "2026-03-06", "viewer_timezone": "Asia/Shanghai"}), 404, "NOT_FOUND")


# ---------------- 地理服务 ----------------

def test_geo_search_beijing(client):
    resp = client.get("/api/v1/geo/search", params={"q": "北京"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["results"], "北京必须命中"
    assert len(body["results"]) <= 10
    top = body["results"][0]
    assert set(top.keys()) == {"city", "country", "lat", "lng", "timezone"}
    assert top["timezone"] == "Asia/Shanghai"
    assert abs(top["lat"] - 39.9) < 0.5 and abs(top["lng"] - 116.4) < 0.5
    # meta 注明数据源与条数
    assert body["meta"]["source"] and body["meta"]["count"] > 0


def test_geo_search_missing_q(client):
    _assert_error(client.get("/api/v1/geo/search"), 400, "INVALID_QUERY")
    _assert_error(client.get("/api/v1/geo/search", params={"q": "  "}), 400, "INVALID_QUERY")


# ---------------- 健康检查 ----------------

def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["algo_version"], str) and body["algo_version"]
    assert isinstance(body["uptime_seconds"], int) and body["uptime_seconds"] >= 0
    assert isinstance(body["charts_computed"], int) and body["charts_computed"] >= 0


# ---------------- P95 延迟冒烟 ----------------

def test_chart_p95_latency(client):
    """连续50次不同日期排盘, P95 < 500ms(节气 lru_cache 首次预热不计入)。"""
    dates = [(date(1950, 1, 1) + timedelta(days=i * 137)).isoformat() for i in range(50)]
    for d in dates:  # 预热(节气缓存按年份缓存, 不计入统计)
        assert _post_chart(client, birth_date=d).status_code == 200
    elapsed = []
    for d in dates:
        t0 = time.perf_counter()
        resp = _post_chart(client, birth_date=d)
        elapsed.append(time.perf_counter() - t0)
        assert resp.status_code == 200
    elapsed.sort()
    p95 = elapsed[int(len(elapsed) * 0.95) - 1]
    print(f"\nP95 = {p95 * 1000:.1f} ms (n=50)")
    assert p95 < 0.5, f"P95 延迟超标: {p95 * 1000:.1f} ms"


# ---------------- 时辰反推 ----------------

@pytest.mark.skipif(HAS_HOUR_INFERENCE, reason="计算模块已就绪, 走全流程测试")
def test_hour_inference_fallback_when_module_missing(client):
    """模块缺席: 两个接口都返回 501 NOT_IMPLEMENTED 的统一错误结构。"""
    _assert_error(client.post("/api/v1/hour-inference/start"), 501, "NOT_IMPLEMENTED")
    resp = client.post("/api/v1/hour-inference/answer",
                       json={"session_id": "x", "question_id": "q", "option_key": "a"})
    _assert_error(resp, 501, "NOT_IMPLEMENTED")


@pytest.mark.skipif(not HAS_HOUR_INFERENCE, reason="计算模块未就绪, 走兜底测试")
def test_hour_inference_full_flow(client):
    # start: 12候选 + 先验, 附 session_id; 凭据只在响应头, 不落 JSON body
    resp = client.post("/api/v1/hour-inference/start")
    assert resp.status_code == 200, resp.text
    owner_secret = resp.headers.get(main.HOUR_SESSION_OWNER_HEADER)
    assert owner_secret, "start 必须返回 X-Anima-Hour-Session-Owner 响应头"
    headers = {main.HOUR_SESSION_OWNER_HEADER: owner_secret}
    s = resp.json()
    assert len(s["candidates"]) == 12
    # 各时辰置信度之和≈1(响应可能按4位小数舍入, 容差放宽到0.01)
    assert abs(sum(c["confidence"] for c in s["candidates"]) - 1.0) < 0.01
    assert s["asked_count"] == 0 and s["max_questions"] == 5 and s["locked"] is False
    assert isinstance(s["next_question_id"], str)
    session_id = s["session_id"]

    # 非法 session / question 错误码
    _assert_error(client.post("/api/v1/hour-inference/answer",
                              json={"session_id": str(uuid.uuid4()),
                                    "question_id": s["next_question_id"],
                                    "option_key": "x"}), 404, "INVALID_SESSION")
    _assert_error(client.post("/api/v1/hour-inference/answer",
                              headers=headers,
                              json={"session_id": session_id,
                                    "question_id": "q_不存在的问题",
                                    "option_key": "x"}), 400, "INVALID_QUESTION")

    # 逐问回答直至结束(option_key 从模块问题库取; 取不到则用启发式 key 并容忍 INVALID_OPTION)
    import bazi_engine.hour_inference as hi
    questions = getattr(hi, "QUESTIONS", None) or getattr(hi, "QUESTION_BANK", None)
    if isinstance(questions, list):  # 兼容 list[{"id":…, "options":…}] 形态
        questions = {q["id"]: q for q in questions if isinstance(q, dict) and "id" in q}
    state = s
    for _ in range(5):
        if state["locked"] or state["next_question_id"] is None:
            break
        qid = state["next_question_id"]
        if isinstance(questions, dict) and qid in questions:
            q = questions[qid]
            options = q.get("options") if isinstance(q, dict) else None
            key = (list(options.keys())[0] if isinstance(options, dict)
                   else options[0]["key"] if options else "unknown")
        else:
            pytest.skip("模块未暴露问题库, 无法构造合法 option_key, 跳过全流程")
        resp = client.post("/api/v1/hour-inference/answer",
                           headers=headers,
                           json={"session_id": session_id, "question_id": qid,
                                 "option_key": key})
        assert resp.status_code == 200, resp.text
        state = resp.json()
        assert state["session_id"] == session_id
        assert len(state["candidates"]) == 12

    # 《00》4.2 v1.1(拍板2026-07-17): locked:true 时响应必须带 locked_branch
    # 且等于置信度最高的时辰; 未锁定时不得出现该字段
    if state["locked"]:
        top_branch = max(state["candidates"], key=lambda c: c["confidence"])["branch"]
        assert state["locked_branch"] == top_branch
    else:
        assert "locked_branch" not in state

    # locked 语义: 已达5问且最高置信度<0.90 → locked=False 且 next_question_id=None
    if not state["locked"] and state["asked_count"] >= 5:
        assert state["next_question_id"] is None
        top = max(c["confidence"] for c in state["candidates"])
        assert top < 0.90
        # 结束后继续作答必须被拒
        _assert_error(client.post("/api/v1/hour-inference/answer",
                                  headers=headers,
                                  json={"session_id": session_id,
                                        "question_id": "q_any", "option_key": "x"}),
                      400, "SESSION_FINISHED")


@pytest.mark.skipif(not HAS_HOUR_INFERENCE, reason="计算模块未就绪, 走兜底测试")
def test_hour_inference_start_credential_only_in_header(client):
    """29号口径: 凭据只在响应头, JSON body 永不含 owner_secret/access。"""
    resp = client.post("/api/v1/hour-inference/start")
    assert resp.status_code == 200, resp.text
    owner_secret = resp.headers.get(main.HOUR_SESSION_OWNER_HEADER)
    assert isinstance(owner_secret, str) and owner_secret.strip()
    body = resp.json()
    assert "owner_secret" not in body and "access" not in body
    assert owner_secret not in resp.text


@pytest.mark.skipif(not HAS_HOUR_INFERENCE, reason="计算模块未就绪, 走兜底测试")
def test_hour_inference_answer_requires_owner_secret(client):
    """answer 缺凭据/错凭据统一 404 INVALID_SESSION(不可枚举); 正确凭据 200。"""
    start = client.post("/api/v1/hour-inference/start")
    assert start.status_code == 200, start.text
    session_id = start.json()["session_id"]
    qid = start.json()["next_question_id"]

    import bazi_engine.hour_inference as hi
    questions = getattr(hi, "QUESTIONS", None) or getattr(hi, "QUESTION_BANK", None)
    if isinstance(questions, list):
        questions = {q["id"]: q for q in questions if isinstance(q, dict) and "id" in q}
    if not (isinstance(questions, dict) and qid in questions):
        pytest.skip("模块未暴露问题库, 无法构造合法 option_key")
    options = questions[qid].get("options")
    key = (list(options.keys())[0] if isinstance(options, dict)
           else options[0]["key"] if options else "unknown")

    payload = {"session_id": session_id, "question_id": qid, "option_key": key}
    # 无头与错头归一为同一个 404, 不区分"会话不存在"与"凭据错误"
    _assert_error(client.post("/api/v1/hour-inference/answer", json=payload),
                  404, "INVALID_SESSION")
    _assert_error(client.post("/api/v1/hour-inference/answer",
                              headers={main.HOUR_SESSION_OWNER_HEADER: "not-the-owner"},
                              json=payload), 404, "INVALID_SESSION")
    good = client.post("/api/v1/hour-inference/answer",
                       headers={main.HOUR_SESSION_OWNER_HEADER:
                                start.headers[main.HOUR_SESSION_OWNER_HEADER]},
                       json=payload)
    assert good.status_code == 200, good.text
    assert good.json()["session_id"] == session_id


@pytest.mark.skipif(not HAS_HOUR_INFERENCE, reason="计算模块未就绪, 走兜底测试")
def test_hour_inference_delete_requires_owner_secret(client):
    """delete: 无头 404 / 正确头 204 空体 / 删后 answer 与再删均 404。"""
    start = client.post("/api/v1/hour-inference/start")
    assert start.status_code == 200, start.text
    session_id = start.json()["session_id"]
    headers = {main.HOUR_SESSION_OWNER_HEADER:
               start.headers[main.HOUR_SESSION_OWNER_HEADER]}
    url = f"/api/v1/hour-inference/{session_id}"

    _assert_error(client.delete(url), 404, "INVALID_SESSION")
    _assert_error(client.delete(url, headers={main.HOUR_SESSION_OWNER_HEADER: "wrong"}),
                  404, "INVALID_SESSION")

    deleted = client.delete(url, headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""

    _assert_error(client.post("/api/v1/hour-inference/answer",
                              headers=headers,
                              json={"session_id": session_id,
                                    "question_id": "q_any", "option_key": "x"}),
                  404, "INVALID_SESSION")
    _assert_error(client.delete(url, headers=headers), 404, "INVALID_SESSION")


def test_legacy_hour_sessions_gain_owner_column_fail_closed(tmp_path, monkeypatch):
    """既有库缺 owner_secret_hash 列: init_db 补列, 旧行 fail-closed 不可枚举。"""
    legacy_db = tmp_path / "legacy-hour.db"
    with sqlite3.connect(legacy_db) as conn:
        conn.execute(
            "CREATE TABLE hour_sessions (session_id TEXT PRIMARY KEY, "
            "answers_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO hour_sessions VALUES (?, ?, ?, ?)",
            ("legacy-session", "[]", "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00"),
        )
    monkeypatch.setenv("ANIMA_DB_PATH", str(legacy_db))
    monkeypatch.setenv("ANIMA_OWNER_SECRET_PEPPER", "test-only-owner-pepper")
    monkeypatch.setenv("ANIMA_CHART_TTL_SECONDS", "2592000")
    storage.init_db()
    with sqlite3.connect(legacy_db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(hour_sessions)").fetchall()}
    assert "owner_secret_hash" in columns
    # 旧行保留但凭据永不匹配(含空凭据), 与 charts 的 fail-closed 同口径
    assert storage.load_hour_session("legacy-session") == []
    assert storage.load_hour_session_for_owner("legacy-session", "") is None
    assert storage.load_hour_session_for_owner("legacy-session", "any-secret") is None
    assert not storage.delete_hour_session_for_owner("legacy-session", "any-secret")
    # 迁移后新会话正常可用
    secret = storage.new_owner_secret()
    storage.create_hour_session("fresh-session", secret)
    assert storage.load_hour_session_for_owner("fresh-session", secret) == []
    assert storage.load_hour_session_for_owner("fresh-session", "wrong") is None
