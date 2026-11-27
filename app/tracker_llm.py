"""The Leak judge's model wire, copied from leakhunt 7ccbdd3 (the laptop leak tools; read-only source) llm: the DeepSeek
JSON-mode request, parse_json and the price table, rewritten from httpx onto urllib (the service image has no httpx).
Local: DeepSeek only, URL and DEEPSEEK_MODEL as chat_proxy / profile_extract read them; no spend ledger: callers
get the token counts (tracker usage books them). The key never appears in errors. Stdlib only."""
import http.client
import json
import os
import re
import urllib.error
import urllib.request

KEY_ENV = "DEEPSEEK_API_KEY"
JSON_ONLY = "\n\nRespond with a single JSON object and nothing else."
PRICES = {"deepseek-chat": (0.27, 1.10), "jev-1.13.0": (0.042, 0.0)}  # USD per 1M tokens (input, output), 2026-10
FALLBACK_PRICE = (15.0, 75.0)
MAX_BODY = 1_000_000
_FENCE = re.compile(r"^```[a-zA-Z]*\s*(.*?)\s*```$", re.DOTALL)


class LLMError(Exception):
    pass


def post_json(url, body, headers, timeout):
    """POST `body` as JSON -> (status, headers, body bytes) for any HTTP answer, 4xx / 5xx included. Raises OSError
    on a transport failure (timeout, refused, reset, a cut response)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read(MAX_BODY)
    except urllib.error.HTTPError as e:
        try:
            data = e.read(MAX_BODY)
        except (OSError, http.client.HTTPException):
            data = b""
        return e.code, e.headers, data
    except http.client.HTTPException as e:
        raise OSError(f"{type(e).__name__}") from None


def cost(model, tin, tout):
    pin, pout = PRICES.get(model, FALLBACK_PRICE)
    return (tin * pin + tout * pout) / 1_000_000


def parse_json(text):
    """json.loads after stripping a ``` fence; models add one even in JSON mode."""
    text = text.strip()
    if m := _FENCE.match(text):
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM returned invalid JSON: {e}: {text[:200]!r}") from None


def complete_json(system, user, *, max_tokens=4000, timeout=90, post=post_json):
    """One DeepSeek JSON-mode call -> (parsed JSON, input tokens, output tokens). Raises LLMError on any failure."""
    import chat_proxy

    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise LLMError(f"{KEY_ENV} is not set")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    body = {"model": model, "max_tokens": max_tokens, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system + JSON_ONLY}, {"role": "user", "content": user}]}
    if model.startswith("deepseek-v4"):
        body["thinking"] = {"type": "disabled"}
    try:
        status, _, raw = post(chat_proxy.DEEPSEEK_URL, body, {"Authorization": f"Bearer {key}"}, timeout)
    except OSError as e:
        raise LLMError(f"deepseek request failed: {type(e).__name__}") from None
    if status >= 400:
        detail = raw[:300].decode("utf-8", "replace").replace(key, "***")
        raise LLMError(f"deepseek HTTP {status}: {detail}")
    try:
        data = json.loads(raw)
        text = data["choices"][0]["message"]["content"]
        u = data.get("usage") or {}
        tin, tout = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
        raise LLMError(f"deepseek unexpected response shape: {type(e).__name__}") from None
    return parse_json(text), tin, tout
