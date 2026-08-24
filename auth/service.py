"""Minimal username/password authentication for the platform's paper
trading accounts. Passwords are hashed with salted PBKDF2-HMAC-SHA256
(OWASP-recommended iteration count) using only the Python standard library
- no plaintext password ever touches the database or a log line.

Scope note: this is enough to give each person their own login and keep
their paper trading accounts separate on a personal machine or small
private deployment. It is NOT a hardened multi-tenant identity system -
there's no email verification, password reset flow, rate limiting on
login attempts, or MFA. Don't reuse a password here that matters
elsewhere, and don't expose the backend on the open internet without
putting a real auth layer (or at least HTTPS + a reverse proxy) in front
of it.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from database.db import get_connection

_PBKDF2_ITERATIONS = 600_000
_SESSION_LIFETIME = timedelta(days=7)
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class AuthError(ValueError):
    """Raised for bad credentials, taken usernames, weak passwords, etc.
    Deliberately a plain ValueError subclass so callers can show
    `str(exc)` directly to the user without leaking internals."""


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)


def register(username: str, password: str) -> str:
    username = username.strip()
    if not _USERNAME_RE.match(username):
        raise AuthError("Username must be 3-32 characters: letters, numbers, underscore, dot, or dash.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")

    with get_connection() as con:
        existing = con.execute("SELECT 1 FROM users WHERE username = ?", [username]).fetchone()
        if existing:
            raise AuthError(f"Username '{username}' is already taken.")

        salt = os.urandom(16)
        password_hash = _hash_password(password, salt)
        user_id = f"user_{uuid.uuid4().hex[:10]}"
        con.execute(
            "INSERT INTO users (user_id, username, password_hash, password_salt) VALUES (?, ?, ?, ?)",
            [user_id, username, password_hash.hex(), salt.hex()],
        )
    return user_id


def login(username: str, password: str) -> str:
    """Returns a bearer token on success. Raises AuthError on bad
    credentials - deliberately the same message for "no such user" and
    "wrong password" so login can't be used to enumerate usernames."""
    with get_connection() as con:
        row = con.execute(
            "SELECT user_id, password_hash, password_salt FROM users WHERE username = ?", [username.strip()]
        ).fetchone()
        if row is None:
            raise AuthError("Incorrect username or password.")

        user_id, stored_hash_hex, salt_hex = row
        computed_hash = _hash_password(password, bytes.fromhex(salt_hex))
        if not hmac.compare_digest(computed_hash.hex(), stored_hash_hex):
            raise AuthError("Incorrect username or password.")

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + _SESSION_LIFETIME
        con.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)", [token, user_id, expires_at])
    return token


def verify_token(token: str) -> str | None:
    """Returns the user_id for a valid, unexpired token, else None."""
    if not token:
        return None
    with get_connection(read_only=True) as con:
        row = con.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token = ?", [token]
        ).fetchone()
    if row is None:
        return None
    user_id, expires_at = row
    if datetime.now(timezone.utc).replace(tzinfo=None) > expires_at:
        return None
    return user_id


def logout(token: str) -> None:
    with get_connection() as con:
        con.execute("DELETE FROM sessions WHERE token = ?", [token])


def get_username(user_id: str) -> str | None:
    with get_connection(read_only=True) as con:
        row = con.execute("SELECT username FROM users WHERE user_id = ?", [user_id]).fetchone()
    return row[0] if row else None


def get_user_info(user_id: str) -> dict | None:
    with get_connection(read_only=True) as con:
        row = con.execute(
            "SELECT user_id, username, created_at FROM users WHERE user_id = ?", [user_id]
        ).fetchone()
    if row is None:
        return None
    return {"user_id": row[0], "username": row[1], "created_at": row[2]}
