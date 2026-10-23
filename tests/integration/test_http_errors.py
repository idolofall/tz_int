from uuid import uuid4

import httpx
import pytest

from tests.integration.helpers import credit, generate


@pytest.mark.asyncio
async def test_generate_returns_402_without_tokens(
    app_client: httpx.AsyncClient,
) -> None:
    user_id = uuid4()
    response = await generate(app_client, user_id)
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_too_many_refs_rejected_before_debit(
    app_client: httpx.AsyncClient,
) -> None:
    user_id = uuid4()
    await credit(app_client, user_id, 25)
    response = await generate(
        app_client,
        user_id,
        model_slug="video-long",
        ref_images=["a", "b", "c"],
    )
    assert response.status_code == 400
    balance = (await app_client.get(f"/users/{user_id}/balance")).json()
    assert balance["balance"] == 25


@pytest.mark.asyncio
async def test_fourth_active_task_is_rate_limited(
    app_client: httpx.AsyncClient,
    alpha_client: httpx.AsyncClient,
    beta_client: httpx.AsyncClient,
) -> None:
    await alpha_client.post("/__test__/behavior", json={"no_webhook": True})
    await beta_client.post("/__test__/behavior", json={"no_webhook": True})
    user_id = uuid4()
    await credit(app_client, user_id, 20)
    for _ in range(3):
        created = await generate(app_client, user_id)
        assert created.status_code == 200, created.text
    blocked = await generate(app_client, user_id)
    assert blocked.status_code == 429
