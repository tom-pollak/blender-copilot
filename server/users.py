from typing import Any
from fasthtml.common import database
from datetime import datetime

# Initialize database
db = database('data/users.db')
users = db.t.users

# Create users table if it doesn't exist
if users not in db.t:
    users.create(dict(
        id=str,          # Google's user ID
        email=str,
        name=str,
        created_at=str,  # ISO format timestamp
        last_login=str,  # ISO format timestamp
        api_calls=int,   # Track API usage
        refresh_token=str,  # Store OAuth refresh token instead of our session token
    ), pk='id')

# Create dataclass for type hints and easier access
User = users.dataclass()

def create_or_update_user(ident: str, email: str, name: str, refresh_token: str) -> User:
    """Create a new user or update existing user's info"""
    now = datetime.now().isoformat()

    user_data: dict[str, Any] = {
        'id': ident,
        'email': email,
        'name': name,
        'last_login': now,
        'refresh_token': refresh_token
    }

    try:
        users.update(user_data, ident)
    except Exception:
        # user doesn't exist, create new user
        user_data['created_at'] = now
        user_data['api_calls'] = 0
        users.insert(user_data)

    return users[ident]

def increment_api_calls(user_id: str) -> None:
    """Increment the API call counter for a user"""
    user = users[user_id]
    user.api_calls += 1
    users.update(user)

def get_user(user_id: str) -> User:
    """Get user by ID"""
    return users[user_id]
