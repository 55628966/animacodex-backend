# -*- coding: utf-8 -*-
"""SQLite persistence layer with short-lived, owner-protected charts.

This module stores only the computed ChartResult. It deliberately does not
store the raw chart request: birth date, birth time, and place are sensitive
personal data and are not needed to retrieve or derive a stored chart.

Privacy v1 chart schema:
- chart_id, result_json, algorithm version, HMAC digest of an owner secret,
  creation time, and expiry time.
- anonymous charts expire after 30 days by default.
- chart_id is a locator, never an authorization credential. API reads,
  derived reads, and deletion require the owner secret outside the URL.

The owner secret is a high-entropy bearer credential returned only once in the
POST response header. SQLite keeps an HMAC digest, not the plaintext secret.

Environment:
- ANIMA_DB_PATH: SQLite file location (test isolation).
- ANIMA_CHART_TTL_SECONDS: positive anonymous-chart TTL; default 30 days.
- ANIMA_OWNER_SECRET_PEPPER: production HMAC key. When omitted, a random
  process-local key is used for local development only; restart makes existing
  secrets unverifiable. This explicit fail-closed fallback is not suitable for
  production.

Legacy charts had request_json and no owner secret. They cannot be safely
migrated without treating chart_id as authority, so init_db drops those
unowned records instead of copying sensitive birth data into the new table.
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHART_TTL_SECONDS = 30 * 24 * 60 * 60
_EPHEMERAL_OWNER_SECRET_PEPPER = secrets.token_bytes(32)

_CHART_COLUMNS = {
    "chart_id", "result_json", "algo_version", "owner_secret_hash",
    "created_at", "expires_at",
}


def db_path() -> str:
    """Return the database path and create its parent directory if needed."""
    p = os.environ.get("ANIMA_DB_PATH") or str(_PROJECT_ROOT / "data" / "anima.db")
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    """Create a short-lived SQLite connection."""
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _now_iso() -> str:
    return _now().isoformat()


def chart_ttl_seconds() -> int:
    """Read and validate chart TTL; zero/negative never means retention forever."""
    raw = os.environ.get("ANIMA_CHART_TTL_SECONDS")
    if raw is None:
        return DEFAULT_CHART_TTL_SECONDS
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise RuntimeError("ANIMA_CHART_TTL_SECONDS must be a positive integer") from exc
    if ttl <= 0:
        raise RuntimeError(
            "ANIMA_CHART_TTL_SECONDS must be > 0; anonymous charts cannot be retained forever"
        )
    return ttl


def _owner_secret_key() -> bytes:
    """Return configured HMAC key or a clearly local-only process-random key."""
    configured = os.environ.get("ANIMA_OWNER_SECRET_PEPPER")
    return configured.encode("utf-8") if configured else _EPHEMERAL_OWNER_SECRET_PEPPER


def new_owner_secret() -> str:
    """Generate an approximately 256-bit bearer secret for a newly created chart."""
    return secrets.token_urlsafe(32)


def _owner_secret_hash(owner_secret: str) -> str:
    if not isinstance(owner_secret, str) or not owner_secret:
        # Keep absent credentials on the same digest path as an ordinary secret.
        owner_secret = ""
    return hmac.new(
        _owner_secret_key(), owner_secret.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _create_charts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS charts (
            chart_id          TEXT PRIMARY KEY,
            result_json       TEXT NOT NULL,
            algo_version      TEXT NOT NULL,
            owner_secret_hash TEXT NOT NULL,
            created_at        TEXT NOT NULL,
            expires_at        TEXT NOT NULL
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_charts_expires_at ON charts(expires_at)")


def _chart_column_names(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(charts)").fetchall()}


def _ensure_charts_schema(conn: sqlite3.Connection) -> None:
    """Create privacy v1 schema; remove legacy unowned raw-request records."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'charts'"
    ).fetchone()
    if not exists:
        _create_charts_table(conn)
        return

    if _chart_column_names(conn) == _CHART_COLUMNS:
        return

    # Legacy rows have no owner secret. Preserving them would leave chart_id as
    # authorization and preserve request_json, so the migration fails closed.
    conn.execute("DROP TABLE charts")
    _create_charts_table(conn)


def _create_hour_sessions_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hour_sessions (
            session_id        TEXT PRIMARY KEY,
            answers_json      TEXT NOT NULL,
            owner_secret_hash TEXT NOT NULL,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        )""")


def _ensure_hour_sessions_schema(conn: sqlite3.Connection) -> None:
    """Create the owner-protected schema; add the credential column to legacy DBs.

    CREATE TABLE IF NOT EXISTS never adds columns, so existing databases need an
    explicit ALTER. Legacy rows gain an empty hash that matches no digest, which
    fails closed: they become unreachable instead of being treated as unowned.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'hour_sessions'"
    ).fetchone()
    if not exists:
        _create_hour_sessions_table(conn)
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(hour_sessions)").fetchall()}
    if "owner_secret_hash" not in columns:
        conn.execute(
            "ALTER TABLE hour_sessions ADD COLUMN owner_secret_hash TEXT NOT NULL DEFAULT ''"
        )


