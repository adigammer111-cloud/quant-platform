"""Shared login/register gate. Any page that needs a signed-in user (Paper
Trading, Account) calls `require_login()` at the top of its render function
and returns early if it comes back False - the gate itself renders the
Log In / Create Account forms and stops the page from showing anything
else until session_state has a user_id.
"""
from __future__ import annotations

import streamlit as st

from app.components import error_banner, render_topbar
from auth import service as auth
from auth.service import AuthError


def require_login(page_title: str, subtitle: str) -> bool:
    if st.session_state.get("user_id"):
        return True

    render_topbar(page_title, subtitle)
    st.markdown('<div style="max-width:420px;">', unsafe_allow_html=True)
    tab_login, tab_register = st.tabs(["Log In", "Create Account"])

    with tab_login:
        with st.form("shared_login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log In", type="primary", width="stretch"):
                try:
                    token = auth.login(username, password)
                    st.session_state["user_id"] = auth.verify_token(token)
                    st.session_state["username"] = username.strip()
                    st.session_state["auth_token"] = token
                    st.rerun()
                except AuthError as exc:
                    error_banner(str(exc))

    with tab_register:
        with st.form("shared_register_form"):
            new_username = st.text_input("Choose a username", help="3-32 characters: letters, numbers, underscore, dot, dash.")
            new_password = st.text_input("Choose a password", type="password", help="At least 8 characters.")
            if st.form_submit_button("Create Account", width="stretch"):
                try:
                    auth.register(new_username, new_password)
                    token = auth.login(new_username, new_password)
                    st.session_state["user_id"] = auth.verify_token(token)
                    st.session_state["username"] = new_username.strip()
                    st.session_state["auth_token"] = token
                    st.rerun()
                except AuthError as exc:
                    error_banner(str(exc))

    st.markdown("</div>", unsafe_allow_html=True)
    st.caption(
        "Passwords are hashed (PBKDF2-HMAC-SHA256, salted) - never stored in plain text. "
        "This login is sized for personal/local use, not a hardened public deployment."
    )
    return False


def log_out() -> None:
    auth.logout(st.session_state.get("auth_token", ""))
    for key in ["user_id", "username", "auth_token"]:
        st.session_state.pop(key, None)
