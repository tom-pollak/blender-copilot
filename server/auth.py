import os
import secrets
from time import time
from functools import wraps

from loguru import logger
from fasthtml.oauth import OAuth, GoogleAppClient
from fasthtml.common import RedirectResponse, Request, Response

from .users import create_or_update_user, get_user

def basic_auth(f):
    "Super basic auth for testing purposes"
    password = "1234"
    @wraps(f)
    async def wrapper(request: Request, *args, **kwargs):
        token = request.headers.get("Authorization")
        if token != f"Bearer {password}":
            return Response("Not Authorized",
                            status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
        return await f(request, *args, **kwargs)

    return wrapper



# Create OAuth client
client = GoogleAppClient(
    os.getenv("GOOGLE_CLIENT_ID"),
    os.getenv("GOOGLE_CLIENT_SECRET")
)

class Auth(OAuth):
    def get_auth(self, info, ident, session, state):
        """Called after successful OAuth login to handle user authentication"""
        logger.debug(f"Successfully authenticated user {ident}")
        if info.get('email_verified'):
            # Get tokens from OAuth response
            tokens = self.cli.parse_response(info.get('code')) # type: ignore
            access_token = tokens['access_token']
            refresh_token = tokens.get('refresh_token')
            # Google tokens typically expire in 1 hour
            token_expiry = time() + 3600

            user = create_or_update_user(
                ident=ident,
                email=info.get('email'),
                name=info.get('name'),
                refresh_token=refresh_token
            )

            # Store access token in session
            session['access_token'] = access_token
            session['user_id'] = user.id
            session['token_expiry'] = token_expiry

            return_url = state.get('return_to', '/') if state else '/'
            logger.debug(f"Redirecting to {return_url}")
            return RedirectResponse(return_url, status_code=303)
        return False

def user_authenticated(f):
    """Decorator to require user authentication for a route"""
    @wraps(f)
    async def wrapper(request, *args, **kwargs):
        # Get auth info from session
        user_id = request.session.get('user_id')
        access_token = request.session.get('access_token')
        token_expiry = request.session.get('token_expiry')

        if not user_id or not access_token:
            return _redirect_to_login(request)

        # Check local -- Google client also checks expiry
        if not token_expiry or time() > token_expiry:
            logger.debug("Token expired locally")
            request.session.clear()
            return _redirect_to_login(request)

        # Verify token with Google
        try:
            user_info = await client.get_info(access_token) # type: ignore
            if user_info.get('sub') != user_id:
                # Token belongs to different user - possible session forgery
                logger.warning(f"Token user mismatch: {user_info.get('sub')} != {user_id}")
                request.session.clear()
                return _redirect_to_login(request)

            # Valid -- add user to request
            logger.debug(f"User authenticated: {user_id}")
            user = get_user(user_id)
            request.scope['user'] = user

        except Exception as e:
            # Token invalid/expired or user not found
            logger.error(f"Auth error: {str(e)}")
            request.session.clear()
            return _redirect_to_login(request)

        return await f(request, *args, **kwargs)

    return wrapper

def _redirect_to_login(request):
    """Helper function to generate login redirect with state"""
    csrf_token = secrets.token_urlsafe()
    request.session['csrf_token'] = csrf_token

    state = {
        'return_to': str(request.url),
        'csrf_token': csrf_token
    }
    logger.debug(f"Redirecting to login with state: {state}")
    return RedirectResponse(
        f'/login?state={state}',
        status_code=303
    )

def verify_csrf_token(request):
    """Verify CSRF token in request matches session token"""
    session_token = request.session.get('csrf_token')
    request_token = request.query_params.get('csrf_token')

    if not session_token or not request_token:
        return False

    # Use constant time comparison to prevent timing attacks
    return secrets.compare_digest(session_token, request_token)

def init_auth(app):
    """Initialize authentication for the app"""
    # Create OAuth handler
    oauth = Auth(app, client)

    @app.get('/login')
    def login(request):
        # Get state from query params
        state = request.query_params.get('state', {})

        # Generate login link with state
        login_url = oauth.login_link(
            request,
            state=state
        )
        return f'<a href="{login_url}">Login with Google</a>'

    @app.get('/logout')
    def logout(session):
        session.clear()
        return RedirectResponse('/', status_code=303)

    return oauth
