"""Settings and chat-client factory.

Modes
-----
* foundry  (default when AZURE_AI_PROJECT_ENDPOINT is set): Microsoft Foundry project via
  FoundryChatClient, keyless with DefaultAzureCredential.
* openai   : Azure OpenAI v1 endpoint via OpenAIChatClient, keyless.
* offline  : deterministic ScriptedChatClient; no network. Used by tests and for demos without Azure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def find_dotenv(name: str = ".env") -> str | None:
    """Look for .env in the current folder and its parents (so it works from services/ too)."""
    from pathlib import Path

    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        candidate = folder / name
        if candidate.is_file():
            return str(candidate)
    return None


def load_dotenv(path: str | None = None) -> None:
    path = path or find_dotenv()
    if not path or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


@dataclass
class Settings:
    mode: str = "offline"
    project_endpoint: str = ""
    openai_endpoint: str = ""
    fast_model: str = "gpt-5.4-mini"
    creative_model: str = "gpt-5.4-mini"
    languages: list[str] = field(default_factory=lambda: ["en"])
    max_parallel_moments: int = 3
    llm_timeout_s: float = 25.0
    semantic_check: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        project = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
        openai_ep = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        mode = os.environ.get("GALLERY_MODE") or ("foundry" if project else "openai" if openai_ep else "offline")
        langs = [x.strip() for x in os.environ.get("GALLERY_LANGUAGES", "en,hi,es").split(",") if x.strip()]
        return cls(
            mode=mode, project_endpoint=project, openai_endpoint=openai_ep,
            fast_model=os.environ.get("GALLERY_FAST_MODEL", "gpt-5.4-mini"),
            creative_model=os.environ.get("GALLERY_CREATIVE_MODEL", os.environ.get("GALLERY_FAST_MODEL",
                                                                                    "gpt-5.4-mini")),
            languages=langs,
            max_parallel_moments=int(os.environ.get("GALLERY_PARALLEL", "3")),
            semantic_check=os.environ.get("GALLERY_SEMANTIC_CHECK", "1") != "0",
        )


_CREDENTIALS: list = []


async def close_credentials() -> None:
    """Close the async Azure credentials opened by make_client (avoids 'Unclosed client session')."""
    while _CREDENTIALS:
        cred = _CREDENTIALS.pop()
        try:
            await cred.close()
        except Exception:  # noqa: BLE001
            pass


def make_client(settings: Settings, model: str):
    """Return an Agent Framework chat client for the configured mode."""
    if settings.mode == "offline":
        from .offline import ScriptedChatClient

        return ScriptedChatClient()

    from azure.identity.aio import DefaultAzureCredential

    credential = DefaultAzureCredential()
    _CREDENTIALS.append(credential)
    if settings.mode == "foundry":
        from agent_framework.foundry import FoundryChatClient

        return FoundryChatClient(project_endpoint=settings.project_endpoint, model=model, credential=credential)
    if settings.mode == "openai":
        from agent_framework.openai import OpenAIChatClient

        return OpenAIChatClient(model=model, base_url=settings.openai_endpoint.rstrip("/") + "/",
                                credential=credential)
    raise ValueError(f"Unknown GALLERY_MODE {settings.mode!r}")
