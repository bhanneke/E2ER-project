"""GitHub: public repositories' metadata (search, details, languages, contributors, releases), via the REST API.

- Service: https://api.github.com (REST, ``X-GitHub-Api-Version: 2022-11-28``).
  ``search/repositories`` finds repositories by query, topic, language, stars
  and creation date (at most 1,000 results per search, 100 per page);
  ``repos/<owner>/<name>`` (with ``/languages`` and ``/contributors``) and
  ``repos/<owner>/<name>/releases`` describe one repository.
- Key: optional. Without one GitHub allows 60 requests an hour and 10
  searches a minute per IP address; with a token 5,000 an hour and 30
  searches a minute (https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api,
  https://docs.github.com/en/rest/search/search). e2er reads the token from
  the setting ``GITHUB_TOKEN`` only, never from the machine's ``gh`` login, and
  never prints it. A load stops with advice when GitHub reports its limit
  reached.
- Terms: GitHub's Terms of Service, section H (API Terms), and the Acceptable
  Use Policies, section 7: "Researchers may use public, non-personal
  information from the Service for research purposes, only if any publications
  resulting from that research are open access." Repository contents belong to
  their owners under their own licences (ToS section D); the operations return
  metadata only, never repository contents, and no personal fields beyond the
  owner's account name (no e-mail addresses, no contributor identities).
  GitHub grants no licence to pass the metadata on, so e2er treats them as
  data a published study may not pass on (the replication package loads them
  again with get_data.py).
- Citation: GitHub publishes none for its API; e2er cites the REST API with
  the date of the load.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .base import Arg, Context, Doctor, Fetched, FetchError, Key, Operation, Polite, Restricted, Source

API = "https://api.github.com"
TERMS_URL = "https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies"
TOS_URL = "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service"
#: GitHub's own limit: a search returns at most 1,000 results (10 pages of 100).
MAX_SEARCH = 1000
#: The most repositories `repo` describes in one load (3 requests each; 60 an hour without a token).
MAX_REPOS = 15
MAX_REPOS_TOKEN = 100
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _headers(ctx: Context) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if ctx.key:
        h["Authorization"] = f"Bearer {ctx.key}"
    return h


async def _get(ctx: Context, url: str, params: dict[str, Any] | None = None) -> tuple[Any, Any]:
    """GET with GitHub's headers; a rate-limit refusal becomes advice."""
    try:
        resp = await ctx.http.get(url, params, headers=_headers(ctx))
    except FetchError as e:
        msg = str(e)
        if "rate limit" in msg.lower() or "HTTP 429" in msg:
            raise FetchError(
                "GitHub's rate limit is reached"
                + ("" if ctx.key else " (60 requests an hour, 10 searches a minute without a token)")
                + ": wait, ask for less, or set GITHUB_TOKEN (a personal access token, no scopes needed)"
            ) from None
        raise
    try:
        return resp.json(), resp
    except ValueError:
        raise FetchError(f"{ctx.http.requests[-1]}: not JSON") from None


