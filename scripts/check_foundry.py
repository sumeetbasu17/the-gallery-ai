"""Smoke test: call the Foundry model deployment with keyless (Entra ID) auth.

Prerequisites: `az login`, and your user holds the "Cognitive Services OpenAI User"
role on the Foundry resource. Settings come from environment variables or .env.
"""

import os
import sys

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    _load_dotenv()
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    model = os.environ.get("GALLERY_FAST_MODEL", "gpt-5.4-mini")
    if not endpoint:
        sys.exit("Set AZURE_OPENAI_ENDPOINT (see .env.example)")
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    client = OpenAI(base_url=endpoint.rstrip("/") + "/", api_key=token_provider)
    reply = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a veteran football pundit. Answer in one sentence."},
            {"role": "user", "content": "What does 'parking the bus' mean?"},
        ],
    )
    print(f"[{model}] {reply.choices[0].message.content}")


if __name__ == "__main__":
    main()
