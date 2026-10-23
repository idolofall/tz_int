import os
from collections.abc import AsyncIterator

import httpx
import pytest

APP_URL = os.getenv("APP_URL", "http://localhost:8000")
ALPHA_URL = os.getenv("ALPHA_URL", "http://localhost:8001")
BETA_URL = os.getenv("BETA_URL", "http://localhost:8002")


@pytest.fixture
async def app_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=APP_URL, timeout=10.0) as client:
        try:
            response = await client.get("/health")
        except httpx.HTTPError as exc:
            pytest.skip(f"generation service is not running: {exc}")
        if response.status_code != 200:
            pytest.skip("generation service is not running; start docker compose")
        yield client


@pytest.fixture
async def alpha_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=ALPHA_URL, timeout=10.0) as client:
        yield client


@pytest.fixture
async def beta_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=BETA_URL, timeout=10.0) as client:
        yield client


@pytest.fixture(autouse=True)
async def reset_providers(
    alpha_client: httpx.AsyncClient,
    beta_client: httpx.AsyncClient,
) -> AsyncIterator[None]:
    reset = {
        "fail_rate": 0.0,
        "error_type": "technical",
        "sync_error": None,
        "double_webhook": False,
        "no_webhook": False,
        "delay_seconds": 0.2,
        "late_completed": False,
        "webhook_status": None,
    }
    try:
        await alpha_client.post("/__test__/behavior", json=reset)
        await beta_client.post("/__test__/behavior", json=reset)
    except httpx.HTTPError as exc:
        pytest.skip(f"providers are not running: {exc}")
    yield
