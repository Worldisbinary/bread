"""LLM access with the reliability a long simulation needs.

- Any OpenAI-compatible endpoint (Groq by default; Ollama or others by URL).
- A token-per-minute limiter per model, so a run paces itself under free-tier
  limits instead of failing on 429s; on a 429 it waits for the time the provider asks.
- A response cache keyed by the full request: re-running a seed replays identical
  outputs at zero cost, which makes experiments reproducible and debuggable.
- Usage accounting (requests, tokens, cache hits, latency) for observability.
- FakeLLM for tests: deterministic, offline, scripted by a function.
"""

import hashlib
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "r-life/0.1"  # Groq's CDN rejects Python's default agent


class LLMError(Exception):
    pass


@dataclass
class Completion:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    latency_s: float = 0.0


@dataclass
class Usage:
    requests: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    errors: int = 0
    by_model: dict = field(default_factory=dict)

    def add(self, model: str, c: Completion) -> None:
        if c.cached:
            self.cache_hits += 1
        else:
            self.requests += 1
            self.prompt_tokens += c.prompt_tokens
            self.completion_tokens += c.completion_tokens
            self.latency_s += c.latency_s
        m = self.by_model.setdefault(model, {"requests": 0, "tokens": 0})
        m["requests"] += 0 if c.cached else 1
        m["tokens"] += 0 if c.cached else c.prompt_tokens + c.completion_tokens


def parse_json(text: str):
    """Parse a JSON object or array from a model reply, tolerating code fences and chatter."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if match:
            return json.loads(match.group(1))
        raise


class RateLimiter:
    """Sliding one-minute window of estimated tokens per model."""

    def __init__(self, tokens_per_minute: int, clock=time.monotonic, sleep=time.sleep) -> None:
        self.tpm = tokens_per_minute
        self.clock, self.sleep = clock, sleep
        self.window: deque[tuple[float, int]] = deque()
        self.lock = threading.Lock()

    def acquire(self, tokens: int) -> None:
        tokens = min(tokens, self.tpm)
        while True:
            with self.lock:
                now = self.clock()
                while self.window and now - self.window[0][0] >= 60:
                    self.window.popleft()
                used = sum(t for _, t in self.window)
                if used + tokens <= self.tpm:
                    self.window.append((now, tokens))
                    return
                wait = 60 - (now - self.window[0][0]) + 0.05
            self.sleep(wait)


class Cache:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, json.dumps(value)))
            self.db.commit()


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        tokens_per_minute: int = 7500,
        cache: Cache | None = None,
        reasoning_effort: str | None = "low",
        timeout: float = 60,
        max_quota_wait_s: float = 4 * 3600,
        sleep=time.sleep,
    ) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.tpm = tokens_per_minute
        self.cache = cache
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self.sleep = sleep
        self.limiters: dict[str, RateLimiter] = {}
        self.max_quota_wait_s = max_quota_wait_s
        self.quota_waits = 0
        self.usage = Usage()

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        max_tokens: int = 400,
        temperature: float = 0.9,
        json_mode: bool = False,
        seed: int | None = None,
    ) -> Completion:
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort and "gpt-oss" in model:
            body["reasoning_effort"] = self.reasoning_effort
        if seed is not None:
            body["seed"] = seed
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if self.cache and (hit := self.cache.get(key)):
            c = Completion(hit["text"], hit["prompt_tokens"], hit["completion_tokens"], cached=True)
            self.usage.add(model, c)
            return c

        # Typical replies use a fraction of max_tokens; if this underestimates, the provider's 429
        # and retry-after handling below absorbs it.
        estimate = sum(len(m["content"]) for m in messages) // 4 + min(max_tokens, 300)
        limiter = self.limiters.setdefault(model, RateLimiter(self.tpm, sleep=self.sleep))
        attempt = 0
        quota_waited = 0.0
        while attempt < 6:
            limiter.acquire(estimate)
            started = time.perf_counter()
            try:
                data = self._post(body)
            except _BadJSON:
                if "response_format" not in body:
                    raise LLMError(f"{model}: invalid JSON even without strict mode") from None
                self.usage.errors += 1
                body = {k: v for k, v in body.items() if k != "response_format"}  # lenient parse instead
                continue
            except _Retry as exc:
                self.usage.errors += 1
                if exc.daily:
                    # A rolling daily quota frees up within minutes. Pause rather than drop the turn,
                    # so experiment arms stay comparable; give up only after max_quota_wait_s.
                    if quota_waited + exc.after > self.max_quota_wait_s:
                        raise LLMError(f"{model}: daily quota still exhausted after waiting") from exc
                    self.quota_waits += 1
                    quota_waited += exc.after + 1
                    self.sleep(exc.after + 1)
                    continue
                attempt += 1
                self.sleep(min(exc.after, 65) + attempt)
                continue
            message = data["choices"][0]["message"]
            usage = data.get("usage", {})
            c = Completion(
                (message.get("content") or "").strip(),
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                latency_s=time.perf_counter() - started,
            )
            if self.cache:
                self.cache.put(
                    key,
                    {
                        "text": c.text,
                        "prompt_tokens": c.prompt_tokens,
                        "completion_tokens": c.completion_tokens,
                    },
                )
            self.usage.add(model, c)
            return c
        raise LLMError(f"{model}: still rate limited after retries")

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:300]
            if exc.code == 429 or exc.code >= 500:
                after = exc.headers.get("retry-after") if exc.headers else None
                match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", detail)
                wait = (
                    float(after)
                    if after
                    else (int(match.group(1) or 0) * 60 + float(match.group(2)) if match else 10.0)
                )
                daily = "per day" in detail or "TPD" in detail or "RPD" in detail
                raise _Retry(wait, daily=daily) from exc
            if exc.code == 400 and "json_validate_failed" in detail:
                raise _BadJSON() from exc
            raise LLMError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise _Retry(5.0) from exc


class _BadJSON(Exception):
    pass


class _Retry(Exception):
    def __init__(self, after: float, daily: bool = False) -> None:
        super().__init__(after)
        self.after = after
        self.daily = daily


class FakeLLM:
    """Offline stand-in. `respond(messages, model)` returns the reply text."""

    def __init__(self, respond: Callable[[list[dict], str], str]) -> None:
        self.respond = respond
        self.calls: list[dict] = []
        self.usage = Usage()

    def complete(self, messages, *, model, max_tokens=400, temperature=0.9, json_mode=False, seed=None):
        self.calls.append({"model": model, "messages": messages})
        c = Completion(self.respond(messages, model), prompt_tokens=100, completion_tokens=50)
        self.usage.add(model, c)
        return c
