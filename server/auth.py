import os
import secrets
from time import time
from functools import wraps

from loguru import logger
from fasthtml.oauth import OAuth, GoogleAppClient
from fasthtml.common import RedirectResponse, Request, Response

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
        if info.get("email_verified"):
            # Get tokens from OAuth response
            tokens = self.cli.parse_response(info.get("code"))  # type: ignore
            access_token = tokens["access_token"]
            refresh_token = tokens.get("refresh_token")
            # Google tokens typically expire in 1 hour
            token_expiry = time() + 3600

            user = create_or_update_user(
                ident=ident,
                email=info.get("email"),
                name=info.get("name"),
                refresh_token=refresh_token,
            )

            # Store access token in session
            session["access_token"] = access_token
            session["user_id"] = user.id
            session["token_expiry"] = token_expiry

            return_url = state.get("return_to", "/") if state else "/"
            logger.debug(f"Redirecting to {return_url}")
            return RedirectResponse(return_url, status_code=303)
        return False

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
            user_info = self.cli.get_info(access_token)
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
    # Create OAuth handler with skip paths
    oauth = Auth(app, client, skip=[
        r'/favicon\.ico',
        r'/static/.*',
        r'.*\.css',
        '/login',
        '/home'  # Skip auth check for home route
    ])

    @app.get("/login")
    def login(request):
        # Get state from query params
        state = request.query_params.get("state", {})

        # Generate login link with state
        login_url = oauth.login_link(request, state=state)
        return f'<a href="{login_url}">Login with Google</a>'

    @app.get("/logout")
    def logout(session):
        session.clear()
        return RedirectResponse("/", status_code=303)

    return oauth
