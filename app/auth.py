import secrets
from datetime import datetime, timedelta
from typing import Optional

import requests
from itsdangerous import URLSafeTimedSerializer

from app.config import settings
from app.database import get_db


def generate_state() -> str:
    """Generate a random state parameter for OAuth"""
    return secrets.token_urlsafe(32)


def get_orcid_auth_url(state: str) -> str:
    """Get ORCID authorization URL"""
    params = {
        "client_id": settings.orcid_client_id,
        "response_type": "code",
        "scope": "/authenticate",
        "redirect_uri": settings.orcid_redirect_uri,
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{settings.orcid_auth_url}?{query}"


def exchange_code_for_token(code: str) -> dict:
    """Exchange authorization code for access token"""
    data = {
        "client_id": settings.orcid_client_id,
        "client_secret": settings.orcid_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.orcid_redirect_uri,
    }
    headers = {"Accept": "application/json"}

    response = requests.post(settings.orcid_token_url, data=data, headers=headers)
    response.raise_for_status()
    return response.json()


def get_orcid_profile(orcid_id: str, access_token: str) -> dict:
    """Fetch ORCID profile information"""
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    url = f"{settings.orcid_api_url}/v3.0/{orcid_id}/person"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def create_or_update_user(orcid_id: str, name: Optional[str] = None, email: Optional[str] = None) -> int:
    """Create or update user in database"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if user exists
        cursor.execute("SELECT id FROM users WHERE orcid_id = ?", (orcid_id,))
        result = cursor.fetchone()

        now = datetime.utcnow()

        if result:
            # Update existing user
            user_id = result["id"]
            cursor.execute(
                "UPDATE users SET name = ?, email = ?, last_login = ? WHERE id = ?",
                (name, email, now, user_id)
            )
        else:
            # Create new user
            cursor.execute(
                "INSERT INTO users (orcid_id, name, email, last_login) VALUES (?, ?, ?, ?)",
                (orcid_id, name, email, now)
            )
            user_id = cursor.lastrowid

        return user_id


def create_session(user_id: int) -> str:
    """Create a new session for user"""
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=7)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_id, user_id, expires_at)
        )

    return session_id


def get_session_user(session_id: str) -> Optional[dict]:
    """Get user from session ID"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Get session and check expiry
        cursor.execute(
            """
            SELECT s.user_id, s.expires_at, u.orcid_id, u.name, u.email
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.id = ?
            """,
            (session_id,)
        )
        result = cursor.fetchone()

        if not result:
            return None

        # Check if session expired
        expires_at = datetime.fromisoformat(result["expires_at"])
        if expires_at < datetime.utcnow():
            # Delete expired session
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return None

        return dict(result)


def delete_session(session_id: str):
    """Delete a session"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def cleanup_expired_sessions():
    """Remove expired sessions from database"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.utcnow(),))
