"""Stream a match through Azure Event Hubs (keyless: managed identity or az login).

`publish` plays the simulator into the hub at broadcast pace; `consume` reads it
back for the match room. Running both proves the full ingest path: simulator ->
Event Hubs -> stats engine -> crew -> viewers. Fabric Eventstream (or any other
consumer group) can subscribe to the same hub for analytics.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import AsyncIterator

from gallery_schema.events import Envelope
from simulator import MatchSimulator, northgate_united, riverside_athletic
from simulator.scenarios import teams_from_scenario

BATCH_EVERY_S = 0.25


def _ns() -> str:
    return os.environ["EVENTHUB_NAMESPACE"]


async def publish(seed: int, speed: float, scenario: dict | None = None, half_time_break_s: float = 15.0) -> None:
    """Play the match into the hub at broadcast pace, with a real half-time break (no data during it)."""
    from azure.eventhub import EventData
    from azure.eventhub.aio import EventHubProducerClient
    from azure.identity.aio import DefaultAzureCredential

    home, away = teams_from_scenario(scenario) if scenario else (riverside_athletic(), northgate_united())
    match = MatchSimulator(home, away, seed=seed).run()
    async with DefaultAzureCredential() as cred:
        producer = EventHubProducerClient(fully_qualified_namespace=_ns(),
                                          eventhub_name=os.environ["EVENTHUB_NAME"], credential=cred)
        async with producer:
            started, last_flush = time.monotonic(), time.monotonic()
            paused = 0.0
            batch = await producer.create_batch(partition_key=match.metadata.match_id)
            for env in match.envelopes():
                t = env.event.second if env.event else env.frame.second if env.frame else 0.0
                wait = t / max(speed, 0.1) - (time.monotonic() - started - paused)
                if wait > 0:
                    await asyncio.sleep(wait)
                data = EventData(env.model_dump_json(exclude_none=True))
                try:
                    batch.add(data)
                except ValueError:
                    await producer.send_batch(batch)
                    batch = await producer.create_batch(partition_key=match.metadata.match_id)
                    batch.add(data)
                is_ht = env.kind == "event" and env.event.type.value == "half_time"
                if time.monotonic() - last_flush >= BATCH_EVERY_S or env.kind == "metadata" or is_ht:
                    await producer.send_batch(batch)
                    batch = await producer.create_batch(partition_key=match.metadata.match_id)
                    last_flush = time.monotonic()
                if is_ht:  # the players go off: nothing is published until the second half kicks off
                    await asyncio.sleep(half_time_break_s)
                    paused += half_time_break_s
            if len(batch):
                await producer.send_batch(batch)


async def consume() -> AsyncIterator[Envelope]:
    from azure.eventhub.aio import EventHubConsumerClient
    from azure.identity.aio import DefaultAzureCredential

    queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=20000)
    credential = DefaultAzureCredential()
    client = EventHubConsumerClient(
        fully_qualified_namespace=_ns(), eventhub_name=os.environ["EVENTHUB_NAME"],
        consumer_group=os.environ.get("EVENTHUB_CONSUMER_GROUP", "$Default"), credential=credential)

    async def on_event(_ctx, event):
        if event is not None:
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
