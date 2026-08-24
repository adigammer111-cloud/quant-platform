from __future__ import annotations

import pytest

from auth import service as auth
from auth.service import AuthError


def test_register_and_login_roundtrip(temp_db):
    user_id = auth.register("alice", "correct-horse-battery")
    token = auth.login("alice", "correct-horse-battery")
    assert auth.verify_token(token) == user_id


def test_register_rejects_short_password(temp_db):
    with pytest.raises(AuthError):
        auth.register("bob", "short")


def test_register_rejects_invalid_username(temp_db):
    with pytest.raises(AuthError):
        auth.register("a b!", "longenoughpassword")


def test_register_rejects_duplicate_username(temp_db):
    auth.register("carol", "longenoughpassword")
    with pytest.raises(AuthError):
        auth.register("carol", "differentpassword123")


def test_login_wrong_password_fails(temp_db):
    auth.register("dave", "longenoughpassword")
    with pytest.raises(AuthError):
        auth.login("dave", "totallywrongpassword")


def test_login_unknown_username_fails(temp_db):
    with pytest.raises(AuthError):
        auth.login("nobody", "whatever12345")


def test_password_is_never_stored_in_plaintext(temp_db):
    from database.db import get_connection

    auth.register("erin", "supersecretpassword")
    with get_connection(read_only=True) as con:
        row = con.execute("SELECT password_hash FROM users WHERE username = 'erin'").fetchone()
    assert "supersecretpassword" not in row[0]


def test_invalid_token_returns_none(temp_db):
    assert auth.verify_token("not-a-real-token") is None
    assert auth.verify_token("") is None


def test_logout_invalidates_token(temp_db):
    auth.register("frank", "longenoughpassword")
    token = auth.login("frank", "longenoughpassword")
    assert auth.verify_token(token) is not None
    auth.logout(token)
    assert auth.verify_token(token) is None


def test_get_user_info_returns_profile(temp_db):
    user_id = auth.register("ivan", "longenoughpassword")
    info = auth.get_user_info(user_id)
    assert info["user_id"] == user_id
    assert info["username"] == "ivan"
    assert info["created_at"] is not None


def test_get_user_info_returns_none_for_unknown_user(temp_db):
    assert auth.get_user_info("not_a_real_user_id") is None


def test_two_users_get_different_ids(temp_db):
    id1 = auth.register("grace", "longenoughpassword")
    id2 = auth.register("heidi", "longenoughpassword")
    assert id1 != id2
