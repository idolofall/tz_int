from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import uuid
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

PROVIDER_NAME = os.getenv("PROVIDER_NAME", "alpha")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev-webhook-secret")
DEFAULT_MIN_DELAY = float(os.getenv("WEBHOOK_MIN_DELAY_SECONDS", "2"))
DEFAULT_MAX_DELAY = float(os.getenv("WEBHOOK_MAX_DELAY_SECONDS", "20"))
PROVIDER_TIMEOUT = float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "60"))


class Behavior(BaseModel):
    fail_rate: float = 0.0
    error_type: Literal["technical", "moderation", "payload"] = "technical"
    sync_error: Literal["503", "timeout"] | None = None
    double_webhook: bool = False
    no_webhook: bool = False
    delay_seconds: float | None = None
    late_completed: bool = False
    webhook_status: Literal["completed", "failed"] | None = None


class TaskIn(BaseModel):
    prompt: str
    ref_images: list[str] = Field(default_factory=list)
    model: str
    webhook_url: str
    external_id: str | None = None


behavior = Behavior()
behavior_lock = asyncio.Lock()
background_tasks: set[asyncio.Task[None]] = set()

app = FastAPI(title=f"Fake provider {PROVIDER_NAME}")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": PROVIDER_NAME}


@app.get("/__test__/behavior")
async def get_behavior() -> Behavior:
    async with behavior_lock:
        return behavior.model_copy()


@app.post("/__test__/behavior")
async def set_behavior(payload: Behavior) -> Behavior:
    async with behavior_lock:
        for field, value in payload.model_dump().items():
            setattr(behavior, field, value)
        return behavior.model_copy()


@app.post("/tasks", status_code=202)
async def create_task(payload: TaskIn) -> dict[str, str]:
    async with behavior_lock:
        current = behavior.model_copy()

    if current.sync_error == "503":
        raise HTTPException(status_code=503, detail="provider unavailable")
    if current.sync_error == "timeout":
        await asyncio.sleep(current.delay_seconds or 30)
        raise HTTPException(status_code=503, detail="provider timed out")

    external_id = payload.external_id or str(uuid.uuid4())
    if not current.no_webhook:
        task = asyncio.create_task(
            _deliver_webhook(payload.webhook_url, external_id, current),
            name=f"webhook-{external_id}",
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
    return {"external_id": external_id}


async def _deliver_webhook(url: str, external_id: str, current: Behavior) -> None:
    await asyncio.sleep(_resolve_delay(current))
    body = _build_body(external_id, current)
    if current.double_webhook:
        await asyncio.gather(_post(url, body), _post(url, body))
        return
    await _post(url, body)


def _resolve_delay(current: Behavior) -> float:
    if current.late_completed:
        extra = current.delay_seconds
        return (PROVIDER_TIMEOUT if extra is None else extra) + 2
    if current.delay_seconds is not None:
        return current.delay_seconds
    return random.uniform(DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY)


def _build_body(external_id: str, current: Behavior) -> dict[str, Any]:
    failed = current.webhook_status == "failed" or random.random() < current.fail_rate
    if failed:
        return {
            "external_id": external_id,
            "status": "failed",
            "error_type": current.error_type,
        }
    return {
        "external_id": external_id,
        "status": "completed",
        "file_url": f"https://files.example/{PROVIDER_NAME}/{external_id}",
    }


async def _post(url: str, body: dict[str, Any]) -> None:
    raw_body = json.dumps(body, separators=(",", ":")).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                url,
                content=raw_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": signature,
                },
            )
            logger.info("webhook %s -> %s", url, response.status_code)
    except httpx.HTTPError as exc:
        logger.warning("webhook delivery failed: %s", exc)
