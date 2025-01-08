from typing import Any
from fasthtml.common import database
from datetime import datetime, date
from fasthtml.common import Response
from functools import wraps
from fastapi import Request
from loguru import logger
# Add plan limits
PLAN_LIMITS = {
    'free': 20,      # Unauthenticated or free tier
    'basic': 100,    # Default authenticated tier
    'premium': 500   # Premium tier
}

# Initialize database
db = database('data/main.db')
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
        refresh_token=str,
        plan=str,        # User's plan type
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

def create_or_update_user(ident: str, email: str, name: str, refresh_token: str) -> User:
    """Create a new user or update existing user's info"""
    now = datetime.now().isoformat()
    today = date.today().isoformat()

    user_data = {
        "refresh_token": refresh_token,
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
            **user_data,
        })

    return users[ident]

def get_user(user_id: str) -> User:
    """Get user by ID"""
    return users[user_id]

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
        user = req.scope.get('user')

        # Authenticated users
        err_resp = Response(
            "Daily API limit exceeded. Try again tomorrow or upgrade your plan.",
            status_code=429
        )
        # Authenticated users
        if user:
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
