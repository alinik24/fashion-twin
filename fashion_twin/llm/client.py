"""Unified LLM client — supports OpenRouter, external API providers, and local models.

Provider mapping:
  openrouter   → OpenRouter (100+ models including Claude, GPT, Llama, etc.)
  api_provider → External API (Azure OpenAI, OpenAI, Claude, etc.)
  local        → Ollama: local open-source models

All providers expose OpenAI-compatible chat completions API.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, Optional

from openai import AzureOpenAI, OpenAI

from config import get_settings

logger = logging.getLogger(__name__)


def _make_azure_client(endpoint: str, api_key: str, api_version: str) -> AzureOpenAI:
    """Create Azure OpenAI client."""
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
    )


def _make_openai_compatible_client(base_url: str, api_key: str) -> OpenAI:
    """Create OpenAI-compatible client (for OpenRouter, Databricks, Ollama)."""
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
    )


@lru_cache(maxsize=10)
def _get_client(provider: str) -> AzureOpenAI | OpenAI:
    """Get or create cached client for a provider."""
    cfg = get_settings()

    if provider == "openrouter":
        if not cfg.openrouter_api_key:
            raise ValueError(
                "OpenRouter API key not set. Please set OPENROUTER_API_KEY in .env"
            )
        return _make_openai_compatible_client(
            cfg.openrouter_base_url,
            cfg.openrouter_api_key,
        )

    if provider == "api_provider":
        if not cfg.api_provider_key:
            raise ValueError("API provider credentials not set in .env")
        return _make_azure_client(
            cfg.api_provider_endpoint,
            cfg.api_provider_key,
            cfg.api_provider_version,
        )

    if provider == "local":
        logger.info("Using local Ollama endpoint at %s", cfg.local_llm_base_url)
        return _make_openai_compatible_client(cfg.local_llm_base_url, "local")

    raise ValueError(f"Unknown provider: {provider}. Supported: openrouter, api_provider, local")


class LLMClient:
    """
    High-level LLM interface used throughout fashion-twin.

    Supports multiple providers with automatic routing based on task type.

    Examples:
        # Use default provider for reward modeling
        client = LLMClient(role="reward")

        # Explicitly specify provider and model
        client = LLMClient(provider="openrouter", model="anthropic/claude-3.5-sonnet")

        # Use config-based task assignment
        client = LLMClient.for_task("deal")  # Uses deal-specific model from config
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        role: str = "reasoning",
    ) -> None:
        """
        Initialize LLM client.

        Args:
            provider: LLM provider (openrouter, api_provider, local)
                     If None, uses config default for the role
            model: Model name/identifier. If None, uses config default for the role
            role: Task role (reward, fast, reasoning, deal, general)
        """
        cfg = get_settings()

        if provider and model:
            self.provider = provider
            self.model = model
        else:
            # Get provider and model from settings based on role
            self.provider = provider or getattr(
                cfg, f"llm_{role}_provider", cfg.llm_primary_provider
            )
            self.model = model or getattr(
                cfg, f"llm_{role}_model", cfg.openrouter_vision_model
            )

        self._client = _get_client(self.provider)
        logger.debug(
            "LLMClient initialized: provider=%s model=%s role=%s",
            self.provider,
            self.model,
            role,
        )

    @classmethod
    def for_task(cls, task: str) -> LLMClient:
        """
        Create LLM client for a specific task using config.

        Args:
            task: One of 'reward', 'fast', 'reasoning', 'deal', 'general'

        Returns:
            Configured LLMClient instance
        """
        cfg = get_settings()
        llm_config = cfg.get_llm_config(task)
        return cls(provider=llm_config["provider"], model=llm_config["model"])

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 1024,
        response_format: Optional[dict] = None,
        **kwargs,
    ) -> str:
        """
        Send chat messages, return assistant content string.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            response_format: Optional format specification (e.g., {"type": "json_object"})
            **kwargs: Additional arguments passed to the API

        Returns:
            Assistant's response as string
        """
        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        # Some API providers (e.g., Azure) with certain models have specific requirements
        if self.provider == "api_provider" and "gpt-5" in self.model.lower():
            call_kwargs["max_completion_tokens"] = max_tokens
            # Some model variants only support temperature=1.0
            if "mini" not in self.model.lower():
                call_kwargs["temperature"] = temperature
        else:
            call_kwargs["max_tokens"] = max_tokens
            call_kwargs["temperature"] = temperature

        if response_format:
            call_kwargs["response_format"] = response_format

        call_kwargs.update(kwargs)

        try:
            resp = self._client.chat.completions.create(**call_kwargs)
            content = resp.choices[0].message.content or ""
            return content.strip()
        except Exception as e:
            logger.error(
                "LLM call failed: provider=%s model=%s error=%s",
                self.provider,
                self.model,
                str(e),
            )
            raise

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> dict:
        """
        Chat with JSON mode; parses and returns dict.

        Args:
            messages: List of message dicts
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            Parsed JSON response as dict
        """
        content = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Strip markdown fences if present
            clean = (
                content.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
            )
            try:
                return json.loads(clean)
            except json.JSONDecodeError as e:
                logger.error("Failed to parse JSON response: %s", content[:200])
                raise ValueError(f"Invalid JSON response from LLM: {e}") from e

    def system_user(
        self, system: str, user: str, temperature: float = 0.2, **kwargs
    ) -> str:
        """
        Convenience method for system + user message pattern.

        Args:
            system: System message (instructions)
            user: User message (query)
            temperature: Sampling temperature
            **kwargs: Additional arguments

        Returns:
            Assistant's response
        """
        return self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
            **kwargs,
        )

    def describe_image(
        self, image_url: str, prompt: str = "Describe this fashion item in detail.", **kwargs
    ) -> str:
        """
        Vision-language task: describe an image.

        Args:
            image_url: URL or base64 data URI of the image
            prompt: Instruction for the model
            **kwargs: Additional arguments

        Returns:
            Description of the image
        """
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        return self.chat(messages, **kwargs)


