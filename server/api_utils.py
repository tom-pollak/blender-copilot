from loguru import logger
from datetime import date, datetime
from functools import wraps
from fasthtml.common import *

from .plans import PLANS
from .db import User, get_user_by_api_token, IPUsage, ip_usage_tbl, user_tbl

def increment_api_calls(data: User | IPUsage, tbl, limit: int) -> bool:
    """Increment API calls and update last call date"""
    today = date.today().isoformat()
    now = datetime.now().isoformat()
    if data.last_call_date != today:
        data.daily_calls = 0
        logger.debug(f"Resetting daily calls for {data}")

    if data.daily_calls + 1 > limit:
        logger.debug(f"Daily limit exceeded for {data}")
        return False

    logger.debug(f"Incrementing API calls for {data}")
    if hasattr(data, "api_calls"):
        data.api_calls += 1  # type: ignore
    data.daily_calls += 1
    data.last_call_date = today
    data.last_call_time = now

    tbl.update(data)  # update db
    return True


def rate_limited(f):
    """Decorator to check rate limit and increment API calls if allowed"""

    @wraps(f)
    async def wrapper(req: Request, *args: Any, **kwargs: Any):
        err_resp = Response(
            "Daily API limit exceeded. Try again tomorrow or upgrade your plan.",
            status_code=429,
        )
        token = req.headers.get("Authorization")
        logger.debug(f"Requested with token: {token}")
        if token:
            token = token.removeprefix("Bearer ")
            user = get_user_by_api_token(token)
            logger.debug(f"User: {user}")
            if not user or not increment_api_calls(
                user, user_tbl, PLANS[user.plan]["limit"]
            ):
                return err_resp
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
            if not increment_api_calls(ip_data, ip_usage_tbl, free_limit):
                return err_resp
        return await f(req, *args, **kwargs)

    return wrapper
