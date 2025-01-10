from __future__ import annotations
import os
from datetime import datetime
from loguru import logger

import stripe
from stripe.error import StripeError  # type: ignore
from fasthtml.common import *

from .users import User
from .app import rt, DOMAIN
from .users import user_tbl


stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

SUBSCRIPTION_PRICE_ID = "price_H5ggYwtDq4fbrJ"


@patch()
def get_stripe_customer_id(self: User) -> str:
    if self.stripe_customer_id:
        logger.info(
            f"Using existing Stripe customer {self.stripe_customer_id} for user {self.id}"
        )
        return self.stripe_customer_id

    try:
        customer = stripe.Customer.create(
            email=self.email,
            name=self.name,
            metadata={
                "user_id": self.id,
            },
        )
        self.stripe_customer_id = customer.id
    except StripeError as e:
        logger.error(f"Error creating Stripe customer for user {self.id}: {e}")
        raise e

    logger.info(f"Created Stripe customer {self.stripe_customer_id} for user {self.id}")
    user_tbl.update(self)
    return self.stripe_customer_id


@dataclass
class Subscription:
    id: str
    status: str
    current_period_end: datetime
    plan_name: str
    amount: int
    currency: str
    interval: str
    cancel_at_period_end: bool

    @classmethod
    def from_user(cls, user: User) -> Subscription | None:
        try:
            subscriptions = stripe.Subscription.list(
                customer=user.get_stripe_customer_id(),
                status="active",
                expand=["data.plan"],  # type: ignore
            )

            if not subscriptions.data:
                logger.info(
                    f"No active subscription found for customer {user.get_stripe_customer_id()}"
                )
                return None

            subscription = subscriptions.data[0]
            logger.info(
                f"Active subscription found for customer {user.get_stripe_customer_id()}: {subscription.id}"
            )
            return Subscription(
                id=subscription.id,
                status=subscription.status,
                current_period_end=datetime.fromtimestamp(
                    subscription.current_period_end
                ),
                plan_name=subscription.plan.nickname,
                amount=subscription.plan.amount / 100,
                currency=subscription.plan.currency,
                interval=subscription.plan.interval,
                cancel_at_period_end=subscription.cancel_at_period_end,
            )

        except StripeError as e:
            logger.error(f"Stripe error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            raise


@rt("/subscription/create")
def create_checkout_session(req, user: User):
    try:
        checkout_session = stripe.checkout.Session.create(
            customer=user.get_stripe_customer_id(),
            payment_method_types=["card"],
            line_items=[{
                "price": SUBSCRIPTION_PRICE_ID,
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"{DOMAIN}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{DOMAIN}/subscription/cancel",
        )
        assert checkout_session.url is not None
        return RedirectResponse(checkout_session.url, status_code=303)
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        return {"success": False, "error": str(e)}


@rt("/subscription/success")
def success(req):
    return "success"


@rt("/subscription/cancel")
def cancel_subscription(user: User):
    subscription = Subscription.from_user(user)
    if not subscription:
        return {"success": False, "error": "No active subscription found"}

    try:
        canceled_subscription = stripe.Subscription.modify(
            subscription.id, cancel_at_period_end=True
        )
        return {
            "success": True,
            "end_date": datetime.fromtimestamp(
                canceled_subscription.current_period_end
            ),
        }
    except StripeError as e:
        return {"success": False, "error": str(e)}

@rt("/webhook", methods=["POST"])
def webhook_received(req):
    payload = req.body.read()
    sig_header = req.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv("STRIPE_WEBHOOK_SECRET")
        )

        if event.type == "customer.subscription.updated":
            subscription = event.data.object
            # Handle subscription update

        elif event.type == "customer.subscription.deleted":
            subscription = event.data.object
            # Handle subscription cancellation

        elif event.type == "invoice.payment_failed":
            # Handle failed payment
            pass

        return {"success": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"success": False, "error": str(e)}

