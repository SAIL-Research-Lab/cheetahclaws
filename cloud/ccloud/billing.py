"""Credit top-ups with Stripe Checkout (REST API; no stripe SDK needed).

Flow: account page → POST /_cc/api/topup {amount} → Stripe Checkout URL →
user pays → Stripe calls /_cc/stripe/webhook (checkout.session.completed) →
credits are added once per session id. The webhook is authoritative; the
success redirect only shows a "thanks" message.

The iOS app never shows top-up UI (App Store rule 3.1.1): credits bought
on the web are simply usable in the app (multiplatform services, 3.1.3(b)).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional

import httpx

from .db import MICRO, Database
from .settings import Settings

STRIPE_API = "https://api.stripe.com/v1"


class BillingError(RuntimeError):
    pass


async def create_checkout(settings: Settings, uid: int, email: str, amount_usd: float,
                          transport: Optional[httpx.AsyncBaseTransport] = None) -> str:
    if not settings.stripe_secret:
        raise BillingError("payments are not configured on this server")
    if amount_usd not in settings.topup_packs_usd:
        raise BillingError("unknown top-up amount")
    cents = int(round(amount_usd * 100))
    form = {
        "mode": "payment",
        "success_url": f"{settings.public_url}/_cc/account?paid=1",
        "cancel_url": f"{settings.public_url}/_cc/account",
        "client_reference_id": str(uid),
        "customer_email": email,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(cents),
        "line_items[0][price_data][product_data][name]": f"CheetahClaws credits (${amount_usd:g})",
        "metadata[user_id]": str(uid),
        "metadata[credit_micro]": str(int(round(amount_usd * MICRO))),
    }
    async with httpx.AsyncClient(transport=transport, timeout=30) as c:
        r = await c.post(f"{STRIPE_API}/checkout/sessions", data=form,
                         auth=(settings.stripe_secret, ""))
    if r.status_code != 200:
        raise BillingError(f"Stripe error: {r.json().get('error', {}).get('message', r.text)}")
    return r.json()["url"]


def verify_signature(payload: bytes, header: str, secret: str,
                     tolerance: int = 300, now: Optional[float] = None) -> bool:
    """Stripe-Signature: t=<ts>,v1=<hex hmac of '<ts>.<payload>'>[,v1=…]"""
    try:
        parts = [p.split("=", 1) for p in header.split(",")]
        ts = next(v for k, v in parts if k == "t")
        sigs = [v for k, v in parts if k == "v1"]
    except (StopIteration, ValueError):
        return False
    if abs((now or time.time()) - int(ts)) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload,
                        hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def handle_webhook(settings: Settings, db: Database, payload: bytes,
                   signature: str) -> tuple[int, str]:
    if not settings.stripe_webhook_secret:
        return 400, "webhook secret not configured"
    if not verify_signature(payload, signature, settings.stripe_webhook_secret):
        return 400, "bad signature"
    event = json.loads(payload)
    if event.get("type") != "checkout.session.completed":
        return 200, "ignored"
    obj = event["data"]["object"]
    if obj.get("payment_status") != "paid":
        return 200, "not paid"
    meta = obj.get("metadata") or {}
    try:
        uid = int(meta["user_id"])
        credit = int(meta["credit_micro"])
    except (KeyError, ValueError):
        return 400, "missing metadata"
    # Never credit more than was actually charged.
    paid_micro = int(obj.get("amount_total") or 0) * (MICRO // 100)
    credit = min(credit, paid_micro)
    if not db.get_user(uid):
        return 200, "user gone"
    applied = db.credit(uid, credit, "stripe", obj["id"])
    return 200, "credited" if applied else "duplicate"
