from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from fastapi.responses import RedirectResponse

from app.auth import (
    create_or_update_user,
    create_session,
    delete_session,
    exchange_code_for_token,
    generate_state,
    get_orcid_auth_url,
    get_orcid_profile,
    get_session_user,
)
from app.models import AuthResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["authentication"])

# In-memory state storage (in production, use Redis or database)
_oauth_states = {}


@router.get("/login")
async def login():
    """Redirect to ORCID OAuth authorization page"""
    state = generate_state()
    _oauth_states[state] = True  # Mark state as valid

    auth_url = get_orcid_auth_url(state)
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def callback(code: str, state: str, response: Response):
    """Handle ORCID OAuth callback"""
    # Verify state parameter (CSRF protection)
    if state not in _oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter"
        )

    # Remove used state
    del _oauth_states[state]

    try:
        # Exchange code for token
        token_data = exchange_code_for_token(code)
        orcid_id = token_data.get("orcid")
        access_token = token_data.get("access_token")

        if not orcid_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No ORCID iD in response"
            )

        # Get user profile (optional - to get name and email)
        try:
            profile = get_orcid_profile(orcid_id, access_token)
            name = profile.get("name", {}).get("credit-name", {}).get("value")
            # Email might not be available depending on user privacy settings
            email = None
        except Exception:
            name = None
            email = None

        # Create or update user in database
        user_id = create_or_update_user(orcid_id, name, email)

        # Create session
        session_id = create_session(user_id)

        # Set session cookie
        response = RedirectResponse(url="/submit.html", status_code=302)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=7 * 24 * 60 * 60,  # 7 days
            samesite="lax"
        )

        return response

    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error communicating with ORCID: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication error: {str(e)}"
        )


@router.post("/logout")
async def logout(response: Response, session_id: Optional[str] = Cookie(None)):
    """Logout user and clear session"""
    if session_id:
        delete_session(session_id)

    response = Response(status_code=200)
    response.delete_cookie("session_id")
    return {"status": "success", "message": "Logged out successfully"}


@router.get("/me", response_model=AuthResponse)
async def get_current_user_info(session_id: Optional[str] = Cookie(None)):
    """Get current authenticated user information"""
    if not session_id:
        return AuthResponse(authenticated=False)

    user = get_session_user(session_id)
    if not user:
        return AuthResponse(authenticated=False)

    return AuthResponse(
        authenticated=True,
        user=UserInfo(
            orcid_id=user["orcid_id"],
            name=user.get("name"),
            email=user.get("email")
        )
    )


# Import requests for the callback function
import requests
