"""The Jev wire, copied from leakhunt 7ccbdd3 (the laptop leak tools; read-only source) llm: a JSON POST and the price
table, rewritten from httpx onto urllib (the service image has no httpx). Local: Jev's price only; the judge's DeepSeek
call is profile_extract.deepseek_json. Stdlib only."""
import http.client
import json
import urllib.error
import urllib.request

PRICES = {"jev-1.13.0": (0.042, 0.0)}  # USD per 1M tokens (input, output), 2026-10
MAX_BODY = 1_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a 3xx surfaces as HTTPError, as with httpx: the Authorization header never follows a redirect


_opener = urllib.request.build_opener(_NoRedirect)


def post_json(url, body, headers, timeout):
    """POST `body` as JSON -> (status, headers, body bytes) for any HTTP answer, 3xx / 4xx / 5xx included. Raises
    OSError on a transport failure (timeout, refused, reset, a cut response)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with _opener.open(req, timeout=timeout) as r:
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
    pin, pout = PRICES[model]
    return (tin * pin + tout * pout) / 1_000_000
