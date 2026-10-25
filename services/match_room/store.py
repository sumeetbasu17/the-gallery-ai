"""The match archive: every finished (or stopped) match, kept for studios to review.

One document per match: summary, every overlay that aired (with evidence, agent trace and all
language/audience versions), coach reports, the recap and the win-probability story. Tracking frames
are NOT stored: the simulator is deterministic, so the seed (plus the scenario, if any) regenerates
every frame on demand. A 90-minute match is ~150-400 KB instead of tens of MB.

Backends
  Azure Cosmos DB (keyless) when COSMOS_ENDPOINT is set: container partitioned on /match_id.
  Local JSON files otherwise (GALLERY_DATA_DIR, default ./.gallery-data), so the archive works offline.

Retention: the newest GALLERY_ARCHIVE_MAX matches (default 50) are kept; older ones are pruned.
Listing is paginated with an opaque cursor (Cosmos continuation token, or an offset locally).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("gallery.store")

SUMMARY_FIELDS = ("id", "match_id", "title", "home", "away", "score", "minute", "ended", "seed", "speed",
                  "scenario_title", "started_at", "ended_at", "headline", "insights", "source")


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: doc.get(k) for k in SUMMARY_FIELDS}


class MatchArchive:
    def __init__(self) -> None:
        self.cosmos = bool(os.environ.get("COSMOS_ENDPOINT"))
        self.max_matches = int(os.environ.get("GALLERY_ARCHIVE_MAX", "50"))
        self.folder = Path(os.environ.get("GALLERY_DATA_DIR", ".gallery-data")).resolve() / "matches"
        self._container = None
        self._lock = asyncio.Lock()

    @property
    def backend(self) -> str:
        return "cosmos" if self.cosmos else "local"

    # ------------------------------------------------------------------ cosmos
    async def _get(self):
        if self._container is None:
            from azure.cosmos.aio import CosmosClient
            from azure.identity.aio import DefaultAzureCredential

            client = CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=DefaultAzureCredential())
            db = client.get_database_client(os.environ.get("COSMOS_DATABASE", "gallery"))
            self._container = db.get_container_client(os.environ.get("COSMOS_CONTAINER", "insights"))
        return self._container

    # ------------------------------------------------------------------ api
    async def save(self, doc: dict[str, Any]) -> None:
        """Persist one match. Never raises: the broadcast must not depend on storage."""
        doc = {**doc, "kind": "match", "match_id": doc["id"]}
        try:
            async with self._lock:
                if self.cosmos:
                    await (await self._get()).upsert_item(doc)
                else:
                    self.folder.mkdir(parents=True, exist_ok=True)
                    (self.folder / f"{doc['id']}.json").write_text(json.dumps(doc, ensure_ascii=False, default=str),
                                                                  encoding="utf-8")
                await self._prune()
        except Exception as exc:  # noqa: BLE001
            log.warning("archive write failed: %s", exc)

    async def list(self, limit: int = 10, cursor: Optional[str] = None) -> dict[str, Any]:
        limit = max(1, min(50, limit))
        try:
            if self.cosmos:
                container = await self._get()
                fields = ", ".join(f"c.{f}" for f in SUMMARY_FIELDS)
                query = f"SELECT {fields} FROM c WHERE c.kind = 'match' ORDER BY c.ended_at DESC"
                pager = container.query_items(query, max_item_count=limit).by_page(cursor or None)
                items: list[dict] = []
                async for page in pager:
                    items = [i async for i in page]
                    break
                return {"items": items, "next": pager.continuation_token, "backend": "cosmos"}
            files = self._files()
            start = int(cursor or 0)
            items = [summary(json.loads(p.read_text(encoding="utf-8"))) for p in files[start:start + limit]]
            nxt = str(start + limit) if start + limit < len(files) else None
            return {"items": items, "next": nxt, "total": len(files), "backend": "local"}
        except Exception as exc:  # noqa: BLE001
            log.warning("archive list failed: %s", exc)
            return {"items": [], "next": None, "error": "The archive is unavailable right now."}

    async def get(self, match_id: str) -> Optional[dict[str, Any]]:
        try:
            if self.cosmos:
                return await (await self._get()).read_item(match_id, partition_key=match_id)
            path = self.folder / f"{Path(match_id).name}.json"
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except Exception as exc:  # noqa: BLE001
            log.warning("archive read failed: %s", exc)
            return None

    async def delete(self, match_id: str) -> bool:
        try:
            if self.cosmos:
                await (await self._get()).delete_item(match_id, partition_key=match_id)
                return True
            path = self.folder / f"{Path(match_id).name}.json"
            if path.is_file():
                path.unlink()
                return True
        except Exception as exc:  # noqa: BLE001
            log.warning("archive delete failed: %s", exc)
        return False

    # ------------------------------------------------------------------ internals
    def _files(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return sorted(self.folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    async def _prune(self) -> None:
        if self.cosmos:
            container = await self._get()
            query = "SELECT c.id FROM c WHERE c.kind = 'match' ORDER BY c.ended_at DESC OFFSET @n LIMIT 100"
            old = [i async for i in container.query_items(query, parameters=[{"name": "@n",
                                                                              "value": self.max_matches}])]
            for item in old:
                await container.delete_item(item["id"], partition_key=item["id"])
            return
        for p in self._files()[self.max_matches:]:
            p.unlink(missing_ok=True)
