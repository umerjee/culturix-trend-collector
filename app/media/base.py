from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Optional


@dataclass
class MediaResult:
    asset_bytes: bytes
    content_type: str        # "audio/mpeg" | "video/mp4"
    duration_seconds: Optional[float] = None
    cost_usd: Optional[float] = None


class VoiceProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice: Optional[str] = None) -> MediaResult: ...


class MusicProvider(ABC):
    @abstractmethod
    def generate(self, mood_prompt: str, duration_seconds: int = 30) -> MediaResult: ...


class VideoProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, duration_seconds: int = 5,
                 aspect_ratio: str = "9:16") -> MediaResult: ...