def _repo_row(r: dict[str, Any]) -> dict[str, Any]:
    lic = r.get("license") or {}
    owner = r.get("owner") or {}
    return {
        "full_name": r.get("full_name"),
        "owner": owner.get("login"),
        "owner_type": owner.get("type"),
        "name": r.get("name"),
        "description": r.get("description"),
        "url": r.get("html_url"),
        "language": r.get("language"),
        "topics": ",".join(r.get("topics") or []) or None,
        "license": lic.get("spdx_id") if isinstance(lic, dict) else None,
        "stars": r.get("stargazers_count"),
        "forks": r.get("forks_count"),
        "open_issues": r.get("open_issues_count"),
        "watchers": r.get("subscribers_count", r.get("watchers_count")),
        "size_kb": r.get("size"),
        "fork": r.get("fork"),
        "archived": r.get("archived"),
        "is_template": r.get("is_template"),
        "default_branch": r.get("default_branch"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "pushed_at": r.get("pushed_at"),
    }


def _search_q(params: dict[str, Any]) -> str:
    parts = [str(params["query"]).strip()] if params.get("query") else []
    for t in params.get("topic") or []:
        parts.append(f"topic:{t}")
    if params.get("language"):
        parts.append(f"language:{params['language']}")
    if params.get("min_stars") is not None:
        parts.append(f"stars:>={int(params['min_stars'])}")
    a, b = params.get("created_after"), params.get("created_before")
    for d, what in ((a, "created-after"), (b, "created-before")):
        if d and not _DATE.match(str(d)):
            raise FetchError(f"--{what} {d!r} is not a date (YYYY-MM-DD)")
    if a and b:
        parts.append(f"created:{a}..{b}")
    elif a:
        parts.append(f"created:>={a}")
    elif b:
        parts.append(f"created:<={b}")
    if not parts:
        raise FetchError("give --query, --topic, --language, --min-stars or a creation period")
    return " ".join(parts)


async def fetch_search(ctx: Context, params: dict[str, Any]) -> Fetched:
    q = _search_q(params)
    limit = int(params.get("limit") or 100)
    if not 1 <= limit <= MAX_SEARCH:
        raise FetchError(f"--limit {limit}: between 1 and {MAX_SEARCH} (GitHub returns at most {MAX_SEARCH})")
    sort = params.get("sort")
    per_page = min(100, limit)
    rows: list[dict[str, Any]] = []
    first_url = None
    total = None
    incomplete = False
    page = 1
    while len(rows) < limit:
        doc, _ = await _get(
            ctx,
            f"{API}/search/repositories",
            {"q": q, "sort": sort, "order": "desc" if sort else None, "per_page": per_page, "page": page},
        )
        first_url = first_url or ctx.http.requests[-1]
        total = doc.get("total_count", total)
        incomplete = incomplete or bool(doc.get("incomplete_results"))
        items = doc.get("items") or []
        rows += [_repo_row(r) for r in items]
        if len(items) < per_page:
            break
        page += 1
    rows = rows[:limit]
    note = (
        f"{total} repositories match; {len(rows)} loaded (GitHub returns at most {MAX_SEARCH} per search: narrow "
        "the query or split the creation period for more). Metadata only; contents carry their own licences."
    )
    if incomplete:
        note += " GitHub reported incomplete results (the search timed out): the counts may be short."
    return Fetched(
        rows=rows,
        series=f"GitHub repositories matching '{q}'" + (f", by {sort}" if sort else ""),
        query=first_url,
        version=_today(),
        link=f"https://github.com/search?q={q.replace(' ', '+')}&type=repositories",
        citation=_citation(),
        record={"search": q, "total_count": total, "incomplete_results": incomplete},
        note=note,
    )


def _last_page(link: str | None) -> int | None:
    m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', link or "")
    return int(m.group(1)) if m else None


async def fetch_repo(ctx: Context, params: dict[str, Any]) -> Fetched:
    repos = [str(r).strip().strip("/") for r in params["repos"] or []]
    bad = [r for r in repos if not _REPO.match(r)]
    if not repos or bad:
        raise FetchError(f"--repos {', '.join(bad) or '(empty)'}: give owner/name, e.g. pandas-dev/pandas")
    cap = MAX_REPOS_TOKEN if ctx.key else MAX_REPOS
    if len(repos) > cap:
        raise FetchError(
            f"{len(repos)} repositories: at most {cap} per load"
            + ("" if ctx.key else " without a token (3 requests each, 60 an hour); set GITHUB_TOKEN for more")
        )
    rows = []
    for full in repos:
        doc, _ = await _get(ctx, f"{API}/repos/{full}")
        row = _repo_row(doc)
        langs, _ = await _get(ctx, f"{API}/repos/{full}/languages")
        row["languages"] = ",".join(f"{k}:{v}" for k, v in sorted(langs.items(), key=lambda kv: -kv[1])) or None
        # One contributor per page: the last page's number is the count (anonymous contributors included).
        people, resp = await _get(ctx, f"{API}/repos/{full}/contributors", {"per_page": 1, "anon": "true"})
        last = _last_page(resp.headers.get("link"))
        row["contributors"] = last if last is not None else len(people or [])
        rows.append(row)
    return Fetched(
        rows=rows,
        series=f"GitHub repository metadata: {', '.join(repos)}",
        query=ctx.http.requests[0],
        version=_today(),
        link=f"https://github.com/{repos[0]}",
        citation=_citation(),
        note=(
            "One row per repository: metadata, languages (bytes per language), contributors (a count: GitHub "
            "counts at most 500 by e-mail address). Metadata only; contents carry their own licences."
        ),
    )


async def fetch_releases(ctx: Context, params: dict[str, Any]) -> Fetched:
    full = str(params["repo"]).strip().strip("/")
    if not _REPO.match(full):
        raise FetchError(f"--repo {full!r}: give owner/name, e.g. pandas-dev/pandas")
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        doc, _ = await _get(ctx, f"{API}/repos/{full}/releases", {"per_page": 100, "page": page})
        for r in doc or []:
            assets = r.get("assets") or []
            rows.append(
                {
                    "repo": full,
                    "tag": r.get("tag_name"),
                    "name": r.get("name"),
                    "published_at": r.get("published_at"),
                    "created_at": r.get("created_at"),
                    "prerelease": r.get("prerelease"),
                    "draft": r.get("draft"),
                    "assets": len(assets),
                    "downloads": sum(int(a.get("download_count") or 0) for a in assets),
                    "url": r.get("html_url"),
                }
            )
        if len(doc or []) < 100 or page >= 10:
            break
        page += 1
    return Fetched(
        rows=rows,
        series=f"GitHub releases of {full}",
        query=ctx.http.requests[0],
        version=_today(),
        link=f"https://github.com/{full}/releases",
        citation=_citation(),
        frequency="event",
        note="One row per release (at most 1,000, newest first); downloads are the assets' download counts.",
    )


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _citation() -> str:
    return f"GitHub, Inc. GitHub REST API (version 2022-11-28). https://docs.github.com/en/rest. Accessed {_today()}."


CITATION = "GitHub, Inc. GitHub REST API (version 2022-11-28). https://docs.github.com/en/rest."
CITE_KEY = "GitHub_RESTAPI"
BIBTEX = """@misc{GitHub_RESTAPI,
  author       = {{GitHub, Inc.}},
  title        = {{GitHub REST API}},
  howpublished = {\\url{https://api.github.com}, API version 2022-11-28},
  url          = {https://docs.github.com/en/rest}
}"""

SOURCE = Source(
    name="github",
    label="GitHub",
    dataset="GitHub public repository metadata (REST API), GitHub, Inc.",
    website="https://github.com",
    terms_url=TERMS_URL,
    terms_summary=(
        "Researchers may use public, non-personal information from GitHub only if the resulting publications are "
        "open access. Repository contents carry their owners' licences (e2er loads metadata only). GitHub grants "
        "no licence to pass the metadata on: a published study reloads them."
    ),
    terms_plain=(
        "Research use of public, non-personal information is allowed only if the publications are open access.",
        "Personal information may be used only for the purpose its user authorized; e2er loads no e-mail "
        "addresses or contributor identities.",
        "Repository contents belong to their owners under their own licences; e2er loads metadata only.",
        "Respect GitHub's rate limits; do not share tokens to exceed them.",
    ),
    licence=(
        f'GitHub Acceptable Use Policies, section 7 ({TERMS_URL}): "You may use information from our Service for '
        "the following reasons, regardless of whether the information was scraped, collected through our API, or "
        "obtained otherwise: […] Researchers may use public, non-personal information from the Service for "
        'research purposes, only if any publications resulting from that research are open access." "If you '
        "collect any personal information from the Service, you agree that you will only use that personal "
        'information for the purpose for which that User has authorized it." GitHub Terms of Service '
        f'({TOS_URL}), section H: "All use of the GitHub API is subject to these Terms of Service and the GitHub '
        'Privacy Statement." "You may not share API tokens to exceed GitHub\'s rate limitations." Section D: '
        '"By making a repository public, you grant other Users a nonexclusive, worldwide license to use, '
        "display, perform and reproduce (by forking) Your Content through the Service as permitted by GitHub's "
        'functionality. You may grant additional rights by adopting a license."'
    ),
    citation=CITATION,
    citation_by="e2er",
    bibtex=BIBTEX,
    cite_key=CITE_KEY,
    key=Key(
        setting="github_token",
        env="GITHUB_TOKEN",
        how_to_get=(
            "Optional: a GitHub personal access token (no scopes needed for public data) raises the limits from "
            "60 to 5,000 requests an hour; create one at https://github.com/settings/tokens and set GITHUB_TOKEN."
        ),
        optional=True,
    ),
    redistribution=False,
    restricted=Restricted(
        short="GitHub",
        name="GitHub repository metadata",
        zenodo_licence=None,
        no_zenodo_why=(
            "GitHub grants no licence to republish the metadata, and allows research use only with open-access "
            "publications"
        ),
        limit="grant no licence to pass the metadata on, and allow research use only with open-access publications",
        limit_finish="grant no licence to pass the metadata on",
        confirm="although GitHub grants no licence to pass the metadata on (the paper must be open access)",
        warn="GitHub allows research use only if the resulting publications are open access.",
        article="",
    ),
    use=(
        "Public GitHub repositories as research objects: search by words, topic, language, stars and creation "
        "date (up to 1,000 per search), and per repository its metadata (stars, forks, issues, licence, topics, "
        "languages, dates), contributor count and releases. Open-source ecosystems, software adoption, research "
        "software. Metadata only. Keyless (60 requests an hour); GITHUB_TOKEN raises the limits."
    ),
    coverage="Public repositories' metadata: search, details, languages, contributors count, releases.",
    help="GitHub: public repositories' metadata. Optional GITHUB_TOKEN.",
    operations=(
        Operation(
            "repos",
            "Search repositories, e.g. --topic machine-learning --language Python --min-stars 100 "
            "--created-after 2020-01-01 --sort stars --limit 200.",
            args=(
                Arg("query", "Words (GitHub search syntax allowed), e.g. 'econometrics in:description'."),
                Arg("topic", "Topics, comma-separated (all must match).", type="list"),
                Arg("language", "Main language, e.g. Python."),
                Arg("min-stars", "At least this many stars.", type=int),
                Arg("created-after", "Created on or after (YYYY-MM-DD)."),
                Arg("created-before", "Created on or before (YYYY-MM-DD)."),
                Arg(
                    "sort",
                    "stars, forks, updated or help-wanted-issues (default: best match).",
                    choices=("stars", "forks", "updated", "help-wanted-issues"),
                ),
                Arg("limit", f"Most repositories (default 100, at most {MAX_SEARCH}).", type=int),
            ),
            fetch=fetch_search,
            card="Search public repositories → one row per repository (stars, forks, language, licence, topics, "
            "dates). Params: query, topic (list), language, min_stars, created_after, created_before, sort, limit.",
        ),
        Operation(
            "repo",
            "Metadata of named repositories, with languages and contributors count, e.g. --repos "
            "pandas-dev/pandas,numpy/numpy.",
            args=(
                Arg(
                    "repos",
                    f"owner/name, comma-separated (at most {MAX_REPOS} without a token).",
                    type="list",
                    required=True,
                ),
            ),
            fetch=fetch_repo,
            card="Metadata of named repositories → one row each, with languages and contributor count. Params: "
            "repos (list of owner/name, required).",
        ),
        Operation(
            "releases",
            "Releases of one repository, e.g. --repo pandas-dev/pandas.",
            args=(Arg("repo", "owner/name.", required=True),),
            fetch=fetch_releases,
            card="Releases of a repository → one row per release (tag, date, assets, downloads). Params: repo "
            "(owner/name, required).",
        ),
    ),
    polite=Polite(min_interval=2.0, max_requests=3 * MAX_REPOS_TOKEN + 5, retries=1),
    aliases=("github_api", "github_repositories", "gh"),
    skill="data/github",
    doctor=Doctor("data.github.repos", operation="repos", params={"query": "repo:statsmodels/statsmodels", "limit": 1}),
)
