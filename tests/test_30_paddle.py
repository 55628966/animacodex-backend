# -*- coding: utf-8 -*-
"""30号 Paddle 支付契约测试: POST /api/v1/checkout/create + /api/v1/webhooks/paddle。

运行: .venv/bin/python -m pytest tests/test_30_paddle.py -q  (在项目根目录)

覆盖: A.未配置→501 B.价格表/校验 C.MockTransport 蒙外呼的正常路径
      D.Paddle 异常→502 E.webhook 验签/幂等/权益写入 F.红线(不泄露不伪造)
"""
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from fastapi.testclient import TestClient

import api.main as main
from api import auth as auth_module
from api import paddle as paddle_module
from api import storage

WEBHOOK_SECRET = "pdl_ntfset_test_secret_0123456789"
PADDLE_ENV = ("PADDLE_API_KEY", "PADDLE_SELLER_ID", "PADDLE_SANDBOX", "PADDLE_WEBHOOK_SECRET")


@pytest.fixture(scope="module")
def isolated_db(tmp_path_factory):
    """Isolate tests from the developer database."""
    db_file = tmp_path_factory.mktemp("paddle-test-db") / "anima-test.db"
    prev = {
        name: os.environ.get(name)
        for name in ("ANIMA_DB_PATH", "ANIMA_OWNER_SECRET_PEPPER", "ANIMA_CHART_TTL_SECONDS")
    }
    os.environ["ANIMA_DB_PATH"] = str(db_file)
    os.environ["ANIMA_OWNER_SECRET_PEPPER"] = "test-owner-pepper"
    os.environ["ANIMA_CHART_TTL_SECONDS"] = "2592000"
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


@pytest.fixture(autouse=True)
def clean_paddle_env():
    """Each test starts with no Paddle env and no mock transport."""
    prev = {name: os.environ.get(name) for name in PADDLE_ENV}
    for name in PADDLE_ENV:
        os.environ.pop(name, None)
    paddle_module._TEST_TRANSPORT = None
    try:
        yield
    finally:
        paddle_module._TEST_TRANSPORT = None
        for name, value in prev.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# ── helpers ───────────────────────────────────────────────────────────

def _configure_checkout(sandbox="true"):
    os.environ["PADDLE_API_KEY"] = "pdl_test_api_key_fake"
    os.environ["PADDLE_SELLER_ID"] = "12345"
    os.environ["PADDLE_SANDBOX"] = sandbox


def _sign(raw: bytes, secret: str = WEBHOOK_SECRET, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    digest = hmac.new(secret.encode(), f"{ts}:".encode() + raw, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={digest}"


def _post_webhook(client, payload: dict, signature: str | None = None):
    raw = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signature is None:
        signature = _sign(raw)
    headers["Paddle-Signature"] = signature
    return client.post("/api/v1/webhooks/paddle", content=raw, headers=headers)


def _make_user() -> str:
    user_id = str(uuid.uuid4())
    storage.create_user(user_id, hashlib.sha256(user_id.encode()).hexdigest(), "pw-hash")
    return user_id


def _txn_event(event_id: str, txn_id: str, custom_data: dict,
               event_type: str = "transaction.completed") -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-07-21T00:00:00Z",
        "data": {"id": txn_id, "status": "completed", "custom_data": custom_data},
    }


def _paddle_ok_transport(record: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        record["url"] = str(request.url)
        record["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "data": {
                "id": "txn_01mock",
                "checkout": {"url": "https://sandbox-checkout.paddle.com/transaction?_ptxn=txn_01mock"},
            }
        })
    return httpx.MockTransport(handler)


# ── A. 未配置 / 输入校验 ─────────────────────────────────────────────

