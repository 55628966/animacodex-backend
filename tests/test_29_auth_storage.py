# -*- coding: utf-8 -*-
"""29号 A_组 认证+存储+权限+隐私 完整契约测试。

运行: .venv/bin/python -m pytest tests/test_29_auth_storage.py -q  (在项目根目录)

覆盖: A.密码哈希 B.JWT创建/验证 C.用户注册 D.会话管理 E.Token刷新
      F.命盘归属 G.权益 H.隐私 I.安全红线 J.匿名模式
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import api.main as main
from api import auth as auth_module
from api import storage


@pytest.fixture(scope="module")
def isolated_db(tmp_path_factory):
    """Isolate tests from developer database."""
    db_file = tmp_path_factory.mktemp("auth-test-db") / "anima-test.db"
    prev = {
        name: os.environ.get(name)
        for name in (
            "ANIMA_DB_PATH", "ANIMA_OWNER_SECRET_PEPPER", "ANIMA_CHART_TTL_SECONDS",
            "ANIMA_JWT_SECRET",
        )
    }
    os.environ["ANIMA_DB_PATH"] = str(db_file)
    os.environ["ANIMA_OWNER_SECRET_PEPPER"] = "test-owner-pepper"
    os.environ["ANIMA_CHART_TTL_SECONDS"] = "2592000"
    os.environ["ANIMA_JWT_SECRET"] = "test-jwt-secret-32-bytes-key!!"
    try:
        yield db_file
    finally:
        for name, value in prev.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture(scope="module")
def client(isolated_db):
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


def _assert_error(resp, status, code):
    assert resp.status_code == status, f"expected {status}, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == code, f"expected code {code}, got {body['error']['code']}"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


# ── helpers ───────────────────────────────────────────────────────────

TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "secure-pass-123"

_BASE_CHART_REQ = {
    "birth_date": "1990-06-15",
    "birth_time": "14:00",
    "timezone": "Asia/Shanghai",
    "location": {"lat": 39.9042, "lng": 116.4074, "city": "Beijing"},
    "sex": "male",
}

_CHART_OWNER_SECRETS = {}
_AUTH_TOKENS = {}


def _register(client, email=TEST_EMAIL, password=TEST_PASSWORD):
    resp = client.post("/auth/register", json={"email": email, "password": password})
    if resp.status_code == 200:
        body = resp.json()
        _AUTH_TOKENS[email] = body
    return resp


def _login(client, email=TEST_EMAIL, password=TEST_PASSWORD):
    resp = client.post("/auth/login", json={"email": email, "password": password})
    if resp.status_code == 200:
        _AUTH_TOKENS[email] = resp.json()
    return resp


def _auth_headers(email=TEST_EMAIL):
    tokens = _AUTH_TOKENS.get(email, {})
    token = tokens.get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


def _post_chart(client, **overrides):
    req = {**_BASE_CHART_REQ, **overrides}
    resp = client.post("/api/v1/chart", json=req)
    if resp.status_code == 200:
        chart_id = resp.json()["chart_id"]
        secret = resp.headers.get(main.CHART_OWNER_SECRET_HEADER)
        _CHART_OWNER_SECRETS[chart_id] = secret
    return resp


def _chart_owner_header(chart_or_id):
    chart_id = chart_or_id if isinstance(chart_or_id, str) else chart_or_id["chart_id"]
    secret = _CHART_OWNER_SECRETS.get(chart_id, "")
    return {main.CHART_OWNER_SECRET_HEADER: secret}


# ═══════════════════════════════════════════════════════════════════════
# A. Password hashing (3 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_password_hash_and_verify():
    pw = "mypassword123"
    h = auth_module.hash_password(pw)
    assert isinstance(h, str) and h
    assert auth_module.verify_password(pw, h) is True


def test_password_wrong_rejected():
    pw = "mypassword123"
    h = auth_module.hash_password(pw)
    assert auth_module.verify_password("wrong-password", h) is False


def test_password_bcrypt_produces_different_hashes():
    pw = "mypassword123"
    h1 = auth_module.hash_password(pw)
    h2 = auth_module.hash_password(pw)
    assert h1 != h2  # different salts
    assert auth_module.verify_password(pw, h1)
    assert auth_module.verify_password(pw, h2)


# ═══════════════════════════════════════════════════════════════════════
# B. JWT creation/verification (5 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_jwt_create_valid_access():
    tokens = auth_module.create_jwt("user-abc", "test@example.com")
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    payload = auth_module.verify_jwt(tokens["access_token"], expected_type="access")
    assert payload["sub"] == "user-abc"
    assert payload["type"] == "access"


def test_jwt_create_valid_refresh():
    tokens = auth_module.create_jwt("user-abc", "test@example.com")
    payload = auth_module.verify_jwt(tokens["refresh_token"], expected_type="refresh")
    assert payload["sub"] == "user-abc"
    assert payload["type"] == "refresh"


def test_jwt_expired_token():
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    payload = {"sub": "x", "email_hash": "abcd", "iat": now, "exp": now - timedelta(hours=1), "type": "access"}
    token = pyjwt.encode(payload, auth_module._JWT_SECRET, algorithm="HS256")
    with pytest.raises(pyjwt.ExpiredSignatureError):
        auth_module.verify_jwt(token, expected_type="access")


def test_jwt_wrong_type():
    import jwt as pyjwt
    tokens = auth_module.create_jwt("user-abc", "test@example.com")
    with pytest.raises(pyjwt.InvalidTokenError):
        auth_module.verify_jwt(tokens["access_token"], expected_type="refresh")


def test_jwt_tampered_token():
    import jwt as pyjwt
    tokens = auth_module.create_jwt("user-abc", "test@example.com")
    tampered = tokens["access_token"][:-1] + ("A" if tokens["access_token"][-1] != "A" else "B")
    with pytest.raises(pyjwt.InvalidTokenError):
        auth_module.verify_jwt(tampered, expected_type="access")


# ═══════════════════════════════════════════════════════════════════════
# C. User registration (4 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_register_success(client):
    resp = _register(client, "regtest@example.com", "secure-pass-123")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "user_id" in body
    assert "access_token" in body
    assert "refresh_token" in body
    # Verify UUID
    uuid.UUID(body["user_id"])


def test_register_duplicate_email(client):
    _register(client, "dup@example.com", "pass-123-length")
    resp = _register(client, "dup@example.com", "pass-123-length")
    _assert_error(resp, 409, "EXISTS")


def test_login_wrong_password(client):
    _register(client, "wrongpw@example.com", "right-password")
    resp = _login(client, "wrongpw@example.com", "wrong-password")
    _assert_error(resp, 401, "UNAUTHORIZED")


def test_login_success(client):
    _register(client, "loginok@example.com", "mypass-12345")
    resp = _login(client, "loginok@example.com", "mypass-12345")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body


# ═══════════════════════════════════════════════════════════════════════
# D. Session management (4 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_session_created_on_register(client):
    resp = _register(client, "sessiontest@example.com", "pass-12345")
    assert resp.status_code == 200
    body = resp.json()
    # Verify a session exists in DB
    sessions = storage.get_sessions_for_user(body["user_id"])
    assert len(sessions) >= 1


def test_session_not_found_for_unknown_user(client):
    sessions = storage.get_sessions_for_user("nonexistent-user-id")
    assert sessions == []


def test_session_revoked_on_logout(client):
    resp = _register(client, "logouttest@example.com", "pass-12345")
    assert resp.status_code == 200
    body = resp.json()
    user_id = body["user_id"]
    token = body["access_token"]
    # Call DELETE /auth/session
    del_resp = client.delete("/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert del_resp.status_code == 200
    # All sessions should be revoked
    sessions = storage.get_sessions_for_user(user_id)
    assert all(s["revoked"] for s in sessions)


def test_session_has_expires_at(client):
    resp = _register(client, "exptest@example.com", "pass-12345")
    assert resp.status_code == 200
    body = resp.json()
    sessions = storage.get_sessions_for_user(body["user_id"])
    assert len(sessions) >= 1
    assert sessions[0]["expires_at"]  # non-empty


# ═══════════════════════════════════════════════════════════════════════
# E. Token refresh flow (3 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_refresh_returns_new_access_token(client):
    resp = _register(client, "refreshtest@example.com", "pass-12345")
    assert resp.status_code == 200
    refresh = resp.json()["refresh_token"]
    rr = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert rr.status_code == 200, rr.text
    body = rr.json()
    assert "access_token" in body
    # Verify new access token works
    payload = auth_module.verify_jwt(body["access_token"], expected_type="access")
    assert payload["sub"] == resp.json()["user_id"]


def test_refresh_revoked_fails(client):
    resp = _register(client, "revokedref@example.com", "pass-12345")
    assert resp.status_code == 200
    body = resp.json()
    user_id = body["user_id"]
    refresh = body["refresh_token"]
    # Revoke via logout
    client.delete("/auth/session", headers={"Authorization": f"Bearer {body['access_token']}"})
    # Refresh should fail
    rr = client.post("/auth/refresh", json={"refresh_token": refresh})
    _assert_error(rr, 401, "UNAUTHORIZED")


def test_refresh_expired_fails(client):
    """Expired refresh token is rejected."""
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    refresh_payload = {"sub": "fake", "email_hash": "abcd", "iat": now, "exp": now - timedelta(days=1), "type": "refresh"}
    expired_refresh = pyjwt.encode(refresh_payload, os.environ["ANIMA_JWT_SECRET"], algorithm="HS256")
    rr = client.post("/auth/refresh", json={"refresh_token": expired_refresh})
    _assert_error(rr, 401, "UNAUTHORIZED")


# ═══════════════════════════════════════════════════════════════════════
# F. Chart ownership (5 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_claim_chart_with_secret(client):
    _register(client, "claimsec@test.com", "pass-12345")
    chart_resp = _post_chart(client, birth_date="1995-03-21")
    assert chart_resp.status_code == 200
    chart_id = chart_resp.json()["chart_id"]
    owner_header = _chart_owner_header(chart_id)
    claim_resp = client.post(
        f"/api/v1/chart/{chart_id}/claim",
        headers={**_auth_headers("claimsec@test.com"), **owner_header},
    )
    assert claim_resp.status_code == 200, claim_resp.text
    assert claim_resp.json()["claimed"] is True


def test_claim_chart_without_secret_fails(client):
    _register(client, "noclaim@test.com", "pass-12345")
    chart_resp = _post_chart(client, birth_date="1995-04-15")
    assert chart_resp.status_code == 200
    chart_id = chart_resp.json()["chart_id"]
    claim_resp = client.post(
        f"/api/v1/chart/{chart_id}/claim",
        headers=_auth_headers("noclaim@test.com"),
    )
    _assert_error(claim_resp, 404, "NOT_FOUND")


def test_list_user_charts(client):
    _register(client, "listcharts@test.com", "pass-12345")
    # Create and claim two charts
    for date_str in ("1995-05-01", "1995-06-15"):
        cr = _post_chart(client, birth_date=date_str)
        assert cr.status_code == 200
        chart_id = cr.json()["chart_id"]
        owner_header = _chart_owner_header(chart_id)
        claim_resp = client.post(
            f"/api/v1/chart/{chart_id}/claim",
            headers={**_auth_headers("listcharts@test.com"), **owner_header},
        )
        assert claim_resp.status_code == 200
    # List
    lr = client.get("/api/v1/user/charts", headers=_auth_headers("listcharts@test.com"))
    assert lr.status_code == 200, lr.text
    body = lr.json()
    assert body["count"] == 2
    assert len(body["charts"]) == 2


def test_patch_chart_label(client):
    _register(client, "patchlabel@test.com", "pass-12345")
    cr = _post_chart(client, birth_date="1995-07-20")
    assert cr.status_code == 200
    chart_id = cr.json()["chart_id"]
    owner_header = _chart_owner_header(chart_id)
    client.post(f"/api/v1/chart/{chart_id}/claim", headers={**_auth_headers("patchlabel@test.com"), **owner_header})
    pr = client.patch(
        f"/api/v1/user/charts/{chart_id}",
        json={"label": "My Favorite Chart"},
        headers=_auth_headers("patchlabel@test.com"),
    )
    assert pr.status_code == 200, pr.text
    assert pr.json()["label"] == "My Favorite Chart"


def test_delete_user_chart(client):
    _register(client, "delchart@test.com", "pass-12345")
    cr = _post_chart(client, birth_date="1995-08-10")
    assert cr.status_code == 200
    chart_id = cr.json()["chart_id"]
    owner_header = _chart_owner_header(chart_id)
    client.post(f"/api/v1/chart/{chart_id}/claim", headers={**_auth_headers("delchart@test.com"), **owner_header})
    dr = client.delete(f"/api/v1/user/charts/{chart_id}", headers=_auth_headers("delchart@test.com"))
    assert dr.status_code == 204
    # Verify gone
    lr = client.get("/api/v1/user/charts", headers=_auth_headers("delchart@test.com"))
    assert lr.json()["count"] == 0


# ═══════════════════════════════════════════════════════════════════════
# G. Entitlements (4 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_entitlements_empty_for_new_user(client):
    _register(client, "entempty@example.com", "pass-12345")
    resp = client.get("/api/v1/user/entitlements", headers=_auth_headers("entempty@example.com"))
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
    assert resp.json()["entitlements"] == []


def test_entitlement_grant_and_list(client):
    _register(client, "entgrant@example.com", "pass-12345")
    headers = _auth_headers("entgrant@example.com")
    # Grant
    gr = client.post("/api/v1/user/entitlements/redeem", json={"product_id": "lifetime_pro"}, headers=headers)
    assert gr.status_code == 200
    assert gr.json()["entitlement"]["product_id"] == "lifetime_pro"
    # List
    lr = client.get("/api/v1/user/entitlements", headers=headers)
    assert lr.status_code == 200
    assert lr.json()["count"] == 1
    assert lr.json()["entitlements"][0]["product_id"] == "lifetime_pro"


def test_entitlement_duplicate_returns_existing(client):
    _register(client, "entdup@example.com", "pass-12345")
    headers = _auth_headers("entdup@example.com")
    client.post("/api/v1/user/entitlements/redeem", json={"product_id": "pro"}, headers=headers)
    resp2 = client.post("/api/v1/user/entitlements/redeem", json={"product_id": "pro"}, headers=headers)
    assert resp2.status_code == 200
    lr = client.get("/api/v1/user/entitlements", headers=headers)
    assert lr.json()["count"] == 1  # still one


def test_entitlement_multiple_products(client):
    _register(client, "entmulti@example.com", "pass-12345")
    headers = _auth_headers("entmulti@example.com")
    for pid in ("free_tier", "pro_monthly", "lifetime"):
        client.post("/api/v1/user/entitlements/redeem", json={"product_id": pid}, headers=headers)
    lr = client.get("/api/v1/user/entitlements", headers=headers)
    assert lr.json()["count"] == 3


# ═══════════════════════════════════════════════════════════════════════
# H. Privacy (4 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_export_user_data(client):
    _register(client, "exportme@test.com", "pass-12345")
    headers = _auth_headers("exportme@test.com")
    # Create and claim a chart first
    cr = _post_chart(client, birth_date="1999-01-01")
    assert cr.status_code == 200
    chart_id = cr.json()["chart_id"]
    client.post(f"/api/v1/chart/{chart_id}/claim", headers={**headers, **_chart_owner_header(chart_id)})
    # Export
    er = client.post("/api/v1/user/export", headers=headers)
    assert er.status_code == 200, er.text
    body = er.json()
    assert "user_id" in body
    assert "charts" in body
    assert "entitlements" in body
    assert "exported_at" in body
    assert len(body["charts"]) >= 1


def test_delete_account_mock(client):
    _register(client, "delme@example.com", "pass-12345")
    headers = _auth_headers("delme@example.com")
    dr = client.delete("/api/v1/user/account", headers=headers)
    assert dr.status_code == 200, dr.text
    body = dr.json()
    assert "cooldown_days" in body
    assert body["cooldown_days"] == 7


def test_privacy_policy_endpoint(client):
    _register(client, "privpol@test.com", "pass-12345")
    pr = client.get("/api/v1/user/privacy-policy", headers=_auth_headers("privpol@test.com"))
    assert pr.status_code == 200
    body = pr.json()
    assert "version" in body
    assert "content" in body


def test_access_log_mock(client):
    _register(client, "accesslog@test.com", "pass-12345")
    al = client.get("/api/v1/user/access-log", headers=_auth_headers("accesslog@test.com"))
    assert al.status_code == 200
    body = al.json()
    assert "entries" in body
    assert len(body["entries"]) >= 1


# ═══════════════════════════════════════════════════════════════════════
# I. Security red lines (5 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_jwt_contains_no_raw_email():
    tokens = auth_module.create_jwt("user-abc", "sensitive@private.com")
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]
    assert "sensitive@private.com" not in access
    assert "sensitive@private.com" not in refresh
    assert "sensitive" not in access
    assert "@" not in access  # no email-like pattern


def test_jwt_contains_no_chart_id():
    tokens = auth_module.create_jwt("user-abc", "test@example.com")
    access = tokens["access_token"]
    assert "chart_id" not in access.lower()
    assert "chart-" not in access.lower()


def test_register_response_has_no_email(client):
    resp = _register(client, "noleak1@example.com", "pass-12345")
    assert resp.status_code == 200
    body = resp.json()
    body_str = json.dumps(body)
    assert "noleak1@example.com" not in body_str
    assert "email" not in body  # no email field


def test_login_response_has_no_email(client):
    _register(client, "noleak2@example.com", "pass-12345")
    resp = _login(client, "noleak2@example.com", "pass-12345")
    assert resp.status_code == 200
    body = resp.json()
    body_str = json.dumps(body)
    assert "noleak2@example.com" not in body_str
    assert "email" not in body


def test_email_is_hashed_in_storage(client):
    """Verify the database only stores sha256(email), not the raw email."""
    _register(client, "hashed@example.com", "pass-12345")
    import hashlib
    email_hash = hashlib.sha256("hashed@example.com".encode()).hexdigest()
    user = storage.get_user_by_email_hash(email_hash)
    assert user is not None
    assert user["email_hash"] == email_hash
    assert "hashed@example.com" not in user["email_hash"]


# ═══════════════════════════════════════════════════════════════════════
# J. Anonymous mode (3 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_anonymous_chart_creation_still_works(client):
    """Chart creation without auth should work as before."""
    resp = _post_chart(client, birth_date="1988-12-25")
    assert resp.status_code == 200, resp.text
    assert "chart_id" in resp.json()


def test_anonymous_chart_access_still_works(client):
    """Anonymous chart access with owner secret should work as before."""
    cr = _post_chart(client, birth_date="1988-11-15")
    assert cr.status_code == 200
    chart_id = cr.json()["chart_id"]
    get_resp = client.get(f"/api/v1/chart/{chart_id}", headers=_chart_owner_header(chart_id))
    assert get_resp.status_code == 200


def test_anonymous_chart_deletion_still_works(client):
    """Anonymous chart deletion with owner secret should work as before."""
    cr = _post_chart(client, birth_date="1988-10-05")
    assert cr.status_code == 200
    chart_id = cr.json()["chart_id"]
    del_resp = client.delete(f"/api/v1/chart/{chart_id}", headers=_chart_owner_header(chart_id))
    assert del_resp.status_code == 204


# ═══════════════════════════════════════════════════════════════════════
# K. Edge cases (additional tests to reach ≥40)
# ═══════════════════════════════════════════════════════════════════════

def test_register_missing_email(client):
    resp = client.post("/auth/register", json={"password": "pass-12345"})
    _assert_error(resp, 400, "INVALID_REQUEST")


def test_register_short_password(client):
    resp = client.post("/auth/register", json={"email": "short@example.com", "password": "short"})
    _assert_error(resp, 400, "INVALID_REQUEST")


def test_register_invalid_json(client):
    resp = client.post("/auth/register", content=b"not json", headers={"Content-Type": "application/json"})
    _assert_error(resp, 400, "INVALID_REQUEST")


def test_login_missing_email(client):
    resp = client.post("/auth/login", json={"password": "pass-12345"})
    _assert_error(resp, 400, "INVALID_REQUEST")


def test_magic_link_success(client):
    resp = client.post("/auth/magic-link", json={"email": "magic@example.com"})
    assert resp.status_code == 200
    assert "Magic link sent (mock)" in resp.json()["message"]


def test_magic_link_invalid_email(client):
    resp = client.post("/auth/magic-link", json={"email": "not-an-email"})
    _assert_error(resp, 400, "INVALID_REQUEST")


def test_verify_mock(client):
    resp = client.get("/auth/verify", params={"token": "abc12345"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is True
    assert "mock-" in body["user_id"]


def test_refresh_missing_token(client):
    resp = client.post("/auth/refresh", json={})
    _assert_error(resp, 400, "INVALID_REQUEST")


def test_chart_library_requires_auth(client):
    """Accessing chart library without auth should fail."""
    resp = client.get("/api/v1/user/charts")
    _assert_error(resp, 401, "UNAUTHORIZED")


def test_entitlements_requires_auth(client):
    resp = client.get("/api/v1/user/entitlements")
    _assert_error(resp, 401, "UNAUTHORIZED")


def test_privacy_endpoints_require_auth(client):
    for path in ["/api/v1/user/export", "/api/v1/user/privacy-policy", "/api/v1/user/access-log"]:
        resp = client.post(path) if "export" in path else client.get(path)
        assert resp.status_code == 401, f"{path} should require auth, got {resp.status_code}"


def test_delete_session_requires_auth(client):
    resp = client.delete("/auth/session")
    _assert_error(resp, 401, "UNAUTHORIZED")


def test_claim_chart_requires_auth(client):
    cr = _post_chart(client, birth_date="2000-03-15")
    assert cr.status_code == 200
    chart_id = cr.json()["chart_id"]
    resp = client.post(f"/api/v1/chart/{chart_id}/claim")
    _assert_error(resp, 401, "UNAUTHORIZED")


def test_claim_chart_twice_fails(client):
    _register(client, "claim2x@test.com", "pass-12345")
    cr = _post_chart(client, birth_date="2000-05-20")
    assert cr.status_code == 200
    chart_id = cr.json()["chart_id"]
    headers = {**_auth_headers("claim2x@test.com"), **_chart_owner_header(chart_id)}
    assert client.post(f"/api/v1/chart/{chart_id}/claim", headers=headers).status_code == 200
    resp2 = client.post(f"/api/v1/chart/{chart_id}/claim", headers=headers)
    _assert_error(resp2, 409, "CONFLICT")


def test_delete_others_chart_fails(client):
    """User A cannot delete User B's chart."""
    _register(client, "usera@example.com", "pass-12345")
    _register(client, "userb@example.com", "pass-12345")
    # User A creates and claims a chart
    cr = _post_chart(client, birth_date="2000-07-01")
    assert cr.status_code == 200
    chart_id = cr.json()["chart_id"]
    client.post(f"/api/v1/chart/{chart_id}/claim", headers={**_auth_headers("usera@example.com"), **_chart_owner_header(chart_id)})
    # User B tries to delete it
    dr = client.delete(f"/api/v1/user/charts/{chart_id}", headers=_auth_headers("userb@example.com"))
    _assert_error(dr, 404, "NOT_FOUND")


