import os
import time
import voyageai
from dotenv import load_dotenv

load_dotenv()

_client = None

# Voyage AI free tier: 3 RPM, 10K TPM
# Standard tier (after adding payment method): 2000 RPM
# Chunk size and delay are conservative enough to work on free tier.
_BATCH_CHUNK = 20       # texts per API call
_RETRY_DELAY = 22       # seconds to wait after a rate-limit error


def _get_client() -> voyageai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("VOYAGE_API_KEY")
        if not api_key:
            raise RuntimeError("VOYAGE_API_KEY not set in environment")
        _client = voyageai.Client(api_key=api_key)
    return _client


def embed_text(text: str) -> list:
    return embed_batch([text])[0]


def embed_batch(texts: list) -> list:
    if not texts:
        return []
    client = _get_client()
    results = []
    for i in range(0, len(texts), _BATCH_CHUNK):
        chunk = texts[i: i + _BATCH_CHUNK]
        for attempt in range(3):
            try:
                result = client.embed(chunk, model="voyage-3")
                results.extend(result.embeddings)
                # Small gap between chunks to stay under RPM limit
                if i + _BATCH_CHUNK < len(texts):
                    time.sleep(1)
                break
            except Exception as e:
                if "rate" in str(e).lower() and attempt < 2:
                    print(f"[embeddings] Rate limit hit, waiting {_RETRY_DELAY}s...")
                    time.sleep(_RETRY_DELAY)
                else:
                    raise
    return results
