"""OpenAI-compatible chat client for the local LLM (llama-swap in front of llama.cpp).

Only `message.content` is used; `reasoning_content` is discarded. One call runs at a time
because the server has a single slot (--parallel 1).
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ..config import settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """An error whose message is safe and useful to show to the user."""


@dataclass
class LLMResult:
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: str | None
    seconds: float


_lock = asyncio.Lock()


def host() -> str:
    return urlparse(settings.llm_base_url).netloc or settings.llm_base_url


def unreachable_message(detail: str = "") -> str:
    msg = f"LLM server unreachable ({host()}). Is the machine on?"
    return f"{msg} [{detail}]" if detail else msg


async def check_reachable(timeout: float = 3.0) -> tuple[bool, str]:
    """GET /models. Does not load the model, so it is cheap and safe to call often."""
    url = settings.llm_base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
    except httpx.HTTPError as exc:
        return False, type(exc).__name__
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    return True, "online"


async def chat(
    messages: list[dict],
    *,
    temperature: float = 0.9,
    max_tokens: int | None = None,
    thinking: bool | None = None,
) -> LLMResult:
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    payload: dict = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "stream": False,
    }
    if thinking is None:
        thinking = settings.llm_enable_thinking
    if not thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": False}

    timeout = httpx.Timeout(settings.llm_timeout, connect=5.0)
    async with _lock:
        started = time.monotonic()
        response: httpx.Response | None = None
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, json=payload)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise LLMError(unreachable_message(type(exc).__name__)) from exc
            except httpx.TimeoutException as exc:
                if attempt == 1:
                    log.warning("LLM request timed out; retrying once")
                    continue
                raise LLMError(
                    f"The LLM did not answer within {settings.llm_timeout}s (tried twice)."
                ) from exc
            except httpx.HTTPError as exc:
                raise LLMError(f"Network error talking to the LLM: {type(exc).__name__}: {exc}") from exc
        seconds = time.monotonic() - started

    assert response is not None
    if response.status_code != 200:
        snippet = response.text.strip().replace("\n", " ")[:300]
        raise LLMError(f"LLM server returned HTTP {response.status_code}: {snippet}")

    try:
        data = response.json()
        choice = data["choices"][0]
        content = (choice.get("message", {}).get("content") or "").strip()
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("The LLM server returned a response in an unexpected format.") from exc

    finish = choice.get("finish_reason")
    if not content:
        if finish == "length":
            raise LLMError(
                "The model used all of its output tokens (mostly on thinking) before writing an "
                f"answer. Raise LLM_MAX_TOKENS (currently {settings.llm_max_tokens}) or try a "
                "smaller scope."
            )
        raise LLMError(f"The model returned an empty answer (finish reason: {finish}).")

    usage = data.get("usage") or {}
    if finish == "length":
        log.warning("LLM answer was cut off by max_tokens")
        content += "\n\n_[The answer was cut off because it hit the output token limit.]_"
    return LLMResult(
        content=content,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        finish_reason=finish,
        seconds=seconds,
    )
