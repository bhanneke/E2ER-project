"""The kit's HTTP client: polite to the source, and replayable in tests.

``PoliteClient`` spaces requests to one source (``Polite.min_interval``, shared
by every client of that source in the process), retries after HTTP 429, 502,
503 and 504 (honouring ``Retry-After``), names e2er in its User-Agent, stops
an operation that would make more than ``Polite.max_requests`` requests, and
turns every failure into a :class:`~.base.FetchError` whose message names the
URL and the status.

Recorded fixtures (``use_cassette``): a test records the source's responses
once, live (``E2ER_RECORD_FIXTURES=1``), into a JSON file under
``tests/data/fixtures/``; afterwards it replays them with no network. A
request the cassette has no response for fails the test with the URL, so CI
never reaches a live service.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .base import FetchError, Polite

#: The transport every PoliteClient uses instead of the network while a cassette is active.
_TRANSPORT: contextvars.ContextVar[httpx.AsyncBaseTransport | None] = contextvars.ContextVar(
    "e2er_kit_transport", default=None
)
#: When each source was last asked (monotonic seconds), for the spacing between requests.
_LAST_CALL: dict[str, float] = {}
_RETRY_STATUS = frozenset({429, 502, 503, 504})
#: False in tests that mock the network (respx): no waiting between requests or before a retry.
PACING = True


def user_agent() -> str:
    from .... import __version__

    return f"e2er/{__version__} (+https://e2er.org; research data connector)"


class PoliteClient:
    """An httpx client for one source, used as ``async with PoliteClient("usgs", polite) as http``."""

    def __init__(self, source: str, polite: Polite | None = None) -> None:
        self.source = source
        self.polite = polite or Polite()
        #: Every URL requested, in order (with its query string).
        self.requests: list[str] = []
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> PoliteClient:
        headers = {"User-Agent": user_agent(), **dict(self.polite.headers)}
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.polite.timeout),
            follow_redirects=True,
            headers=headers,
            transport=_TRANSPORT.get(),
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _pace(self) -> None:
        last = _LAST_CALL.get(self.source)
        if last is not None:
            wait = last + self.polite.min_interval - time.monotonic()
            if wait > 0 and PACING and _TRANSPORT.get() is None:
                await asyncio.sleep(wait)
        _LAST_CALL[self.source] = time.monotonic()

    async def get(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """GET ``url``; the response when it is 2xx, else a FetchError naming the URL and status."""
        if self._client is None:
            raise RuntimeError("use PoliteClient as `async with PoliteClient(...) as http`")
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        attempt = 0
        while True:
            if len(self.requests) >= self.polite.max_requests:
                raise FetchError(
                    f"this load would need more than {self.polite.max_requests} requests to {self.source}; "
                    "ask for less (a shorter period, fewer series)"
                )
            await self._pace()
            # No params: keep the URL's own query (a "next" link); httpx would replace it with an empty one.
            request = self._client.build_request("GET", url, params=clean or None, headers=headers)
            self.requests.append(str(request.url))
            try:
                resp = await self._client.send(request)
            except httpx.HTTPError as e:
                if attempt < self.polite.retries and isinstance(e, httpx.TransportError):
                    attempt += 1
                    await self._backoff(attempt, None)
                    continue
                raise FetchError(f"{request.url}: transport error: {type(e).__name__}: {e}") from None
            if resp.status_code in _RETRY_STATUS and attempt < self.polite.retries:
                attempt += 1
                await self._backoff(attempt, resp.headers.get("Retry-After"))
                continue
            if resp.status_code // 100 != 2:
                body = " ".join(resp.text[:300].split())
                raise FetchError(f"{request.url}: HTTP {resp.status_code}" + (f": {body}" if body else ""))
            return resp

    async def _backoff(self, attempt: int, retry_after: str | None) -> None:
        if not PACING or _TRANSPORT.get() is not None:
            return  # replaying a cassette, or a mocked network: no waiting
        try:
            wait = float(retry_after) if retry_after else 2.0 ** (attempt - 1)
        except ValueError:
            wait = 2.0 ** (attempt - 1)
        await asyncio.sleep(min(wait, 30.0))

    async def get_json(self, url: str, params: dict[str, Any] | None = None, **kw: Any) -> Any:
        resp = await self.get(url, params, **kw)
        try:
            return resp.json()
        except ValueError as e:
            raise FetchError(f"{resp.request.url}: not JSON ({e})") from None

    async def get_text(self, url: str, params: dict[str, Any] | None = None, **kw: Any) -> str:
        return (await self.get(url, params, **kw)).text

    async def get_bytes(self, url: str, params: dict[str, Any] | None = None, **kw: Any) -> bytes:
        return (await self.get(url, params, **kw)).content


# ── recorded fixtures ────────────────────────────────────────────────────────


def _canonical(url: str) -> str:
    """A URL with its query parameters sorted, so the same request matches however it was built."""
    parts = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


class Cassette:
    """Responses of a source, recorded once and replayed in tests (see ``use_cassette``)."""

    def __init__(self, path: Path, record: bool) -> None:
        self.path = Path(path)
        self.record = record
        self.entries: list[dict[str, Any]] = []
        if not record:
            if not self.path.is_file():
                raise FileNotFoundError(
                    f"no recorded fixture {self.path}; record it once with E2ER_RECORD_FIXTURES=1 (live requests)"
                )
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))["interactions"]
        self._served: dict[int, int] = {}

    def transport(self) -> httpx.AsyncBaseTransport:
        return _Recorder(self) if self.record else _Replayer(self)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "$comment": "Recorded live by the e2er connector kit (use_cassette); replayed in tests with no network.",
            "interactions": self.entries,
        }
        self.path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _body_out(content: bytes, content_type: str) -> dict[str, str]:
    textual = any(t in content_type for t in ("json", "text", "csv", "xml", "javascript"))
    if textual:
        try:
            return {"text": content.decode("utf-8")}
        except UnicodeDecodeError:
            pass
    return {"base64": base64.b64encode(content).decode("ascii")}


class _Recorder(httpx.AsyncBaseTransport):
    def __init__(self, cassette: Cassette) -> None:
        self._cassette = cassette
        self._real = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        resp = await self._real.handle_async_request(request)
        content = await resp.aread()
        ctype = resp.headers.get("content-type", "")
        self._cassette.entries.append(
            {
                "method": request.method,
                "url": _canonical(str(request.url)),
                "status": resp.status_code,
                "content_type": ctype,
                **_body_out(content, ctype),
            }
        )
        return httpx.Response(resp.status_code, headers={"content-type": ctype} if ctype else {}, content=content)

    async def aclose(self) -> None:
        pass  # one real transport serves every client of the cassette; closed with the process


class _Replayer(httpx.AsyncBaseTransport):
    def __init__(self, cassette: Cassette) -> None:
        self._cassette = cassette

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = _canonical(str(request.url))
        matches = [i for i, e in enumerate(self._cassette.entries) if e["method"] == request.method and e["url"] == url]
        if not matches:
            raise AssertionError(
                f"the recorded fixture {self._cassette.path.name} has no response for {request.method} {url}; "
                "record it again with E2ER_RECORD_FIXTURES=1"
            )
        # The same request twice: the recorded responses in order, the last one repeated.
        served = self._cassette._served.get(hash(url), 0)
        entry = self._cassette.entries[matches[min(served, len(matches) - 1)]]
        self._cassette._served[hash(url)] = served + 1
        content = entry["text"].encode("utf-8") if "text" in entry else base64.b64decode(entry.get("base64", ""))
        headers = {"content-type": entry["content_type"]} if entry.get("content_type") else {}
        return httpx.Response(entry["status"], headers=headers, content=content, request=request)


@contextlib.contextmanager
def use_cassette(path: Path | str, record: bool | None = None) -> Iterator[Cassette]:
    """Replay the responses recorded in ``path`` (or record them live, ``E2ER_RECORD_FIXTURES=1``).

    Every ``PoliteClient`` opened inside the block uses the cassette instead of
    the network; replay does not wait between requests.
    """
    if record is None:
        record = os.environ.get("E2ER_RECORD_FIXTURES") == "1"
    cassette = Cassette(Path(path), record)
    token = _TRANSPORT.set(cassette.transport())
    try:
        yield cassette
    finally:
        _TRANSPORT.reset(token)
        if record:
            cassette.save()