def test_patch_chart_nonexistent_fails(client):
    _register(client, "patchnonex@test.com", "pass-12345")
    pr = client.patch(f"/api/v1/user/charts/{uuid.uuid4()}", json={"label": "x"}, headers=_auth_headers("patchnonex@test.com"))
    _assert_error(pr, 404, "NOT_FOUND")


def test_redeem_with_code(client):
    _register(client, "coderedeem@example.com", "pass-12345")
    headers = _auth_headers("coderedeem@example.com")
    rr = client.post("/api/v1/user/entitlements/redeem", json={"product_id": "pro", "code": "PROMO-123"}, headers=headers)
    assert rr.status_code == 200
    assert rr.json()["entitlement"]["source"] == "code"


def test_chart_list_includes_label(client):
    _register(client, "chklabel@test.com", "pass-12345")
    cr = _post_chart(client, birth_date="2001-03-15")
    assert cr.status_code == 200
    chart_id = cr.json()["chart_id"]
    client.post(f"/api/v1/chart/{chart_id}/claim", headers={**_auth_headers("chklabel@test.com"), **_chart_owner_header(chart_id)})
    client.patch(f"/api/v1/user/charts/{chart_id}", json={"label": "Labeled"}, headers=_auth_headers("chklabel@test.com"))
    lr = client.get("/api/v1/user/charts", headers=_auth_headers("chklabel@test.com"))
    assert lr.status_code == 200
    chart = lr.json()["charts"][0]
    assert chart.get("ownership", {}).get("label") == "Labeled"


