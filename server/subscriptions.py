import os
import stripe

from loguru import logger
from fasthtml.common import *

from .app import rt, DOMAIN
from .db import User, user_tbl, get_authenticated_user
from .plans import PlansT

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
# WEBHOOK_ENDPOINT_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
WEBHOOK_ENDPOINT_SECRET = "whsec_681e078f76ca423a17f843921b1e8374341477f9222ba2018b8c3b04c60b7f0e"

PAYMENT_LINK_URL = "https://buy.stripe.com/test_cN2cQwgQ59iBguc3cc"


@rt("/manage-billing")
def manage_billing(req):
    user = get_authenticated_user(req)
    if not user.stripe_customer_id:
        return Titled("No subscription", P("You have no Stripe customer ID."))

    portal_session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"https://{DOMAIN}/profile",
    )
    return RedirectResponse(portal_session.url, status_code=303)


def _update_user(
    user: User,
    plan: PlansT,
    subscription_id: str | None,
    customer_id: str | None = None,
):
    """
    Update user with new plan, subscription ID, and customer ID.

    If customer_id is None, then it is not updated.
    """
    logger.info(f"Upgraded user {user.id} ({user.email}) to {plan}.")
    user.plan = plan
    user.stripe_subscription_id = subscription_id
    if customer_id:
        user.stripe_customer_id = customer_id
    user_tbl.update(user)


def sub_upgrade(session):
    """
    Payment Link or Checkout completed.
    - session["subscription"] => subscription ID
    - session["customer"]     => customer ID
    - session["customer_details"]["email"] => user email
    """
    logger.debug("Checkout session completed, upgrading user")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")
    if not subscription_id or not customer_id:
        logger.warning(
            "Session missing subscription or customer. Possibly one-time payment."
        )
        return

    email = session["customer_details"]["email"]
    user = user_tbl(
        where="email = :email",
        where_args=dict(email=email),
        limit=1,
    )
    if not user:
        logger.warning(f"No user found with {email=}, ignoring.")
        return

    _update_user(user[0], "premium", customer_id, subscription_id)


def sub_free(session):
    """
    The invoice or PaymentIntent failed. You can notify the user, mark them as 'past_due', etc.
    """
    logger.debug("Subscription free, updating user")
    sub_id = session.get("subscription")
    if not sub_id:
        logger.warning("Invoice missing subscription. Ignoring.")
        return

    user = user_tbl(
        where="stripe_subscription_id = :sid", where_args={"sid": sub_id}, limit=1
    )
    if not user:
        logger.warning(f"Subscription {sub_id} not found in DB.")
        return

    _update_user(user[0], "free", None)


@rt("/stripe/webhook", methods=["POST"])
async def stripe_webhook(req: Request):
    logger.debug("Stripe webhook called")
    # data = await req.json()
    data = await req.body()

    sig_header = req.headers.get("Stripe-Signature")
    if not sig_header:
        logger.warning("Missing Stripe-Signature header")
        raise HTTPException(400, "Missing Stripe-Signature header")

    try:
        event = stripe.Webhook.construct_event(
            data, sig_header, WEBHOOK_ENDPOINT_SECRET
        )
    except stripe.error.SignatureVerificationError:  # type: ignore
        logger.warning("Invalid signature")
        raise HTTPException(400, "Invalid signature")

    event_type = event["type"]
    obj = event["data"]["object"]
    logger.debug(f"Event type: {event_type}")
    # logger.debug(f"Object: {obj}")

    if event_type == "checkout.session.completed":
        sub_upgrade(obj)
    elif event_type in (
        "customer.subscription.deleted",
        "invoice.payment_failed",
        "invoice.payment_action_required",
    ):
        sub_free(obj)
    elif event_type == "customer.subscription.updated":
        # optional: handle updated subscription status
        pass
    # etc. as needed

    return JSONResponse({"status": "ok"})
