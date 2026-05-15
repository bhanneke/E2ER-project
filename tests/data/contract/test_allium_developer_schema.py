"""Contract tests for Lane C — Allium Developer-tier REST endpoints.

These tests pin our `AlliumDeveloperProvider` method signatures against
Allium's published OpenAPI specs. They run on every PR that touches Lane
C, and a nightly schema-drift workflow re-fetches the upstream specs and
opens an issue if anything changes.

Why this exists: live paper runs #14-#18 all surfaced wrapper-vs-Allium
schema mismatches (wrong param names, list-vs-object body shapes, silent
date-filter ignores). Each of those cost a real specialist invocation
plus hours of debugging. These tests catch the same class of bug in
~50ms, on the PR, before merge.

Fixtures: tests/data/fixtures/*-api.json are snapshots of
https://docs.allium.so/_openapi/{tokens,wallet,balances,prices}-api.json.
The nightly workflow refreshes them. Local devs can refresh with:

    for e in tokens wallet balances prices; do
      curl -sf "https://docs.allium.so/_openapi/${e}-api.json" \\
        -o "tests/data/fixtures/${e}-api.json"
    done
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from src.modules.data.allium_developer import AlliumDeveloperProvider

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load_spec(name: str) -> dict[str, Any]:
    path = _FIXTURES / f"{name}-api.json"
    if not path.exists():
        pytest.skip(f"fixture missing: {path} — run the fetch loop in the docstring")
    return json.loads(path.read_text(encoding="utf-8"))


def _endpoint(spec: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    """Return the endpoint definition or skip the test cleanly if missing."""
    paths = spec.get("paths", {})
    endpoint = paths.get(path) or paths.get(f"/api/v1{path}")
    if endpoint is None:
        pytest.fail(f"endpoint {path} not found in spec")
    method_def = endpoint.get(method.lower())
    if method_def is None:
        pytest.fail(f"endpoint {path} {method} not found in spec")
    return method_def


def _query_param_names(endpoint_def: dict[str, Any]) -> set[str]:
    return {p["name"] for p in endpoint_def.get("parameters", []) if p.get("in") == "query"}


def _required_query_params(endpoint_def: dict[str, Any]) -> set[str]:
    return {
        p["name"] for p in endpoint_def.get("parameters", []) if p.get("in") == "query" and p.get("required", False)
    }


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a `#/components/schemas/X` ref against the spec."""
    parts = ref.lstrip("#/").split("/")
    obj: Any = spec
    for p in parts:
        obj = obj[p]
    return obj


def _body_schema(spec: dict[str, Any], endpoint_def: dict[str, Any]) -> dict[str, Any] | None:
    rb = endpoint_def.get("requestBody", {}).get("content", {}).get("application/json", {})
    schema = rb.get("schema")
    if not schema:
        return None
    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])
    return schema


