from typing import Any

import httpx


class ProviderClient:
    def __init__(self, *, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds

    async def create_task(
        self,
        *,
        base_url: str,
        payload: dict[str, Any],
    ) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{base_url}/tasks", json=payload)
            response.raise_for_status()
            data = response.json()
            return str(data["external_id"])
