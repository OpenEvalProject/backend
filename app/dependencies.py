from typing import Optional

from fastapi import Cookie, HTTPException, status

from app.auth import get_session_user


async def get_current_user(session_id: Optional[str] = Cookie(None)) -> dict:
    """Dependency to get current authenticated user"""
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please login to submit papers."
        )

    user = get_session_user(session_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please login again."
        )

    return user


async def get_current_user_optional(session_id: Optional[str] = Cookie(None)) -> Optional[dict]:
    """Dependency to optionally get current user (for public endpoints)"""
    if not session_id:
        return None

    return get_session_user(session_id)
