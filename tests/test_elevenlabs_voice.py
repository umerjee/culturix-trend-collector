"""Tests for app/media/elevenlabs_voice.py's generate_dialogue() adapter —
see app/media/protocols.py (Phase 6, docs/culturix-comedy-architecture.md §3.8).
No prior test file existed for this module; scoped here to the new adapter,
not a full retroactive test suite for synthesize()/list_voices()."""
from app.media.elevenlabs_voice import ElevenLabsProvider
from app.media.protocols import VoiceProvider, AudioResult


class TestGenerateDialogueProtocolAdapter:
    def test_wraps_bytes_as_dataclass(self, mocker):
        provider = ElevenLabsProvider(api_key="fake-key")
        assert isinstance(provider, VoiceProvider)  # structurally satisfies the protocol

        mocker.patch.object(provider, "synthesize", return_value=b"fake-mp3-bytes")
        result = provider.generate_dialogue("Hello there", "voice-123")

        assert isinstance(result, AudioResult)
        assert result.audio_bytes == b"fake-mp3-bytes"
        provider.synthesize.assert_called_once_with("Hello there", "voice-123")