class EmbeddingClient:
    """
    Text embedding client supporting multiple backends.

    Can use external API providers or OpenRouter for text embeddings.
    """

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None) -> None:
        """
        Initialize embedding client.

        Args:
            provider: Embedding provider (api_provider, openrouter)
            model: Model identifier
        """
        cfg = get_settings()

        # Default to API provider if configured, otherwise OpenRouter
        self.provider = provider or ("api_provider" if cfg.embedding_api_endpoint else "openrouter")
        self.model = model or cfg.embedding_api_model
        self._dim = cfg.embedding_api_dim

        if self.provider == "api_provider":
            if not cfg.embedding_api_endpoint:
                raise ValueError("Embedding API endpoint not configured in .env")
            self._client = _make_azure_client(
                cfg.embedding_api_endpoint,
                cfg.embedding_api_key,
                cfg.embedding_api_version,
            )
        elif self.provider == "openrouter":
            self._client = _make_openai_compatible_client(
                cfg.openrouter_base_url,
                cfg.openrouter_api_key,
            )
            self.model = "openai/text-embedding-3-large"  # Available on OpenRouter
            self._dim = 3072
        else:
            raise ValueError(f"Unsupported embedding provider: {self.provider}")

    @property
    def dim(self) -> int:
        """Embedding dimensionality."""
        return self._dim

    def embed(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """
        Return embeddings for a list of strings (batched).

        Args:
            texts: List of strings to embed
            batch_size: Number of texts per API call

        Returns:
            List of embedding vectors
        """
        results: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                resp = self._client.embeddings.create(model=self.model, input=batch)
                results.extend([e.embedding for e in resp.data])
            except Exception as e:
                logger.error("Embedding failed for batch %d: %s", i, str(e))
                raise
        return results

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text."""
        return self.embed([text])[0]


# ══════════════════════════════════════════════════════════════════════════════
# Cached Convenience Getters
# ══════════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def get_reward_llm() -> LLMClient:
    """Get LLM client for reward modeling / fashion judging."""
    return LLMClient.for_task("reward")


@lru_cache(maxsize=1)
def get_fast_llm() -> LLMClient:
    """Get LLM client for fast inference (real-time preference scoring)."""
    return LLMClient.for_task("fast")


@lru_cache(maxsize=1)
def get_reasoning_llm() -> LLMClient:
    """Get LLM client for reasoning tasks (trend analysis, style profiling)."""
    return LLMClient.for_task("reasoning")


@lru_cache(maxsize=1)
def get_deal_llm() -> LLMClient:
    """Get LLM client for deal analysis and price evaluation."""
    return LLMClient.for_task("deal")


@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    """Get text embedding client."""
    return EmbeddingClient()
