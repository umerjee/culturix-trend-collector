"""VideoProvider/VoiceProvider protocols for CultureToons — see
docs/culturix-comedy-architecture.md §3.8 and §7 Phase 6.

KlingOmniProvider (app/media/kling_omni.py) and ElevenLabsProvider
(app/media/elevenlabs_voice.py) each gain a thin adapter method
(generate_scene/generate_dialogue) implementing these protocols, so the
*type* a future second provider would need to satisfy exists and is
documented — but app/services/culturetoon_video.py's actual call sites are
deliberately left calling the concrete generate_omni_video()/synthesize()
methods directly, unchanged. Migrating a working, tested video-generation
pipeline's call sites to route through a protocol with only one real
implementation would add a layer with no present payoff — the seam exists
for when (not before) a second provider (Runway, Veo, etc.) is actually
being integrated.

Methods here are synchronous (not `async def`, unlike the architecture
doc's illustrative sketch) — every provider call in this codebase today
(httpx synchronous client, FastAPI BackgroundTasks running the sync
function in a thread) is synchronous; introducing async here would be
inventing a calling convention nothing in the codebase actually uses yet.
"""
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class VideoGenerationResult:
    video_bytes: bytes
    duration_seconds: float
    task_id: str


@dataclass
class AudioResult:
    audio_bytes: bytes


@runtime_checkable
class VideoProvider(Protocol):
    def generate_scene(self, contents: list, settings: dict, options: Optional[dict] = None) -> VideoGenerationResult: ...


@runtime_checkable
class VoiceProvider(Protocol):
    def generate_dialogue(self, dialogue: str, voice_id: str) -> AudioResult: ...
