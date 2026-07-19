"""
Stripe self-serve billing — checkout, customer portal, and webhook sync.

Requires three env vars before any of this actually works:
  STRIPE_SECRET_KEY       — Stripe API secret key
  STRIPE_PRICE_ID_PRO     — recurring Price ID for the Pro plan
  STRIPE_WEBHOOK_SECRET   — from registering the webhook endpoint in the
                            Stripe dashboard, pointed at
                            POST /api/webhooks/stripe on this service
"""
import logging
import os

logger = logging.getLogger("culturix.billing")


def _get_stripe():
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def create_checkout_session(user_id: str, email: str, base_url: str) -> str:
    """Creates (or reuses) a Stripe Customer and a Checkout Session for the
    Pro subscription. Returns the hosted checkout URL to redirect to."""
    stripe = _get_stripe()
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile
    import uuid as _uuid

    session = SessionLocal()
    try:
        profile = session.query(UserProfile).filter_by(user_id=_uuid.UUID(user_id)).first()
        customer_id = profile.stripe_customer_id if profile else None

        if not customer_id:
            customer = stripe.Customer.create(email=email, metadata={"user_id": user_id})
            customer_id = customer.id
            if profile:
                profile.stripe_customer_id = customer_id
                session.commit()

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            client_reference_id=user_id,
            mode="subscription",
            line_items=[{"price": os.environ["STRIPE_PRICE_ID_PRO"], "quantity": 1}],
            success_url=f"{base_url}/settings?checkout=success",
            cancel_url=f"{base_url}/settings?checkout=cancelled",
        )
        return checkout_session.url
    finally:
        session.close()


def create_portal_session(user_id: str, base_url: str) -> str:
    """Returns a Stripe-hosted billing portal URL for an existing customer
    to manage/cancel their subscription. Raises if they have no customer yet."""
    stripe = _get_stripe()
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile
    import uuid as _uuid

    session = SessionLocal()
    try:
        profile = session.query(UserProfile).filter_by(user_id=_uuid.UUID(user_id)).first()
        if not profile or not profile.stripe_customer_id:
            raise ValueError("No Stripe customer on file for this user")

        portal_session = stripe.billing_portal.Session.create(
            customer=profile.stripe_customer_id,
            return_url=f"{base_url}/settings",
        )
        return portal_session.url
    finally:
        session.close()


def _set_plan_by_customer_id(customer_id: str, plan: str, subscription_id: str = None):
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile

    session = SessionLocal()
    try:
        profile = session.query(UserProfile).filter_by(stripe_customer_id=customer_id).first()
        if not profile:
            logger.warning("Webhook for unknown Stripe customer %s — no matching user_profile", customer_id)
            return
        profile.plan = plan
        if subscription_id:
            profile.stripe_subscription_id = subscription_id
        session.commit()
        logger.info("Set plan=%s for user %s (customer %s)", plan, profile.user_id, customer_id)
    finally:
        session.close()


def handle_webhook_event(payload: bytes, sig_header: str) -> dict:
    """Verifies the Stripe signature and syncs user_profiles.plan accordingly.
    Returns a small dict describing what happened (for logging in the route)."""
    stripe = _get_stripe()
    event = stripe.Webhook.construct_event(
        payload, sig_header, os.environ["STRIPE_WEBHOOK_SECRET"]
    )

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        user_id = obj.get("client_reference_id")
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")
        if user_id and customer_id:
            from app.db import SessionLocal
            from app.models.user_profile import UserProfile
            import uuid as _uuid

            session = SessionLocal()
            try:
                profile = session.query(UserProfile).filter_by(user_id=_uuid.UUID(user_id)).first()
                if profile:
                    profile.plan = "pro"
                    profile.stripe_customer_id = customer_id
                    profile.stripe_subscription_id = subscription_id
                    session.commit()
            finally:
                session.close()
        return {"event": event_type, "user_id": user_id}

    elif event_type == "customer.subscription.updated":
        customer_id = obj.get("customer")
        status = obj.get("status")
        new_plan = "pro" if status in ("active", "trialing") else "free"
        _set_plan_by_customer_id(customer_id, new_plan, obj.get("id"))
        return {"event": event_type, "customer_id": customer_id, "status": status}

    elif event_type == "customer.subscription.deleted":
        customer_id = obj.get("customer")
        _set_plan_by_customer_id(customer_id, "free")
        return {"event": event_type, "customer_id": customer_id}

    return {"event": event_type, "handled": False}
