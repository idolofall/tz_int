import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx

from tests.conftest import sign


async def credit(client: httpx.AsyncClient, user_id: UUID, tokens: int) -> str:
    payment_id = f"pay-{uuid4()}"
    body, headers = sign(
        {
            "payment_id": payment_id,
            "user_id": str(user_id),
            "tokens": tokens,
            "status": "completed",
        }
    )
    response = await client.post("/webhooks/payments", content=body, headers=headers)
    response.raise_for_status()
    return payment_id


async def generate(
    client: httpx.AsyncClient,
    user_id: UUID,
    *,
    model_slug: str = "image-fast",
    prompt: str = "a cat",
    ref_images: list[str] | None = None,
) -> httpx.Response:
    return await client.post(
        "/generate",
        json={
            "user_id": str(user_id),
            "model_slug": model_slug,
            "prompt": prompt,
            "ref_images": ref_images or [],
        },
    )


async def wait_task(
    client: httpx.AsyncClient,
    task_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            while True:
                response = await client.get(f"/tasks/{task_id}")
                response.raise_for_status()
                last = response.json()
                if predicate(last):
                    return last
                await asyncio.sleep(0.2)
    except TimeoutError as exc:
        raise AssertionError(
            f"task {task_id} did not reach expected state: {last}"
        ) from exc


async def send_provider_webhook(
    client: httpx.AsyncClient,
    provider: str,
    payload: dict[str, Any],
) -> httpx.Response:
    body, headers = sign(payload)
    return await client.post(
        f"/webhooks/providers/{provider}",
        content=body,
        headers=headers,
    )
