"""OpenRouter's model list: what each model costs and whether it can call tools.

OpenRouter publishes every model it routes, with per-token prices, at a public
endpoint (no key needed). e2er reads it once at the start of a run, keeps a copy
under ``~/.e2er/cache/`` for a day, and uses it

* to price calls when a response does not report its own cost (OpenRouter
  normally does: ``usage.cost``), so a model missing from the fixed table in
  ``tracking/costs.py`` is not charged the $3/$15 guess, and
* to offer the setup page a model picker: the models that support tool calls,
  with their price.

Nothing here raises: without network and without a cached copy the list is
empty and callers fall back to the fixed table.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

MODELS_URL = "https://openrouter.ai/api/v1/models"
#: A cached list older than this is fetched again (a stale copy is still used when offline).
_REFRESH_SECONDS = 24 * 3600
_TIMEOUT_SECONDS = 10.0
_MILLION = Decimal("1000000")

_memory: dict[str, OpenRouterModel] | None = None


@dataclass(frozen=True)
class OpenRouterModel:
    id: str
    name: str
    #: USD per million tokens. ``None`` when OpenRouter lists no price.
    input_per_m: str | None
    output_per_m: str | None
    cache_read_per_m: str | None
    context_length: int
    tools: bool

    def rates(self) -> tuple[Decimal, Decimal, Decimal | None] | None:
        if self.input_per_m is None or self.output_per_m is None:
            return None
        cache = Decimal(self.cache_read_per_m) if self.cache_read_per_m is not None else None
        return Decimal(self.input_per_m), Decimal(self.output_per_m), cache

    def price_label(self) -> str:
        """``$0.23 in / $0.46 out per million tokens`` (``free`` when both are zero)."""
        r = self.rates()
        if r is None:
            return "price not listed"
        inp, out, _ = r
        if inp == 0 and out == 0:
            return "free"
        return f"${_short(inp)} in / ${_short(out)} out per million tokens"


def _short(d: Decimal) -> str:
    if d >= 10:
        return f"{d:.0f}"
    if d >= Decimal("0.1"):
        return f"{d:.2f}"
    return f"{d:.3f}"


def _per_million(raw: Any) -> str | None:
    """OpenRouter lists USD per token as a string (``"0.00000022794"``)."""
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if d < 0:  # "-1" marks a router whose price depends on the model it picks
        return None
    return str((d * _MILLION).normalize())


def parse_models(payload: dict[str, Any]) -> dict[str, OpenRouterModel]:
    out: dict[str, OpenRouterModel] = {}
    for m in payload.get("data") or []:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        pricing = m.get("pricing") or {}
        params = m.get("supported_parameters") or []
        out[str(m["id"])] = OpenRouterModel(
            id=str(m["id"]),
            name=str(m.get("name") or m["id"]),
            input_per_m=_per_million(pricing.get("prompt")),
            output_per_m=_per_million(pricing.get("completion")),
            cache_read_per_m=_per_million(pricing["input_cache_read"]) if "input_cache_read" in pricing else None,
            context_length=int(m.get("context_length") or 0),
            tools="tools" in params,
        )
    return out


def cache_file() -> Path:
    return Path.home() / ".e2er" / "cache" / "openrouter-models.json"


def _read_cache() -> tuple[dict[str, OpenRouterModel], float] | None:
    try:
        raw = json.loads(cache_file().read_text(encoding="utf-8"))
        models = {m["id"]: OpenRouterModel(**m) for m in raw["models"]}
        return models, float(raw["fetched_at"])
    except Exception:  # noqa: BLE001 — a missing or damaged cache is just absent
        return None


def _write_cache(models: dict[str, OpenRouterModel]) -> None:
    try:
        path = cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"fetched_at": time.time(), "models": [asdict(m) for m in models.values()]}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        logger.debug("could not cache the OpenRouter model list: %s", e)


def _fetch() -> dict[str, OpenRouterModel] | None:
    import httpx

    try:
        resp = httpx.get(MODELS_URL, timeout=_TIMEOUT_SECONDS, follow_redirects=True)
        resp.raise_for_status()
        models = parse_models(resp.json())
    except Exception as e:  # noqa: BLE001 — offline or OpenRouter down: fall back
        logger.info("OpenRouter model list not available (%s); using cached or fixed prices", e)
        return None
    return models or None


def load_models(*, refresh: bool = False, network: bool = True) -> dict[str, OpenRouterModel]:
    """The model list: from memory, a fresh cache, OpenRouter, or a stale cache, in that order.

    ``network=False`` never fetches (for pricing a call in the middle of a run).
    """
    global _memory
    if _memory is not None and not refresh:
        return _memory
    cached = _read_cache()
    if cached and not refresh and (time.time() - cached[1]) < _REFRESH_SECONDS:
        _memory = cached[0]
        return _memory
    if network:
        fetched = _fetch()
        if fetched:
            _write_cache(fetched)
            _memory = fetched
            return _memory
    if cached:
        _memory = cached[0]
        return _memory
    return {}


def canonical_id(model: str) -> str:
    """OpenRouter's own spelling of a model id.

    OpenRouter accepts ``anthropic/claude-sonnet-4-5`` but lists it as
    ``anthropic/claude-sonnet-4.5``; e2er's settings use the first form.
    """
    return re.sub(r"(?<=\d)-(?=\d)", ".", model)


def find_model(model: str, *, network: bool = False) -> OpenRouterModel | None:
    models = load_models(network=network)
    return models.get(model) or models.get(canonical_id(model))


def model_rates(model: str) -> tuple[Decimal, Decimal, Decimal | None] | None:
    """USD per million (input, output, cache read) for an OpenRouter model id, or None.

    Reads only what is already loaded or cached; never goes to the network.
    """
    m = find_model(model)
    return m.rates() if m else None


def tool_models() -> list[OpenRouterModel]:
    """The models that can call tools (e2er's specialists need them), by name.

    The ``:batch`` variants are left out: they answer within hours, not during a run.
    """
    return sorted(
        (m for m in load_models().values() if m.tools and not m.id.endswith(":batch")),
        key=lambda m: m.name.lower(),
    )


def _reset_for_tests() -> None:
    global _memory
    _memory = None
