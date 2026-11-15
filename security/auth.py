
"""TwinFlame Google OIDC authentication and operator authorization."""

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

COOKIE_NAME = "twinflame_auth"
SESSION_SECONDS = 8 * 60 * 60
oauth = OAuth()


def _production():
    return os.getenv("APP_ENV", "development") == "production"


def _frontend():
    return os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/")


def _allowed_emails():
    return {
        email.strip().lower()
        for email in os.getenv("GOOGLE_OPERATOR_EMAILS", "").split(",")
        if email.strip()
    }


def _database():
    path = Path(
        os.getenv("AUTH_DB_PATH", str(ROOT / "database" / "auth_sessions.sqlite3"))
    )
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            google_sub TEXT NOT NULL,
            email TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    return connection


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_session(google_sub, email):
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + SESSION_SECONDS

    with _database() as db:
        db.execute(
            """
            INSERT INTO auth_sessions
            (token_hash, google_sub, email, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (_token_hash(token), google_sub, email, expires),
        )

    return token


def _current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)

    if not token:
        return None

    with _database() as db:
        row = db.execute(
            """
            SELECT google_sub, email
            FROM auth_sessions
            WHERE token_hash = ? AND expires_at > ?
            """,
            (_token_hash(token), int(time.time())),
        ).fetchone()

    if not row:
        return None

    return {"sub": row[0], "email": row[1]}


def _check_origin(request: Request):
    # Require the exact trusted frontend origin for state-changing requests.
    if request.headers.get("origin") != _frontend():
        raise HTTPException(status_code=403, detail="Invalid request origin")


def require_operator(request: Request):
    user = _current_user(request)

    if user is None:
        raise HTTPException(status_code=401, detail="Login required")

    if user["email"].lower() not in _allowed_emails():
        raise HTTPException(status_code=403, detail="Operator access required")

    _check_origin(request)
    return user


def configure_auth(app: FastAPI):
    session_secret = os.getenv("SESSION_SECRET_KEY")
    google_id = os.getenv("GOOGLE_CLIENT_ID")
    google_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if session_secret:
        app.add_middleware(
            SessionMiddleware,
            secret_key=session_secret,
            session_cookie="twinflame_oidc_state",
            max_age=600,
            same_site="lax",
            https_only=_production(),
        )

    if google_id and google_secret:
        oauth.register(
            name="google",
            client_id=google_id,
            client_secret=google_secret,
            server_metadata_url=(
                "https://accounts.google.com/.well-known/openid-configuration"
            ),
            client_kwargs={"scope": "openid email profile"},
        )

    @app.get("/auth/google/login")
    async def google_login(request: Request):
        if not (session_secret and google_id and google_secret):
            raise HTTPException(503, "Google login is not configured")

        redirect_uri = os.getenv(
            "GOOGLE_REDIRECT_URI",
            "http://localhost:8000/auth/google/callback",
        )

        return await oauth.google.authorize_redirect(
            request, redirect_uri
        )

    @app.get("/auth/google/callback")
    async def google_callback(request: Request):
        if not (session_secret and google_id and google_secret):
            raise HTTPException(503, "Google login is not configured")

        try:
            token = await oauth.google.authorize_access_token(request)
            userinfo = token["userinfo"]
        except Exception:
            raise HTTPException(401, "Google authentication failed") from None

        if not userinfo.get("email_verified"):
            raise HTTPException(403, "Verified Google email required")

        google_sub = str(userinfo["sub"])
        email = str(userinfo["email"]).lower()

        session_token = _create_session(google_sub, email)

        response = RedirectResponse(_frontend(), status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            session_token,
            httponly=True,
            secure=_production(),
            samesite="lax",
            max_age=SESSION_SECONDS,
            path="/",
        )

        return response

    @app.get("/auth/me")
    def auth_me(request: Request):
        user = _current_user(request)

        if not user:
            return {"authenticated": False, "role": "visitor"}

        role = (
            "operator"
            if user["email"].lower() in _allowed_emails()
            else "viewer"
        )

        return {
            "authenticated": True,
            "email": user["email"],
            "role": role,
        }

    @app.post("/auth/logout")
    def logout(request: Request):
        _check_origin(request)

        token = request.cookies.get(COOKIE_NAME)
        if token:
            with _database() as db:
                db.execute(
                    "DELETE FROM auth_sessions WHERE token_hash = ?",
                    (_token_hash(token),),
                )

        response = RedirectResponse(_frontend(), status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/")
        return response
