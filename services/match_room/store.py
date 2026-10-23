"""Optional persistence of overlays and recaps in Azure Cosmos DB (keyless).

Enabled when COSMOS_ENDPOINT is set. Gives studios a durable, queryable record of
every insight that aired, with its evidence and agent trace.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

log = logging.getLogger("gallery.store")


class InsightStore:
    def __init__(self) -> None:
        self._container = None
        self._client = None
        self.enabled = bool(os.environ.get("COSMOS_ENDPOINT"))

    async def _get(self):
        if self._container is None and self.enabled:
            from azure.cosmos.aio import CosmosClient
            from azure.identity.aio import DefaultAzureCredential

            self._client = CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=DefaultAzureCredential())
            db = self._client.get_database_client(os.environ.get("COSMOS_DATABASE", "gallery"))
            self._container = db.get_container_client(os.environ.get("COSMOS_CONTAINER", "insights"))
        return self._container

    async def save(self, doc: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            container = await self._get()
            await container.upsert_item(doc)
        except Exception as exc:  # noqa: BLE001 - persistence must never stop the broadcast
            log.warning("cosmos write failed: %s", exc)

    async def recent(self, match_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        if not self.enabled:
            return []
        container = await self._get()
        query = "SELECT TOP @n c.id, c.match_id, c.kind, c.minute, c.headline, c.body, c.verified, c.saved_at " \
                "FROM c ORDER BY c.saved_at DESC"
        params = [{"name": "@n", "value": limit}]
        items = [i async for i in container.query_items(query, parameters=params,
                                                         partition_key=match_id if match_id else None)]
        return items
