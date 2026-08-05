"""Optional ElevenLabs voice provider for CultureToons — only invoked when a
CharacterVariant opts into it (voice_provider="elevenlabs") and its brand has
supplied its own ElevenLabs API key (CharacterBrand.elevenlabs_api_key_encrypted).
Kling's own native voice/lip-sync (app/media/kling_omni.py) is the default;
this exists as a proven, accent-strong fallback since native-audio-speaks-
dialogue is an unverified assumption about Kling's behavior.

The API key is passed in by the caller (already decrypted from the owning
brand), not read from a global env var — this is a per-user credential, not
an app-wide one, unlike every other media provider in this codebase.
"""
import httpx

_BASE = "https://api.elevenlabs.io/v1"


class ElevenLabsError(Exception):
    pass


class ElevenLabsProvider:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ElevenLabsError("ElevenLabs API key is required")
        self._api_key = api_key

    def _headers(self) -> dict:
        return {"xi-api-key": self._api_key}

    def synthesize(self, text: str, voice_id: str) -> bytes:
        """POST /text-to-speech/{voice_id}. Returns mp3 audio bytes."""
        try:
            resp = httpx.post(
                f"{_BASE}/text-to-speech/{voice_id}",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_multilingual_v2"},
                timeout=60,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = getattr(exc.response, "text", "")
            raise ElevenLabsError(f"ElevenLabs synthesis failed: {exc} | {body[:500]}") from exc
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"ElevenLabs synthesis failed: {exc}") from exc

        if not resp.content:
            raise ElevenLabsError("ElevenLabs returned no audio data")
        return resp.content

    def list_voices(self) -> list:
        """GET /voices — populates the variant-level voice picker in the UI."""
        try:
            resp = httpx.get(f"{_BASE}/voices", headers=self._headers(), timeout=20)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"ElevenLabs list_voices failed: {exc}") from exc
        return resp.json().get("voices", [])
