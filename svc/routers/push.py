"""Authenticated, account-scoped Web Push lifecycle and preferences."""

import asyncio
import base64
import os
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from database import push as storage
from service import web_push
from svc.dependencies import VerifiedAccount, get_verified_account, get_db
from svc.rate_limit import ASSIGNMENT_MUTATE_LIMIT, limiter

router = APIRouter(prefix="/push", tags=["push"])
Account = Annotated[VerifiedAccount, Depends(get_verified_account)]
Store = Annotated[Any, Depends(get_db)]


class PushPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workout_reminders: StrictBool = False
    alerts: StrictBool = True
    coach_updates: StrictBool = True
    reminder_time: str = Field(default="18:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_start: str = Field(default="22:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str = Field(default="08:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="UTC", max_length=100)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Choose an IANA timezone.") from None
        return value


class PushSubscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    endpoint: str = Field(max_length=4096)
    keys: dict[str, str]

    @field_validator("endpoint")
    @classmethod
    def valid_endpoint(cls, value):
        url = urlsplit(value)
        host = url.hostname or ""
        # Browser push services only: an arbitrary HTTPS endpoint would allow SSRF.
        allowed = host in ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")
        allowed = allowed or host.endswith(".push.services.mozilla.com") or host.endswith(".notify.windows.com")
        if not allowed or url.scheme != "https" or url.port not in (None, 443) or url.username or url.password or url.fragment:
            raise ValueError("Unsupported browser push endpoint.")
        return value

    @field_validator("keys")
    @classmethod
    def valid_keys(cls, value):
        if set(value) != {"p256dh", "auth"}:
            raise ValueError("A subscription needs p256dh and auth keys.")
        for key, length in (("p256dh", 65), ("auth", 16)):
            if len(value[key]) > 100:
                raise ValueError("Invalid subscription key.")
            try:
                decoded = base64.b64decode(value[key] + "=" * (-len(value[key]) % 4), altchars=b"-_", validate=True)
            except (ValueError, TypeError):
                raise ValueError("Invalid subscription key.") from None
            if len(decoded) != length or (key == "p256dh" and decoded[0] != 4):
                raise ValueError("Invalid subscription key.")
        return value


@router.get("")
async def status(account: Account, db: Store, device_id: str = ""):
    prefs = await asyncio.to_thread(web_push.account_preferences, db, account.account_id)
    with db.catalog_locked() as conn:
        subscribed = conn.execute("SELECT 1 FROM push_subscriptions WHERE account_id=? AND device_id=?",
                                  (account.account_id, device_id)).fetchone() is not None
    return {"enabled": web_push.configured(),
            "subscribed": subscribed,
            "public_key": os.getenv("VAPID_PUBLIC_KEY", "") if web_push.configured() else None,
            "preferences": prefs}


@router.put("/preferences")
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def preferences(request: Request, body: PushPreferences, account: Account, db: Store):
    return await asyncio.to_thread(storage.save_preferences, db, account.account_id, body.model_dump())


@router.put("/subscriptions")
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def subscribe(request: Request, body: PushSubscription, account: Account, db: Store):
    if not web_push.configured():
        raise HTTPException(503, "Push notifications are unavailable.")
    try:
        await asyncio.to_thread(storage.subscribe, db, account.account_id, body.device_id,
                                body.endpoint, body.keys, datetime.now(UTC).isoformat())
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    return {"ok": True}


@router.delete("/subscriptions/{device_id}")
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def unsubscribe(request: Request, device_id: str, account: Account, db: Store):
    await asyncio.to_thread(storage.unsubscribe, db, account.account_id, device_id)
    return {"ok": True}
