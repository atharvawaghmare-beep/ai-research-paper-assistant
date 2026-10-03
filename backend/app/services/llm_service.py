from __future__ import annotations

import logging
import time

import httpx

from app.config.settings import get_settings

settings = get_settings()
logger = logging.getLogger("app.llm")


class LLMGenerationError(RuntimeError):
    """Raised when the configured LLM backend fails to produce a response."""


def generate_chat_completion(messages: list[dict[str, str]]) -> str:
    """Generate a chat completion from the configured LLM backend.

    `messages` is a plain list of {"role": "system"|"user"|"assistant", "content": str}
    dicts — the shape every major chat API (Ollama, Anthropic, OpenAI) uses — and the
    return value is a plain string. Callers never see anything Ollama-specific, so
    swapping the backend later (e.g. to the Anthropic or OpenAI API) means rewriting
    the body of this one function, not any caller.

    Currently backed by a local Ollama server (see OLLAMA_BASE_URL / OLLAMA_MODEL).
    Every call is logged with latency and token counts — the closest local-model
    equivalent of "cost" (Ollama itself is free to run; token volume is what a
    hosted-API swap would actually be billed on).
    """
    start = time.perf_counter()
    try:
        response = httpx.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=settings.llm_request_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        elapsed = time.perf_counter() - start
        logger.warning("llm_call_failed model=%s elapsed_s=%.2f error=%s", settings.ollama_model, elapsed, error)
        raise LLMGenerationError(f"Ollama request failed: {error}") from error

    elapsed = time.perf_counter() - start
    body = response.json()
    content = body.get("message", {}).get("content")
    if not content:
        logger.warning("llm_call_empty_response model=%s elapsed_s=%.2f", settings.ollama_model, elapsed)
        raise LLMGenerationError(f"Ollama returned an empty response: {body}")

    prompt_tokens = body.get("prompt_eval_count")
    completion_tokens = body.get("eval_count")
    total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
    logger.info(
        "llm_call model=%s elapsed_s=%.2f prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        settings.ollama_model,
        elapsed,
        prompt_tokens,
        completion_tokens,
        total_tokens,
    )
    return content