def init_db() -> None:
    """Create tables, perform the privacy migration, and purge expired charts."""
    # Validate retention configuration at startup, not after a user submits data.
    chart_ttl_seconds()
    with _connect() as conn:
        _ensure_charts_schema(conn)
        _ensure_hour_sessions_schema(conn)

        # ── 29号 A_组: authentication + entitlements + chart ownership ──
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email_hash TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                refresh_token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entitlements (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                product_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'purchase',
                granted_at TEXT NOT NULL,
                expires_at TEXT,
                UNIQUE(user_id, product_id)
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chart_ownership (
                chart_id TEXT PRIMARY KEY REFERENCES charts(chart_id),
                user_id TEXT NOT NULL REFERENCES users(id),
                label TEXT DEFAULT '',
                claimed_at TEXT NOT NULL
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chart_ownership_user ON chart_ownership(user_id)")

        # ── 29号 B4: Paddle webhook 幂等去重表 ──
        conn.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                transaction_id TEXT,
                processed INTEGER NOT NULL DEFAULT 0,
                received_at TEXT NOT NULL
            )""")

        # ── 29号 A_组 痛点23: password reset tokens ──
        _ensure_reset_tokens_table(conn)

        conn.execute("DELETE FROM charts WHERE expires_at <= ?", (_now_iso(),))


# ---------------- charts ----------------

def save_chart(chart_id: str, result_obj: dict, owner_secret: str) -> str:
    """Persist a short-lived ChartResult and return its UTC ISO expiry time.

    request_obj is intentionally not an argument. Stored chart retrieval and
    all current derivations only require the ChartResult, not raw birth data.
    """
    now = _now()
    expires_at = (now + timedelta(seconds=chart_ttl_seconds())).isoformat()
    with _connect() as conn:
        conn.execute("DELETE FROM charts WHERE expires_at <= ?", (now.isoformat(),))
        conn.execute(
            "INSERT INTO charts (chart_id, result_json, algo_version, owner_secret_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                chart_id,
                json.dumps(result_obj, ensure_ascii=False),
                result_obj.get("meta", {}).get("algo_version", ""),
                _owner_secret_hash(owner_secret),
                now.isoformat(),
                expires_at,
            ),
        )
    return expires_at


def load_chart_for_owner(chart_id: str, owner_secret: str):
    """Return a ChartResult for a matching owner secret; otherwise return None.

    Missing, expired, wrong-secret, and unknown charts intentionally collapse
    to one result so the API can return a non-enumerable 404 response.
    """
    now_iso = _now_iso()
    candidate_hash = _owner_secret_hash(owner_secret)
    with _connect() as conn:
        conn.execute("DELETE FROM charts WHERE expires_at <= ?", (now_iso,))
        row = conn.execute(
            "SELECT result_json, owner_secret_hash FROM charts WHERE chart_id = ?",
            (chart_id,),
        ).fetchone()
    if not row or not hmac.compare_digest(row[1], candidate_hash):
        return None
    return json.loads(row[0])


def delete_chart_for_owner(chart_id: str, owner_secret: str) -> bool:
    """Delete only a matching owner chart; invalid ownership returns False."""
    now_iso = _now_iso()
    candidate_hash = _owner_secret_hash(owner_secret)
    with _connect() as conn:
        conn.execute("DELETE FROM charts WHERE expires_at <= ?", (now_iso,))
        row = conn.execute(
            "SELECT owner_secret_hash FROM charts WHERE chart_id = ?", (chart_id,)
        ).fetchone()
        if not row or not hmac.compare_digest(row[0], candidate_hash):
            return False
        deleted = conn.execute(
            "DELETE FROM charts WHERE chart_id = ? AND owner_secret_hash = ?",
            (chart_id, candidate_hash),
        ).rowcount
    return deleted == 1


# ---------------- hour_sessions ----------------

def create_hour_session(session_id: str, owner_secret: str) -> None:
    """Create a session with an empty answer sequence; store only the secret digest."""
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO hour_sessions (session_id, answers_json, owner_secret_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, "[]", _owner_secret_hash(owner_secret), now, now))


def load_hour_session(session_id: str):
    """Return a session answer sequence, or None when the session is absent.

    Internal use only; API endpoints must go through load_hour_session_for_owner.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT answers_json FROM hour_sessions WHERE session_id = ?",
            (session_id,)).fetchone()
    return json.loads(row[0]) if row else None


