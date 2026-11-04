"""Preflight stays quick with many data sources: checks run side by side, bounded, within a time budget,
with no retries; the dashboard keeps the result for a few minutes and opens the page at once."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from src import doctor
from src.doctor import FAIL, PASS, Check

#: As many connector-kit sources as e2er 0.16.0 ships, and then some.
N_SOURCES = 20


def _settings() -> SimpleNamespace:
    return SimpleNamespace(fred_api_key=None)


def _fake_sources(n: int = N_SOURCES) -> list[tuple[str, SimpleNamespace]]:
    return [(f"data.src{i}.probe", SimpleNamespace(name=f"src{i}")) for i in range(n)]


def _patch_checks(monkeypatch, run) -> None:
    """Every network check of the preflight becomes ``run(name)``."""
    for fn, name in [
        ("data_catalog_check", "data.list_data_sources"),
        ("yfinance_check", "data.yfinance.history"),
        ("fred_check", "data.fred.observations"),
        ("gmd_check", "data.gmd.versions"),
        ("allium_check", "data.allium.list_tables"),
        ("openalex_check", "lit.search_papers"),
        ("read_reference_check", "lit.read_reference (OA PDF)"),
        ("zotero_check", "lit.zotero.library"),
    ]:

        async def check(_settings, _name=name):
            return await run(_name)

        monkeypatch.setattr(doctor, fn, check)
    monkeypatch.setattr(doctor, "_source_jobs", _fake_sources)

    async def source_check(source, _settings):
        return await run(f"data.{source.name}.probe")

    monkeypatch.setattr(doctor, "_source_check", source_check)


async def test_all_sources_unreachable_finish_within_the_budget(monkeypatch):
    """Every service refuses after a moment: the round takes about one check's time, not the sum."""

    async def refused(name):
        await asyncio.sleep(0.2)
        return Check(name, FAIL, "transport error: ConnectError: All connection attempts failed")

    _patch_checks(monkeypatch, refused)
    t0 = time.monotonic()
    checks = await doctor.run_provider_checks(_settings())
    took = time.monotonic() - t0
    network = [c for c in checks if c.name != "data.fred.key"]
    assert len(network) == 8 + N_SOURCES and all(c.status == FAIL for c in network)
    # One after the other this is 28 × 0.2 s = 5.6 s; side by side (16 at once), two rounds.
    assert took < 1.5, f"{took:.1f} s"


async def test_a_service_that_never_answers_fails_as_timed_out(monkeypatch):
    monkeypatch.setattr(doctor, "CHECK_TIMEOUT", 0.2)
    monkeypatch.setattr(doctor, "SLOW_CHECK_TIMEOUT", 0.3)

    async def hangs(name):
        await asyncio.sleep(60)

    _patch_checks(monkeypatch, hangs)
    t0 = time.monotonic()
    checks = await doctor.run_provider_checks(_settings())
    took = time.monotonic() - t0
    network = [c for c in checks if c.name != "data.fred.key"]
    assert all(c.status == FAIL and c.detail.startswith("timed out: no answer within") for c in network)
    assert took < 2.0, f"{took:.1f} s"


async def test_a_timed_out_check_reads_as_unreachable_on_the_dashboard():
    from src.core.labels import check_detail

    assert check_detail("data.fred.observations", "timed out: no answer within 5 s").startswith(
        "FRED could not be reached"
    )


async def test_no_more_checks_run_at_once_than_the_bound(monkeypatch):
    monkeypatch.setattr(doctor, "MAX_CONCURRENT_CHECKS", 3)
    now = peak = 0

    async def counted(name):
        nonlocal now, peak
        now += 1
        peak = max(peak, now)
        await asyncio.sleep(0.02)
        now -= 1
        return Check(name, PASS, "ok")

    _patch_checks(monkeypatch, counted)
    checks = await doctor.run_provider_checks(_settings())
    assert peak == 3
    assert len(checks) == 9 + N_SOURCES


async def test_the_order_is_the_list_order_whatever_finishes_first(monkeypatch):
    async def reversed_speed(name):
        await asyncio.sleep(0.05 if name.startswith("data.list") else 0)
        return Check(name, PASS, "ok")

    _patch_checks(monkeypatch, reversed_speed)
    names = [c.name for c in await doctor.run_provider_checks(_settings())]
    assert names[:5] == [
        "data.list_data_sources",
        "data.yfinance.history",
        "data.fred.key",
        "data.fred.observations",
        "data.gmd.versions",
    ]
    assert names[5 : 5 + N_SOURCES] == [n for n, _ in _fake_sources()]
    assert names[-1] == "lit.zotero.library"


