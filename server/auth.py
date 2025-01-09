import os
import secrets
from time import time
from functools import wraps

from loguru import logger
from fasthtml.oauth import OAuth, GoogleAppClient
from fasthtml.common import *

from .users import create_or_update_user, get_user

__all__ = ["init_auth", "verify_csrf_token"]


def basic_auth(f):
    """Super basic auth for testing purposes"""
    password = "1234"

    @wraps(f)
    async def wrapper(request: Request, *args, **kwargs):
        token = request.headers.get("Authorization")
        if token != f"Bearer {password}":
            return Response(
                "Not Authorized",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await f(request, *args, **kwargs)

    return wrapper


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

        # # Get tokens from OAuth response
        tokens = self.cli.parse_response(  # type: ignore
            info.get("code"),
            redirect_uri=self.redir_path,  # type: ignore
        )
        # access_token = tokens["access_token"]
        # refresh_token = tokens.get("refresh_token")
        # # Google tokens typically expire in 1 hour
        # token_expiry = time() + 3600

        # user = create_or_update_user(
        #     ident=ident,
        #     email=info.get("email"),
        #     name=info.get("name"),
        #     refresh_token=refresh_token,
        # )

        # # Store access token in session
        # session["access_token"] = access_token
        # session["user_id"] = user.id
        # session["token_expiry"] = token_expiry

        logger.debug("Redirecting to redirect url")
        return self.redir_login(session)

    def check_invalid(self, req, session, auth):
        """Verify the current session is valid"""
        access_token = session.get("access_token")
        token_expiry = session.get("token_expiry")

        if not access_token or not token_expiry:
            return self.redir_login(session)

        # Check if token is expired locally
        if time() > token_expiry:
            logger.debug("Token expired locally")
            session.clear()
            return self.redir_login(session)

        try:
            # Verify token with Google
            user_info = self.cli.get_info(access_token)  # type: ignore
            if not user_info or not user_info.get("sub"):
                logger.warning("Invalid token response from Google")
                session.clear()
                return self.redir_login(session)

            # Add user to request scope
            req.scope["user"] = get_user(user_info["sub"])
            return False  # Valid token

        except Exception as e:
            logger.error(f"Token verification failed: {str(e)}")
            session.clear()
            return self.redir_login(session)


# class Auth(OAuth):
#     def get_auth(self, info, ident, session, state):
#         logger.debug(f"Successfully authenticated user {ident}")
#         if info.email_verified:
#             tokens = self.cli.parse_response(info.get("code"))  # type: ignore
#             access_token = tokens["access_token"]
#             refresh_token = tokens.get("refresh_token")

#             user = create_or_update_user(
#                 ident=ident,
#                 email=info.get("email"),
#                 name=info.get("name"),
#                 refresh_token=refresh_token,
#             )
#             session["user_id"] = user.id
#             logger.debug("Redirecting to return url")
#             return self.redir_login(session)
#         return False


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
        ],
    )

    @app.get("/login")
    def login(request):
        print("Login endpoint called")
        state = request.query_params.get("state", {})
        login_url = oauth.login_link(request, state=state)
        return A("Login with Google", href=login_url)

    @app.get("/logout")
    def logout(session):
        print("Logout endpoint called")
        session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/whoami")
    def whoami(request):
        """Debug endpoint to check auth status"""
        logger.debug("=== Whoami called ===")
        logger.debug(f"Session: {request.session}")
        logger.debug(f"User: {request.scope.get('user')}")
        return JSONResponse(
            {
                "authenticated": bool(request.scope.get("user", False)),
                "session": dict(request.session),
                "user": request.scope.get("user", False),
            }
        )

    return oauth
