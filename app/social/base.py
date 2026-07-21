from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Optional


@dataclass
class PostMetrics:
    platform_post_id: str
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None


@dataclass
class TokenResult:
    access_token: str
    refresh_token: Optional[str]
    expires_in_seconds: Optional[int]
    platform_account_id: Optional[str] = None
    platform_username: Optional[str] = None


class OAuthProvider(ABC):
    @abstractmethod
    def get_authorize_url(self, state: str) -> str: ...

    @abstractmethod
    def exchange_code(self, code: str) -> TokenResult: ...

    @abstractmethod
    def refresh_access_token(self, refresh_token: str) -> TokenResult: ...

    @abstractmethod
    def fetch_post_metrics(self, access_token: str, post_url: str) -> PostMetrics: ...

    @abstractmethod
    def publish(self, access_token: str, video_bytes: bytes, title: str, description: str) -> PostMetrics:
        """Publishes a video and returns PostMetrics for the brand-new post
        (views/likes/comments/shares all None or zero — nothing to report yet)."""
        ...
