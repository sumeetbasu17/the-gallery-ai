"""Azure AI Speech text-to-speech through the Foundry (AIServices) resource, keyless.

Uses the resource's Entra ID token ("aad#<resource id>#<token>"), so the same managed identity that calls
the models can speak the recap. Returns None when Speech is not configured, so the browser voice is used.
"""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from typing import Optional
from xml.sax.saxutils import escape

log = logging.getLogger("gallery.speech")

VOICES = {"en": ("en-GB", "en-GB-RyanNeural"), "hi": ("hi-IN", "hi-IN-MadhurNeural"),
          "es": ("es-ES", "es-ES-AlvaroNeural")}


_CACHE: "OrderedDict[tuple[str, str], bytes]" = OrderedDict()
_CACHE_MAX = 64


def available() -> bool:
    return bool(os.environ.get("SPEECH_REGION") and os.environ.get("SPEECH_RESOURCE_ID"))


async def synthesize(text: str, language: str) -> Optional[bytes]:
    """MP3 bytes, or None (not configured / failed). Recent clips are cached: replays cost nothing."""
    region = os.environ.get("SPEECH_REGION")
    resource_id = os.environ.get("SPEECH_RESOURCE_ID")
    if not (region and resource_id and text.strip()):
        return None
    key = (language, text)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    audio = await _synthesize(text, language, region, resource_id)
    if audio:
        _CACHE[key] = audio
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return audio


async def _synthesize(text: str, language: str, region: str, resource_id: str) -> Optional[bytes]:
    try:
        import httpx
        from azure.identity.aio import DefaultAzureCredential

        async with DefaultAzureCredential() as cred:
            token = (await cred.get_token("https://cognitiveservices.azure.com/.default")).token
        locale, voice = VOICES.get(language, VOICES["en"])
        ssml = (f"<speak version='1.0' xml:lang='{locale}'><voice name='{voice}'>"
                f"<prosody rate='+4%'>{escape(text)}</prosody></voice></speak>")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
                headers={"Authorization": f"Bearer aad#{resource_id}#{token}",
                         "Content-Type": "application/ssml+xml",
                         "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                         "User-Agent": "the-gallery"},
                content=ssml.encode("utf-8"))
        if r.status_code != 200:
            log.warning("speech failed: %s %s", r.status_code, r.text[:200])
            return None
        return r.content
    except Exception as exc:  # noqa: BLE001 - fall back to the browser voice
        log.warning("speech unavailable: %s", exc)
        return None
