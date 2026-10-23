"""Consume simulator envelopes from Azure Event Hubs (keyless, managed identity / az login)."""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

from gallery_schema.events import Envelope


async def consume() -> AsyncIterator[Envelope]:
    from azure.eventhub.aio import EventHubConsumerClient
    from azure.identity.aio import DefaultAzureCredential

    queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=10000)
    credential = DefaultAzureCredential()
    client = EventHubConsumerClient(
        fully_qualified_namespace=os.environ["EVENTHUB_NAMESPACE"],
        eventhub_name=os.environ["EVENTHUB_NAME"],
        consumer_group=os.environ.get("EVENTHUB_CONSUMER_GROUP", "$Default"),
        credential=credential,
    )

    async def on_event(partition_context, event):
        if event is None:
            return
        await queue.put(Envelope.model_validate_json(event.body_as_str()))

    async def pump():
        async with client:
            await client.receive(on_event=on_event, starting_position="@latest")

    task = asyncio.create_task(pump())
    try:
        while True:
            env = await queue.get()
            yield env
            if env.kind == "event" and env.event and env.event.type.value == "full_time":
                break
    finally:
        task.cancel()
        await credential.close()
