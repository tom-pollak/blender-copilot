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
        logger.debug(f"=== Successfully authenticated user {ident} ===")
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

        create_or_update_user(
            ident=ident,
            email=info.get("email"),
            name=info.get("name"),
        )

        return RedirectResponse("/profile", status_code=303)

def verify_csrf_token(request):
    """Verify CSRF token in request matches session token"""
    session_token = request.session.get("csrf_token")
    request_token = request.query_params.get("csrf_token")

    logger.debug("=== Verifying CSRF token ===")

    if not session_token or not request_token:
        logger.debug("=== CSRF token not found ===")
        return False

    logger.debug(f"Session token: {session_token}")
    logger.debug(f"Request token: {request_token}")
    logger.debug(f"Comparison: {secrets.compare_digest(session_token, request_token)}")

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
    def login(req):
        print("Login endpoint called")

        # Redirect to profile if logged in
        if req.session.get('auth'):
            return RedirectResponse("/profile", status_code=303)

        state = req.query_params.get("state", {})
        login_url = oauth.login_link(req, state=state)
        return RedirectResponse(login_url, status_code=303)
        # return A("Login with Google", href=login_url)

    @app.get("/logout")
    def logout(session):
        print("Logout endpoint called")
        session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/whoami")
    def whoami(req):
        """Debug endpoint to check auth status"""
        # localhost route only
        if not url_match(req.url, (r'^(localhost|127\.0\.0\.1)(:\d+)?$',)):
            raise HTTPException(status_code=404)

        user = get_user(req)
        user_data = asdict(user) if user else None

        logger.debug("=== Whoami called ===")
        logger.debug(f"Session:\n{req.session}")
        logger.debug(f"User:\n{user}")

        return JSONResponse(
            {
                "session": dict(req.session),
                "user": user_data
            }
        )

    return oauth
