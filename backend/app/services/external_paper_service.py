from __future__ import annotations

import logging
import ssl
import time
import xml.etree.ElementTree as ET

import httpx

from app.config.settings import Settings, get_settings
from app.schemas.paper import ExternalPaperResult

logger = logging.getLogger("app.external_papers")

_RETRYABLE_STATUSES = {406, 429}


class _NoAlpnSSLContext(ssl.SSLContext):
    """An SSL context that ignores ALPN.

    arXiv's edge answers 406 Not Acceptable to any TLS connection that
    negotiates ALPN ``http/1.1`` whenever the request misses their cache
    (verified with raw sockets: identical request, ALPN on -> 406, ALPN off ->
    200). httpcore unconditionally calls ``set_alpn_protocols`` on whatever
    context it is given, so the only way to opt out is a context that swallows
    that call. Without ALPN the server simply falls back to HTTP/1.1.
    """

    def set_alpn_protocols(self, alpn_protocols) -> None:  # noqa: ARG002
        return None


def _build_ssl_context() -> ssl.SSLContext:
    context = _NoAlpnSSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_default_certs()
    return context


_SSL_CONTEXT = _build_ssl_context()


def _http_client(settings: Settings) -> httpx.Client:
    """One place to construct the outbound client so every external call
    (arXiv search, Semantic Scholar, PDF download) shares the same timeout,
    redirect policy, and the ALPN-free TLS context."""
    return httpx.Client(
        timeout=settings.external_api_timeout_seconds,
        follow_redirects=True,
        verify=_SSL_CONTEXT,
    )

# Recent-category candidates for recommendations are cached briefly so every
# dashboard load (and React StrictMode's dev-only double fetch) doesn't turn
# into a fresh arXiv query — that burst is exactly what triggers arXiv's 406s.
_RECENT_CACHE_TTL_SECONDS = 600
_recent_category_cache: dict[tuple[tuple[str, ...], int], tuple[float, list[ExternalPaperResult]]] = {}

_ATOM_NS = "{http://www.w3.org/2005/Atom}"

# A curated subset of arXiv's category taxonomy, scoped to what this app's
# audience (AI/ML paper research) actually browses — arXiv has 150+ categories
# across every field of science, and exposing all of them would make the filter
# control useless. These are real arXiv category codes, not invented tags: they
# drive the actual `cat:` query term, not just a display label.
ARXIV_CATEGORIES: dict[str, str] = {
    "cs.LG": "Machine Learning",
    "cs.AI": "Artificial Intelligence",
    "cs.CV": "Computer Vision",
    "cs.CL": "Computation and Language (NLP)",
    "cs.RO": "Robotics",
    "cs.NE": "Neural and Evolutionary Computing",
    "cs.IR": "Information Retrieval",
    "cs.CR": "Cryptography and Security",
    "stat.ML": "Statistics - Machine Learning",
}


class ExternalPaperError(RuntimeError):
    """Raised when an external paper-search/download call fails after retries, or a
    downloaded file isn't actually usable. Routers translate this into a client-facing
    HTTPException (502/400) rather than letting it surface as a raw 500.
    """


