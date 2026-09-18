"""Literature module — open-access PDF resolver chain (v0.9 M3).

Distinct from the metadata fetch chain (``doi_fetch_sources``) — that
returns full ``PaperMetadata`` and is OK to stop at the first source
that recognises the DOI even if that source has no PDF. This chain
has one job: produce an OA PDF URL for a DOI. Each resolver tries;
first hit wins.

Why a separate chain: live-test on M1 showed many Zotero items hold
metadata only (PDFs not in cloud storage), so ``read_reference`` has
to fall through to OA-by-DOI. Pre-M3 that meant a single OpenAlex
lookup — `oa_url` is often null for older / paywalled work even when
a green-OA copy exists somewhere. Unpaywall + Crossref ``link[]``
fill that gap.

Default order (best OA coverage first, cheapest fallback last):

1. **Unpaywall** — best OA coverage, scrapes repositories +
   publishers; keyless but email required.
2. **OpenAlex** — already in the metadata chain so cached; good
   coverage for newer work via ``best_oa_location``.
3. **Crossref** — publisher-deposited PDF links from the DOI record's
   ``link[]`` array; narrower but catches publisher cases the others
   miss.
4. **Semantic Scholar** — ``openAccessPdf.url``; complements when S2
   has a paper the others don't.

The chain returns *just* a URL (or ``None``) — full PaperMetadata
lives in the metadata-fetch chain. ``LiteratureToolHandler`` calls
this from ``_read_reference`` when the metadata chain's
``PaperMetadata.pdf_url`` is empty.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ...config import Settings
from ...logging_config import get_logger
from . import crossref, openalex, semantic_scholar, unpaywall

logger = get_logger(__name__)


class OAResolver(ABC):
    """Resolve a DOI to a single OA PDF URL.

    ``resolve`` MUST NOT raise — degrade to ``None`` so a chain
    iteration can continue past a transient outage.
    """

    name: str

    @abstractmethod
    async def resolve(self, doi: str) -> str | None: ...


class UnpaywallOA(OAResolver):
    name = "unpaywall"

    def __init__(self, email: str) -> None:
        self._email = email

    async def resolve(self, doi: str) -> str | None:
        try:
            return await unpaywall.find_oa_pdf(doi, self._email)
        except Exception as e:  # noqa: BLE001 — outages are normal
            logger.info("UnpaywallOA: %s", e)
            return None


class OpenAlexOA(OAResolver):
    name = "openalex"

    async def resolve(self, doi: str) -> str | None:
        try:
            p = await openalex.fetch_by_doi(doi)
        except Exception as e:  # noqa: BLE001
            logger.info("OpenAlexOA: %s", e)
            return None
        return p.pdf_url if (p and p.pdf_url) else None


class CrossrefOA(OAResolver):
    name = "crossref"

    async def resolve(self, doi: str) -> str | None:
        try:
            return await crossref.find_oa_pdf(doi)
        except Exception as e:  # noqa: BLE001
            logger.info("CrossrefOA: %s", e)
            return None


class SemanticScholarOA(OAResolver):
    name = "semantic_scholar"

    async def resolve(self, doi: str) -> str | None:
        try:
            p = await semantic_scholar.fetch_by_doi(doi)
        except Exception as e:  # noqa: BLE001
            logger.info("SemanticScholarOA: %s", e)
            return None
        return p.pdf_url if (p and p.pdf_url) else None


def oa_pdf_resolvers(settings: Settings) -> list[OAResolver]:
    """Ordered OA-PDF resolver chain. Unpaywall first (best coverage),
    OpenAlex next (cached from metadata fetch), then Crossref and S2
    as deeper fallbacks."""
    return [
        UnpaywallOA(settings.unpaywall_email),
        OpenAlexOA(),
        CrossrefOA(),
        SemanticScholarOA(),
    ]