async def test_one_broken_check_does_not_end_the_round(monkeypatch):
    async def run(name):
        if name == "data.src3.probe":
            raise RuntimeError("boom")
        return Check(name, PASS, "ok")

    _patch_checks(monkeypatch, run)
    checks = {c.name: c for c in await doctor.run_provider_checks(_settings())}
    assert checks["data.src3.probe"].status == FAIL and "boom" in checks["data.src3.probe"].detail
    assert checks["data.src4.probe"].status == PASS


# ── the kit's client in reachability mode ────────────────────────────────────


class _Refusing(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise httpx.ConnectError("All connection attempts failed", request=request)


async def _get_through(transport: _Refusing, reach: bool) -> None:
    from src.modules.data.sources import http
    from src.modules.data.sources.base import FetchError, Polite

    token = http._TRANSPORT.set(transport)
    try:
        ctx = http.reachability(connect=3.0, read=5.0) if reach else None
        if ctx is not None:
            ctx.__enter__()
        try:
            async with http.PoliteClient("refusing-test", Polite(retries=2, min_interval=0)) as client:
                if reach:
                    assert client._client is not None
                    assert client._client.timeout.connect == 3.0 and client._client.timeout.read == 5.0
                with pytest.raises(FetchError, match="transport error"):
                    await client.get("https://example.invalid/x")
        finally:
            if ctx is not None:
                ctx.__exit__(None, None, None)
    finally:
        http._TRANSPORT.reset(token)


async def test_reachability_asks_once_and_a_data_load_retries():
    once, loading = _Refusing(), _Refusing()
    await _get_through(once, reach=True)
    await _get_through(loading, reach=False)
    assert once.calls == 1  # a refused connection fails at once
    assert loading.calls == 3  # a load keeps its retries


# ── the dashboard: kept for a few minutes, page opens at once ────────────────


@pytest.fixture
def fresh_cache(monkeypatch):
    from src.api import app as app_module

    app_module.forget_preflight()
    runs: list[int] = []

    async def fake_run():
        runs.append(1)
        await asyncio.sleep(0.05)  # in flight long enough that a second look joins it (no clock is read)
        return {
            "checks": [{"name": "data.fred.observations", "status": "FAIL", "detail": "transport error: x"}],
            "ready": True,
            "blockers": [],
            "n_pass": 0,
            "n_skip": 0,
            "n_fail": 1,
            "error": "",
        }

    monkeypatch.setattr(app_module, "_run_preflight", fake_run)
    yield app_module, runs
    app_module.forget_preflight()


async def test_a_second_look_within_minutes_runs_nothing(fresh_cache):
    app_module, runs = fresh_cache
    first = await app_module._preflight()
    second = await app_module._preflight()
    assert len(runs) == 1 and first["checks"] == second["checks"]
    await app_module._preflight(fresh=True)  # "Check again"
    assert len(runs) == 2


async def test_the_kept_result_expires(fresh_cache, monkeypatch):
    app_module, runs = fresh_cache
    await app_module._preflight()
    # Made longer ago than the keep time: a 0.01 s sleep against a 0.0 TTL raced the
    # clock's resolution (a coarse monotonic clock reads the same value twice).
    app_module._preflight_cache["at"] -= app_module.PREFLIGHT_TTL + 1
    await app_module._preflight()
    assert len(runs) == 2


async def test_other_settings_are_checked_again(fresh_cache, monkeypatch):
    app_module, runs = fresh_cache
    await app_module._preflight()
    monkeypatch.setattr(app_module, "_preflight_key", lambda: "other settings")
    await app_module._preflight()
    assert len(runs) == 2
    app_module.forget_preflight()
    await app_module._preflight()
    assert len(runs) == 3


async def test_a_page_and_its_banner_opened_together_share_one_round(fresh_cache):
    app_module, runs = fresh_cache
    a, b = await asyncio.gather(app_module._preflight(), app_module._preflight())
    assert len(runs) == 1 and a["checks"] == b["checks"]


def test_the_page_opens_before_the_checks_and_shows_them_once_kept(fresh_cache):
    from fastapi.testclient import TestClient

    app_module, runs = fresh_cache
    client = TestClient(app_module.app)
    page = client.get("/preflight").text
    assert 'hx-get="/htmx/preflight-checks"' in page and "Running the checks" in page and not runs
    checks = client.get("/htmx/preflight-checks").text
    assert "FRED could not be reached" in checks and "Check again" in checks and len(runs) == 1
    again = client.get("/preflight").text  # kept: the checks are in the page itself
    assert "FRED could not be reached" in again and "Running the checks" not in again and len(runs) == 1
    client.get("/htmx/preflight-checks?fresh=1")
    assert len(runs) == 2


# ── a service's own trouble, and slow archives (tester report, 2026-11-02) ────


async def test_a_server_error_is_a_warning_in_plain_words_without_the_html(monkeypatch):
    html = (
        "https://ghoapi.azureedge.net/api/WHOSIS_000001?%24filter=x: HTTP 500: <html><head><title>Server Error"
        "</title></head><body>Server Error 500</body></html>"
    )

    async def run(name):
        if name == "data.src1.probe":
            return Check("data.who_gho.data", FAIL, html)
        if name == "data.src2.probe":
            return Check("data.src2.probe", FAIL, "https://x/y: HTTP 429: slow down")
        if name == "data.src3.probe":
            return Check("data.src3.probe", FAIL, "https://x/y: HTTP 404: no such indicator")
        return Check(name, PASS, "ok")

    _patch_checks(monkeypatch, run)
    checks = {c.name: c for c in await doctor.run_provider_checks(_settings())}
    who = checks["data.who_gho.data"]
    assert who.status == doctor.WARN
    assert who.detail == (
        "WHO Global Health Observatory: their service answered with a server error (500); try again later"
    )
    assert "<html" not in who.detail
    assert checks["data.src2.probe"].status == doctor.WARN and "(429)" in checks["data.src2.probe"].detail
    assert checks["data.src3.probe"].status == FAIL, "a 404 is the request's problem, not the service's"


def test_warnings_do_not_fail_the_doctor():
    out = doctor.render_human(
        [
            Check("db", PASS, "SQLite default"),
            Check("data.who_gho.data", doctor.WARN, "WHO Global Health Observatory: their service answered …"),
        ]
    )
    assert "✅ Ready" in out and "1 to try again later" in out and "  ! [WARN]" in out


async def test_a_slow_archive_gets_its_own_budget(monkeypatch):
    """Gaia's TAP service answered after 5 s and failed as timed out; a slow archive gets SLOW_SERVICE_TIMEOUT."""
    monkeypatch.setattr(doctor, "CHECK_TIMEOUT", 0.1)
    slow = SimpleNamespace(name="gaia", doctor=SimpleNamespace(check="data.gaia.cone", timeout=0.6))
    quick = SimpleNamespace(name="quick", doctor=SimpleNamespace(check="data.quick.probe", timeout=0.0))
    monkeypatch.setattr(doctor, "_source_jobs", lambda: [("data.gaia.cone", slow), ("data.quick.probe", quick)])
    seen: dict[str, object] = {}

    async def answers_after(source, _settings):
        from src.modules.data.sources.http import _REACHABILITY

        seen[source.name] = _REACHABILITY.get()
        await asyncio.sleep(0.3)
        return Check(source.doctor.check, PASS, "1 rows")

    monkeypatch.setattr("src.modules.data.sources.runtime.doctor_check", answers_after)
    checks = {c.name: c for c in await doctor.source_checks(_settings())}
    assert checks["data.gaia.cone"].status == PASS
    assert checks["data.quick.probe"].status == FAIL and "within 0.1 s" in checks["data.quick.probe"].detail
    assert seen["gaia"] == (doctor.CONNECT_TIMEOUT, 0.6), "the request may wait as long as the check"


def test_the_tap_archives_declare_the_slow_budget():
    from src.modules.data.sources import all_sources

    budgets = {s.name: s.doctor.timeout for s in all_sources() if s.doctor is not None}
    for name in ("gaia", "exoplanets", "nasa_power"):
        assert budgets[name] == doctor.SLOW_SERVICE_TIMEOUT, name
    assert budgets["worldbank"] == 0.0
