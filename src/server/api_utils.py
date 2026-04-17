from loguru import logger
from datetime import date, datetime
from functools import wraps
from fasthtml.common import *

from .plans import PLANS
from .db import User, get_user_by_api_token, IPUsage, ip_usage_tbl, user_tbl

def check_api_limit(data: User | IPUsage, limit: int) -> bool:
    """Check if API calls are within limit"""
    today = date.today().isoformat()
    if data.last_call_date != today:
        return True

    return data.daily_calls < limit

def increment_api_calls(data: User | IPUsage, tbl) -> None:
    """Increment API calls and update last call date"""
    today = date.today().isoformat()
    now = datetime.now().isoformat()
    if data.last_call_date != today:
        data.daily_calls = 0
        logger.debug(f"Resetting daily calls for {data}")

    logger.debug(f"Incrementing API calls for {data}")
    if hasattr(data, "api_calls"):
        data.api_calls += 1  # type: ignore
    data.daily_calls += 1
    data.last_call_date = today
    data.last_call_time = now

    tbl.update(data)  # update db

def rate_limited(f):
    """Decorator to check rate limit and increment API calls if allowed"""
    @wraps(f)
    async def wrapper(req: Request, *args: Any, **kwargs: Any):
        err_resp = Response(
            "Daily API limit exceeded. Try again tomorrow or upgrade your plan.",
            status_code=429,
        )

        # Track user/IP data for incrementing later
        user_data = None
        user_table = None

        token = req.headers.get("Authorization")
        logger.debug(f"Requested with token: {token}")
        if token:
            token = token.removeprefix("Bearer ")
            user = get_user_by_api_token(token)
            logger.debug(f"User: {user}")
            if not user or not check_api_limit(user, PLANS[user.plan]["limit"]):
                return err_resp
            user_data = user
            user_table = user_tbl
        # Anonymous users -- no IP
        elif not req.client:
            logger.debug("Anonymous user -- no IP")
            return err_resp
        # Anonymous users -- with IP
        else:
            client_ip = req.client.host
            logger.debug(f"Anonymous user -- with IP {client_ip}")
            free_limit = PLANS["free"]["limit"]
            try:
                ip_data = ip_usage_tbl[client_ip]
                logger.debug(f"IP {client_ip} found in db")
            except Exception:
                logger.debug(f"IP {client_ip} not found in db, inserting")
                today = date.today().isoformat()
                ip_usage_tbl.insert(
                    {"ip": client_ip, "daily_calls": 0, "last_call_date": today}
                )
                ip_data = ip_usage_tbl[client_ip]

            if not check_api_limit(ip_data, free_limit):
                return err_resp
            user_data = ip_data
            user_table = ip_usage_tbl

        response = await f(req, *args, **kwargs)

        # increment if the call was successful
        if response.status_code == 200:
            if not user_data: raise HTTPException(status_code=500, detail="User data not found")
            increment_api_calls(user_data, user_table)

        return response

    return wrapper