def load_hour_session_for_owner(session_id: str, owner_secret: str):
    """Return the answer sequence for a matching owner secret; otherwise None.

    Unknown sessions and wrong secrets intentionally collapse to one result so
    the API can return a non-enumerable 404 response.
    """
    candidate_hash = _owner_secret_hash(owner_secret)
    with _connect() as conn:
        row = conn.execute(
            "SELECT answers_json, owner_secret_hash FROM hour_sessions WHERE session_id = ?",
            (session_id,)).fetchone()
    if not row or not hmac.compare_digest(row[1], candidate_hash):
        return None
    return json.loads(row[0])


def delete_hour_session_for_owner(session_id: str, owner_secret: str) -> bool:
    """Delete only a matching owner session; invalid ownership returns False."""
    candidate_hash = _owner_secret_hash(owner_secret)
    with _connect() as conn:
        row = conn.execute(
            "SELECT owner_secret_hash FROM hour_sessions WHERE session_id = ?",
            (session_id,)).fetchone()
        if not row or not hmac.compare_digest(row[0], candidate_hash):
            return False
        deleted = conn.execute(
            "DELETE FROM hour_sessions WHERE session_id = ? AND owner_secret_hash = ?",
            (session_id, candidate_hash),
        ).rowcount
    return deleted == 1


def update_hour_session(session_id: str, answers: list) -> None:
    """Overwrite the answer sequence; server logic recomputes from all answers."""
    with _connect() as conn:
        conn.execute(
            "UPDATE hour_sessions SET answers_json = ?, updated_at = ? WHERE session_id = ?",
            (json.dumps(answers, ensure_ascii=False), _now_iso(), session_id))


# ═══════════════════════════════════════════════════════════════════════
# 29号 A_组: users, sessions, entitlements, chart_ownership
# ═══════════════════════════════════════════════════════════════════════

# ── users ─────────────────────────────────────────────────────────────

def create_user(user_id: str, email_hash: str, password_hash: str) -> str:
    """Insert a new user; return the user_id."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (id, email_hash, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (user_id, email_hash, password_hash, _now_iso()),
        )
    return user_id


def get_user_by_email_hash(email_hash: str) -> dict | None:
    """Return user dict {id, email_hash, password_hash, created_at} or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email_hash, password_hash, created_at FROM users WHERE email_hash = ?",
            (email_hash,),
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "email_hash": row[1], "password_hash": row[2], "created_at": row[3]}


def update_user_password(user_id: str, password_hash: str) -> bool:
    """Update a user's password hash. Returns False if user not found."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        return cur.rowcount == 1


def get_user_by_id(user_id: str) -> dict | None:
    """Return user dict or None by primary key."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email_hash, password_hash, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "email_hash": row[1], "password_hash": row[2], "created_at": row[3]}


# ── sessions ──────────────────────────────────────────────────────────

def create_session(user_id: str, refresh_token_hash: str, expires_at: str) -> str:
    """Create a new session record and return its id."""
    import uuid as _uuid_mod
    session_id = str(_uuid_mod.uuid4())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, refresh_token_hash, expires_at, revoked) VALUES (?, ?, ?, ?, 0)",
            (session_id, user_id, refresh_token_hash, expires_at),
        )
    return session_id


def get_sessions_for_user(user_id: str) -> list[dict]:
    """Return all sessions (including revoked) for a user."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, user_id, refresh_token_hash, expires_at, revoked FROM sessions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return [
        {"id": r[0], "user_id": r[1], "refresh_token_hash": r[2], "expires_at": r[3], "revoked": bool(r[4])}
        for r in rows
    ]


def revoke_session(session_id: str) -> None:
    """Mark a session as revoked."""
    with _connect() as conn:
        conn.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (session_id,))


def revoke_all_sessions(user_id: str) -> None:
    """Revoke every session belonging to a user (logout all)."""
    with _connect() as conn:
        conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user_id,))


# ── entitlements ──────────────────────────────────────────────────────

def get_or_create_entitlement(user_id: str, product_id: str, source: str = "purchase") -> dict:
    """Return existing or newly created entitlement {id, user_id, product_id, source, granted_at, expires_at}."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, product_id, source, granted_at, expires_at FROM entitlements WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        ).fetchone()
        if row:
            return {
                "id": row[0], "user_id": row[1], "product_id": row[2],
                "source": row[3], "granted_at": row[4], "expires_at": row[5],
            }
        import uuid as _uuid_mod
        ent_id = str(_uuid_mod.uuid4())
        now = _now_iso()
        conn.execute(
            "INSERT INTO entitlements (id, user_id, product_id, source, granted_at, expires_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (ent_id, user_id, product_id, source, now),
        )
    return {
        "id": ent_id, "user_id": user_id, "product_id": product_id,
        "source": source, "granted_at": now, "expires_at": None,
    }


