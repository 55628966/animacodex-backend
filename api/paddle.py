# -*- coding: utf-8 -*-
"""Paddle 支付集成(29号 B4, MoR 模式)。

两条职责:
1. checkout/create: 用 Paddle Transactions API 建 checkout, 价格只以本模块
   PRODUCTS 常量表为准 —— 前端绝不提交金额/币种(29号红线: 支付不伪造)。
2. webhooks/paddle: 按 Paddle 官方 Paddle-Signature 头(HMAC-SHA256)验签。
   验签不过一律 401, 任何 paid/entitlement 写入必须先过验签。

凭据全部走环境变量(不硬编码不入 git):
- PADDLE_API_KEY:        Paddle 后台 Developer Tools → Authentication 的 API key
- PADDLE_SELLER_ID:      Paddle 后台 Developer Tools → Authentication 的 seller id
- PADDLE_SANDBOX:        "true"(默认, 用 sandbox-api) / "false"(生产 api.paddle.com)
- PADDLE_WEBHOOK_SECRET: Paddle 后台 Developer Tools → Notifications 的 endpoint secret
"""
import hashlib
import hmac
import os
import time
from dataclasses import dataclass

import httpx

# ── 产品价格表(唯一权威来源; 前端 commerce.js 的 COMMERCIAL_CONFIG 是镜像) ──
# amount_cents 为美分; kind: one_time 一次性 / subscription 订阅。
PRODUCTS: dict[str, dict] = {
    "first_scroll": {
        "name": "First Scroll", "kind": "one_time",
        "amount_cents": 599, "currency": "USD",
    },
    "full_codex": {
        "name": "Full Codex", "kind": "one_time",
        "amount_cents": 1999, "currency": "USD",
    },
    "sanctum_monthly": {
        "name": "Sanctum Monthly", "kind": "subscription",
        "amount_cents": 799, "currency": "USD", "interval": "month",
    },
    "sanctum_yearly": {
        "name": "Sanctum Yearly", "kind": "subscription",
        "amount_cents": 6999, "currency": "USD", "interval": "year",
    },
}

SANDBOX_BASE_URL = "https://sandbox-api.paddle.com"
PRODUCTION_BASE_URL = "https://api.paddle.com"

# 测试挂钩: 置为 httpx.MockTransport 即可蒙住一切外呼。
_TEST_TRANSPORT: httpx.BaseTransport | None = None


class PaddleUnavailable(Exception):
    """Paddle 不可达/超时/返回异常 —— 端点统一映射为 502, 消息不得含凭据细节。"""


@dataclass(frozen=True)
class PaddleConfig:
    api_key: str | None
    seller_id: str | None
    sandbox: bool
    webhook_secret: str | None

    @property
    def checkout_configured(self) -> bool:
        return bool(self.api_key and self.seller_id)

    @property
    def base_url(self) -> str:
        return SANDBOX_BASE_URL if self.sandbox else PRODUCTION_BASE_URL


def load_config() -> PaddleConfig:
    """每次请求现场读环境变量(测试可 monkeypatch, 进程无需重启)。"""
    sandbox_raw = os.environ.get("PADDLE_SANDBOX", "true").strip().lower()
    return PaddleConfig(
        api_key=os.environ.get("PADDLE_API_KEY") or None,
        seller_id=os.environ.get("PADDLE_SELLER_ID") or None,
        sandbox=sandbox_raw not in ("false", "0", "no"),
        webhook_secret=os.environ.get("PADDLE_WEBHOOK_SECRET") or None,
    )


# ── checkout ─────────────────────────────────────────────────────────

def _transaction_payload(product_id: str, custom_data: dict) -> dict:
    """构造 Paddle Transactions API 请求体(内联自定义价格, 金额只来自 PRODUCTS)。"""
    product = PRODUCTS[product_id]
    price = {
        "description": f"Anima Codex — {product['name']}",
        "name": product["name"],
        "type": "custom",
        "unit_price": {
            "amount": str(product["amount_cents"]),
            "currency_code": product["currency"],
        },
        "product": {
            "name": f"Anima Codex {product['name']}",
            "tax_category": "standard",
        },
    }
    if product["kind"] == "subscription":
        price["billing_cycle"] = {"interval": product["interval"], "frequency": 1}
    return {
        "items": [{"quantity": 1, "price": price}],
        "custom_data": custom_data,
    }


async def create_checkout_url(config: PaddleConfig, product_id: str, custom_data: dict) -> str:
    """调 Paddle 创建 transaction 并返回 checkout.url; 失败抛 PaddleUnavailable。"""
    payload = _transaction_payload(product_id, custom_data)
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10, transport=_TEST_TRANSPORT) as client:
            resp = await client.post(f"{config.base_url}/transactions",
                                     json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise PaddleUnavailable("payment provider unreachable") from exc
    if resp.status_code >= 400:
        raise PaddleUnavailable(f"payment provider rejected the request (HTTP {resp.status_code})")
    try:
        data = resp.json().get("data") or {}
    except Exception as exc:
        raise PaddleUnavailable("payment provider returned an unreadable response") from exc
    url = (data.get("checkout") or {}).get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise PaddleUnavailable("payment provider did not return a checkout url")
    return url


# ── webhook 验签 ──────────────────────────────────────────────────────

def verify_signature(raw_body: bytes, signature_header: str, secret: str,
                     tolerance_seconds: int = 300) -> bool:
    """按 Paddle 官方方案验证 Paddle-Signature 头。

    头格式: "ts=<unix秒>;h1=<hex>[;h1=<hex>...]"
    签名内容: "<ts>:<raw_body>", HMAC-SHA256(secret)。
    ts 超出容差窗口(默认 5 分钟)一律拒绝, 防重放。
    """
    if not signature_header or not secret:
        return False
    parts: dict[str, list[str]] = {}
    for chunk in signature_header.split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        parts.setdefault(key.strip(), []).append(value.strip())
    ts_list = parts.get("ts") or []
    h1_list = parts.get("h1") or []
    if not ts_list or not h1_list:
        return False
    try:
        ts = int(ts_list[0])
    except ValueError:
        return False
    if tolerance_seconds > 0 and abs(int(time.time()) - ts) > tolerance_seconds:
        return False
    signed = ts_list[0].encode("utf-8") + b":" + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in h1_list)
