#!/usr/bin/env python3
"""Check the LLM endpoint the way Know Thy Self will use it. Standard library only.

    python3 scripts/test_llm.py
    LLM_BASE_URL=http://192.168.1.80:8090/v1 LLM_MODEL=gemma-official python3 scripts/test_llm.py

The first request after the model was idle can take 20-30s while it loads.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("LLM_BASE_URL", "http://192.168.1.80:8090/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "gemma-official")
TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "600"))


def call(method: str, path: str, body: dict | None = None, timeout: int = TIMEOUT):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    return payload, time.monotonic() - started


def chat(extra: dict | None = None) -> tuple[dict, float]:
    body = {
        "model": MODEL,
        "max_tokens": 4096,
        "temperature": 0.9,
        "messages": [{"role": "user", "content": "Reply with exactly one word: pong"}],
    }
    body.update(extra or {})
    return call("POST", "/chat/completions", body)


def describe(payload: dict, seconds: float) -> dict:
    choice = payload["choices"][0]
    msg = choice.get("message", {})
    usage = payload.get("usage", {})
    return {
        "content": (msg.get("content") or "").strip(),
        "reasoning_chars": len(msg.get("reasoning_content") or ""),
        "finish": choice.get("finish_reason"),
        "completion_tokens": usage.get("completion_tokens"),
        "seconds": round(seconds, 1),
    }


def main() -> int:
    print(f"Endpoint: {BASE}\nModel:    {MODEL}\n")

    print("1) GET /models")
    try:
        models, secs = call("GET", "/models", timeout=5)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"   FAILED: {exc}\n   The server is unreachable. Is the machine on, and is this the right address?")
        return 1
    ids = [m.get("id") for m in models.get("data", [])]
    print(f"   ok in {secs:.2f}s. Models: {', '.join(map(str, ids)) or '(none listed)'}")
    if MODEL not in ids:
        print(f"   WARNING: '{MODEL}' is not in that list. Set LLM_MODEL to one of the names above.")

    print("\n2) Chat with thinking at the server default (this may load the model; be patient)")
    try:
        default, secs = chat()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"   FAILED: {exc}")
        return 1
    d = describe(default, secs)
    print(f"   {d}")
    if not d["content"]:
        print("   PROBLEM: content is empty. Thinking probably used all the tokens.")

    print("\n3) Chat with chat_template_kwargs.enable_thinking = false")
    try:
        off, secs = chat({"chat_template_kwargs": {"enable_thinking": False}})
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"   FAILED: {exc}")
        return 1
    o = describe(off, secs)
    print(f"   {o}")

    print("\nSummary")
    print(f"   Answer with default settings: {d['content']!r}")
    works = o["reasoning_chars"] == 0 and d["reasoning_chars"] > 0
    if d["reasoning_chars"] == 0:
        print("   Thinking was not present in step 2, so there is nothing to turn off.")
    elif works:
        print("   The enable_thinking=false switch WORKS (no reasoning came back). It is safe to use for summaries.")
    else:
        print("   The enable_thinking=false switch did NOT stop reasoning on this server. Leave LLM_ENABLE_THINKING=true.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
