from typing import Any, Literal


PlansT = Literal["free", "premium"]

PLANS: dict[PlansT, dict[str, Any]] = {
    "free": {
        "price": 0.0,
        "limit": 10,
        "features": [
            "Up to 10 API calls per day",
            "Basic features",
            "Community support",
            "Standard response time",
        ],
    },
    "premium": {
        "price": 12.99,
        "limit": 200,
        "features": [
            "Up to 200 API calls per day",
            "Advanced features",
            "Priority support",
            "Custom configurations",
            "Usage analytics",
        ],
    },
}
