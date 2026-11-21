"""Model access. Every model is called through OpenRouter's chat completions API.

OpenRouter gives one request format for every vendor's models, so the harness
has one code path and no model gets special handling. Standard library only.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API = "https://openrouter.ai/api/v1/chat/completions"
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}
ATTEMPTS = 5


class ModelError(RuntimeError):
    """The model could not be reached or the request was rejected."""

    out_of_credit = False


class OutOfCredit(ModelError):
    """The OpenRouter account has no credit left. Nothing else can run until it is topped up."""

    out_of_credit = True


class OpenRouter:
    def __init__(self, timeout_s: int = 600, provider_prefs: dict | None = None):
        self.key = os.environ.get("OPENROUTER_API_KEY")
        if not self.key:
            raise ModelError("OPENROUTER_API_KEY is not set in this process.")
        self.timeout_s = timeout_s
        self.provider_prefs = provider_prefs or {}

    def complete(self, model: str, messages: list[dict], tools: list[dict], tool_choice: str,
                 max_tokens: int, extra: dict | None = None) -> dict:
        """One request. Returns {"message", "finish_reason", "usage", "provider", "id"}.

        Retries only on failures of the connection or the service (rate limits,
        server errors, timeouts). It never retries because of what a model wrote.
        """
        body = {"model": model, "messages": messages, "tools": tools, "tool_choice": tool_choice,
                "max_tokens": max_tokens, "usage": {"include": True}}
        if self.provider_prefs:
            body["provider"] = self.provider_prefs
        body.update(extra or {})
        data = json.dumps(body).encode()
        last = "unknown error"
        for attempt in range(ATTEMPTS):
            if attempt:
                time.sleep(min(60, 3 * 2 ** attempt))
            req = urllib.request.Request(API, data=data, method="POST")
            req.add_header("Authorization", "Bearer " + self.key)
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    out = json.load(resp)
            except urllib.error.HTTPError as err:
                detail = err.read().decode(errors="replace")
                last = f"HTTP {err.code}: {detail[:400]}"
                if err.code in RETRY_STATUS:
                    continue
                if err.code == 402:
                    # OpenRouter holds back credit for requests still running. With a low
                    # balance that hold can block a new request for a short while.
                    if "in_flight" in detail and attempt < ATTEMPTS - 1:
                        time.sleep(20)
                        continue
                    raise OutOfCredit(f"{model}: {last}") from err
                raise ModelError(f"{model}: {last}") from err
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as err:
                last = f"{type(err).__name__}: {err}"
                continue
            # OpenRouter can report an upstream failure inside a 200 response.
            error = out.get("error") or ((out.get("choices") or [{}])[0].get("error"))
            if error:
                code = error.get("code") if isinstance(error, dict) else None
                last = f"upstream error {code}: {str(error)[:400]}"
                if code is None or code in RETRY_STATUS or (isinstance(code, int) and code >= 500):
                    continue
                raise ModelError(f"{model}: {last}")
            if not out.get("choices"):
                last = "response had no choices"
                continue
            choice = out["choices"][0]
            return {"message": choice.get("message") or {}, "finish_reason": choice.get("finish_reason"),
                    "usage": out.get("usage") or {}, "provider": out.get("provider"), "id": out.get("id")}
        raise ModelError(f"{model}: gave up after {ATTEMPTS} attempts ({last})")