class TestCheckoutNotConfigured:
    def test_no_env_returns_501(self, client):
        resp = client.post("/api/v1/checkout/create", json={"product_id": "full_codex"})
        assert resp.status_code == 501
        body = resp.json()
        assert body["error"]["code"] == "NOT_IMPLEMENTED"
        assert "payment not configured" in body["error"]["message"]

    def test_partial_env_returns_501(self, client):
        os.environ["PADDLE_API_KEY"] = "pdl_test_api_key_fake"  # 缺 SELLER_ID
        resp = client.post("/api/v1/checkout/create", json={"product_id": "full_codex"})
        assert resp.status_code == 501

    def test_unknown_product_400(self, client):
        _configure_checkout()
        resp = client.post("/api/v1/checkout/create", json={"product_id": "everything_free"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_PRODUCT"

    def test_bad_chart_id_400(self, client):
        _configure_checkout()
        resp = client.post("/api/v1/checkout/create",
                           json={"product_id": "full_codex", "chart_id": "  "})
        assert resp.status_code == 400


# ── B/C. 正常路径(MockTransport 蒙住外呼) ────────────────────────────

class TestCheckoutSuccess:
    def test_checkout_url_and_price_from_server_table(self, client):
        _configure_checkout()
        record: dict = {}
        paddle_module._TEST_TRANSPORT = _paddle_ok_transport(record)
        resp = client.post("/api/v1/checkout/create",
                           json={"product_id": "full_codex", "chart_id": "chart-abc"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["checkout_url"].startswith("https://")
        assert body["product_id"] == "full_codex"
        # 外呼细节: sandbox 基址 + 服务端价格表金额 + custom_data 透传 chart_id
        assert record["url"].startswith("https://sandbox-api.paddle.com/")
        sent = record["body"]
        price = sent["items"][0]["price"]
        assert price["unit_price"] == {"amount": "1999", "currency_code": "USD"}
        assert sent["custom_data"]["chart_id"] == "chart-abc"
        assert sent["custom_data"]["product_id"] == "full_codex"
        assert "user_id" not in sent["custom_data"]

    def test_production_base_url_when_sandbox_false(self, client):
        _configure_checkout(sandbox="false")
        record: dict = {}
        paddle_module._TEST_TRANSPORT = _paddle_ok_transport(record)
        resp = client.post("/api/v1/checkout/create", json={"product_id": "sanctum_yearly"})
        assert resp.status_code == 200
        assert record["url"].startswith("https://api.paddle.com/")
        price = record["body"]["items"][0]["price"]
        assert price["unit_price"]["amount"] == "6999"
        assert price["billing_cycle"] == {"interval": "year", "frequency": 1}

    def test_jwt_user_attached_to_custom_data(self, client):
        _configure_checkout()
        user_id = _make_user()
        tokens = auth_module.create_jwt(user_id, f"{user_id}@example.com")
        record: dict = {}
        paddle_module._TEST_TRANSPORT = _paddle_ok_transport(record)
        resp = client.post(
            "/api/v1/checkout/create",
            json={"product_id": "sanctum_monthly"},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert resp.status_code == 200
        sent = record["body"]
        assert sent["custom_data"]["user_id"] == user_id
        assert sent["items"][0]["price"]["unit_price"]["amount"] == "799"
        assert sent["items"][0]["price"]["billing_cycle"] == {"interval": "month", "frequency": 1}

    def test_invalid_jwt_degrades_to_anonymous(self, client):
        _configure_checkout()
        record: dict = {}
        paddle_module._TEST_TRANSPORT = _paddle_ok_transport(record)
        resp = client.post(
            "/api/v1/checkout/create",
            json={"product_id": "full_codex"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 200
        assert "user_id" not in record["body"]["custom_data"]


# ── D. Paddle 不可达 → 502 ────────────────────────────────────────────

class TestCheckoutProviderFailure:
    def test_paddle_http_error_502(self, client):
        _configure_checkout()
        paddle_module._TEST_TRANSPORT = httpx.MockTransport(
            lambda _req: httpx.Response(500, json={"error": {"detail": "boom"}}))
        resp = client.post("/api/v1/checkout/create", json={"product_id": "full_codex"})
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "PAYMENT_PROVIDER_ERROR"

    def test_paddle_unreachable_502(self, client):
        _configure_checkout()

        def handler(_req):
            raise httpx.ConnectError("connection refused")
        paddle_module._TEST_TRANSPORT = httpx.MockTransport(handler)
        resp = client.post("/api/v1/checkout/create", json={"product_id": "full_codex"})
        assert resp.status_code == 502

    def test_missing_checkout_url_502(self, client):
        _configure_checkout()
        paddle_module._TEST_TRANSPORT = httpx.MockTransport(
            lambda _req: httpx.Response(200, json={"data": {"id": "txn_x"}}))
        resp = client.post("/api/v1/checkout/create", json={"product_id": "full_codex"})
        assert resp.status_code == 502


# ── E. webhook ────────────────────────────────────────────────────────

class TestWebhook:
    def test_no_secret_returns_503(self, client):
        resp = _post_webhook(client, _txn_event("evt_1", "txn_1", {"product_id": "full_codex"}))
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "PAYMENT_NOT_CONFIGURED"

    def test_bad_signature_401_and_no_entitlement(self, client):
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        user_id = _make_user()
        event = _txn_event("evt_bad_sig", "txn_bad_sig",
                           {"product_id": "full_codex", "user_id": user_id})
        raw = json.dumps(event).encode("utf-8")
        resp = client.post("/api/v1/webhooks/paddle", content=raw,
                           headers={"Paddle-Signature": "ts=1;h1=" + "0" * 64})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_SIGNATURE"
        assert storage.list_entitlements(user_id) == []

    def test_stale_timestamp_401(self, client):
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        user_id = _make_user()
        event = _txn_event("evt_stale", "txn_stale",
                           {"product_id": "full_codex", "user_id": user_id})
        raw = json.dumps(event).encode("utf-8")
        stale = _sign(raw, ts=int(time.time()) - 3600)
        resp = client.post("/api/v1/webhooks/paddle", content=raw,
                           headers={"Paddle-Signature": stale})
        assert resp.status_code == 401
        assert storage.list_entitlements(user_id) == []

    def test_transaction_completed_grants_entitlement(self, client):
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        user_id = _make_user()
        event = _txn_event("evt_ok_1", "txn_ok_1",
                           {"product_id": "full_codex", "user_id": user_id, "chart_id": "c1"})
        resp = _post_webhook(client, event)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["transaction_id"] == "txn_ok_1"
        assert body["entitlement"]["product_id"] == "full_codex"
        assert body["entitlement"]["source"] == "paddle"
        ents = storage.list_entitlements(user_id)
        assert len(ents) == 1 and ents[0]["source"] == "paddle"

    def test_replay_is_idempotent(self, client):
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        user_id = _make_user()
        event = _txn_event("evt_replay", "txn_replay",
                           {"product_id": "full_codex", "user_id": user_id})
        first = _post_webhook(client, event)
        assert first.json()["status"] == "ok"
        second = _post_webhook(client, event)
        assert second.status_code == 200
        assert second.json()["status"] == "duplicate"
        assert len(storage.list_entitlements(user_id)) == 1

    def test_other_event_types_ignored_200(self, client):
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        event = _txn_event("evt_other", "txn_other", {"product_id": "full_codex"},
                           event_type="subscription.created")
        resp = _post_webhook(client, event)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    def test_anonymous_chart_payment_attaches_via_claim(self, client):
        """匿名 chart 支付: custom_data 无 user_id 时回查 chart_ownership。"""
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        user_id = _make_user()
        chart_id = f"chart-{uuid.uuid4().hex[:8]}"
        secret = storage.new_owner_secret()
        storage.save_chart(chart_id, {"meta": {"algo_version": "test"}}, secret)
        assert storage.claim_chart(chart_id, user_id)
        event = _txn_event("evt_claim", "txn_claim",
                           {"product_id": "sanctum_monthly", "chart_id": chart_id})
        resp = _post_webhook(client, event)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        ents = storage.list_entitlements(user_id)
        assert [e["product_id"] for e in ents] == ["sanctum_monthly"]

    def test_unresolvable_user_pending_no_entitlement(self, client):
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        event = _txn_event("evt_pending", "txn_pending",
                           {"product_id": "full_codex", "chart_id": "never-claimed"})
        resp = _post_webhook(client, event)
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_user"

    def test_unknown_product_unprocessable(self, client):
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        user_id = _make_user()
        event = _txn_event("evt_unknown_prod", "txn_unknown_prod",
                           {"product_id": "gold_membership", "user_id": user_id})
        resp = _post_webhook(client, event)
        assert resp.status_code == 200
        assert resp.json()["status"] == "unprocessable"
        assert storage.list_entitlements(user_id) == []


# ── F. 红线: 不泄露凭据/email; 不伪造 ─────────────────────────────────

class TestRedLines:
    def test_responses_never_leak_secrets_or_email(self, client):
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        _configure_checkout()
        record: dict = {}
        paddle_module._TEST_TRANSPORT = _paddle_ok_transport(record)
        user_id = _make_user()
        tokens = auth_module.create_jwt(user_id, "payer-secret@example.com")

        responses = [
            client.post("/api/v1/checkout/create",
                        json={"product_id": "full_codex"},
                        headers={"Authorization": f"Bearer {tokens['access_token']}"}),
            _post_webhook(client, _txn_event("evt_leak", "txn_leak",
                                             {"product_id": "full_codex", "user_id": user_id})),
        ]
        bad_markers = (WEBHOOK_SECRET, "pdl_test_api_key_fake", "payer-secret@example.com")
        for resp in responses:
            for marker in bad_markers:
                assert marker not in resp.text

    def test_unverified_payment_never_grants_entitlement(self, client):
        """不验签/无 webhook 的任何路径都不能产生 source='paddle' 的权益。"""
        os.environ["PADDLE_WEBHOOK_SECRET"] = WEBHOOK_SECRET
        user_id = _make_user()
        # 伪造签名
        forged = _txn_event("evt_forged", "txn_forged",
                            {"product_id": "full_codex", "user_id": user_id})
        raw = json.dumps(forged).encode("utf-8")
        resp = client.post("/api/v1/webhooks/paddle", content=raw,
                           headers={"Paddle-Signature": _sign(raw, secret="wrong-secret")})
        assert resp.status_code == 401
        assert storage.list_entitlements(user_id) == []
