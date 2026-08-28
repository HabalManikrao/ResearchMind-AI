"""Provider-agnostic LLM interface (spec §22).

Every provider implements the same surface so the application is never coupled to
one model or vendor. The MVP ships OllamaProvider; OpenAI/Anthropic providers can be
added by subclassing AIProvider and registering them in the factory.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class LLMError(RuntimeError):
    """Raised when the provider fails (connection, timeout, bad response)."""


class AIProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return a single completion for the prompt."""

    @abstractmethod
    def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        """Yield completion chunks as they arrive."""

    @abstractmethod
    async def structured_output(
        self, prompt: str, *, schema: dict[str, Any], system: str | None = None
    ) -> Any:
        """Return parsed JSON conforming to `schema` (JSON Schema)."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return an embedding vector for each input text."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and usable."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return available model identifiers."""
