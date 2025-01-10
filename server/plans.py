from typing import Literal


PLANS = Literal["free", "premium"]

PLAN_LIMITS: dict[PLANS, int] = {
    "free": 10,  # Unauthenticated or free tier
    "premium": 200,  # Premium tier
}


PLAN_FEATURES: dict[PLANS, dict[str, int | list[str]]] = {
    "free": {
        "price": 0,
        "features": [
            f"Up to {format(PLAN_LIMITS['free'], ',')} API calls per day",
            "Basic features",
            "Community support",
            "Standard response time",
        ],
    },
    "premium": {
        "price": 29,
        "features": [
            f"Up to {format(PLAN_LIMITS['premium'], ',')} API calls per day",
            "Advanced features",
            "Priority support",
            "Custom configurations",
            "Usage analytics",
        ],
    },
}
