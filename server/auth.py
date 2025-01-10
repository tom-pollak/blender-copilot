import os
import secrets

from loguru import logger
from fasthtml.oauth import OAuth, GoogleAppClient, url_match
from fasthtml.common import *

from .users import create_or_update_user, get_user

__all__ = ["init_auth", "verify_csrf_token"]


# Create OAuth client
client = GoogleAppClient(
    os.getenv("GOOGLE_CLIENT_ID"), os.getenv("GOOGLE_CLIENT_SECRET")
)


class Auth(OAuth):
    def get_auth(self, info, ident, session, state):
        """Called after successful OAuth login to handle user authentication"""
        logger.debug(f"Successfully authenticated user {ident}")
        logger.debug(f"Info: {info}")
        logger.debug(f"Ident: {ident}")
        logger.debug(f"Session: {session}")
        logger.debug(f"State: {state}")

        if not info.get("email_verified", False):
            return False

        email = info.get("email")
        name = info.get("name")
        if not email or not name:
            return False

        user = create_or_update_user(
            ident=ident,
            email=info.get("email"),
            name=info.get("name"),
        )
        session["user_id"] = user.id

        logger.debug("Redirecting to profile")
        return RedirectResponse("/profile", status_code=303)

def verify_csrf_token(request):
    """Verify CSRF token in request matches session token"""
    session_token = request.session.get("csrf_token")
    request_token = request.query_params.get("csrf_token")

    if not session_token or not request_token:
        return False

    # Use constant time comparison to prevent timing attacks
    return secrets.compare_digest(session_token, request_token)


def init_auth(app):
    """Initialize authentication for the app"""
    oauth = Auth(
        app,
        client,
        skip=[
            r"/favicon\.ico",
            r"/static/.*",
            r".*\.css",
            "/login",
            "/",
            "/redirect",
            "/whoami",
            r"/infer/.*"
        ],
    )

    @app.get("/login")
    def login(request):
        print("Login endpoint called")

        # Redirect to profile if logged in
        if request.session.get('auth'):
            return RedirectResponse("/profile", status_code=303)

        state = request.query_params.get("state", {})
        login_url = oauth.login_link(request, state=state)
        return RedirectResponse(login_url, status_code=303)
        # return A("Login with Google", href=login_url)

    @app.get("/logout")
    def logout(session):
        print("Logout endpoint called")
        session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/whoami")
    def whoami(request):
        """Debug endpoint to check auth status"""
        # localhost route only
        if not url_match(request.url, (r'^(localhost|127\.0\.0\.1)(:\d+)?$',)):
            raise HTTPException(status_code=404)

        logger.debug("=== Whoami called ===")
        logger.debug(f"Session: {request.session}")
        user_id = request.session.get('user_id')
        user = get_user(user_id)
        user_data = asdict(user) if user else None
        return JSONResponse(
            {
                "session": dict(request.session),
                "user": user_data
            }
        )

    return oauth
