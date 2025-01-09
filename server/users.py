from dataclasses import dataclass
import secrets
from datetime import datetime, date
from fasthtml.common import database
from loguru import logger
from pathlib import Path
from fastlite import NotFoundError

db = database(Path(__file__).parent / "data" / "main.db")


@dataclass
class User:
    id: str
    email: str
    name: str
    created_at: str
    last_login: str
    api_calls: int  # Total API calls
    daily_calls: int  # Calls made today
    last_call_date: str  # Date of last API call
    plan: str  # User's plan type
    api_token: str  # API token


@dataclass
class IPUsage:
    ip: str
    daily_calls: int
    last_call_date: str


# Create if don't exist
user_tbl = db.t.user
if user_tbl not in db.t:
    db.create(User, pk="id")

ip_usage_tbl = db.t.ip_usage
if ip_usage_tbl not in db.t:
    db.create(IPUsage, pk="ip")

# return dataclass
user_tbl.dataclass()
ip_usage_tbl.dataclass()


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
        user_tbl.update(user_data, ident)
    except Exception:
        logger.debug(f"User {ident} not found in db, inserting")
        user_tbl.insert(
            {
                "id": ident,
                "email": email,
                "name": name,
                "last_call_date": today,
                "created_at": now,
                "api_calls": 0,
                "daily_calls": 0,
                "plan": "free",  # Default to free plan
                "api_token": generate_api_token(),
                **user_data,
            }
        )

    return user_tbl[ident]


def get_user(user_id: str) -> User | None:
    """Get user by ID"""
    try:
        return user_tbl.get(user_id)
    except NotFoundError:
        return None


def get_user_by_api_token(api_token: str) -> User | None:
    """Get user by API token"""
    res = user_tbl(
        where=f"{user_tbl.c.api_token} = :api_token",
        where_args=dict(api_token=api_token),
        limit=1,
    )
    if res:
        return res[0]
    return None