def list_entitlements(user_id: str) -> list[dict]:
    """Return all entitlements for a user."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, user_id, product_id, source, granted_at, expires_at FROM entitlements WHERE user_id = ? ORDER BY granted_at DESC",
            (user_id,),
        ).fetchall()
    return [
        {"id": r[0], "user_id": r[1], "product_id": r[2], "source": r[3], "granted_at": r[4], "expires_at": r[5]}
        for r in rows
    ]


# ── chart_ownership ───────────────────────────────────────────────────

def claim_chart(chart_id: str, user_id: str, label: str = "") -> bool:
    """Assign a chart to a user. Returns False if chart doesn't exist or is already claimed."""
    with _connect() as conn:
        # Verify the chart exists
        chart = conn.execute("SELECT 1 FROM charts WHERE chart_id = ?", (chart_id,)).fetchone()
        if chart is None:
            return False
        # Check if already claimed
        existing = conn.execute("SELECT 1 FROM chart_ownership WHERE chart_id = ?", (chart_id,)).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO chart_ownership (chart_id, user_id, label, claimed_at) VALUES (?, ?, ?, ?)",
            (chart_id, user_id, label, _now_iso()),
        )
    return True


def list_user_charts(user_id: str) -> list[dict]:
    """Return all chart dicts owned by the user, joined with charts table."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT c.chart_id, c.result_json, c.algo_version, c.created_at, c.expires_at,
                   co.label, co.claimed_at
            FROM charts c
            JOIN chart_ownership co ON c.chart_id = co.chart_id
            WHERE co.user_id = ?
            ORDER BY co.claimed_at DESC
        """, (user_id,)).fetchall()
    results = []
    for r in rows:
        chart_data = json.loads(r[1])
        chart_data["ownership"] = {"label": r[5], "claimed_at": r[6]}
        results.append(chart_data)
    return results


def update_chart_label(chart_id: str, user_id: str, label: str) -> bool:
    """Update the user-defined label for an owned chart. Returns False if not owned or no change."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE chart_ownership SET label = ? WHERE chart_id = ? AND user_id = ?",
            (label, chart_id, user_id),
        )
        return cur.rowcount == 1


def delete_user_chart(chart_id: str, user_id: str) -> bool:
    """Delete a chart and its ownership record if owned by user. Returns True on success."""
    with _connect() as conn:
        # Check ownership
        owned = conn.execute(
            "SELECT 1 FROM chart_ownership WHERE chart_id = ? AND user_id = ?",
            (chart_id, user_id),
        ).fetchone()
        if owned is None:
            return False
        conn.execute("DELETE FROM chart_ownership WHERE chart_id = ?", (chart_id,))
        conn.execute("DELETE FROM charts WHERE chart_id = ?", (chart_id,))
        return True


# ── webhook_events(29号 B4) ─────────────────────────────────────────

def record_webhook_event(event_id: str, event_type: str,
                         transaction_id: str | None = None, processed: bool = False) -> bool:
    """Record a webhook event for idempotency. Returns False when already recorded."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO webhook_events (event_id, event_type, transaction_id, processed, received_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_id, event_type, transaction_id, 1 if processed else 0, _now_iso()),
        )
        return cur.rowcount == 1


def get_chart_owner_user_id(chart_id: str) -> str | None:
    """Return the user_id that claimed the chart, or None for anonymous/unknown charts."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM chart_ownership WHERE chart_id = ?", (chart_id,)
        ).fetchone()
    return row[0] if row else None


# ── password reset tokens ───────────────────────────────────────────────

def _ensure_reset_tokens_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token       TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL REFERENCES users(id),
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            used        INTEGER NOT NULL DEFAULT 0
        )""")


def create_reset_token(user_id: str) -> str:
    """Generate a password-reset token (valid 1 hour), store it, return the token."""
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = (now + timedelta(hours=1)).isoformat()
    with _connect() as conn:
        _ensure_reset_tokens_table(conn)
        conn.execute(
            "INSERT INTO password_reset_tokens (token, user_id, created_at, expires_at, used) "
            "VALUES (?, ?, ?, ?, 0)",
            (token, user_id, now.isoformat(), expires_at),
        )
    return token


def consume_reset_token(token: str) -> str | None:
    """Validate and consume a reset token. Returns user_id on success, None otherwise."""
    with _connect() as conn:
        _ensure_reset_tokens_table(conn)
        row = conn.execute(
            "SELECT user_id, used, expires_at FROM password_reset_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None or row[1] != 0 or row[2] < _now_iso():
            return None
        conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE token = ?", (token,)
        )
        return row[0]


def count_charts() -> int:
    """Return the total number of non-expired charts stored."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM charts WHERE expires_at > ?", (_now_iso(),)
        ).fetchone()
    return row[0] if row else 0

