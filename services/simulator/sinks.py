"""Where simulated envelopes go: a JSONL file, the console, or Azure Event Hubs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from gallery_schema.events import Envelope


class Sink(Protocol):
    def send(self, env: Envelope) -> None: ...
    def close(self) -> None: ...


class JsonlSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")

    def send(self, env: Envelope) -> None:
        self._fh.write(env.model_dump_json(exclude_none=True) + "\n")

    def close(self) -> None:
        self._fh.close()


class ConsoleSink:
    """Prints events only (frames are too chatty for a terminal)."""

    def __init__(self, names: dict[str, str]):
        self.names = names

    def send(self, env: Envelope) -> None:
        if env.kind == "metadata":
            m = env.metadata
            print(f"== {m.home.name} vs {m.away.name} at {m.venue} ({m.match_id}) ==")
        elif env.kind == "event":
            e = env.event
            who = self.names.get(e.player_id or "", "")
            extra = f" {e.outcome}" if e.outcome else ""
            print(f"{e.minute:>3}' {e.type.value:<18} {who}{extra}")

    def close(self) -> None:
        pass


class EventHubSink:
    """Batches envelopes into Azure Event Hubs.

    Auth: keyless via DefaultAzureCredential (az login / managed identity) using
    EVENTHUB_NAMESPACE (e.g. myns.servicebus.windows.net) and EVENTHUB_NAME.
    """

    def __init__(self, batch_size: int = 50):
        from azure.eventhub import EventData, EventHubProducerClient  # optional dependency
        from azure.identity import DefaultAzureCredential

        self._EventData = EventData
        self._client = EventHubProducerClient(
            fully_qualified_namespace=os.environ["EVENTHUB_NAMESPACE"],
            eventhub_name=os.environ["EVENTHUB_NAME"],
            credential=DefaultAzureCredential(),
        )
        self._buffer: list[str] = []
        self._batch_size = batch_size

    def send(self, env: Envelope) -> None:
        self._buffer.append(env.model_dump_json(exclude_none=True))
        if len(self._buffer) >= self._batch_size or env.kind == "metadata":
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        batch = self._client.create_batch(partition_key=json.loads(self._buffer[0]).get("kind", "x"))
        for item in self._buffer:
            batch.add(self._EventData(item))
        self._client.send_batch(batch)
        self._buffer.clear()

    def close(self) -> None:
        self.flush()
        self._client.close()
