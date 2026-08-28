"""Ollama local LLM provider."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.llm.base import AIProvider, LLMError


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout: float = 600.0,  # generous — CPU-only generation is slow
        embedding_model: str = "nomic-embed-text",
        keep_alive: str = "30m",
        num_ctx: int = 0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.embedding_model = embedding_model
        # keep_alive keeps the model resident between calls so we don't pay the
        # multi-GB reload cost on every step — critical for slow CPU-only inference.
        self.keep_alive = keep_alive
        # num_ctx > 0 pins the context window; smaller = faster prefill on CPU.
        self.num_ctx = num_ctx
        # Slow CPU-only inference intermittently drops the connection to Ollama
        # (WinError 10054 / RemoteProtocolError) under load; retry transient failures.
        self.max_retries = 3

    async def _generate_raw(self, payload: dict[str, Any], *, what: str) -> str:
        """POST /api/generate, retrying only transient connection drops.

        On CPU-only inference Ollama occasionally resets the connection mid-request
        (WinError 10054 → httpx NetworkError/ProtocolError); those are retried. A read
        timeout means generation is genuinely too slow — retrying just wastes another
        full timeout, so we surface an actionable error instead.
        """
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/api/generate", json=payload
                    )
                    resp.raise_for_status()
                    return resp.json().get("response", "").strip()
            except (httpx.NetworkError, httpx.ProtocolError) as exc:
                last = exc
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2.0 * (attempt + 1))
            except httpx.TimeoutException as exc:
                raise LLMError(
                    f"Ollama {what} timed out after {self.timeout:.0f}s — inference is too "
                    "slow for this request. Lower LLM_MAX_TOKENS, shrink the prompt, or use "
                    "a faster model/GPU."
                ) from exc
            except httpx.HTTPError as exc:
                raise LLMError(f"Ollama {what} failed: {exc}") from exc
        raise LLMError(
            f"Ollama {what} failed after {self.max_retries} connection retries: {last}"
        ) from last

    def _options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "temperature": self.temperature,
            "num_predict": self.max_tokens,
        }
        if self.num_ctx > 0:
            opts["num_ctx"] = self.num_ctx
        return opts

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": self._options(),
        }
        return await self._generate_raw(payload, what="generate")

    async def stream(  # type: ignore[override]
        self, prompt: str, *, system: str | None = None
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": self._options(),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/generate", json=payload
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if token := chunk.get("response"):
                            yield token
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama stream failed: {exc}") from exc

    async def structured_output(
        self, prompt: str, *, schema: dict[str, Any], system: str | None = None
    ) -> Any:
        # Ollama accepts a JSON Schema in `format` and constrains output to match it.
        sys_prompt = (
            (system + "\n\n" if system else "")
            + "Respond ONLY with valid JSON matching the requested schema. No prose."
        )
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": sys_prompt,
            "stream": False,
            "format": schema,
            "keep_alive": self.keep_alive,
            "options": self._options(),
        }
        raw = await self._generate_raw(payload, what="structured_output")

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: extract the first JSON object/array from the text.
            extracted = _extract_json(raw)
            if extracted is not None:
                return extracted
            raise LLMError(f"Ollama returned non-JSON output: {raw[:200]!r}")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Ollama's /api/embed accepts a batch via `input`; fall back per-text if needed.
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.embedding_model, "input": texts},
                )
                resp.raise_for_status()
                data = resp.json()
                if "embeddings" in data:
                    return data["embeddings"]
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama embed failed: {exc}") from exc
        raise LLMError("Ollama embed returned no embeddings")

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def embeddings_available(self) -> bool:
        try:
            vecs = await self.embed(["health check"])
            return bool(vecs and vecs[0])
        except LLMError:
            return False

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                return [m["name"] for m in resp.json().get("models", [])]
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama list_models failed: {exc}") from exc


def _extract_json(text: str) -> Any | None:
    """Best-effort extraction of the first balanced JSON value from text."""
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None