def _request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_retries: int,
    **kwargs,
) -> httpx.Response:
    """Issues one HTTP request with exponential backoff on timeouts, connection
    errors, 429s, 406s, and 5xxs — the failure modes a free, rate-limited public
    API actually produces. Any other 4xx (bad query, 404, etc.) is not retried
    since retrying it would just fail the same way again.

    406 is included because arXiv's edge returns it (not 429) when requests
    arrive faster than its ~3s/request guideline; the identical query succeeds a
    moment later, so it behaves like a rate limit rather than a bad request.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as error:
            last_error = error
            if attempt < max_retries:
                _backoff_and_log(url, attempt, max_retries, error)
                continue
            raise ExternalPaperError(
                f"Request to {url.split('?')[0]} failed after {max_retries + 1} attempts: {error}"
            ) from error

        if response.status_code in _RETRYABLE_STATUSES or response.status_code >= 500:
            last_error = httpx.HTTPStatusError(
                f"retryable status {response.status_code}", request=response.request, response=response
            )
            if attempt < max_retries:
                _backoff_and_log(url, attempt, max_retries, last_error)
                continue
            raise ExternalPaperError(
                f"Request to {url.split('?')[0]} failed after {max_retries + 1} attempts: {last_error}"
            ) from last_error

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            # A non-retryable 4xx (bad query, 404 not found, ...) — retrying would
            # just fail the same way again, so surface it on the first attempt
            # instead of burning through backoff delays for nothing.
            raise ExternalPaperError(f"Request to {url.split('?')[0]} failed: {error}") from error

        return response

    raise ExternalPaperError(f"Request to {url.split('?')[0]} failed after {max_retries + 1} attempts: {last_error}") from last_error


def _backoff_and_log(url: str, attempt: int, max_retries: int, error: Exception) -> None:
    backoff_seconds = 0.5 * (2**attempt)
    logger.warning(
        "external_api_retry url=%s attempt=%d/%d error=%s",
        url,
        attempt + 1,
        max_retries + 1,
        error,
    )
    time.sleep(backoff_seconds)


def _build_arxiv_search_query(query: str | None, categories: list[str] | None) -> str:
    """Combines a free-text keyword and one or more arXiv category filters into
    arXiv's `search_query` syntax: categories OR'd together, AND'd with the
    keyword when both are present. At least one of the two must be given —
    callers (search_papers / the router) validate that before calling in.
    """
    terms = []
    if categories:
        category_clause = " OR ".join(f"cat:{category}" for category in categories)
        terms.append(f"({category_clause})" if len(categories) > 1 else category_clause)
    if query:
        terms.append(f"all:{query}")
    return " AND ".join(terms)


def build_arxiv_phrase_query(phrases: list[str], categories: list[str] | None = None) -> str:
    """arXiv query for "papers mentioning any of these exact phrases", optionally
    within categories: (all:"p1" OR all:"p2" ...) AND (cat:a OR cat:b).

    Quoted phrases are matched as phrases by arXiv, which is what makes
    LLM-extracted terminology like "whole-body humanoid locomotion" a useful
    search key — unquoted, arXiv would OR the individual words together and
    return everything mentioning "locomotion".
    """
    cleaned = [" ".join(phrase.replace('"', " ").split()) for phrase in phrases]
    cleaned = [phrase for phrase in cleaned if phrase]
    if not cleaned:
        raise ValueError("at least one phrase is required")
    phrase_clause = " OR ".join(f'all:"{phrase}"' for phrase in cleaned)
    terms = [f"({phrase_clause})" if len(cleaned) > 1 else phrase_clause]
    if categories:
        category_clause = " OR ".join(f"cat:{category}" for category in categories)
        terms.append(f"({category_clause})" if len(categories) > 1 else category_clause)
    return " AND ".join(terms)


def search_arxiv(
    query: str | None,
    limit: int,
    settings: Settings,
    *,
    categories: list[str] | None = None,
    sort: str = "relevance",
    search_query: str | None = None,
) -> list[ExternalPaperResult]:
    """`search_query`, when given, is a fully formed arXiv query string used
    as-is (see `build_arxiv_phrase_query`); otherwise one is built from the
    keyword + categories like the Discover page does."""
    params = {
        "search_query": search_query or _build_arxiv_search_query(query, categories),
        "start": 0,
        "max_results": limit,
    }
    if sort == "recent":
        # arXiv's own submission-date sort — this is what makes "recent papers in
        # a category, no keyword" a real query rather than an approximation.
        params["sortBy"] = "submittedDate"
        params["sortOrder"] = "descending"

    with _http_client(settings) as client:
        response = _request_with_retry(
            client,
            "GET",
            settings.arxiv_api_base_url,
            max_retries=settings.external_api_max_retries,
            params=params,
        )

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as error:
        raise ExternalPaperError(f"arXiv returned an unparsable response: {error}") from error

    results: list[ExternalPaperResult] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        raw_id = (entry.findtext(f"{_ATOM_NS}id") or "").strip()
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1]
        if not arxiv_id:
            continue

        title = " ".join((entry.findtext(f"{_ATOM_NS}title") or "").split())
        abstract = " ".join((entry.findtext(f"{_ATOM_NS}summary") or "").split()) or None
        published = entry.findtext(f"{_ATOM_NS}published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            name
            for author in entry.findall(f"{_ATOM_NS}author")
            if (name := (author.findtext(f"{_ATOM_NS}name") or "").strip())
        ]
        entry_categories = [
            term for category in entry.findall(f"{_ATOM_NS}category") if (term := category.get("term"))
        ]

        pdf_url = next(
            (link.get("href") for link in entry.findall(f"{_ATOM_NS}link") if link.get("type") == "application/pdf"),
            None,
        )
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        results.append(
            ExternalPaperResult(
                source="arxiv",
                external_id=arxiv_id,
                title=title or "Untitled",
                authors=authors,
                abstract=abstract,
                year=year,
                pdf_url=pdf_url,
                external_url=raw_id or None,
                importable=True,
                categories=entry_categories,
            )
        )
    return results


def search_semantic_scholar(query: str, limit: int, settings: Settings) -> list[ExternalPaperResult]:
    headers = {"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else None
    with _http_client(settings) as client:
        response = _request_with_retry(
            client,
            "GET",
            f"{settings.semantic_scholar_api_base_url}/paper/search",
            max_retries=settings.external_api_max_retries,
            params={
                "query": query,
                "limit": limit,
                "fields": "title,abstract,authors,year,externalIds,openAccessPdf,url,fieldsOfStudy",
            },
            headers=headers,
        )

    try:
        body = response.json()
    except ValueError as error:
        raise ExternalPaperError(f"Semantic Scholar returned an unparsable response: {error}") from error

    results: list[ExternalPaperResult] = []
    for item in body.get("data") or []:
        paper_id = item.get("paperId")
        if not paper_id:
            continue

        open_access_pdf = item.get("openAccessPdf") or {}
        pdf_url = open_access_pdf.get("url")
        authors = [name for author in item.get("authors") or [] if (name := author.get("name"))]

        results.append(
            ExternalPaperResult(
                source="semantic_scholar",
                external_id=paper_id,
                title=item.get("title") or "Untitled",
                authors=authors,
                abstract=item.get("abstract"),
                year=item.get("year"),
                pdf_url=pdf_url,
                external_url=item.get("url"),
                importable=pdf_url is not None,
                # Not the arXiv taxonomy driving the actual filter — just Semantic
                # Scholar's own field-of-study labels, shown as a secondary badge.
                categories=item.get("fieldsOfStudy") or [],
            )
        )
    return results


def _get_arxiv_id(external_ids: dict) -> str | None:
    # Semantic Scholar documents the key as "ArXiv", but external APIs are not
    # worth a hard crash over a casing surprise — check case-insensitively.
    for key, value in external_ids.items():
        if key.lower() == "arxiv" and value:
            return str(value)
    return None


def map_citation_graph_entry(item: dict) -> ExternalPaperResult | None:
    """Maps one entry from Semantic Scholar's `references`/`citations` sub-fields
    (a nested paper stub, not a full search result) into the same `ExternalPaperResult`
    shape search uses — so the frontend and the `/papers/import` endpoint don't need
    a second code path to handle citation-graph results.

    Returns None for stubs Semantic Scholar couldn't resolve to a known paper (no
    `paperId`) or has no title for — there's nothing actionable to show for those.
    """
    paper_id = item.get("paperId")
    title = item.get("title")
    if not paper_id or not title:
        return None

    external_ids = item.get("externalIds") or {}
    arxiv_id = _get_arxiv_id(external_ids)
    open_access_pdf = item.get("openAccessPdf") or {}
    pdf_url = open_access_pdf.get("url")
    authors = [name for author in item.get("authors") or [] if (name := author.get("name"))]

    if arxiv_id:
        source, external_id = "arxiv", arxiv_id
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        external_url = f"https://arxiv.org/abs/{arxiv_id}"
    else:
        source, external_id = "semantic_scholar", paper_id
        external_url = f"https://www.semanticscholar.org/paper/{paper_id}"

    return ExternalPaperResult(
        source=source,
        external_id=external_id,
        title=title,
        authors=authors,
        abstract=None,
        year=item.get("year"),
        pdf_url=pdf_url,
        external_url=external_url,
        importable=pdf_url is not None,
        citation_count=item.get("citationCount"),
    )


_CITATION_GRAPH_FIELDS = (
    "title,citationCount,referenceCount,"
    "references.title,references.year,references.authors,references.externalIds,"
    "references.openAccessPdf,references.citationCount,"
    "citations.title,citations.year,citations.authors,citations.externalIds,"
    "citations.openAccessPdf,citations.citationCount"
)


def fetch_semantic_scholar_paper_graph(
    source: str,
    external_id: str,
    settings: Settings | None = None,
) -> dict | None:
    """Looks up citation-graph metadata (citation count, references, citing papers)
    for an imported paper via Semantic Scholar's paper-details endpoint.

    Works for arXiv imports too: Semantic Scholar accepts `ARXIV:<id>` as a paper
    id, so an arXiv-sourced import can still get graph data without ever having
    gone through Semantic Scholar search. Returns None (never raises) when
    Semantic Scholar has no record for this paper or the lookup fails — citation
    data is a nice-to-have, not something that should break an import or a page
    load.
    """
    settings = settings or get_settings()
    versionless_id = external_id.split("v")[0] if source == "arxiv" else external_id
    s2_paper_id = f"ARXIV:{versionless_id}" if source == "arxiv" else versionless_id

    headers = {"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else None
    try:
        with _http_client(settings) as client:
            response = _request_with_retry(
                client,
                "GET",
                f"{settings.semantic_scholar_api_base_url}/paper/{s2_paper_id}",
                max_retries=settings.external_api_max_retries,
                params={"fields": _CITATION_GRAPH_FIELDS},
                headers=headers,
            )
    except ExternalPaperError as error:
        logger.info("semantic_scholar_graph_lookup_unavailable external_id=%s error=%s", external_id, error)
        return None

    try:
        return response.json()
    except ValueError as error:
        logger.warning("semantic_scholar_graph_lookup_unparsable external_id=%s error=%s", external_id, error)
        return None


def search_papers(
    query: str | None,
    limit: int = 10,
    settings: Settings | None = None,
    *,
    categories: list[str] | None = None,
    sort: str = "relevance",
) -> tuple[list[ExternalPaperResult], list[str]]:
    """Queries arXiv (keyword and/or category, optionally sorted by recency) and
    Semantic Scholar (keyword only — it has no query-less category browse at this
    API tier) and merges the results.

    Each provider is isolated in its own try/except: one being down, rate-limited,
    or timing out doesn't take out the whole search — the caller gets whatever
    results the other provider returned, plus a warning describing what was
    skipped, instead of a 500. Semantic Scholar is skipped (not "failed") when
    there's no keyword to search it with — that's an expected omission for
    category-only browsing, not a warning-worthy problem.
    """
    settings = settings or get_settings()
    results: list[ExternalPaperResult] = []
    warnings: list[str] = []

    try:
        results.extend(search_arxiv(query, limit, settings, categories=categories, sort=sort))
    except ExternalPaperError as error:
        logger.warning("arxiv_search_failed query=%r categories=%r error=%s", query, categories, error)
        warnings.append(f"arXiv search unavailable: {error}")

    if query:
        try:
            results.extend(search_semantic_scholar(query, limit, settings))
        except ExternalPaperError as error:
            logger.warning("semantic_scholar_search_failed query=%r error=%s", query, error)
            warnings.append(f"Semantic Scholar search unavailable: {error}")

    if not results and not warnings:
        warnings.append("No results found for that search.")

    return results, warnings


def search_recent_category_papers(
    categories: list[str],
    limit: int,
    settings: Settings | None = None,
) -> tuple[list[ExternalPaperResult], list[str]]:
    """Fetches recent arXiv candidates for a user's interest categories.

    Recommendations intentionally use arXiv only: it supports category-only
    recent browsing, while Semantic Scholar requires a keyword query.
    """
    settings = settings or get_settings()
    cache_key = (tuple(sorted(categories)), limit)
    cached = _recent_category_cache.get(cache_key)
    if cached is not None and time.monotonic() - cached[0] < _RECENT_CACHE_TTL_SECONDS:
        return [result.model_copy() for result in cached[1]], []

    try:
        results = search_arxiv(None, limit, settings, categories=categories, sort="recent")
    except ExternalPaperError as error:
        logger.warning("recommendation_arxiv_search_failed categories=%r error=%s", categories, error)
        # Serve stale candidates over nothing if we have them — a rate-limit
        # blip shouldn't blank the recommendations panel.
        # The full error (URL, status, attempts) is already in the log above;
        # the UI just needs to know it's a transient upstream problem.
        if cached is not None:
            return [result.model_copy() for result in cached[1]], [
                "arXiv is temporarily unavailable; showing recently fetched candidates."
            ]
        return [], ["arXiv is temporarily unavailable (it returns sporadic errors); refresh in a minute to retry."]

    _recent_category_cache[cache_key] = (time.monotonic(), results)
    # Callers annotate results per-user (matched_categories, score), so hand out
    # copies and keep the cached originals pristine.
    return [result.model_copy() for result in results], []


def download_pdf(pdf_url: str, max_size_bytes: int, settings: Settings | None = None) -> bytes:
    """Downloads a PDF from an external source (arXiv / Semantic Scholar open-access
    link) with the same retry/backoff behavior as search, then enforces the same
    size limit and PDF validity check the manual-upload path applies — an import
    should not be able to bypass either.
    """
    settings = settings or get_settings()
    with _http_client(settings) as client:
        response = _request_with_retry(
            client,
            "GET",
            pdf_url,
            max_retries=settings.external_api_max_retries,
        )

    content_length = response.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_size_bytes:
        raise ExternalPaperError(f"Remote PDF exceeds the {max_size_bytes // (1024 * 1024)} MB limit")

    contents = response.content
    if len(contents) > max_size_bytes:
        raise ExternalPaperError(f"Remote PDF exceeds the {max_size_bytes // (1024 * 1024)} MB limit")

    if not contents.startswith(b"%PDF-"):
        raise ExternalPaperError("The downloaded file does not look like a valid PDF")

    return contents
