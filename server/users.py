import os
import secrets
from typing import Any
from functools import wraps
from datetime import datetime, date
from fasthtml.common import database, Response, Request
from loguru import logger
from pathlib import Path

__all__ = ["create_or_update_user", "get_user", "rate_limited"]

# Add plan limits
PLAN_LIMITS = {
    'free': 20,      # Unauthenticated or free tier
    'basic': 100,    # Default authenticated tier
    'premium': 500   # Premium tier
}

# Initialize database
db = database(Path(__file__).parent / "data" / "main.db")
users = db.t.users

# Add plan field to users table
if users not in db.t:
    users.create(dict(
        id=str,
        email=str,
        name=str,
        created_at=str,
        last_login=str,
        api_calls=int,   # Total API calls
        daily_calls=int, # Calls made today
        last_call_date=str,  # Date of last API call
        plan=str,        # User's plan type
        api_token=str,   # API token
    ), pk='id')

# Add IP tracking table
ip_usage = db.t.ip_usage
if ip_usage not in db.t:
    ip_usage.create(dict(
        ip=str,
        daily_calls=int,
        last_call_date=str,
    ), pk='ip')

User = users.dataclass()
IPUsage = ip_usage.dataclass()

def generate_api_token():
    return secrets.token_urlsafe(32)

def create_or_update_user(ident: str, email: str, name: str) -> User:
    """Create a new user or update existing user's info"""
    now = datetime.now().isoformat()
    today = date.today().isoformat()

    user_data = {
        "last_login": now,
    }

    try:
        logger.debug(f"Updating user {ident} in db")
        users.update(user_data, ident)
    except Exception:
        logger.debug(f"User {ident} not found in db, inserting")
        users.insert({
            'id': ident,
            'email': email,
            'name': name,
            'last_call_date': today,
            "created_at": now,
            "api_calls": 0,
            "daily_calls": 0,
            "plan": 'free',  # Default to free plan
            "api_token": generate_api_token(),
            **user_data,
        })

    return users[ident]

def get_user(user_id: str) -> User:
    """Get user by ID"""
    return users[user_id]

def get_user_by_api_token(api_token: str) -> User:
    """Get user by API token"""
    return users.selectone(api_token=api_token)

def increment_api_calls(data: User | IPUsage, limit: int) -> bool:
    """Increment API calls and update last call date"""
    DataTable = users if isinstance(data, User) else ip_usage
    logger.debug(f"Incrementing API calls for {DataTable}")

    today = date.today().isoformat()
    if data.last_call_date != today:
        data.daily_calls = 0
        logger.debug(f"Resetting daily calls for {data}")

    if data.daily_calls + 1 > limit:
        logger.debug(f"Daily limit exceeded for {data}")
        return False

    logger.debug(f"Incrementing API calls for {data}")
    data.api_calls += 1
    data.daily_calls += 1
    data.last_call_date = today

    DataTable.update(data) # update db
    return True

def rate_limited(f):
    """Decorator to check rate limit and increment API calls if allowed"""
    @wraps(f)
    async def wrapper(req: Request, *args: Any, **kwargs: Any):
        err_resp = Response(
            "Daily API limit exceeded. Try again tomorrow or upgrade your plan.",
            status_code=429
        )
        user_id = req.session.get('user_id')
        logger.debug(f"User ID: {user_id}")

        # I don't really want user id, I want to include a api token in the request that I can use to get the user
        # Authenticated users
        if user_id:
            user = get_user(user_id)
            if not increment_api_calls(user, PLAN_LIMITS[user.plan]):
                return err_resp
        # Anonymous users -- no IP
        elif not req.client:
            logger.debug("Anonymous user -- no IP")
            return err_resp
        # Anonymous users -- with IP
        else:
            client_ip = req.client.host
            logger.debug(f"Anonymous user -- with IP {client_ip}")
            free_limit = PLAN_LIMITS['free']
            try:
                ip_data = ip_usage[client_ip]
                logger.debug(f"IP {client_ip} found in db")
            except Exception:
                logger.debug(f"IP {client_ip} not found in db, inserting")
                today = date.today().isoformat()
                ip_usage.insert({
                    'ip': client_ip,
                    'daily_calls': 0,
                    'last_call_date': today
                })
            if not increment_api_calls(ip_data, free_limit):
                return err_resp
        return await f(req, *args, **kwargs)

    return wrapper