def _body_schema_variants(spec: dict[str, Any], endpoint_def: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all candidate body schemas, flattening `anyOf` / `oneOf` unions.

    Allium uses anyOf for endpoints that accept multiple payload shapes
    (e.g. prices/history has a current and a legacy variant). We need to
    inspect each variant separately rather than treat the union itself as
    the schema.
    """
    schema = _body_schema(spec, endpoint_def)
    if schema is None:
        return []
    if "anyOf" in schema or "oneOf" in schema:
        variants = schema.get("anyOf") or schema.get("oneOf") or []
        resolved = []
        for v in variants:
            if "$ref" in v:
                resolved.append(_resolve_ref(spec, v["$ref"]))
            else:
                resolved.append(v)
        return resolved
    return [schema]


def _method_kwargs(method) -> set[str]:
    """Return the names of all non-self keyword params on a bound async method."""
    sig = inspect.signature(method)
    return {
        name
        for name, p in sig.parameters.items()
        if name != "self" and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }


# ---------- /developer/tokens/transfers (GET) ----------


def test_get_token_transfers_required_params():
    """Allium's required query params must be in our get_token_transfers signature."""
    spec = _load_spec("tokens")
    endpoint = _endpoint(spec, "/api/v1/developer/tokens/transfers", "get")
    required_upstream = _required_query_params(endpoint)
    method_params = _method_kwargs(AlliumDeveloperProvider.get_token_transfers)
    missing = required_upstream - method_params
    assert not missing, (
        f"get_token_transfers is missing required Allium params: {sorted(missing)}. "
        f"Upstream required: {sorted(required_upstream)}. "
        f"Our signature: {sorted(method_params)}."
    )


def test_get_token_transfers_no_drifted_param_names():
    """Every kwarg on get_token_transfers must correspond to a real Allium query param.

    Catches the wrapper bug from run #17: we were passing `from`/`to` and
    `block_timestamp_gte` while Allium expects `min_timestamp`/`max_timestamp`.
    Allium silently ignores unknown params, so this drift used to be invisible
    until a live run.
    """
    spec = _load_spec("tokens")
    endpoint = _endpoint(spec, "/api/v1/developer/tokens/transfers", "get")
    upstream = _query_param_names(endpoint)
    ours = _method_kwargs(AlliumDeveloperProvider.get_token_transfers)
    drift = ours - upstream
    assert not drift, (
        f"get_token_transfers passes unknown params to Allium: {sorted(drift)}. "
        f"Allium silently ignores these. Upstream accepts: {sorted(upstream)}."
    )


# ---------- /developer/wallet/transactions (POST) ----------


def test_get_wallet_transactions_required_params():
    spec = _load_spec("wallet")
    endpoint = _endpoint(spec, "/api/v1/developer/wallet/transactions", "post")
    required_upstream = _required_query_params(endpoint)
    method_params = _method_kwargs(AlliumDeveloperProvider.get_wallet_transactions)
    missing = required_upstream - method_params
    assert not missing, f"get_wallet_transactions missing required Allium query params: {sorted(missing)}"


def test_get_wallet_transactions_no_date_filter_drift():
    """wallet/transactions has NO date filter per Allium's spec.

    Run #17 had us passing start_timestamp / end_timestamp / from / to —
    all ignored. Our signature must NOT include those. The only filter
    knobs are cursor, transaction_hash, activity_type, limit.
    """
    method_params = _method_kwargs(AlliumDeveloperProvider.get_wallet_transactions)
    forbidden = {"from_ts", "to_ts", "from_timestamp", "to_timestamp", "start_timestamp", "end_timestamp"}
    leaked = method_params & forbidden
    assert not leaked, (
        f"get_wallet_transactions accepts date-filter kwargs Allium doesn't support: {sorted(leaked)}. "
        "These get sent to Allium and silently ignored. Use cursor instead."
    )


# ---------- /developer/wallet/balances/history (POST) ----------


def test_get_wallet_balances_history_body_shape():
    """Body must be a single object with `addresses: [{chain, address}]`, not a list."""
    spec = _load_spec("balances")
    endpoint = _endpoint(spec, "/api/v1/developer/wallet/balances/history", "post")
    body = _body_schema(spec, endpoint)
    assert body is not None, "no body schema for balances/history"
    # Must be type=object with addresses + start_timestamp + end_timestamp at top level
    assert body.get("type") == "object", (
        f"balances/history body should be object, got {body.get('type')}. "
        "Run #17 had us posting a [{...}] list; this assertion locks the fix in."
    )
    props = body.get("properties", {})
    assert "addresses" in props, f"balances/history body missing 'addresses' property: {list(props)}"
    assert "start_timestamp" in props, "balances/history body missing 'start_timestamp'"
    assert "end_timestamp" in props, "balances/history body missing 'end_timestamp'"


# ---------- /developer/prices/history (POST) ----------


def test_prices_history_body_shape():
    """prices/history accepts an object body with addresses + timestamps + granularity.

    Allium publishes two payload variants under `anyOf` (current +
    Legacy). We only require ONE variant to match the shape our provider
    sends, so the test stays green when Allium adds new variants.
    """
    spec = _load_spec("prices")
    endpoint = _endpoint(spec, "/api/v1/developer/prices/history", "post")
    variants = _body_schema_variants(spec, endpoint)
    assert variants, "no body schema (or no anyOf variants) for prices/history"

    required_fields = {"addresses", "start_timestamp", "end_timestamp", "time_granularity"}
    matches = []
    for v in variants:
        if v.get("type") == "object" and required_fields.issubset(v.get("properties", {}).keys()):
            matches.append(v)
    assert matches, (
        f"no prices/history payload variant matches our provider's body shape "
        f"(needs {sorted(required_fields)}). "
        f"Variants offered: {[v.get('title') or v.get('type') for v in variants]}."
    )


# ---------- /developer/prices (POST, latest spot) ----------


def test_prices_latest_body_shape():
    spec = _load_spec("prices")
    endpoint = _endpoint(spec, "/api/v1/developer/prices", "post")
    body = _body_schema(spec, endpoint)
    assert body is not None
    # This endpoint takes a list body, not an object — different from history.
    # Pin both shapes so a future Allium API change can't silently break us.
    assert body.get("type") == "array", (
        f"/developer/prices body should be array (list of {{chain, token_address}}), got {body.get('type')}"
    )
