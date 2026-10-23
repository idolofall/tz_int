import asyncio
from uuid import uuid4

import httpx
import pytest

from tests.integration.helpers import (
    credit,
    generate,
    send_provider_webhook,
    wait_task,
)


@pytest.mark.asyncio
async def test_twenty_identical_payment_webhooks_credit_once(
    app_client: httpx.AsyncClient,
) -> None:
    user_id = uuid4()
    payment = {
        "payment_id": f"pay-{user_id}",
        "user_id": str(user_id),
        "tokens": 40,
        "status": "completed",
    }
    from tests.conftest import sign

    body, headers = sign(payment)

    async def once() -> httpx.Response:
        return await app_client.post(
            "/webhooks/payments", content=body, headers=headers
        )

    responses = await asyncio.gather(*[once() for _ in range(20)])
    assert all(item.status_code == 202 for item in responses)

    balance = (await app_client.get(f"/users/{user_id}/balance")).json()
    assert balance["balance"] == 40
    payments = [row for row in balance["journal"] if row["kind"] == "payment"]
    assert len(payments) == 1


@pytest.mark.asyncio
async def test_ten_concurrent_last_leg_failures_refund_once(
    app_client: httpx.AsyncClient,
    beta_client: httpx.AsyncClient,
) -> None:
    await beta_client.post(
        "/__test__/behavior",
        json={"no_webhook": True, "delay_seconds": 0.1},
    )
    user_id = uuid4()
    await credit(app_client, user_id, 25)
    created = await generate(
        app_client,
        user_id,
        model_slug="video-long",
        ref_images=["a", "b"],
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["task_id"]

    task = await wait_task(
        app_client,
        task_id,
        lambda item: bool(item["attempts"] and item["attempts"][0]["external_id"]),
    )
    external_id = task["attempts"][0]["external_id"]
    failed = {
        "external_id": external_id,
        "status": "failed",
        "error_type": "technical",
    }

    responses = await asyncio.gather(
        *[send_provider_webhook(app_client, "beta", failed) for _ in range(10)]
    )
    assert all(item.status_code == 202 for item in responses)

    task = await wait_task(
        app_client, task_id, lambda item: item["status"] == "failed"
    )
    assert task["result_url"] is None

    balance = (await app_client.get(f"/users/{user_id}/balance")).json()
    assert balance["balance"] == 25
    refunds = [row for row in balance["journal"] if row["kind"] == "refund"]
    assert len(refunds) == 1


@pytest.mark.asyncio
async def test_first_leg_failure_completes_on_second(
    app_client: httpx.AsyncClient,
    alpha_client: httpx.AsyncClient,
    beta_client: httpx.AsyncClient,
) -> None:
    await alpha_client.post(
        "/__test__/behavior",
        json={
            "webhook_status": "failed",
            "error_type": "technical",
            "delay_seconds": 0.2,
        },
    )
    await beta_client.post(
        "/__test__/behavior",
        json={"webhook_status": "completed", "delay_seconds": 0.2},
    )
    user_id = uuid4()
    await credit(app_client, user_id, 2)
    created = await generate(app_client, user_id)
    assert created.status_code == 200, created.text
    task_id = created.json()["task_id"]

    task = await wait_task(
        app_client,
        task_id,
        lambda item: item["status"] == "completed",
        timeout_seconds=20,
    )
    assert len(task["attempts"]) == 2
    assert task["attempts"][0]["provider"] == "alpha"
    assert task["attempts"][0]["error_type"] == "technical"
    assert task["attempts"][1]["provider"] == "beta"
    assert task["result_url"]
    balance = (await app_client.get(f"/users/{user_id}/balance")).json()
    assert balance["balance"] == 0


@pytest.mark.asyncio
async def test_late_completed_after_watchdog_does_not_pay_and_deliver(
    app_client: httpx.AsyncClient,
    beta_client: httpx.AsyncClient,
) -> None:
    await beta_client.post(
        "/__test__/behavior",
        json={"no_webhook": True, "delay_seconds": 0.1},
    )
    user_id = uuid4()
    await credit(app_client, user_id, 25)
    created = await generate(
        app_client,
        user_id,
        model_slug="video-long",
        ref_images=["a", "b"],
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["task_id"]

    pending = await wait_task(
        app_client,
        task_id,
        lambda item: bool(item["attempts"] and item["attempts"][0]["external_id"]),
    )
    external_id = pending["attempts"][0]["external_id"]

    failed = await wait_task(
        app_client,
        task_id,
        lambda item: item["status"] == "failed",
        timeout_seconds=75,
    )
    assert failed["result_url"] is None
    balance_after_timeout = (
        await app_client.get(f"/users/{user_id}/balance")
    ).json()
    assert balance_after_timeout["balance"] == 25

    await send_provider_webhook(
        app_client,
        "beta",
        {
            "external_id": external_id,
            "status": "completed",
            "file_url": "https://files.example/late",
        },
    )
    await asyncio.sleep(0.5)
    late = (await app_client.get(f"/tasks/{task_id}")).json()
    assert late["status"] == "failed"
    assert late["result_url"] is None

    balance = (await app_client.get(f"/users/{user_id}/balance")).json()
    assert balance["balance"] == 25
    refunds = [row for row in balance["journal"] if row["kind"] == "refund"]
    assert len(refunds) == 1