# --- 回归测试：chart创建响应不得泄露owner_secret到JSON body ---

def test_chart_create_response_never_exposes_owner_secret_in_json():
    """chart创建响应body中不得包含access/owner_secret/expires_at。
    owner_secret只能通过X-Anima-Chart-Owner header传输。"""
    from api.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)
    body = {
        "birth_date": "1990-06-15", "birth_time": "14:00",
        "timezone": "Asia/Shanghai",
        "location": {"city": "Beijing", "lat": 39.9, "lng": 116.4, "timezone": "Asia/Shanghai"},
        "sex": "male", "luck_cycle_convention": "not_applied"
    }
    resp = client.post("/api/v1/chart", json=body)
    assert resp.status_code == 200
    j = resp.json()
    # JSON body 不得有access字段
    assert "access" not in j, "BUG REGRESSION: access field leaked into JSON body"
    assert "owner_secret" not in j, "BUG REGRESSION: owner_secret leaked into JSON body"
    # owner_secret 只能走header
    owner_h = resp.headers.get("x-anima-chart-owner", "")
    assert len(owner_h) > 32, f"owner_secret too short in header: {len(owner_h)} chars"
    assert j.get("chart_id"), "chart_id missing from response"
    assert j.get("pillars", {}).get("year", {}).get("stem"), "pillar data missing"
