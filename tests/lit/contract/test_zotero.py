"""Lane B — Zotero Web API reference-library provider (M2).

Mock-only (no network). Pins the JSON-direct item→PaperMetadata mapping,
attachment-PDF capture, item-type filtering, pagination, library-id URL
routing, auth header, graceful degradation, and registry wiring.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from src.modules.literature.providers import ZoteroLibrary
from src.modules.literature.registry import reference_libraries
from src.modules.literature.zotero import fetch_library

_ZOTERO = "src.modules.literature.zotero.fetch_text_sync"


def _item(**data_overrides):
    data = {
        "itemType": "journalArticle",
        "title": "Concentrated Liquidity in AMMs",
        "creators": [
            {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
            {"creatorType": "author", "name": "Some Institute"},
            {"creatorType": "translator", "firstName": "X", "lastName": "Y"},
        ],
        "date": "2023-06-15",
        "DOI": "10.1234/amm.2023",
        "publicationTitle": "Journal of DeFi",
        "abstractNote": "We study concentrated liquidity.",
        "url": "https://example.org/amm",
    }
    data.update(data_overrides)
    return {
        "key": "ABCD1234",
        "data": data,
        "links": {
            "alternate": {"href": "https://www.zotero.org/abc"},
            "attachment": {
                "href": "https://api.zotero.org/users/1/items/PDFKEY/file/view",
                "attachmentType": "application/pdf",
            },
        },
    }


# ---------------------------------------------------------------------------
# JSON-direct mapping
# ---------------------------------------------------------------------------


def test_maps_item_fields():
    with patch(_ZOTERO, return_value=json.dumps([_item()])):
        papers = fetch_library("KEY", user_id="1")

    assert len(papers) == 1
    p = papers[0]
    assert p.title == "Concentrated Liquidity in AMMs"
    # translator excluded; institutional single-field name kept
    assert p.authors == ["Ada Lovelace", "Some Institute"]
    assert p.year == 2023
    assert p.doi == "10.1234/amm.2023"
    assert p.journal == "Journal of DeFi"
    assert p.abstract == "We study concentrated liquidity."
    assert p.source == "zotero"
    assert p.pdf_url == "https://api.zotero.org/users/1/items/PDFKEY/file/view"


def test_no_pdf_url_when_attachment_absent():
    item = _item()
    item["links"].pop("attachment")
    with patch(_ZOTERO, return_value=json.dumps([item])):
        papers = fetch_library("KEY", user_id="1")
    assert papers[0].pdf_url == ""


def test_no_pdf_url_when_attachment_not_pdf():
    item = _item()
    item["links"]["attachment"]["attachmentType"] = "text/html"
    with patch(_ZOTERO, return_value=json.dumps([item])):
        papers = fetch_library("KEY", user_id="1")
    assert papers[0].pdf_url == ""


def test_skips_non_bibliographic_item_types():
    note = _item(itemType="note", title="a standalone note")
    attach = _item(itemType="attachment", title="a loose pdf")
    good = _item(title="Real Paper")
    with patch(_ZOTERO, return_value=json.dumps([note, attach, good])):
        papers = fetch_library("KEY", user_id="1")
    assert [p.title for p in papers] == ["Real Paper"]


def test_skips_untitled_items():
    with patch(_ZOTERO, return_value=json.dumps([_item(title="")])):
        assert fetch_library("KEY", user_id="1") == []


def test_year_parsed_from_freeform_date():
    with patch(_ZOTERO, return_value=json.dumps([_item(date="Spring 2019")])):
        assert fetch_library("KEY", user_id="1")[0].year == 2019


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pages_until_short_page():
    full = json.dumps([_item() for _ in range(100)])
    tail = json.dumps([_item()])
    with patch(_ZOTERO, side_effect=[full, tail]) as m:
        papers = fetch_library("KEY", user_id="1")
    assert len(papers) == 101
    assert m.call_count == 2


def test_stops_on_empty_first_page():
    with patch(_ZOTERO, return_value=json.dumps([])) as m:
        assert fetch_library("KEY", user_id="1") == []
    assert m.call_count == 1


# ---------------------------------------------------------------------------
# URL routing, auth, degradation
# ---------------------------------------------------------------------------


def test_user_library_url():
    with patch(_ZOTERO, return_value="[]") as m:
        fetch_library("KEY", user_id="42")
    assert "/users/42/items/top" in m.call_args.args[0]


def test_group_library_url():
    with patch(_ZOTERO, return_value="[]") as m:
        fetch_library("KEY", group_id="9")
    assert "/groups/9/items/top" in m.call_args.args[0]


def test_sends_api_key_header():
    with patch(_ZOTERO, return_value="[]") as m:
        fetch_library("SECRET", user_id="1")
    assert m.call_args.kwargs["headers"]["Zotero-API-Key"] == "SECRET"


def test_no_library_id_returns_empty():
    with patch(_ZOTERO) as m:
        assert fetch_library("KEY") == []
    m.assert_not_called()


def test_fetch_failure_returns_empty():
    with patch(_ZOTERO, side_effect=RuntimeError("503")):
        assert fetch_library("KEY", user_id="1") == []


def test_library_entries_never_raises():
    with patch("src.modules.literature.zotero.fetch_library", side_effect=RuntimeError("boom")):
        assert ZoteroLibrary("KEY", user_id="1").entries() == []


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


def _settings(**kwargs):
    base = {
        "literature_bibtex_file": None,
        "local_data_dir": None,
        "local_data_dir_recursive": False,
        "zotero_enabled": False,
        "zotero_api_key": None,
        "zotero_user_id": None,
        "zotero_group_id": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_registry_includes_zotero_when_enabled():
    libs = reference_libraries(_settings(zotero_enabled=True, zotero_api_key="k", zotero_user_id="1"))
    assert [lib.name for lib in libs] == ["zotero"]


def test_registry_omits_zotero_when_disabled():
    assert reference_libraries(_settings()) == []


def test_registry_orders_local_then_zotero():
    libs = reference_libraries(
        _settings(
            literature_bibtex_file="/refs.bib",
            zotero_enabled=True,
            zotero_api_key="k",
            zotero_group_id="9",
        )
    )
    assert [lib.name for lib in libs] == ["local_bibtex", "zotero"]
