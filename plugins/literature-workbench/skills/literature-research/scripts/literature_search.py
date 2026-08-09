#!/usr/bin/env python3
"""PubMed/arXiv/WoS literature search helper for literature-research."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None


def is_windows_platform(platform: str | None = None) -> bool:
    return (platform or sys.platform).lower().startswith("win")


def default_config_path(
    platform: str | None = None,
    env: dict[str, str] | os._Environ[str] | None = None,
    home: Path | None = None,
) -> Path:
    environment = env if env is not None else os.environ
    user_home = home or Path.home()
    if is_windows_platform(platform):
        local_app_data = Path(environment.get("LOCALAPPDATA") or user_home / "AppData" / "Local")
        return local_app_data / "frank-ai4s" / "academic-research.json"
    return user_home / ".config" / "frank-ai4s" / "academic-research.json"


def default_easyscholar_cache_path(
    platform: str | None = None,
    env: dict[str, str] | os._Environ[str] | None = None,
    home: Path | None = None,
) -> Path:
    environment = env if env is not None else os.environ
    user_home = home or Path.home()
    if is_windows_platform(platform):
        local_app_data = Path(environment.get("LOCALAPPDATA") or user_home / "AppData" / "Local")
        return local_app_data / "frank-ai4s" / "cache" / "easyscholar_journal_ranks.json"
    return user_home / ".cache" / "frank-ai4s" / "easyscholar_journal_ranks.json"


LEGACY_CONFIG_PATH = Path.home() / ".config" / "frank-ai4s" / "academic-research.json"
LEGACY_EASYSCHOLAR_CACHE = Path.home() / ".cache" / "frank-ai4s" / "easyscholar_journal_ranks.json"
CONFIG_PATH = default_config_path()
USER_AGENT = "FrankAI4S/literature-research (literature_search.py)"
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ARXIV_BASE = "https://export.arxiv.org/api/query"
DEFAULT_JOURNAL_METRICS = Path(__file__).resolve().parent.parent / "references" / "jcr_journals_2025.csv"
EASYSCHOLAR_BASE = "https://www.easyscholar.cc/open/getPublicationRank"
DEFAULT_EASYSCHOLAR_CACHE = default_easyscholar_cache_path()
STOPWORDS = {
    "about",
    "and",
    "are",
    "between",
    "for",
    "from",
    "how",
    "in",
    "into",
    "last",
    "of",
    "on",
    "past",
    "recent",
    "role",
    "the",
    "to",
    "what",
    "with",
    "year",
    "years",
}

DATABASE_ROUTES: dict[str, dict[str, Any]] = {
    "pubmed": {
        "display_name": "PubMed",
        "aliases": ["pubmed", "ncbi", "pmid", "medline"],
        "access_mode": "api-first",
        "primary_tool": "search-pubmed",
        "requires_web_access": False,
        "pattern_reference": "references/database-patterns/pubmed.md",
        "start_url": "https://pubmed.ncbi.nlm.nih.gov/",
        "expected_evidence": [
            "query plan JSON",
            "PubMed records JSON from search-pubmed",
            "ranked JSON/CSV after merge-rank",
        ],
        "warnings": [
            "Always pass --limit and report that capped retrieval is not exhaustive.",
            "Use browser verification only for page-level checks that the API cannot answer.",
        ],
    },
    "arxiv": {
        "display_name": "arXiv",
        "aliases": ["arxiv", "arxiv.org", "preprint"],
        "access_mode": "api-first",
        "primary_tool": "search-arxiv",
        "requires_web_access": False,
        "pattern_reference": "references/database-patterns/arxiv.md",
        "start_url": "https://arxiv.org/search/",
        "expected_evidence": [
            "query plan JSON",
            "arXiv records JSON from search-arxiv",
            "ranked JSON/CSV after merge-rank",
        ],
        "warnings": [
            "Treat arXiv records as preprints unless peer-review status is separately verified.",
            "Use compact keyword queries; arXiv is weaker for biomedical Boolean expansion.",
        ],
    },
    "web-of-science": {
        "display_name": "Web of Science",
        "aliases": ["web of science", "wos", "clarivate", "webofscience.com"],
        "access_mode": "campus-browser-official-export",
        "primary_tool": "import-wos-export",
        "requires_web_access": True,
        "web_access_entrypoint": "web-access/scripts/check-deps.mjs",
        "pattern_reference": "references/database-patterns/webofscience.md",
        "start_url": "https://www.webofscience.com/wos/alldb/basic-search",
        "expected_evidence": [
            "query plan JSON with wos_query",
            "optional screenshot of WoS query/result context",
            "official WoS CSV/TSV export kept outside the repository",
            "normalized WoS records JSON from import-wos-export",
            "ranked JSON/CSV after merge-rank",
        ],
        "warnings": [
            "Use web-access for browser readiness and navigation; do not copy CDP code here.",
            "Prefer official exports over DOM scraping.",
            "Do not bypass CAPTCHA, institutional login, license limits, or export controls.",
        ],
    },
}


class RateLimitError(RuntimeError):
    """Raised when an API returns HTTP 429."""


class RateLimiter:
    """Cross-platform file-lock rate limiter.

    POSIX: uses fcntl.flock for cross-process coordination.
    Windows: uses msvcrt.locking for cross-process coordination.
    Fallback: uncoordinated sleep (when neither is available).
    """

    def __init__(self, name: str, min_interval: float) -> None:
        self.name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        self.min_interval = min_interval
        root = Path(tempfile.gettempdir()) / "frank_ai4s_rate_limits"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"{self.name}.lock"

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        if fcntl is not None:
            self._wait_posix()
        elif msvcrt is not None:
            self._wait_windows()
        else:
            time.sleep(self.min_interval)

    def _wait_posix(self) -> None:
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                now = self._compute_and_write(handle)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _wait_windows(self) -> None:
        # msvcrt.locking works on files opened in binary mode
        self.path.touch(exist_ok=True)
        with self.path.open("r+b") as handle:
            # Spin until we acquire the lock (bounded retries)
            for _ in range(200):
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.02)
            else:
                # Fallback: proceed without lock rather than hang
                time.sleep(self.min_interval)
                return
            try:
                now = self._compute_and_write(handle)
            finally:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass

    def _compute_and_write(self, handle: Any) -> float:
        """Read last timestamp, sleep if needed, write current timestamp."""
        handle.seek(0)
        raw = handle.read().strip()
        now = time.monotonic()
        try:
            last = float(raw) if raw else 0.0
        except ValueError:
            last = 0.0
        if 0 < last <= now:
            delay = self.min_interval - (now - last)
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
        handle.seek(0)
        handle.truncate()
        handle.write(f"{now:.6f}".encode() if "b" in getattr(handle, "mode", "") else f"{now:.6f}")
        handle.flush()
        return now


def sanitize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in {"api_key", "secretkey"}
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )


def request_text(url: str, rate_name: str, min_interval: float, retries: int = 3) -> str:
    limiter = RateLimiter(rate_name, min_interval)
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(retries + 1):
        limiter.wait()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            safe_url = sanitize_url(url)
            if exc.code == 429:
                raise RateLimitError(f"HTTP 429 rate limit from {safe_url}") from exc
            if 500 <= exc.code < 600 and attempt < retries:
                delay = 2**attempt
                print(f"Transient HTTP {exc.code}; retrying in {delay}s: {safe_url}", file=sys.stderr)
                time.sleep(delay)
                continue
            raise RuntimeError(f"HTTP {exc.code} from {safe_url}: {body[:1000]}") from exc
        except urllib.error.URLError as exc:
            safe_url = sanitize_url(url)
            if attempt < retries:
                delay = 2**attempt
                print(f"Network error; retrying in {delay}s: {safe_url}", file=sys.stderr)
                time.sleep(delay)
                continue
            raise RuntimeError(f"Network error from {safe_url}: {exc}") from exc
    raise RuntimeError(f"Request failed after retries: {sanitize_url(url)}")


def write_json(path: str | Path, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or CONFIG_PATH
    if (
        path is None
        and is_windows_platform()
        and target == default_config_path()
        and not target.exists()
        and LEGACY_CONFIG_PATH.exists()
    ):
        target = LEGACY_CONFIG_PATH
    if not target.exists():
        return {}
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def current_date() -> str:
    return dt.date.today().isoformat()


def compact_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def text_of(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return compact_space(" ".join(node.itertext()))


def _current_year() -> int:
    """Return the current year. Patchable for testing."""
    return dt.date.today().year


def detect_year_range(query: str) -> dict[str, int] | None:
    now = _current_year()
    match = re.search(r"(?:past|last)\s+(\d{1,2})\s+years?", query, re.I)
    if match:
        years = int(match.group(1))
        return {"start_year": now - years + 1, "end_year": now}
    match = re.search(r"(?:过去|近)\s*([一二三四五六七八九十\d]{1,3})\s*年", query)
    if match:
        years = chinese_or_int(match.group(1))
        if years:
            return {"start_year": now - years + 1, "end_year": now}
    match = re.search(r"(20\d{2}|19\d{2})\s*[-–]\s*(20\d{2}|19\d{2})", query)
    if match:
        return {"start_year": int(match.group(1)), "end_year": int(match.group(2))}
    return None


def chinese_or_int(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + digits.get(value[-1], 0)
    if value.endswith("十"):
        return digits.get(value[0], 0) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value)


def extract_candidate_terms(query: str) -> list[str]:
    """Extract candidate search terms from a natural-language query.

    Captures both ASCII identifiers (gene/protein names, acronyms) and
    CJK continuous runs (Chinese biomedical terms). This is a naive
    extraction; use ``expand-query`` for LLM-assisted domain expansion.
    """
    terms: list[str] = []
    # ASCII tokens: gene names, acronyms, identifiers (e.g. GPLD1, COVID-19)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", query):
        if token.lower() not in STOPWORDS and token not in terms:
            terms.append(token)
    # CJK tokens: Chinese biomedical terms (e.g. 心血管疾病, 心肌病)
    # Split CJK runs by ASCII characters, digits, and common delimiters
    for token in re.findall(r"[一-鿿]+", query):
        if token not in terms:
            terms.append(token)
    return terms


def command_config(args: argparse.Namespace) -> None:
    if (
        is_windows_platform()
        and CONFIG_PATH == default_config_path()
        and not CONFIG_PATH.exists()
        and LEGACY_CONFIG_PATH.exists()
    ):
        write_json(CONFIG_PATH, load_config(LEGACY_CONFIG_PATH))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    set_keys = [
        ("pubmed_api_key", getattr(args, "set_pubmed_api_key", None)),
        # Retained for backward compatibility but intentionally hidden from
        # first-run onboarding and default status output.
        ("s2_api_key", getattr(args, "set_s2_api_key", None)),
        ("easyscholar_secret_key", getattr(args, "set_easyscholar_key", None)),
    ]
    any_key_set = False
    for config_key, value in set_keys:
        if value is None:
            continue
        config = load_config()
        if value:
            config[config_key] = value
        else:
            config.pop(config_key, None)
        write_json(CONFIG_PATH, config)
        if not is_windows_platform():
            CONFIG_PATH.chmod(0o600)
        any_key_set = True
        print(f"Updated {config_key} in {CONFIG_PATH}")

    if args.init:
        if not CONFIG_PATH.exists():
            write_json(
                CONFIG_PATH,
                {
                    "pubmed_api_key": "",
                    "easyscholar_secret_key": "",
                    "email": "",
                },
            )
            if not is_windows_platform():
                CONFIG_PATH.chmod(0o600)
            print(f"Created config template: {CONFIG_PATH}")
        else:
            print(f"Config already exists: {CONFIG_PATH}")

    if args.show or (not args.init and not any_key_set):
        config = load_config()
        has_pubmed = bool(config.get("pubmed_api_key") or os.environ.get("PUBMED_API_KEY"))
        has_easyscholar = bool(
            config.get("easyscholar_secret_key") or os.environ.get("EASYSCHOLAR_SECRET_KEY")
        )
        print(f"Config path: {CONFIG_PATH}")
        print(f"PubMed API key configured: {'yes' if has_pubmed else 'no'}")
        print(f"easyscholar API key configured: {'yes' if has_easyscholar else 'no'}")


def command_plan(args: argparse.Namespace) -> None:
    plan = build_query_plan(args.query)
    write_json(args.output, plan)
    print(f"Success! Query plan written to: {args.output}")


def build_query_plan(query: str) -> dict[str, Any]:
    terms = extract_candidate_terms(query)
    year_range = detect_year_range(query)
    return {
        "created_at": current_date(),
        "question": query,
        "constraints": {"year_range": year_range, "notes": []},
        "core_terms": terms,
        "expanded_terms": [],
        "exclude_terms": [],
        "mesh_terms": [],
        "pubmed_query": " AND ".join(f"({term})" for term in terms) if terms else query,
        "arxiv_query": " ".join(terms) if terms else query,
        "wos_query": f"TS=(({' AND '.join(terms)}))" if terms else query,
        "screening_notes": [
            "Review and edit this machine-generated plan before relying on it.",
            "Add MeSH terms, synonyms, organism constraints, and exclusions explicitly.",
            "Use expand-query for LLM-assisted domain expansion of terms and MeSH vocabulary.",
        ],
        "expansion_source": None,
    }


def pubmed_interval(api_key: str | None) -> float:
    return 0.11 if api_key else 0.34


def get_pubmed_api_key(args: argparse.Namespace) -> str | None:
    if args.api_key:
        return args.api_key
    if os.environ.get("PUBMED_API_KEY"):
        return os.environ["PUBMED_API_KEY"]
    return load_config().get("pubmed_api_key") or None


def get_easyscholar_api_key(args: argparse.Namespace) -> str | None:
    """Resolve easyscholar secretKey from args, env, or config."""
    if getattr(args, "easyscholar_api_key", None):
        return args.easyscholar_api_key
    if os.environ.get("EASYSCHOLAR_SECRET_KEY"):
        return os.environ["EASYSCHOLAR_SECRET_KEY"]
    return load_config().get("easyscholar_secret_key") or None


def resolve_pubmed_query(args: argparse.Namespace) -> str:
    query = compact_space(getattr(args, "query", "") or "")
    if query:
        return query
    query_json = getattr(args, "query_json", None)
    if query_json:
        data = load_json(query_json)
        field = getattr(args, "query_field", "pubmed_query") or "pubmed_query"
        value = compact_space(data.get(field, ""))
        if value:
            return value
        raise ValueError(f"query field '{field}' was empty in {query_json}")
    raise ValueError("provide --query or --query-json")


def pubmed_url(endpoint: str, params: dict[str, Any]) -> str:
    return f"{NCBI_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"


def command_search_pubmed(args: argparse.Namespace) -> None:
    query = resolve_pubmed_query(args)
    api_key = get_pubmed_api_key(args)
    interval = pubmed_interval(api_key)
    params: dict[str, Any] = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": args.limit,
        "sort": "relevance",
    }
    if api_key:
        params["api_key"] = api_key
    search_data = json.loads(request_text(pubmed_url("esearch.fcgi", params), "pubmed", interval))
    ids = search_data.get("esearchresult", {}).get("idlist", [])
    records: list[dict[str, Any]] = []
    for start in range(0, len(ids), 100):
        batch = ids[start : start + 100]
        if not batch:
            continue
        fetch_params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(batch),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if api_key:
            fetch_params["api_key"] = api_key
        xml_text = request_text(pubmed_url("efetch.fcgi", fetch_params), "pubmed", interval)
        records.extend(parse_pubmed_xml(xml_text))
    output = {
        "source": "pubmed",
        "query": query,
        "retrieved_at": current_date(),
        "limit": args.limit,
        "count": len(records),
        "records": records,
    }
    write_json(args.output, output)
    print(f"Success! PubMed records written to: {args.output}")


def parse_pubmed_xml(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    records: list[dict[str, Any]] = []
    for article in root.findall(".//PubmedArticle"):
        medline = article.find("MedlineCitation")
        pmid = text_of(medline.find("PMID") if medline is not None else None)
        art = article.find(".//Article")
        title = text_of(art.find("ArticleTitle") if art is not None else None)
        abstract_parts = [text_of(node) for node in article.findall(".//Abstract/AbstractText")]
        abstract = compact_space(" ".join(part for part in abstract_parts if part))
        journal = text_of(article.find(".//Journal/Title"))
        year = extract_pubmed_year(article)
        doi = ""
        for node in article.findall(".//ArticleId"):
            if node.attrib.get("IdType", "").lower() == "doi":
                doi = text_of(node)
                break
        mesh_terms = [text_of(node.find("DescriptorName")) for node in article.findall(".//MeshHeading")]
        article_types = [text_of(node) for node in article.findall(".//PublicationType")]
        authors = extract_pubmed_authors(article)
        issns = []
        for node in article.findall(".//Journal/ISSN"):
            issn = normalize_issn(text_of(node))
            if issn and issn not in issns:
                issns.append(issn)
        records.append(
            {
                "source": "pubmed",
                "id": pmid,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "journal": journal,
                "year": year,
                "published": str(year) if year else "",
                "doi": doi,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                "issns": issns,
                "mesh_terms": [term for term in mesh_terms if term],
                "article_types": [kind for kind in article_types if kind],
            }
        )
    return records


def extract_pubmed_year(article: ET.Element) -> int | None:
    for path in [
        ".//ArticleDate/Year",
        ".//JournalIssue/PubDate/Year",
        ".//DateCompleted/Year",
        ".//DateRevised/Year",
    ]:
        value = text_of(article.find(path))
        if value.isdigit():
            return int(value)
    medline_date = text_of(article.find(".//JournalIssue/PubDate/MedlineDate"))
    match = re.search(r"(19|20)\d{2}", medline_date)
    return int(match.group(0)) if match else None


def extract_pubmed_authors(article: ET.Element) -> list[str]:
    authors: list[str] = []
    for node in article.findall(".//AuthorList/Author"):
        collective = text_of(node.find("CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        last = text_of(node.find("LastName"))
        initials = text_of(node.find("Initials"))
        if last:
            authors.append(f"{last} {initials}".strip())
    return authors


def command_search_arxiv(args: argparse.Namespace) -> None:
    params = {
        "search_query": f"all:{args.query}",
        "start": 0,
        "max_results": args.limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    xml_text = request_text(f"{ARXIV_BASE}?{urllib.parse.urlencode(params)}", "arxiv", 3.0)
    records = parse_arxiv_xml(xml_text)
    output = {
        "source": "arxiv",
        "query": args.query,
        "retrieved_at": current_date(),
        "limit": args.limit,
        "count": len(records),
        "records": records,
    }
    write_json(args.output, output)
    print(f"Success! arXiv records written to: {args.output}")


def parse_arxiv_xml(xml_text: str) -> list[dict[str, Any]]:
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_text)
    records: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        url = text_of(entry.find("atom:id", ns))
        arxiv_id = url.rstrip("/").split("/")[-1] if url else ""
        published = text_of(entry.find("atom:published", ns))
        year = int(published[:4]) if re.match(r"\d{4}", published) else None
        doi = text_of(entry.find("arxiv:doi", ns))
        authors = [text_of(author.find("atom:name", ns)) for author in entry.findall("atom:author", ns)]
        categories = [node.attrib.get("term", "") for node in entry.findall("atom:category", ns)]
        records.append(
            {
                "source": "arxiv",
                "id": arxiv_id,
                "title": text_of(entry.find("atom:title", ns)),
                "abstract": text_of(entry.find("atom:summary", ns)),
                "authors": [author for author in authors if author],
                "journal": "arXiv",
                "year": year,
                "published": published,
                "doi": doi,
                "url": url,
                "issns": [],
                "mesh_terms": [],
                "article_types": ["preprint"],
                "categories": [cat for cat in categories if cat],
            }
        )
    return records


def normalize_issn(value: str) -> str:
    cleaned = re.sub(r"[^0-9Xx]", "", value or "").upper()
    if len(cleaned) == 8:
        return f"{cleaned[:4]}-{cleaned[4:]}"
    return cleaned


def normalize_journal_name(value: str) -> str:
    """Normalize a journal name for cache-key and fuzzy matching.

    Steps: compact whitespace, lowercase, remove punctuation/non-alphanumerics,
    strip leading articles (the, journal of, annals of), collapse spaces.
    """
    text = compact_space(value or "")
    text = text.lower()
    # Replace punctuation and non-alphanumeric with space, but keep CJK chars.
    text = re.sub(r"[^\w一-鿿]", " ", text)
    text = compact_space(text)
    # Strip leading articles that are common in journal titles.
    prefixes = ("the journal of ", "journal of ", "journal of the ", "annals of ", "the ")
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix):]
                changed = True
                break
    return compact_space(text)


def load_easyscholar_cache(path: str | Path | None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_EASYSCHOLAR_CACHE
    if (
        path is None
        and is_windows_platform()
        and target == default_easyscholar_cache_path()
        and not target.exists()
        and LEGACY_EASYSCHOLAR_CACHE.exists()
    ):
        target = LEGACY_EASYSCHOLAR_CACHE
    if not target.exists():
        return {"version": 1, "created_at": current_date(), "entries": {}}
    try:
        data = load_json(target)
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            return data
    except Exception as exc:
        print(f"EasyScholar cache load failed ({target}): {exc}; starting fresh.", file=sys.stderr)
    return {"version": 1, "created_at": current_date(), "entries": {}}


def save_easyscholar_cache(path: str | Path | None, cache: dict[str, Any]) -> None:
    target = Path(path) if path else DEFAULT_EASYSCHOLAR_CACHE
    target.parent.mkdir(parents=True, exist_ok=True)
    cache.setdefault("version", 1)
    cache["updated_at"] = current_date()
    write_json(target, cache)




def split_multi_value(value: Any) -> list[str]:
    text = compact_space(str(value or ""))
    if not text:
        return []
    parts = re.split(r"\s*(?:;|\||\n)\s*", text)
    return [part.strip() for part in parts if part.strip()]


def read_delimited_rows(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    if source.suffix.lower() in {".xlsx", ".xls"}:
        raise ValueError("convert binary Excel exports to CSV or tab-delimited text before import")
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = source.read_text(encoding=encoding, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    else:
        text = source.read_text(encoding="utf-8", errors="replace")
    sample = text[:4096]
    if source.suffix.lower() in {".tsv", ".tab", ".txt"}:
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
        except csv.Error:
            delimiter = "\t" if "\t" in sample else ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError(f"no tabular records found in {source}")
    return rows


def normalized_row(row: dict[str, str]) -> dict[str, str]:
    return {normalize_header(key): value for key, value in row.items()}


def first_wos_value(row: dict[str, str], candidates: list[str]) -> str:
    normalized = normalized_row(row)
    for candidate in candidates:
        value = normalized.get(normalize_header(candidate), "")
        if value:
            return compact_space(value)
    return ""


def parse_year_value(value: str) -> int | None:
    match = re.search(r"(19|20)\d{2}", value or "")
    return int(match.group(0)) if match else None


def normalize_wos_export_record(row: dict[str, str]) -> dict[str, Any]:
    title = first_wos_value(row, ["Article Title", "Title", "TI"])
    journal = first_wos_value(row, ["Source Title", "Publication Name", "Journal", "SO"])
    year = parse_year_value(first_wos_value(row, ["Publication Year", "Year Published", "PY", "Year"]))
    doi = first_wos_value(row, ["DOI", "DI"])
    accession = first_wos_value(row, ["UT (Unique WOS ID)", "UT", "Accession Number"])
    abstract = first_wos_value(row, ["Abstract", "AB"])
    authors = split_multi_value(first_wos_value(row, ["Authors", "Author Full Names", "AU", "AF"]))
    issns = []
    for value in split_multi_value(first_wos_value(row, ["ISSN", "SN"])):
        issn = normalize_issn(value)
        if issn and issn not in issns:
            issns.append(issn)
    for value in split_multi_value(first_wos_value(row, ["eISSN", "EI"])):
        issn = normalize_issn(value)
        if issn and issn not in issns:
            issns.append(issn)
    article_types = split_multi_value(first_wos_value(row, ["Document Type", "DT"]))
    keywords = split_multi_value(first_wos_value(row, ["Author Keywords", "Keywords", "DE", "ID"]))
    return {
        "source": "wos",
        "id": accession,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal,
        "year": year,
        "published": str(year) if year else "",
        "doi": doi,
        "url": f"https://doi.org/{doi}" if doi else "",
        "issns": issns,
        "mesh_terms": [],
        "article_types": article_types,
        "keywords": keywords,
    }


def wos_import_identity(record: dict[str, Any]) -> tuple[str, str]:
    """Return a conservative identity key for merging official WoS export batches."""
    accession = str(record.get("id") or "").strip().casefold()
    if accession:
        return ("ut", accession)
    doi = str(record.get("doi") or "").strip().casefold()
    if doi:
        return ("doi", doi)
    return ("", "")


def command_import_wos_export(args: argparse.Namespace) -> None:
    input_paths = [Path(path) for path in args.input]
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    duplicate_count = 0
    for path in input_paths:
        for row in read_delimited_rows(path):
            record = normalize_wos_export_record(row)
            if not (record.get("title") or record.get("doi") or record.get("id")):
                continue
            identity = wos_import_identity(record)
            if identity != ("", "") and identity in seen:
                duplicate_count += 1
                continue
            if identity != ("", ""):
                seen.add(identity)
            records.append(record)
    records = records[: args.limit]
    output = {
        "source": "wos",
        "query": args.query or "",
        "retrieved_at": current_date(),
        "input_files": [str(path) for path in input_paths],
        "limit": args.limit,
        "count": len(records),
        "records": records,
        "notes": [
            "Imported from official Web of Science export file batches.",
            "Records are de-duplicated by WoS UT, then DOI, before applying the explicit limit.",
            "Verify that the export was generated through authorized campus or institutional access.",
        ],
        "duplicate_records_skipped": duplicate_count,
    }
    write_json(args.output, output)
    print(f"Success! Web of Science export imported to: {args.output}")


def normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value or "").lower()


def pick_column(fieldnames: list[str], candidates: list[str]) -> str | None:
    normalized = {normalize_header(name): name for name in fieldnames}
    for candidate in candidates:
        if normalize_header(candidate) in normalized:
            return normalized[normalize_header(candidate)]
    return None


def parse_float_safe(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"N/A", "NA", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_zone(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def read_csv_rows(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with Path(path).open("r", encoding=encoding, newline="", errors="strict") as handle:
                reader = csv.DictReader(handle)
                rows = [dict(row) for row in reader]
                return list(reader.fieldnames or []), rows
        except UnicodeDecodeError:
            continue
    with Path(path).open("r", encoding="utf-8", newline="", errors="replace") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames or []), rows


def journal_metric_columns(fieldnames: list[str]) -> dict[str, str | None]:
    return {
        "journal": pick_column(fieldnames, ["Journal", "期刊名称", "名字", "全称", "简称", "journal_name"]),
        "issn": pick_column(fieldnames, ["ISSN", "Print ISSN", "P-ISSN"]),
        "eissn": pick_column(fieldnames, ["EISSN", "E-ISSN", "Electronic ISSN"]),
        "cas_zone": pick_column(fieldnames, ["CAS-zone", "CAS分区", "大类分区", "中科院分区"]),
        "jcr_zone": pick_column(fieldnames, ["JCR-zone", "JCR分区", "JCR", "Q分区"]),
        "impact_factor": pick_column(fieldnames, ["2024-IF", "2024最新IF", "2023最新IF", "最新影响因子", "影响因子", "Impact Factor", "IF"]),
        "five_year_if": pick_column(fieldnames, ["5-year-IF", "5年IF", "5 Year IF"]),
        "rank": pick_column(fieldnames, ["JIF Rank", "排名", "Rank"]),
    }


def load_journal_metrics(path: str | Path) -> list[dict[str, Any]]:
    fieldnames, rows = read_csv_rows(path)
    cols = journal_metric_columns(fieldnames)
    if not cols["issn"] and not cols["eissn"]:
        raise ValueError("journal metrics CSV must contain ISSN or EISSN columns")
    metrics: list[dict[str, Any]] = []
    for row in rows:
        issns = []
        for key in ("issn", "eissn"):
            col = cols[key]
            if col:
                issn = normalize_issn(row.get(col, ""))
                if issn and issn not in issns:
                    issns.append(issn)
        if not issns:
            continue
        metrics.append(
            {
                "journal": row.get(cols["journal"], "").strip() if cols["journal"] else "",
                "issns": issns,
                "cas_zone": row.get(cols["cas_zone"], "").strip() if cols["cas_zone"] else "",
                "jcr_zone": row.get(cols["jcr_zone"], "").strip() if cols["jcr_zone"] else "",
                "impact_factor": row.get(cols["impact_factor"], "").strip() if cols["impact_factor"] else "",
                "five_year_if": row.get(cols["five_year_if"], "").strip() if cols["five_year_if"] else "",
                "rank": row.get(cols["rank"], "").strip() if cols["rank"] else "",
            }
        )
    return metrics


def metric_matches(
    metric: dict[str, Any],
    cas_zones: list[str] | None,
    jcr_zones: list[str] | None,
    if_min: float | None,
    if_max: float | None,
) -> bool:
    if cas_zones and normalize_zone(metric.get("cas_zone")) not in {normalize_zone(zone) for zone in cas_zones}:
        return False
    if jcr_zones and normalize_zone(metric.get("jcr_zone")) not in {normalize_zone(zone) for zone in jcr_zones}:
        return False
    if if_min is not None or if_max is not None:
        impact = parse_float_safe(metric.get("impact_factor"))
        if impact is None:
            return False
        if if_min is not None and impact < if_min:
            return False
        if if_max is not None and impact > if_max:
            return False
    return True


def command_journal_filter_query(args: argparse.Namespace) -> None:
    metrics = load_journal_metrics(args.journal_metrics)
    selected = [
        metric
        for metric in metrics
        if metric_matches(
            metric,
            getattr(args, "cas_zones", None),
            getattr(args, "jcr_zones", None),
            getattr(args, "if_min", None),
            getattr(args, "if_max", None),
        )
    ]
    issns: list[str] = []
    for metric in selected:
        for issn in metric["issns"]:
            if issn and issn not in issns:
                issns.append(issn)
    query = " OR ".join(f'("{issn}"[ISSN])' for issn in issns)
    if len(issns) > 1:
        query = f"({query})"

    # Optional MeSH terms clause
    mesh_clause = ""
    mesh_terms = args.mesh_terms or []
    if mesh_terms:
        mesh_parts = [f'"{term}"[MeSH Terms]' for term in mesh_terms]
        mesh_clause = " OR ".join(mesh_parts)
        if len(mesh_parts) > 1:
            mesh_clause = f"({mesh_clause})"

    # Combined query: ISSN filter AND MeSH filter
    combined_parts = []
    if query:
        combined_parts.append(query)
    if mesh_clause:
        combined_parts.append(mesh_clause)
    combined_query = " AND ".join(combined_parts) if combined_parts else ""

    output = {
        "created_at": current_date(),
        "source_file": str(args.journal_metrics),
        "filters": {
            "cas_zones": args.cas_zones or [],
            "jcr_zones": args.jcr_zones or [],
            "if_min": args.if_min,
            "if_max": args.if_max,
            "mesh_terms": mesh_terms,
        },
        "matched_journals": len(selected),
        "matched_issns": len(issns),
        "pubmed_issn_query": query,
        "pubmed_mesh_query": mesh_clause,
        "pubmed_combined_query": combined_query,
        "journals": selected,
    }
    write_json(args.output, output)
    if args.markdown:
        lines = [
            "# PubMed ISSN + MeSH Filter Query",
            "",
            f"- Matched journals: {len(selected)}",
            f"- Matched ISSNs: {len(issns)}",
            f"- MeSH terms: {', '.join(mesh_terms) if mesh_terms else 'none'}",
            "",
            "### ISSN Query",
            "",
            "```text",
            query or "No ISSN matched the filters.",
            "```",
            "",
        ]
        if mesh_clause:
            lines += [
                "### MeSH Terms Query",
                "",
                "```text",
                mesh_clause,
                "```",
                "",
                "### Combined Query (ISSN AND MeSH)",
                "",
                "```text",
                combined_query,
                "```",
                "",
            ]
        Path(args.markdown).write_text("\n".join(lines), encoding="utf-8")
    print(f"Success! PubMed ISSN filter written to: {args.output}")


def command_compose_pubmed_query(args: argparse.Namespace) -> None:
    data = load_json(args.filter_json)
    filter_query = compact_space(data.get(args.filter_field, ""))
    if not filter_query:
        fallback = "pubmed_combined_query" if args.filter_field != "pubmed_combined_query" else "pubmed_issn_query"
        filter_query = compact_space(data.get(fallback, ""))
    if not filter_query:
        raise ValueError(f"no PubMed filter query found in {args.filter_json}")
    pubmed_query = f"({args.core_query}) AND ({filter_query})"
    output = {
        "created_at": current_date(),
        "core_query": args.core_query,
        "filter_json": str(args.filter_json),
        "filter_field": args.filter_field,
        "filter_query": filter_query,
        "pubmed_query": pubmed_query,
    }
    write_json(args.output, output)
    if args.markdown:
        lines = [
            "# PubMed Combined Query",
            "",
            "```text",
            pubmed_query,
            "```",
            "",
        ]
        Path(args.markdown).write_text("\n".join(lines), encoding="utf-8")
    print(f"Success! Combined PubMed query written to: {args.output}")


def command_enrich_journal_metrics(args: argparse.Namespace) -> None:
    data = load_json(args.ranked_json)
    metrics = [
        metric
        for metric in load_journal_metrics(args.journal_metrics)
        if metric_matches(metric, args.cas_zones, args.jcr_zones, args.if_min, args.if_max)
    ]
    by_issn = {issn: metric for metric in metrics for issn in metric["issns"]}
    enriched = []
    for record in data.get("records", []):
        match = None
        for issn in record.get("issns", []):
            match = by_issn.get(normalize_issn(issn))
            if match:
                break
        result = dict(record)
        if match:
            result["journal_metrics"] = {
                "journal": match.get("journal"),
                "cas_zone": match.get("cas_zone"),
                "jcr_zone": match.get("jcr_zone"),
                "impact_factor": match.get("impact_factor"),
                "five_year_if": match.get("five_year_if"),
                "rank": match.get("rank"),
            }
            result["score"] = round(float(result.get("score", 0)) + 1.0, 2)
            result.setdefault("score_reasons", []).append("journal metrics matched by ISSN")
        elif getattr(args, "filter_to_matches", False):
            continue
        enriched.append(result)
    enriched.sort(key=lambda item: item.get("score", 0), reverse=True)
    for index, record in enumerate(enriched, start=1):
        record["rank"] = index
    data["records"] = enriched
    data["journal_metrics_file"] = str(args.journal_metrics)
    data["journal_metrics_filter"] = {
        "cas_zones": getattr(args, "cas_zones", None) or [],
        "jcr_zones": getattr(args, "jcr_zones", None) or [],
        "if_min": getattr(args, "if_min", None),
        "if_max": getattr(args, "if_max", None),
        "filter_to_matches": bool(getattr(args, "filter_to_matches", False)),
        "matched_metric_journals": len(metrics),
    }
    write_json(args.output, data)
    if args.csv:
        write_csv(args.csv, enriched)
    print(f"Success! Enriched ranked records written to: {args.output}")


# ---------------------------------------------------------------------------
# easyscholar.cc journal rank enrichment
# ---------------------------------------------------------------------------

EASYSCHOLAR_RANK_TEXT_FIELDS = [
    "oneRankText",
    "twoRankText",
    "threeRankText",
    "fourRankText",
    "fiveRankText",
]


def parse_easyscholar_custom_rank(custom_rank: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Parse easyscholar customRank into a readable list of {dataset, rank}.

    The API returns rankInfo (list of dataset metadata) and rank (list of
    "uuid&&&rankIndex" strings). We resolve each rank string against rankInfo.
    """
    if not custom_rank or not isinstance(custom_rank, dict):
        return []

    rank_info_list = custom_rank.get("rankInfo") or []
    if isinstance(rank_info_list, dict):
        rank_info_list = [rank_info_list]
    rank_info_by_uuid = {
        str(info.get("uuid", "")): info
        for info in rank_info_list
        if isinstance(info, dict) and info.get("uuid")
    }

    raw_ranks = custom_rank.get("rank") or []
    if isinstance(raw_ranks, str):
        raw_ranks = [raw_ranks]

    results: list[dict[str, Any]] = []
    for raw in raw_ranks:
        if not isinstance(raw, str):
            continue
        parts = raw.split("&&&")
        if len(parts) != 2:
            continue
        uuid, rank_index_str = parts
        rank_index_str = rank_index_str.strip()
        if not rank_index_str.isdigit():
            continue
        rank_index = int(rank_index_str)
        info = rank_info_by_uuid.get(uuid)
        if not info:
            continue
        abb_name = info.get("abbName", "")
        text_field = EASYSCHOLAR_RANK_TEXT_FIELDS[rank_index - 1] if 1 <= rank_index <= 5 else None
        rank_text = info.get(text_field, "") if text_field else ""
        results.append(
            {
                "uuid": uuid,
                "dataset": abb_name,
                "rank_index": rank_index,
                "rank": rank_text,
            }
        )
    return results


def parse_easyscholar_official_rank(official_rank: dict[str, Any] | None) -> dict[str, Any]:
    """Extract non-empty fields from officialRank.all and officialRank.select."""
    if not official_rank or not isinstance(official_rank, dict):
        return {}

    def clean(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    result: dict[str, Any] = {}
    for bucket in ("all", "select"):
        bucket_data = official_rank.get(bucket)
        if not isinstance(bucket_data, dict):
            continue
        cleaned = {key: value for key, value in bucket_data.items() if clean(value) is not None}
        if cleaned:
            result[bucket] = cleaned
    return result


def fetch_easyscholar_rank(
    publication_name: str,
    api_key: str | None,
    min_interval: float = 1.0,
) -> dict[str, Any] | None:
    """Fetch journal rank data from easyscholar.cc for a single publication name."""
    if not publication_name or not publication_name.strip():
        return None

    params: dict[str, str] = {"publicationName": publication_name.strip()}
    if api_key:
        params["secretKey"] = api_key

    url = f"{EASYSCHOLAR_BASE}?{urllib.parse.urlencode(params)}"
    safe_url = sanitize_url(url)

    try:
        text = request_text(url, "easyscholar", min_interval, retries=3)
        data = json.loads(text)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"EasyScholar request failed for '{publication_name}': {exc}", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        print(f"EasyScholar returned non-JSON object for '{publication_name}'", file=sys.stderr)
        return None

    code = data.get("code")
    if code != 200:
        msg = data.get("msg", "unknown error")
        print(f"EasyScholar API error for '{publication_name}': {code} {msg}", file=sys.stderr)
        return None

    payload = data.get("data") or {}
    if not isinstance(payload, dict):
        print(f"EasyScholar returned empty data for '{publication_name}'", file=sys.stderr)
        return None

    return {
        "publication_name": publication_name.strip(),
        "official_rank": parse_easyscholar_official_rank(payload.get("officialRank")),
        "custom_rank": parse_easyscholar_custom_rank(payload.get("customRank")),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def easyscholar_stable_evidence_id(record: dict[str, Any]) -> str:
    """Return the same stable evidence identity used by literature-manager."""
    doi = str(record.get("doi") or record.get("DOI") or "").strip().casefold()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi).rstrip(" .")
    if doi:
        computed = f"doi:{doi}"
    else:
        pmid_match = re.search(r"\d+", str(record.get("pmid") or record.get("PMID") or record.get("pubmed_id") or ""))
        if pmid_match:
            computed = f"pmid:{pmid_match.group(0)}"
        else:
            source = re.sub(r"[^a-z0-9]+", "-", str(record.get("source") or "source").lower()).strip("-") or "source"
            source_id = str(record.get("id") or record.get("source_id") or "").strip()
            if source_id:
                computed = f"source:{source}:{source_id}"
            else:
                title = re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", str(record.get("title") or "")).casefold(), flags=re.UNICODE)
                title = compact_space(title)
                if not title:
                    raise ValueError("evidence record has no stable identifier or usable title")
                computed = f"title-sha256:{hashlib.sha256(title.encode('utf-8')).hexdigest()}"
    supplied = str(record.get("evidence_id") or "").strip()
    if supplied and supplied != computed:
        raise ValueError(f"evidence ID mismatch: {supplied} != {computed}")
    return computed


def easyscholar_is_preprint(record: dict[str, Any]) -> bool:
    source = str(record.get("source") or "").casefold()
    item_type = str(record.get("itemType") or record.get("item_type") or "").casefold()
    raw_types = record.get("article_types") or record.get("publication_types") or []
    types = raw_types if isinstance(raw_types, list) else [raw_types]
    journal = str(record.get("journal") or record.get("publicationTitle") or "").casefold()
    return (
        source == "arxiv"
        or item_type == "preprint"
        or any("preprint" in str(value).casefold() for value in types)
        or any(server in journal for server in ("biorxiv", "medrxiv", "research square", "ssrn preprint"))
    )


def easyscholar_selected_indexes(records: list[dict[str, Any]], selection_path: str | None) -> list[int]:
    if not selection_path:
        return list(range(len(records)))
    selection = load_json(selection_path)
    if selection.get("schema_version") != "1.0" or not isinstance(selection.get("evidence_ids"), list) or not selection["evidence_ids"]:
        raise ValueError("selection JSON must contain schema_version 1.0 and non-empty evidence_ids")
    selected_ids = [str(value) for value in selection["evidence_ids"]]
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("selection JSON contains duplicate evidence IDs")
    by_id = {easyscholar_stable_evidence_id(record): index for index, record in enumerate(records)}
    missing = [evidence_id for evidence_id in selected_ids if evidence_id not in by_id]
    if missing:
        raise ValueError(f"selection contains unknown evidence IDs: {', '.join(missing)}")
    return [by_id[evidence_id] for evidence_id in selected_ids]


def command_enrich_easyscholar(args: argparse.Namespace) -> None:
    """Enrich ranked records with easyscholar.cc journal rank data.

    Matches by journal name (the API requires publicationName). Uses a disk
    cache to avoid duplicate API calls across runs.
    """
    min_interval = getattr(args, "min_interval", 1.0) or 1.0
    cache_path = getattr(args, "cache", None)

    data = load_json(args.ranked_json)
    records = data.get("records", [])
    if not records:
        raise ValueError(f"no records found in {args.ranked_json}")
    selected_indexes = easyscholar_selected_indexes(records, getattr(args, "selection_json", None))
    selected_records = [records[index] for index in selected_indexes]
    preprint_indexes = {index for index in selected_indexes if easyscholar_is_preprint(records[index])}
    journal_indexes = [index for index in selected_indexes if index not in preprint_indexes]
    journal_records = [records[index] for index in journal_indexes]

    base_stats = {
        "selected": len(selected_records),
        "journal_records": len(journal_records),
        "preprints_skipped": len(preprint_indexes),
        "records_queried": len(journal_records),
        "missing_journal": sum(not compact_space(record.get("journal", "")) for record in journal_records),
    }
    api_key = get_easyscholar_api_key(args)
    if not api_key:
        data["easyscholar_enrichment"] = {
            "enabled": True,
            "status": "unavailable",
            "reason": "api-key-not-configured",
            "api_key_configured": False,
            "cache": str(cache_path) if cache_path else str(DEFAULT_EASYSCHOLAR_CACHE),
            "min_interval": min_interval,
            **base_stats,
            "unique_journals": 0,
            "cache_hits": 0,
            "api_calls": 0,
            "matched": 0,
            "unmatched": len(journal_records),
        }
        write_json(args.output, data)
        if args.csv:
            write_csv(args.csv, records)
        print(f"EasyScholar unavailable; unchanged evidence written to: {args.output}", file=sys.stderr)
        return

    cache = load_easyscholar_cache(cache_path)
    cache_entries = cache.setdefault("entries", {})

    # Collect unique journal names, mapping normalized key -> original name.
    journal_map: dict[str, str] = {}
    for record in journal_records:
        journal = compact_space(record.get("journal", ""))
        if not journal:
            continue
        norm = normalize_journal_name(journal)
        if norm and norm not in journal_map:
            journal_map[norm] = journal

    stats = {
        **base_stats,
        "unique_journals": len(journal_map),
        "cache_hits": 0,
        "api_calls": 0,
        "matched": 0,
        "unmatched": 0,
    }

    fetched: dict[str, dict[str, Any] | None] = {}
    for norm, original in journal_map.items():
        if norm in cache_entries:
            fetched[norm] = cache_entries[norm]
            stats["cache_hits"] += 1
            continue

        result = fetch_easyscholar_rank(original, api_key, min_interval=min_interval)
        stats["api_calls"] += 1
        fetched[norm] = result
        if result:
            cache_entries[norm] = result
            save_easyscholar_cache(cache_path, cache)

    # Attach results to records.
    unmatched: list[str] = []
    for record in journal_records:
        journal = compact_space(record.get("journal", ""))
        if not journal:
            continue
        norm = normalize_journal_name(journal)
        result = fetched.get(norm)
        if not result:
            unmatched.append(journal)
            continue

        official_rank = result.get("official_rank") or {}
        custom_rank = result.get("custom_rank") or []

        # Determine if the API actually returned usable data.
        has_usable_data = bool(official_rank.get("all") or official_rank.get("select") or custom_rank)
        if not has_usable_data:
            unmatched.append(journal)
            continue

        stats["matched"] += 1
        match_method = "exact" if journal == result.get("publication_name", journal) else "query"
        record["easyscholar"] = {
            "query_name": journal,
            "matched_name": result.get("publication_name", journal),
            "match_method": match_method,
            "official_rank": official_rank,
            "custom_rank": custom_rank,
            "fetched_at": result.get("fetched_at"),
            "cache_key": norm,
        }
        record.setdefault("score_reasons", []).append("easyscholar journal rank enriched")

    stats["unmatched"] = len(set(unmatched))

    data["easyscholar_enrichment"] = {
        "enabled": True,
        "status": "complete" if not stats["unmatched"] else "partial",
        "api_key_configured": True,
        "cache": str(cache_path) if cache_path else str(DEFAULT_EASYSCHOLAR_CACHE),
        "min_interval": min_interval,
        **stats,
    }

    write_json(args.output, data)
    if args.csv:
        write_csv(args.csv, data.get("records", []))
    print(f"Success! easyscholar enrichment written to: {args.output}")


# ---------------------------------------------------------------------------
# Citation enrichment (Semantic Scholar / Crossref)
# ---------------------------------------------------------------------------

S2_BASE = "https://api.semanticscholar.org/graph/v1"
CROSSREF_BASE = "https://api.crossref.org/works"


def get_s2_api_key(args: argparse.Namespace) -> str | None:
    """Resolve Semantic Scholar API key from args, env, or config."""
    if getattr(args, "s2_api_key", None):
        return args.s2_api_key
    if os.environ.get("S2_API_KEY"):
        return os.environ["S2_API_KEY"]
    return load_config().get("s2_api_key") or None


def s2_paper_id(record: dict[str, Any]) -> str | None:
    """Build a Semantic Scholar paper identifier from a record."""
    doi = compact_space(record.get("doi", ""))
    if doi:
        return f"DOI:{doi}"
    # arXiv IDs without DOI
    if record.get("source") == "arxiv" and record.get("id"):
        return f"ARXIV:{record['id']}"
    # PubMed ID fallback
    if record.get("source") == "pubmed" and record.get("id"):
        return f"PMID:{record['id']}"
    return None


def fetch_s2_batch(
    paper_ids: list[str],
    api_key: str | None,
) -> dict[str, dict[str, Any]]:
    """Fetch citation data from Semantic Scholar batch endpoint.

    Returns a dict mapping paper_id -> {citation_count, influential_citation_count, ...}.
    """
    if not paper_ids:
        return {}
    results: dict[str, dict[str, Any]] = {}
    batch_size = 500
    interval = 0.1 if api_key else 1.0
    fields = "citationCount,influentialCitationCount,referenceCount,publicationTypes,year,externalIds"
    for start in range(0, len(paper_ids), batch_size):
        batch = paper_ids[start : start + batch_size]
        url = f"{S2_BASE}/paper/batch?fields={fields}"
        headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
        if api_key:
            headers["x-api-key"] = api_key
        body = json.dumps({"ids": batch}).encode("utf-8")
        limiter = RateLimiter("semantic-scholar", interval)
        limiter.wait()
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                data = json.loads(response.read().decode(charset, errors="replace"))
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")[:500]
            print(f"S2 batch HTTP {exc.code}: {body_text}", file=sys.stderr)
            continue
        except Exception as exc:
            print(f"S2 batch error: {exc}", file=sys.stderr)
            continue
        if not isinstance(data, list):
            continue
        for idx, paper in enumerate(data):
            if not paper or not isinstance(paper, dict):
                continue
            original_id = batch[idx] if idx < len(batch) else None
            if not original_id:
                continue
            results[original_id] = {
                "citation_count": paper.get("citationCount"),
                "influential_citation_count": paper.get("influentialCitationCount"),
                "reference_count": paper.get("referenceCount"),
                "publication_types": paper.get("publicationTypes", []),
                "s2_year": paper.get("year"),
            }
    return results


def fetch_crossref_citation(doi: str, email: str | None) -> dict[str, Any] | None:
    """Fetch citation count from Crossref for a single DOI."""
    if not doi:
        return None
    url = f"{CROSSREF_BASE}/{urllib.parse.quote(doi, safe='')}"
    headers = {"User-Agent": f"{USER_AGENT} mailto:{email}"} if email else {"User-Agent": USER_AGENT}
    limiter = RateLimiter("crossref", 0.5)
    limiter.wait()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            data = json.loads(response.read().decode(charset, errors="replace"))
    except Exception as exc:
        print(f"Crossref lookup failed for {doi}: {exc}", file=sys.stderr)
        return None
    message = data.get("message", {})
    return {
        "citation_count": message.get("is-referenced-by-count"),
        "reference_count": message.get("references-count"),
    }


def command_enrich_citations(args: argparse.Namespace) -> None:
    """Enrich ranked records with citation counts from Semantic Scholar / Crossref.

    Citation enrichment does NOT change scores. Re-ranking with citation
    weights is a separate, explicit step via ``merge-rank --citation-weight``.
    """
    data = load_json(args.ranked_json)
    records = data.get("records", [])
    if not records:
        raise ValueError(f"no records found in {args.ranked_json}")

    # Load cache
    cache: dict[str, dict[str, Any]] = {}
    if args.cache and Path(args.cache).exists():
        cache = load_json(args.cache)
        if not isinstance(cache, dict):
            cache = {}

    provider = args.provider or "auto"
    s2_key = get_s2_api_key(args) if provider in ("auto", "semantic-scholar") else None
    email = load_config().get("email") or os.environ.get("CROSSREF_MAILTO")

    # Collect IDs for batch lookup
    s2_ids: list[str] = []
    id_to_record_idx: dict[str, int] = {}
    for idx, record in enumerate(records):
        pid = s2_paper_id(record)
        if pid:
            s2_ids.append(pid)
            id_to_record_idx[pid] = idx

    # Semantic Scholar batch
    s2_results: dict[str, dict[str, Any]] = {}
    if provider in ("auto", "semantic-scholar") and s2_ids:
        # Filter out cached IDs
        uncached_ids = [pid for pid in s2_ids if pid not in cache]
        if uncached_ids:
            print(f"Fetching citation data from Semantic Scholar ({len(uncached_ids)} papers)...", file=sys.stderr)
            s2_results = fetch_s2_batch(uncached_ids, s2_key)
            # Update cache
            for pid, citation_data in s2_results.items():
                cache[pid] = citation_data
        # Merge cached results
        for pid in s2_ids:
            if pid in cache and pid not in s2_results:
                s2_results[pid] = cache[pid]

    # Apply citation data to records
    enriched_records = []
    s2_hit_count = 0
    crossref_hit_count = 0
    for idx, record in enumerate(records):
        result = dict(record)
        pid = s2_paper_id(record)
        citation: dict[str, Any] | None = None

        # Try Semantic Scholar first
        if pid and pid in s2_results:
            s2_data = s2_results[pid]
            citation = {
                "provider": "semantic-scholar",
                "citation_count": s2_data.get("citation_count"),
                "influential_citation_count": s2_data.get("influential_citation_count"),
                "reference_count": s2_data.get("reference_count"),
                "retrieved_at": current_date(),
            }
            s2_hit_count += 1

        # Crossref fallback
        if citation is None and provider in ("auto", "crossref"):
            doi = compact_space(record.get("doi", ""))
            if doi:
                # Check cache first
                cache_key = f"crossref:DOI:{doi}"
                if cache_key in cache:
                    citation = cache[cache_key]
                    crossref_hit_count += 1
                else:
                    cr_data = fetch_crossref_citation(doi, email)
                    if cr_data:
                        citation = {
                            "provider": "crossref",
                            "citation_count": cr_data.get("citation_count"),
                            "influential_citation_count": None,
                            "reference_count": cr_data.get("reference_count"),
                            "retrieved_at": current_date(),
                        }
                        cache[cache_key] = citation
                        crossref_hit_count += 1

        if citation is not None:
            result["citation"] = citation
        else:
            result["citation"] = None
            result["citation_lookup_failed"] = True

        enriched_records.append(result)

    # Save cache
    if args.cache:
        write_json(args.cache, cache)

    data["records"] = enriched_records
    data["citation_enrichment"] = {
        "provider_preference": provider,
        "s2_hits": s2_hit_count,
        "crossref_hits": crossref_hit_count,
        "total_records": len(records),
        "lookup_failures": sum(1 for r in enriched_records if r.get("citation_lookup_failed")),
        "cache_path": str(args.cache) if args.cache else None,
    }
    write_json(args.output, data)
    if args.csv:
        write_csv(
            args.csv,
            enriched_records,
            extra_fields=[
                ("citation_count", lambda r: str(r.get("citation", {}).get("citation_count", "") or "")),
                ("influential_citation_count", lambda r: str(r.get("citation", {}).get("influential_citation_count", "") or "")),
                ("citation_provider", lambda r: r.get("citation", {}).get("provider", "")),
            ],
        )
    print(f"Success! Citation-enriched records written to: {args.output}")
    print(f"  Semantic Scholar hits: {s2_hit_count}, Crossref hits: {crossref_hit_count}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Core-conclusion extraction (scaffold/apply)
# ---------------------------------------------------------------------------

CONCLUSION_SCAFFOLD_INSTRUCTIONS = (
    "For each item below, fill the following fields from the saved abstract:\n"
    "- core_conclusion: a single sentence (≤30 words) stating the paper's main finding.\n"
    "- method: a short label for the study method (e.g., 'RCT', 'cohort', 'in vitro', "
    "'computational', 'review', 'meta-analysis'). Use 'unknown' if not determinable.\n"
    "- confidence: one of 'high', 'medium', 'low' — your confidence that the conclusion "
    "accurately reflects the abstract. Default to 'medium' if uncertain.\n"
    "Write your filled JSON back to the same file path. Do not fabricate findings not "
    "present in the abstract."
)


def command_extract_conclusions(args: argparse.Namespace) -> None:
    """Extract core conclusions from paper abstracts (scaffold/apply two-step).

    scaffold: emit a JSON skeleton with abstracts for the agent (LLM) to fill.
    apply: merge the filled conclusions back into ranked records.
    """
    mode = args.mode

    if mode == "scaffold":
        data = load_json(args.ranked_json)
        records = data.get("records", [])[: args.top_n]
        items = []
        for record in records:
            items.append(
                {
                    "rank": record.get("rank"),
                    "id": record.get("id", ""),
                    "doi": record.get("doi", ""),
                    "title": record.get("title", ""),
                    "abstract": record.get("abstract", ""),
                    "core_conclusion": None,
                    "method": None,
                    "confidence": None,
                }
            )
        scaffold = {
            "task": "extract core conclusions",
            "question": data.get("query_plan", {}).get("question", "") if isinstance(data.get("query_plan"), dict) else "",
            "items": items,
            "instructions": CONCLUSION_SCAFFOLD_INSTRUCTIONS,
        }
        write_json(args.output, scaffold)
        print(f"Success! Conclusion scaffold written to: {args.output}")

    elif mode == "apply":
        if not args.scaffold:
            raise ValueError("--scaffold is required when --mode is apply")
        data = load_json(args.ranked_json)
        scaffold = load_json(args.scaffold)
        filled_items = scaffold.get("items", [])
        # Build lookup by (id, doi) for matching
        conclusion_map: dict[str, dict[str, Any]] = {}
        for item in filled_items:
            key = f"{item.get('id', '')}:{item.get('doi', '')}"
            conclusion_map[key] = {
                "core_conclusion": item.get("core_conclusion"),
                "method": item.get("method"),
                "confidence": item.get("confidence"),
            }
        enriched = []
        for record in data.get("records", []):
            result = dict(record)
            key = f"{record.get('id', '')}:{record.get('doi', '')}"
            conclusion_data = conclusion_map.get(key)
            if conclusion_data and conclusion_data.get("core_conclusion"):
                result["core_conclusion"] = conclusion_data["core_conclusion"]
                result["method"] = conclusion_data.get("method")
                result["confidence"] = conclusion_data.get("confidence")
                result["conclusion_source"] = "abstract-level"
                # Informational only — does not change score
                result.setdefault("score_reasons", []).append("core conclusion extracted (abstract-level)")
            else:
                result["core_conclusion"] = None
            enriched.append(result)
        data["records"] = enriched
        data["conclusions_applied_from"] = str(args.scaffold)
        write_json(args.output, data)
        if args.csv:
            write_csv(
                args.csv,
                enriched,
                extra_fields=[
                    ("core_conclusion", lambda r: r.get("core_conclusion") or ""),
                    ("method", lambda r: r.get("method") or ""),
                    ("confidence", lambda r: r.get("confidence") or ""),
                ],
            )
        print(f"Success! Conclusions applied to: {args.output}")

    else:
        raise ValueError(f"unsupported --mode: {mode} (use 'scaffold' or 'apply')")


# ---------------------------------------------------------------------------
# LLM-assisted query expansion (scaffold/apply)
# ---------------------------------------------------------------------------

EXPANSION_SCAFFOLD_INSTRUCTIONS = (
    "Expand the query terms below using domain knowledge:\n"
    "- synonyms: gene/protein aliases, alternative names, capitalization variants.\n"
    "- mesh_terms: MeSH descriptor terms for diseases, processes, and entities.\n"
    "- related_diseases: broader disease family members (e.g., cardiovascular → "
    "heart failure, MI, cardiomyopathy, atherosclerosis, vascular dysfunction).\n"
    "- exclusions: terms to exclude (e.g., 'mouse' when only human studies needed).\n"
    "- organism: specific organism constraints (e.g., 'human', 'mouse', 'rat').\n"
    "- study_types: desired study types (e.g., 'clinical trial', 'cohort', 'meta-analysis').\n"
    "Preserve the user's original constraints (year range, journal class, etc.).\n"
    "Mark every addition with its source (e.g., 'gene alias', 'MeSH tree', "
    "'disease family expansion'). Write your filled JSON back to the same file path."
)


def command_expand_query(args: argparse.Namespace) -> None:
    """Expand query plan terms with LLM-assisted synonyms and MeSH vocabulary.

    scaffold: emit a JSON skeleton with current terms for the agent to fill.
    apply: merge the filled expansion into the query plan and regenerate queries.
    """
    mode = args.mode

    if mode == "scaffold":
        plan = load_json(args.query_plan)
        scaffold = {
            "task": "expand query terms",
            "question": plan.get("question", ""),
            "current_core_terms": plan.get("core_terms", []),
            "current_constraints": plan.get("constraints", {}),
            "expansion": {
                "synonyms": None,
                "mesh_terms": None,
                "related_diseases": None,
                "exclusions": None,
                "organism": None,
                "study_types": None,
            },
            "instructions": EXPANSION_SCAFFOLD_INSTRUCTIONS,
        }
        write_json(args.output, scaffold)
        print(f"Success! Expansion scaffold written to: {args.output}")

    elif mode == "apply":
        if not args.scaffold:
            raise ValueError("--scaffold is required when --mode is apply")
        plan = load_json(args.query_plan)
        scaffold = load_json(args.scaffold)
        expansion = scaffold.get("expansion", {})

        # Merge expanded terms into the plan
        synonyms = expansion.get("synonyms") or []
        mesh_terms = expansion.get("mesh_terms") or []
        related_diseases = expansion.get("related_diseases") or []
        exclusions = expansion.get("exclusions") or []
        organism = expansion.get("organism")
        study_types = expansion.get("study_types") or []

        # Build expanded_terms list: core_terms + synonyms + related_diseases
        existing = {t.lower() for t in plan.get("core_terms", [])}
        expanded_terms = list(plan.get("core_terms", []))
        for term in synonyms + related_diseases:
            if term.lower() not in existing:
                expanded_terms.append(term)
                existing.add(term.lower())

        # Build exclude_terms
        existing_excl = {t.lower() for t in plan.get("exclude_terms", [])}
        exclude_terms = list(plan.get("exclude_terms", []))
        for term in exclusions:
            if term.lower() not in existing_excl:
                exclude_terms.append(term)
                existing_excl.add(term.lower())

        plan["expanded_terms"] = expanded_terms
        plan["exclude_terms"] = exclude_terms
        plan["mesh_terms"] = mesh_terms
        plan["expansion_detail"] = {
            "synonyms": synonyms,
            "related_diseases": related_diseases,
            "exclusions": exclusions,
            "organism": organism,
            "study_types": study_types,
        }
        plan["expansion_source"] = "llm-assisted"
        plan["expansion_applied_at"] = current_date()

        # Regenerate Boolean queries from expanded terms
        plan["pubmed_query"] = _build_pubmed_query(expanded_terms, exclude_terms, mesh_terms, organism, plan.get("constraints"))
        plan["arxiv_query"] = " ".join(expanded_terms)
        plan["wos_query"] = f"TS=(({' AND '.join(expanded_terms)}))"

        write_json(args.output, plan)
        print(f"Success! Expanded query plan written to: {args.output}")

    else:
        raise ValueError(f"unsupported --mode: {mode} (use 'scaffold' or 'apply')")


def _build_pubmed_query(
    terms: list[str],
    exclude_terms: list[str] | None = None,
    mesh_terms: list[str] | None = None,
    organism: str | None = None,
    constraints: dict[str, Any] | None = None,
) -> str:
    """Build a PubMed Boolean query from expanded terms, MeSH, exclusions, and constraints."""
    # Core term groups: group terms that are synonyms together
    # Simple approach: join all terms with OR within a concept group
    # For now, each term is ANDed (matching current plan behavior)
    term_parts = [f"({term})" for term in terms]
    query = " AND ".join(term_parts)

    # Add MeSH terms as additional OR clauses
    if mesh_terms:
        mesh_clause = " OR ".join(f'"{m}"[MeSH Terms]' for m in mesh_terms)
        query = f"({query}) AND ({mesh_clause})"

    # Add organism constraint
    if organism:
        query = f'{query} AND "{organism}"[Organism]'

    # Add year range constraint
    year_range = (constraints or {}).get("year_range") if constraints else None
    if year_range:
        start = year_range.get("start_year")
        end = year_range.get("end_year")
        if start and end:
            query = f'{query} AND "{start}:{end}"[dp]'

    # Add exclusion terms
    if exclude_terms:
        for excl in exclude_terms:
            query = f'{query} NOT "{excl}"'

    return query


def ranking_terms(args: argparse.Namespace) -> list[str]:
    terms: list[str] = []
    if args.query_plan:
        plan = load_json(args.query_plan)
        for key in ("core_terms", "expanded_terms"):
            value = plan.get(key, [])
            if isinstance(value, dict):
                value = list(value.values())
            for item in value:
                if isinstance(item, list):
                    candidates = item
                else:
                    candidates = [item]
                for candidate in candidates:
                    add_term(terms, str(candidate))
    if args.keywords:
        for term in args.keywords.split(","):
            add_term(terms, term)
    if not terms:
        raise ValueError("merge-rank requires --query-plan or --keywords")
    return terms


def add_term(terms: list[str], term: str) -> None:
    cleaned = compact_space(term)
    if cleaned and cleaned.lower() not in {item.lower() for item in terms}:
        terms.append(cleaned)


def deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = ""
        doi = compact_space(record.get("doi", ""))
        if doi:
            key = f"doi:{doi.lower()}"
        else:
            title = re.sub(r"[^a-z0-9]+", "", record.get("title", "").lower())
            key = f"title:{title}"
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def score_record(record: dict[str, Any], terms: list[str], citation_weight: str = "none") -> dict[str, Any]:
    """Score a record against ranking terms with transparent, auditable scoring.

    Args:
        record: Literature record dict.
        terms: Ranking terms from query plan.
        citation_weight: Citation scoring mode — "none" (default, backward-compatible),
            "log" (log-scaled citation count, cap 5), "bucket" (threshold-based).
    """
    title = record.get("title", "")
    abstract = record.get("abstract", "")
    mesh = " ".join(record.get("mesh_terms", []))
    title_l = title.lower()
    abstract_l = abstract.lower()
    mesh_l = mesh.lower()
    score = 0.0
    reasons: list[str] = []
    for term in terms:
        term_l = term.lower()
        if term_l in title_l:
            score += 6
            reasons.append(f"title matches '{term}'")
        if term_l in abstract_l:
            score += 3
            reasons.append(f"abstract matches '{term}'")
        if mesh_l and term_l in mesh_l:
            score += 2
            reasons.append(f"MeSH matches '{term}'")
    year = record.get("year")
    if isinstance(year, int):
        age = dt.date.today().year - year
        if age <= 5:
            score += 2
            reasons.append("published within 5 years")
        elif age <= 10:
            score += 1
            reasons.append("published within 10 years")
    if record.get("doi"):
        score += 0.5
        reasons.append("DOI available")
    types = " ".join(record.get("article_types", [])).lower()
    if "review" in types:
        score += 1
        reasons.append("review article")

    # Citation-weighted scoring (opt-in, transparent)
    citation = record.get("citation")
    citation_count = citation.get("citation_count") if citation and isinstance(citation, dict) else None
    influential = citation.get("influential_citation_count") if citation and isinstance(citation, dict) else None

    # Informational: always record citation magnitude in reasons (no score change when weight=none)
    if citation_count is not None:
        if citation_weight == "none":
            reasons.append(f"citation count: {citation_count} (not weighted)")
        elif citation_weight == "log":
            import math
            bonus = min(5.0, math.log10(citation_count + 1))
            score += round(bonus, 2)
            reasons.append(f"citation count log-scaled: +{bonus:.2f} ({citation_count} citations)")
        elif citation_weight == "bucket":
            bucket_bonus = 0.0
            if influential is not None and influential >= 10:
                bucket_bonus += 3
                reasons.append(f"influential citations >= 10: +3 ({influential})")
            if citation_count >= 50:
                bucket_bonus += 2
                reasons.append(f"citation count >= 50: +2 ({citation_count})")
            elif citation_count >= 10:
                bucket_bonus += 1
                reasons.append(f"citation count >= 10: +1 ({citation_count})")
            score += bucket_bonus
    elif citation_weight != "none":
        reasons.append("citation data unavailable for weighting")

    result = dict(record)
    result["score"] = round(score, 2)
    result["score_reasons"] = reasons or ["no configured ranking term matched"]
    return result


def write_csv(
    path: str | Path,
    records: list[dict[str, Any]],
    extra_fields: list[tuple[str, Any]] | None = None,
) -> None:
    """Write ranked records to CSV.

    Args:
        path: Output CSV file path.
        records: Ranked record dicts.
        extra_fields: Optional list of (field_name, extractor) tuples appended
            after the default columns. ``extractor`` is a callable that takes a
            record dict and returns a string value.
    """
    fields = [
        "rank",
        "score",
        "source",
        "year",
        "title",
        "journal",
        "issns",
        "cas_zone",
        "jcr_zone",
        "impact_factor",
        "doi",
        "url",
        "score_reasons",
    ]
    if extra_fields:
        fields = fields + [name for name, _ in extra_fields]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row: dict[str, str] = {field: record.get(field, "") for field in fields}
            row["issns"] = "; ".join(record.get("issns", []))
            metrics = record.get("journal_metrics") or {}
            row["cas_zone"] = metrics.get("cas_zone", "")
            row["jcr_zone"] = metrics.get("jcr_zone", "")
            row["impact_factor"] = metrics.get("impact_factor", "")
            row["score_reasons"] = "; ".join(record.get("score_reasons", []))
            if extra_fields:
                for name, extractor in extra_fields:
                    row[name] = extractor(record)
            writer.writerow(row)


def command_merge_rank(args: argparse.Namespace) -> None:
    all_records: list[dict[str, Any]] = []
    source_summaries = []
    for path in args.inputs:
        data = load_json(path)
        records = data.get("records", [])
        all_records.extend(records)
        source_summaries.append({"path": path, "source": data.get("source"), "count": len(records)})
    terms = ranking_terms(args)
    citation_weight = getattr(args, "citation_weight", "none") or "none"
    deduped = deduplicate(all_records)
    ranked = [score_record(record, terms, citation_weight=citation_weight) for record in deduped]
    ranked.sort(key=lambda item: item.get("score", 0), reverse=True)
    for index, record in enumerate(ranked, start=1):
        record["rank"] = index
    output = {
        "created_at": current_date(),
        "query_plan": load_json(args.query_plan) if args.query_plan else None,
        "ranking_terms": terms,
        "citation_weight": citation_weight,
        "sources": source_summaries,
        "input_count": len(all_records),
        "deduplicated_count": len(deduped),
        "top_n": args.top_n,
        "records": ranked[: args.top_n],
    }
    write_json(args.output, output)
    extra_csv: list[tuple[str, Any]] | None = None
    if any(r.get("citation") for r in output["records"]):
        extra_csv = [
            ("citation_count", lambda r: str(r.get("citation", {}).get("citation_count", "") or "")),
            ("influential_citation_count", lambda r: str(r.get("citation", {}).get("influential_citation_count", "") or "")),
            ("citation_provider", lambda r: r.get("citation", {}).get("provider", "")),
        ]
    if args.csv:
        write_csv(args.csv, output["records"], extra_fields=extra_csv)
    print(f"Success! Ranked records written to: {args.output}")


def command_render_report(args: argparse.Namespace) -> None:
    data = load_json(args.ranked_json)
    records = data.get("records", [])[: args.top_n]
    lines: list[str] = []
    lines.append(f"# Integrated Literature Research Report / 综合文献调研报告: {args.question}")
    lines.append("")
    lines.append("## 1. Search Question / 检索问题")
    lines.append(args.question)
    lines.append("")
    lines.append("## 2. Search Strategy / 检索策略")
    lines.append(f"- Date searched / 检索日期: {data.get('created_at', current_date())}")
    sources = data.get("sources", [])
    source_text = ", ".join(f"{item.get('source')} ({item.get('count')})" for item in sources)
    lines.append(f"- Databases / 数据库: {source_text or 'Not recorded'}")
    lines.append(f"- Ranking terms / 排序关键词: {', '.join(data.get('ranking_terms', []))}")
    lines.append(f"- Input records / 原始记录数: {data.get('input_count', 'NA')}")
    lines.append(f"- Deduplicated records / 去重后记录数: {data.get('deduplicated_count', 'NA')}")
    if data.get("citation_weight") and data["citation_weight"] != "none":
        lines.append(f"- Citation weighting / 引用权重: {data['citation_weight']}")
    # Check if records have citation data
    sample_records = data.get("records", [])
    citation_providers = set()
    for r in sample_records:
        cite = r.get("citation")
        if cite and isinstance(cite, dict) and cite.get("provider"):
            citation_providers.add(cite["provider"])
    if citation_providers:
        lines.append(f"- Citation data source / 引用数据来源: {', '.join(sorted(citation_providers))} (point-in-time snapshot)")
    lines.append("")
    lines.append("## 3. Evidence Map / 证据概览")
    lines.append(
        "This draft is based on retrieved metadata and abstracts. Revise the synthesis only after reviewing the saved JSON evidence."
    )
    lines.append("本草稿基于检索到的元数据和摘要。请在阅读已保存 JSON 证据后再修改科学结论。")
    lines.append("")
    lines.append("## 4. Ranked Literature / 排序文献表")
    # Determine optional columns
    has_citations = any(r.get("citation") for r in records)
    has_conclusions = any(r.get("core_conclusion") for r in records)

    # Build header
    header_parts = ["Rank", "Citation", "Source", "Year"]
    if has_conclusions:
        header_parts.append("Core conclusion / 核心结论")
    if has_citations:
        header_parts.append("Citations / 引用数")
    header_parts.extend(["Why included", "Link"])
    lines.append("| " + " | ".join(header_parts) + " |")
    lines.append("|" + "|".join(["---"] * len(header_parts)) + "|")

    for record in records:
        citation = citation_label(record)
        why = "; ".join(record.get("score_reasons", [])[:4])
        link = record.get("url") or doi_url(record.get("doi", ""))
        row_parts = [
            str(record.get("rank", "")),
            escape_md(citation),
            record.get("source", ""),
            str(record.get("year", "") or ""),
        ]
        if has_conclusions:
            conc = record.get("core_conclusion")
            row_parts.append(escape_md(conc) if conc else "abstract-level only / 仅摘要层面")
        if has_citations:
            cite_data = record.get("citation")
            row_parts.append(str(cite_data.get("citation_count", "—")) if cite_data and isinstance(cite_data, dict) else "—")
        row_parts.extend([escape_md(why), link])
        lines.append("| " + " | ".join(row_parts) + " |")
    lines.append("")
    lines.append("## 5. Integrated Research Synthesis / 综合调研结论（科学问题回答）")
    lines.append(
        "This section is the evidence-backed synthesis draft generated from saved metadata and abstracts. The agent must revise it in place before delivery, adding domain-level grouping, inclusion/exclusion decisions, and claims supported by citations such as [^1]."
    )
    lines.append("本节为基于已保存元数据和摘要生成的证据综合初稿。交付前，agent 必须在本文件中原位完善领域分组、纳入/排除判断和带引用的科学结论，不得另建第二份主题报告。")
    lines.append("")
    for index, record in enumerate(records[:5], start=1):
        note = abstract_note(record)
        lines.append(f"- [^{index}] {note}")
    lines.append("")
    lines.append("## 6. Limitations / 局限性")
    lines.append("- Abstract-level screening only unless full text was separately retrieved.")
    lines.append("- Result limits and database coverage can cause missed literature.")
    lines.append("- arXiv records are preprints and require peer-review status checks.")
    lines.append("- 未单独获取全文时，本报告仅代表摘要层面的筛选。")
    lines.append("")
    lines.append("## References / 参考文献")
    for index, record in enumerate(records, start=1):
        lines.append(f"[^{index}]: {reference_text(record)}")
    Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Success! Markdown report written to: {args.output}")


def command_review(args: argparse.Namespace) -> None:
    """Run the common PubMed-first retrieval, ranking, and report workflow."""
    journal_metrics = None if getattr(args, "no_journal_metrics", False) else (
        args.journal_metrics or str(DEFAULT_JOURNAL_METRICS)
    )
    quality_filters = (
        args.filter_journals
        or args.cas_zones
        or args.jcr_zones
        or args.if_min is not None
        or args.if_max is not None
    )
    if quality_filters and not journal_metrics:
        raise ValueError("journal quality filters require --journal-metrics")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    search_plan_path = output_dir / "search_plan.json"
    ranked_path = output_dir / "ranked_all.json"
    csv_path = output_dir / "ranked_all.csv"
    report_path = output_dir / "report.md"

    plan = build_query_plan(args.question)
    if args.pubmed_query:
        plan["pubmed_query"] = compact_space(args.pubmed_query)
        plan["screening_notes"].append("PubMed query was supplied explicitly to the review command.")
    enabled_sources = ["pubmed"]
    if args.arxiv:
        enabled_sources.append("arxiv")
    if args.wos_export:
        enabled_sources.append("web-of-science-official-export")
    plan["workflow"] = "common-pubmed-first-review"
    plan["source_routing"] = {
        "enabled": enabled_sources,
        "pubmed_first": True,
        "arxiv_conditional": bool(args.arxiv),
        "web_of_science_export_conditional": bool(args.wos_export),
    }
    plan["limits"] = {"per_source_retrieval": args.limit, "ranked_top_n": args.top_n}
    plan["conditional_enrichment"] = {
        "citation_provider": args.citation_provider,
        "journal_metrics_enabled": bool(journal_metrics),
        "journal_metrics_source": "bundled-jcr-2025" if journal_metrics == str(DEFAULT_JOURNAL_METRICS) else "user-override",
        "easyscholar_enabled": bool(getattr(args, "easyscholar", False)),
        "easyscholar_api_key_configured": bool(get_easyscholar_api_key(args)),
    }
    plan["journal_filters"] = {
        "cas_zones": args.cas_zones or [],
        "jcr_zones": args.jcr_zones or [],
        "if_min": args.if_min,
        "if_max": args.if_max,
        "filter_to_matches": bool(args.filter_journals),
    }
    write_json(search_plan_path, plan)

    with tempfile.TemporaryDirectory(prefix="academic-review-") as temporary:
        temporary_dir = Path(temporary)
        source_files: list[str] = []

        pubmed_path = temporary_dir / "pubmed.json"
        command_search_pubmed(
            argparse.Namespace(
                query=None,
                query_json=str(search_plan_path),
                query_field="pubmed_query",
                limit=args.limit,
                output=str(pubmed_path),
                api_key=args.api_key,
            )
        )
        source_files.append(str(pubmed_path))

        if args.arxiv:
            arxiv_path = temporary_dir / "arxiv.json"
            command_search_arxiv(
                argparse.Namespace(
                    query=plan["arxiv_query"],
                    limit=args.limit,
                    output=str(arxiv_path),
                )
            )
            source_files.append(str(arxiv_path))

        if args.wos_export:
            wos_path = temporary_dir / "wos.json"
            command_import_wos_export(
                argparse.Namespace(
                    input=args.wos_export,
                    query=plan["wos_query"],
                    limit=args.limit,
                    output=str(wos_path),
                )
            )
            source_files.append(str(wos_path))

        command_merge_rank(
            argparse.Namespace(
                inputs=source_files,
                query_plan=str(search_plan_path),
                keywords=None,
                top_n=args.top_n,
                output=str(ranked_path),
                csv=None,
                citation_weight="none",
            )
        )
        ranked_data = load_json(ranked_path)
        for source in ranked_data.get("sources", []):
            source.pop("path", None)
            source["intermediate_retained"] = False
        write_json(ranked_path, ranked_data)

    if args.citation_provider:
        command_enrich_citations(
            argparse.Namespace(
                ranked_json=str(ranked_path),
                output=str(ranked_path),
                provider=args.citation_provider,
                s2_api_key=args.s2_api_key,
                cache=args.citation_cache,
                csv=None,
            )
        )

    if journal_metrics:
        command_enrich_journal_metrics(
            argparse.Namespace(
                ranked_json=str(ranked_path),
                journal_metrics=journal_metrics,
                cas_zones=args.cas_zones,
                jcr_zones=args.jcr_zones,
                if_min=args.if_min,
                if_max=args.if_max,
                filter_to_matches=args.filter_journals,
                output=str(ranked_path),
                csv=None,
            )
        )

    if getattr(args, "easyscholar", False):
        command_enrich_easyscholar(
            argparse.Namespace(
                ranked_json=str(ranked_path),
                output=str(ranked_path),
                easyscholar_api_key=args.easyscholar_api_key,
                cache=args.easyscholar_cache,
                min_interval=getattr(args, "easyscholar_min_interval", 1.0),
                csv=None,
            )
        )

    final_data = load_json(ranked_path)
    extra_csv: list[tuple[str, Any]] | None = None
    if any(record.get("citation") for record in final_data.get("records", [])):
        extra_csv = [
            ("citation_count", lambda r: str((r.get("citation") or {}).get("citation_count", "") or "")),
            ("influential_citation_count", lambda r: str((r.get("citation") or {}).get("influential_citation_count", "") or "")),
            ("citation_provider", lambda r: (r.get("citation") or {}).get("provider", "")),
        ]
    write_csv(csv_path, final_data.get("records", []), extra_fields=extra_csv)
    command_render_report(
        argparse.Namespace(
            ranked_json=str(ranked_path),
            question=args.question,
            top_n=args.top_n,
            output=str(report_path),
        )
    )
    print(f"Success! Review outputs written to: {output_dir}")


def citation_label(record: dict[str, Any]) -> str:
    authors = record.get("authors", [])
    author_text = ""
    if authors:
        author_text = authors[0] + (" et al." if len(authors) > 1 else "")
    year = record.get("year") or "n.d."
    title = record.get("title", "Untitled")
    return f"{author_text} ({year}). {title}" if author_text else f"({year}). {title}"


def doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}" if doi else ""


def reference_text(record: dict[str, Any]) -> str:
    parts = [citation_label(record)]
    journal = record.get("journal")
    if journal:
        parts.append(str(journal))
    doi = record.get("doi")
    if doi:
        parts.append(f"doi:{doi}")
    if record.get("url"):
        parts.append(record["url"])
    return " ".join(parts)


def abstract_note(record: dict[str, Any]) -> str:
    title = record.get("title", "Untitled")
    # Prefer extracted core conclusion over first-sentence heuristic
    conclusion = record.get("core_conclusion")
    if conclusion:
        return f"{title}: {conclusion}"
    abstract = record.get("abstract", "")
    first_sentence = re.split(r"(?<=[.!?])\s+", abstract.strip())[0] if abstract else ""
    if first_sentence:
        return f"{title}: {first_sentence}"
    return f"{title}: no abstract available in retrieved metadata."


def escape_md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


SCRIPT = "literature-research/scripts/literature_search.py"


def planned_output_path(plan_output: str | Path, suffix: str) -> str:
    base = Path(plan_output)
    return str(base.parent / suffix)


def output_file_policy(allowed_outputs: list[str]) -> dict[str, Any]:
    return {
        "allowed_default_outputs": allowed_outputs,
        "forbidden_default_outputs": [
            "temporary helper scripts such as filter_q1_if.py, filter_*.py, *.R, or *.sh",
            "duplicate metrics files such as *_metrics.json or *_metrics.csv",
            "target-renamed result tables such as <target>_*_records.json or <target>_*_records.csv",
            "duplicate Markdown reports such as <target>.md or <target>_research_progress.md",
        ],
        "policy": (
            "Use scripts/literature_search.py commands and canonical output names for reusable workflows. "
            "Do not create ad hoc helper scripts, renamed duplicate JSON/CSV files, or duplicate Markdown reports unless the user explicitly requests a custom artifact."
        ),
    }


def command_step(
    step_id: str,
    description: str,
    argv: list[str],
    *,
    writes: list[str] | None = None,
    reads: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "owner": "script",
        "description": description,
        "argv": argv,
        "command": shlex.join(argv),
        "reads": reads or [],
        "writes": writes or [],
        "notes": notes or [],
    }


def agent_checkpoint(step_id: str, description: str, requires: list[str]) -> dict[str, Any]:
    return {
        "id": step_id,
        "owner": "agent_checkpoint",
        "description": description,
        "requires": requires,
    }


def journal_filter_args(args: argparse.Namespace) -> list[str]:
    parts: list[str] = []
    if getattr(args, "cas_zones", None):
        parts.extend(["--cas-zones", *args.cas_zones])
    if getattr(args, "jcr_zones", None):
        parts.extend(["--jcr-zones", *args.jcr_zones])
    if getattr(args, "if_min", None) is not None:
        parts.extend(["--if-min", str(args.if_min)])
    if getattr(args, "if_max", None) is not None:
        parts.extend(["--if-max", str(args.if_max)])
    return parts


def has_journal_quality_filter(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "journal_metrics", None)
        or getattr(args, "cas_zones", None)
        or getattr(args, "jcr_zones", None)
        or getattr(args, "if_min", None) is not None
        or getattr(args, "if_max", None) is not None
    )


def _safe_filter_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return token or "filter"


def _format_number_token(value: float) -> str:
    return ("%g" % value).replace(".", "p")


def journal_filtered_output_stem(args: argparse.Namespace) -> str:
    parts: list[str] = ["filtered"]
    if getattr(args, "jcr_zones", None):
        parts.extend(_safe_filter_token(zone) for zone in args.jcr_zones)
    if getattr(args, "if_min", None) is not None:
        parts.append(f"if_gt{_format_number_token(args.if_min)}")
    if getattr(args, "if_max", None) is not None:
        parts.append(f"if_lt{_format_number_token(args.if_max)}")
    if len(parts) == 1:
        parts.append("journal_quality")
    return "_".join(parts)


def append_merge_and_report_steps(
    steps: list[dict[str, Any]],
    *,
    inputs: list[str],
    query_plan: str,
    question: str,
    top_n: int,
    output: str,
    citation_weight: str = "none",
    easyscholar: bool = False,
    easyscholar_cache: str | None = None,
    easyscholar_min_interval: float = 1.0,
) -> None:
    ranked_json = planned_output_path(output, "ranked_all.json")
    ranked_csv = planned_output_path(output, "ranked_all.csv")
    report_md = planned_output_path(output, "report.md")
    merge_argv = [
        "uv",
        "run",
        SCRIPT,
        "merge-rank",
        "--inputs",
        *inputs,
        "--query-plan",
        query_plan,
        "--top-n",
        str(top_n),
        "--output",
        ranked_json,
        "--csv",
        ranked_csv,
    ]
    if citation_weight != "none":
        merge_argv.extend(["--citation-weight", citation_weight])
    steps.append(
        command_step(
            "merge_rank",
            "Merge, deduplicate, and rank saved source records.",
            merge_argv,
            reads=[*inputs, query_plan],
            writes=[ranked_json, ranked_csv],
        )
    )
    if easyscholar:
        enrich_easyscholar_argv = [
            "uv",
            "run",
            SCRIPT,
            "enrich-easyscholar",
            "--ranked-json",
            ranked_json,
            "--output",
            ranked_json,
        ]
        if easyscholar_cache:
            enrich_easyscholar_argv.extend(["--cache", easyscholar_cache])
        enrich_easyscholar_argv.extend(["--min-interval", str(easyscholar_min_interval)])
        steps.append(
            command_step(
                "enrich_easyscholar",
                "Enrich ranked records in place with easyscholar.cc journal rank data.",
                enrich_easyscholar_argv,
                reads=[ranked_json],
                writes=[ranked_json],
                notes=[
                    "Run after merge-rank so ranked records are available for enrichment.",
                    "Resolve the easyscholar API key at execution time from EASYSCHOLAR_SECRET_KEY or local config; plans never contain secrets.",
                ],
            )
        )
    steps.append(
        agent_checkpoint(
            "inspect_ranked_evidence",
            "Inspect top records, score_reasons, source limitations, and whether the search needs another pass.",
            [ranked_json, ranked_csv],
        )
    )
    steps.append(
        command_step(
            "render_report",
            "Render the canonical integrated report scaffold. This file must become the final report after agent synthesis.",
            [
                "uv",
                "run",
                SCRIPT,
                "render-report",
                "--ranked-json",
                ranked_json,
                "--question",
                question,
                "--top-n",
                str(top_n),
                "--output",
                report_md,
            ],
            reads=[ranked_json],
            writes=[report_md],
            notes=[
                "report.md is the only default Markdown report.",
                "The agent must revise report.md in place to combine search strategy, evidence screening, and scientific synthesis.",
                "Do not create a second topical report such as <target>.md or <target>_research_progress.md unless the user explicitly asks.",
            ],
        )
    )
    steps.append(
        agent_checkpoint(
            "finalize_report_in_place",
            "Revise report.md in place into the final integrated report: search strategy, inclusion/exclusion decisions, ranked evidence, limitations, and scientific research-progress synthesis. Do not create a separate topical Markdown report.",
            [report_md, ranked_json],
        )
    )


def command_workflow_plan(args: argparse.Namespace) -> None:
    matches = [(key, route) for key, route in DATABASE_ROUTES.items() if route_matches(args.targets, route)]
    if not matches:
        raise ValueError(
            "no supported database matched --targets; available databases: "
            + ", ".join(route["display_name"] for route in DATABASE_ROUTES.values())
        )
    if has_journal_quality_filter(args) and not args.journal_metrics:
        raise ValueError("--journal-metrics is required when CAS/JCR/IF filters are requested")

    draft_plan = build_query_plan(args.question)
    query_plan = planned_output_path(args.output, "search_plan.json")
    steps: list[dict[str, Any]] = [
        agent_checkpoint(
            "clarify_scope",
            "Resolve high-impact ambiguity before retrieval: biological target, disease/process, species, years, article type, and exclusions.",
            [],
        ),
        command_step(
            "create_query_plan",
            "Create the auditable query-plan JSON scaffold.",
            ["uv", "run", SCRIPT, "plan", "--query", args.question, "--output", query_plan],
            writes=[query_plan],
        ),
        agent_checkpoint(
            "review_query_plan",
            "Review the generated terms and queries. Use expand-query if synonyms, MeSH terms, or CJK term splitting are needed.",
            [query_plan],
        ),
    ]

    source_outputs: list[str] = []
    if any(key == "pubmed" for key, _ in matches):
        if args.journal_metrics:
            subplan = planned_output_path(args.output, "pubmed_review_workflow.json")
            review_argv = [
                "uv",
                "run",
                SCRIPT,
                "pubmed-review-workflow",
                "--question",
                args.question,
                "--core-query",
                draft_plan["pubmed_query"],
                "--limit",
                str(args.limit),
                "--journal-metrics",
                args.journal_metrics,
                *journal_filter_args(args),
                "--top-n",
                str(args.top_n),
                "--output",
                subplan,
            ]
            if getattr(args, "easyscholar", False):
                review_argv.append("--easyscholar")
                if getattr(args, "easyscholar_cache", None):
                    review_argv.extend(["--easyscholar-cache", args.easyscholar_cache])
                review_argv.extend(
                    [
                        "--easyscholar-min-interval",
                        str(getattr(args, "easyscholar_min_interval", 1.0)),
                    ]
                )
            steps.append(
                command_step(
                    "pubmed_review_subplan",
                    "Generate the n8n-style PubMed review workflow plan with local journal-quality filtering.",
                    review_argv,
                    reads=[query_plan, args.journal_metrics],
                    writes=[subplan],
                )
            )
            steps.append(
                agent_checkpoint(
                    "run_pubmed_review_subplan",
                    "Execute the script steps listed in the PubMed review subplan, then continue with its final ranked JSON/report.",
                    [subplan],
                )
            )
        else:
            pubmed_json = planned_output_path(args.output, "pubmed_raw.json")
            source_outputs.append(pubmed_json)
            steps.append(
                command_step(
                    "search_pubmed",
                    "Retrieve PubMed metadata and abstracts through NCBI E-utilities.",
                    [
                        "uv",
                        "run",
                        SCRIPT,
                        "search-pubmed",
                        "--query",
                        draft_plan["pubmed_query"],
                        "--limit",
                        str(args.limit),
                        "--output",
                        pubmed_json,
                    ],
                    reads=[query_plan],
                    writes=[pubmed_json],
                )
            )

    if any(key == "arxiv" for key, _ in matches):
        arxiv_json = planned_output_path(args.output, "arxiv_raw.json")
        source_outputs.append(arxiv_json)
        steps.append(
            command_step(
                "search_arxiv",
                "Retrieve arXiv preprint metadata through the public API.",
                [
                    "uv",
                    "run",
                    SCRIPT,
                    "search-arxiv",
                    "--query",
                    draft_plan["arxiv_query"],
                    "--limit",
                    str(args.limit),
                    "--output",
                    arxiv_json,
                ],
                reads=[query_plan],
                writes=[arxiv_json],
            )
        )

    if any(key == "web-of-science" for key, _ in matches):
        wos_json = planned_output_path(args.output, "wos_raw.json")
        source_outputs.append(wos_json)
        steps.append(
            agent_checkpoint(
                "wos_browser_export",
                "Use web-access with authorized campus/library access to run the WoS Topic query and export official CSV/TSV records.",
                [query_plan],
            )
        )
        steps.append(
            command_step(
                "import_wos_export",
                "Normalize the official Web of Science CSV/TSV export.",
                [
                    "uv",
                    "run",
                    SCRIPT,
                    "import-wos-export",
                    "--input",
                    "WOS_EXPORT.tsv",
                    "--query",
                    draft_plan["wos_query"],
                    "--limit",
                    str(args.limit),
                    "--output",
                    wos_json,
                ],
                reads=["WOS_EXPORT.tsv"],
                writes=[wos_json],
                notes=["Replace WOS_EXPORT.tsv with the authorized official export path."],
            )
        )

    if source_outputs:
        append_merge_and_report_steps(
            steps,
            inputs=source_outputs,
            query_plan=query_plan,
            question=args.question,
            top_n=args.top_n,
            output=args.output,
            citation_weight=args.citation_weight,
            easyscholar=getattr(args, "easyscholar", False),
            easyscholar_cache=getattr(args, "easyscholar_cache", None),
            easyscholar_min_interval=getattr(args, "easyscholar_min_interval", 1.0),
        )

    output = {
        "created_at": current_date(),
        "workflow": "script-led academic literature workflow",
        "question": args.question,
        "targets": args.targets,
        "limit": args.limit,
        "top_n": args.top_n,
        "draft_queries": {
            "pubmed_query": draft_plan["pubmed_query"],
            "arxiv_query": draft_plan["arxiv_query"],
            "wos_query": draft_plan["wos_query"],
        },
        "steps": steps,
        "file_policy": output_file_policy([args.output, *[path for step in steps if step.get("owner") == "script" for path in step.get("writes", [])]]),
        "subagent_policy": (
            "Use subagents only for independent source/topic evidence packages. "
            "Do not create subagents for XML parsing, ISSN filtering, ranking, file writes, or citation formatting. "
            "The canonical Markdown deliverable is report.md; revise it in place and do not create duplicate topical report files by default."
        ),
    }
    write_json(args.output, output)
    print(f"Success! Workflow plan written to: {args.output}")


def command_pubmed_review_workflow(args: argparse.Namespace) -> None:
    if has_journal_quality_filter(args) and not args.journal_metrics:
        raise ValueError("--journal-metrics is required when CAS/JCR/IF filters are requested")
    query_plan = planned_output_path(args.output, "search_plan.json")
    core_json = planned_output_path(args.output, "pubmed_raw.json")
    final_pubmed_json = core_json
    steps: list[dict[str, Any]] = [
        command_step(
            "create_query_plan",
            "Create a query-plan scaffold for audit. The provided core query remains the executable PubMed query.",
            ["uv", "run", SCRIPT, "plan", "--query", args.question, "--output", query_plan],
            writes=[query_plan],
        ),
        agent_checkpoint(
            "review_core_query",
            "Confirm the executable core PubMed query matches the user's biological question before retrieval.",
            [query_plan],
        ),
        command_step(
            "pubmed_core_search",
            "Run the broad first-pass PubMed search and save abstracts plus ISSNs.",
            [
                "uv",
                "run",
                SCRIPT,
                "search-pubmed",
                "--query",
                args.core_query,
                "--limit",
                str(args.limit),
                "--output",
                core_json,
            ],
            writes=[core_json],
        ),
    ]

    ranked_json = planned_output_path(args.output, "ranked_all.json")
    ranked_csv = planned_output_path(args.output, "ranked_all.csv")
    merge_argv = [
        "uv",
        "run",
        SCRIPT,
        "merge-rank",
        "--inputs",
        final_pubmed_json,
        "--query-plan",
        query_plan,
        "--top-n",
        str(args.top_n),
        "--output",
        ranked_json,
        "--csv",
        ranked_csv,
    ]
    if args.citation_weight != "none":
        merge_argv.extend(["--citation-weight", args.citation_weight])
    steps.append(
        command_step(
            "merge_rank",
            "Merge, deduplicate, and rank the broad PubMed result set before journal-quality filtering.",
            merge_argv,
            reads=[final_pubmed_json, query_plan],
            writes=[ranked_json, ranked_csv],
        )
    )
    if getattr(args, "easyscholar", False):
        enrich_easyscholar_argv = [
            "uv",
            "run",
            SCRIPT,
            "enrich-easyscholar",
            "--ranked-json",
            ranked_json,
            "--output",
            ranked_json,
        ]
        if getattr(args, "easyscholar_cache", None):
            enrich_easyscholar_argv.extend(["--cache", args.easyscholar_cache])
        enrich_easyscholar_argv.extend(
            ["--min-interval", str(getattr(args, "easyscholar_min_interval", 1.0))]
        )
        steps.append(
            command_step(
                "enrich_easyscholar",
                "Enrich ranked records in place with easyscholar.cc journal rank data.",
                enrich_easyscholar_argv,
                reads=[ranked_json],
                writes=[ranked_json],
                notes=[
                    "Resolve the easyscholar API key at execution time from EASYSCHOLAR_SECRET_KEY or local config; plans never contain secrets."
                ],
            )
        )
    render_input_json = ranked_json
    if args.journal_metrics:
        filtered_stem = journal_filtered_output_stem(args)
        enriched_json = planned_output_path(args.output, f"{filtered_stem}.json")
        enriched_csv = planned_output_path(args.output, f"{filtered_stem}.csv")
        enrich_argv = [
            "uv",
            "run",
            SCRIPT,
            "enrich-journal-metrics",
            "--ranked-json",
            ranked_json,
            "--journal-metrics",
            args.journal_metrics,
            *journal_filter_args(args),
            "--filter-to-matches",
            "--output",
            enriched_json,
            "--csv",
            enriched_csv,
        ]
        steps.append(
            command_step(
                "local_journal_quality_filter",
                "Locally match ranked records to the journal metrics table by ISSN and keep only records satisfying CAS/JCR/IF filters.",
                enrich_argv,
                reads=[ranked_json, args.journal_metrics],
                writes=[enriched_json, enriched_csv],
                notes=[
                    "This is the default path for Q/IF filtering because it avoids extra audit files and NCBI 413 errors from long ISSN queries.",
                    "The output preserves matched journal metrics for audit.",
                    "Use journal-filter-query only as an explicit troubleshooting or PubMed second-pass fallback.",
                ],
            )
        )
        render_input_json = enriched_json
    steps.append(
        agent_checkpoint(
            "inspect_ranked_evidence",
            "Inspect top records, score_reasons, journal_metrics_filter, source limitations, and whether the search needs another pass.",
            [render_input_json],
        )
    )
    report_md = planned_output_path(args.output, "report.md")
    steps.append(
        command_step(
            "render_report",
            "Render the canonical integrated report scaffold. This file must become the final report after agent synthesis.",
            [
                "uv",
                "run",
                SCRIPT,
                "render-report",
                "--ranked-json",
                render_input_json,
                "--question",
                args.question,
                "--top-n",
                str(args.top_n),
                "--output",
                report_md,
            ],
            reads=[render_input_json],
            writes=[report_md],
            notes=[
                "report.md is the only default Markdown report.",
                "The agent must revise report.md in place to combine search strategy, evidence screening, and scientific synthesis.",
                "Do not create a second topical report such as <target>.md or <target>_research_progress.md unless the user explicitly asks.",
            ],
        )
    )
    steps.append(
        agent_checkpoint(
            "finalize_report_in_place",
            "Revise report.md in place into the final integrated report: search strategy, inclusion/exclusion decisions, ranked evidence, limitations, and scientific research-progress synthesis. Do not create a separate topical Markdown report.",
            [report_md, render_input_json],
        )
    )
    output = {
        "created_at": current_date(),
        "workflow": "n8n-style PubMed review workflow",
        "question": args.question,
        "core_query": args.core_query,
        "limit": args.limit,
        "top_n": args.top_n,
        "journal_quality_filter_enabled": bool(args.journal_metrics),
        "steps": steps,
        "file_policy": output_file_policy([args.output, *[path for step in steps if step.get("owner") == "script" for path in step.get("writes", [])]]),
        "agent_policy": (
            "Agent reviews query semantics, journal-filter intent, ranked evidence, and final synthesis. "
            "Scripts own retrieval, parsing, local ISSN/journal metric filtering, ranking, and report rendering. "
            "Use PubMed ISSN second-pass filtering only as an explicit fallback when result volume requires it and the ISSN query is short enough. "
            "The canonical Markdown deliverable is report.md; revise it in place and do not create duplicate topical report files by default. "
            "Do not create ad hoc helper scripts or renamed duplicate JSON/CSV outputs."
        ),
    }
    write_json(args.output, output)
    print(f"Success! PubMed review workflow written to: {args.output}")


def normalize_route_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def all_routes_requested(target: str) -> bool:
    return normalize_route_text(target) in {"all", "all databases", "all sources", "all supported databases"}


def route_matches(target: str, route: dict[str, Any]) -> bool:
    if all_routes_requested(target):
        return True
    normalized_target = normalize_route_text(target)
    candidates = [route.get("display_name", ""), *route.get("aliases", [])]
    for candidate in candidates:
        normalized_candidate = normalize_route_text(str(candidate))
        if normalized_candidate and normalized_candidate in normalized_target:
            return True
    return False


def command_database_route(args: argparse.Namespace) -> None:
    matches = []
    for key, route in DATABASE_ROUTES.items():
        if route_matches(args.target, route):
            item = dict(route)
            item["key"] = key
            matches.append(item)
    output = {
        "created_at": current_date(),
        "target": args.target,
        "matched_count": len(matches),
        "matches": matches,
        "available_databases": [route["display_name"] for route in DATABASE_ROUTES.values()],
        "default_policy": (
            "Use API-first routes when available. Use web-access only for logged-in, "
            "campus-network, dynamic-page, full-text, or source-verification tasks."
        ),
    }
    write_json(args.output, output)
    print(f"Success! Database route written to: {args.output}")


def subagent_prompt(question: str, route_key: str, route: dict[str, Any], query_plan: str | None) -> str:
    plan_text = f"Use this query-plan file as the source of truth: {query_plan}." if query_plan else "Create or review an auditable query plan before retrieval."
    web_access_text = (
        "You must load the web-access skill and follow its guidance for browser readiness, "
        "site behavior, CDP tab isolation, and anti-bypass rules."
        if route.get("requires_web_access")
        else "Do not use browser access unless API results need source-level verification."
    )
    expected = "; ".join(route.get("expected_evidence", []))
    return (
        "You must load the literature-research skill and follow its No Evidence, No Conclusion rule.\n"
        f"Research question: {question}\n"
        f"Assigned database/source: {route.get('display_name')} ({route.get('access_mode')}).\n"
        f"{plan_text}\n"
        f"{web_access_text}\n"
        f"Use the database pattern reference: {route.get('pattern_reference')}.\n"
        f"Primary tool/path: {route.get('primary_tool')}.\n"
        f"Expected evidence files: {expected}.\n"
        "Return only a concise source-level handoff: exact query used, filters/limits, "
        "record count, output file paths, top 5 candidate records with IDs/DOIs/URLs, "
        "and limitations. Do not write the final scientific conclusion."
    )


def command_subagent_plan(args: argparse.Namespace) -> None:
    matches = []
    for key, route in DATABASE_ROUTES.items():
        if route_matches(args.targets, route):
            item = dict(route)
            item["key"] = key
            item["task_id"] = f"database-{key}"
            item["prompt"] = subagent_prompt(args.question, key, route, args.query_plan)
            item["handoff_required_fields"] = [
                "database",
                "exact_query",
                "filters_and_limits",
                "record_count",
                "output_files",
                "top_records",
                "limitations",
            ]
            matches.append(item)
    if not matches:
        raise ValueError(
            "no supported database matched --targets; available databases: "
            + ", ".join(route["display_name"] for route in DATABASE_ROUTES.values())
        )
    output = {
        "created_at": current_date(),
        "question": args.question,
        "targets": args.targets,
        "query_plan": args.query_plan,
        "subagent_count": len(matches),
        "subagents": matches,
        "main_agent_aggregation": [
            "Wait for every subagent handoff or record an explicit source failure.",
            "Verify each handoff includes saved evidence file paths before using its claims.",
            "Run merge-rank on all produced source JSON files with the shared query plan or keywords.",
            "Inspect score_reasons and source limitations before writing the final synthesis.",
            "Run render-report, then revise conclusions only from saved evidence and citations.",
        ],
        "parallel_policy": (
            "Split only independent database/source tasks. Shared API rate limits remain enforced "
            "by the helper script; browser tasks must use separate web-access/CDP tabs and close them."
        ),
    }
    write_json(args.output, output)
    print(f"Success! Subagent plan written to: {args.output}")

def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Academic literature search helper")
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config", help="initialize or inspect local configuration")
    config.add_argument("--init", action="store_true", help="create local config template")
    config.add_argument("--show", action="store_true", help="show config path and key status")
    config.add_argument("--set-pubmed-api-key", help=argparse.SUPPRESS)
    config.add_argument("--set-s2-api-key", help=argparse.SUPPRESS)
    config.add_argument("--set-easyscholar-key", help=argparse.SUPPRESS)
    config.set_defaults(func=command_config)

    review = sub.add_parser(
        "review",
        help="run the common PubMed-first retrieval, rank, CSV, and report workflow",
    )
    review.add_argument("--question", required=True)
    review.add_argument("--pubmed-query", help="explicit reviewed PubMed query; otherwise use search_plan.json")
    review.add_argument("--limit", required=True, type=positive_int)
    review.add_argument("--top-n", required=True, type=positive_int)
    review.add_argument("--output", required=True, help="output directory for the four canonical artifacts")
    review.add_argument("--api-key", help=argparse.SUPPRESS)
    review.add_argument("--arxiv", action="store_true", help="also retrieve arXiv records")
    review.add_argument("--wos-export", help="also import an authorized official Web of Science CSV/TSV export")
    review.add_argument(
        "--citation-provider",
        choices=["auto", "semantic-scholar", "crossref"],
        metavar="{auto,crossref}",
        help="conditionally enrich citation counts; omitted by default",
    )
    review.add_argument("--s2-api-key", help=argparse.SUPPRESS)
    review.add_argument("--citation-cache", help="optional reusable citation cache JSON")
    review.add_argument(
        "--journal-metrics",
        help="override the default bundled 2025 JCR/IF metrics CSV",
    )
    review.add_argument(
        "--no-journal-metrics",
        action="store_true",
        help="skip the default journal-metrics lookup for this run",
    )
    review.add_argument("--cas-zones", nargs="+")
    review.add_argument("--jcr-zones", nargs="+")
    review.add_argument("--if-min", type=float)
    review.add_argument("--if-max", type=float)
    review.add_argument(
        "--filter-journals",
        action="store_true",
        help="keep only journal-metric matches; requires --journal-metrics",
    )
    review.add_argument(
        "--easyscholar",
        action="store_true",
        help="enrich records with easyscholar.cc journal rank data",
    )
    review.add_argument("--easyscholar-api-key", help=argparse.SUPPRESS)
    review.add_argument("--easyscholar-cache", help="path to easyscholar cache JSON")
    review.add_argument(
        "--easyscholar-min-interval",
        type=float,
        default=1.0,
        help="seconds between easyscholar API calls",
    )
    review.set_defaults(func=command_review)

    workflow = sub.add_parser("workflow-plan", help="generate a script-led academic research workflow plan")
    workflow.add_argument("--question", required=True)
    workflow.add_argument("--targets", required=True)
    workflow.add_argument("--limit", required=True, type=positive_int)
    workflow.add_argument("--top-n", type=positive_int, default=30)
    workflow.add_argument("--journal-metrics")
    workflow.add_argument("--cas-zones", nargs="+")
    workflow.add_argument("--jcr-zones", nargs="+")
    workflow.add_argument("--if-min", type=float)
    workflow.add_argument("--if-max", type=float)
    workflow.add_argument(
        "--citation-weight",
        choices=["none", "log", "bucket"],
        default="none",
        help="citation scoring mode to pass through to merge-rank",
    )
    workflow.add_argument("--easyscholar", action="store_true", help="include easyscholar enrichment step")
    workflow.add_argument("--easyscholar-api-key", help=argparse.SUPPRESS)
    workflow.add_argument("--easyscholar-cache", help="path to easyscholar cache JSON")
    workflow.add_argument(
        "--easyscholar-min-interval",
        type=float,
        default=1.0,
        help="seconds between easyscholar API calls",
    )
    workflow.add_argument("--output", required=True)
    workflow.set_defaults(func=command_workflow_plan)

    pubmed_review = sub.add_parser(
        "pubmed-review-workflow",
        help="generate an n8n-style PubMed review workflow plan",
    )
    pubmed_review.add_argument("--question", required=True)
    pubmed_review.add_argument("--core-query", required=True)
    pubmed_review.add_argument("--limit", required=True, type=positive_int)
    pubmed_review.add_argument("--top-n", type=positive_int, default=30)
    pubmed_review.add_argument("--journal-metrics")
    pubmed_review.add_argument("--cas-zones", nargs="+")
    pubmed_review.add_argument("--jcr-zones", nargs="+")
    pubmed_review.add_argument("--if-min", type=float)
    pubmed_review.add_argument("--if-max", type=float)
    pubmed_review.add_argument(
        "--citation-weight",
        choices=["none", "log", "bucket"],
        default="none",
        help="citation scoring mode to pass through to merge-rank",
    )
    pubmed_review.add_argument("--easyscholar", action="store_true", help="include easyscholar enrichment step")
    pubmed_review.add_argument("--easyscholar-api-key", help=argparse.SUPPRESS)
    pubmed_review.add_argument("--easyscholar-cache", help="path to easyscholar cache JSON")
    pubmed_review.add_argument(
        "--easyscholar-min-interval",
        type=float,
        default=1.0,
        help="seconds between easyscholar API calls",
    )
    pubmed_review.add_argument("--output", required=True)
    pubmed_review.set_defaults(func=command_pubmed_review_workflow)

    plan = sub.add_parser("plan", help="create a query-plan template")
    plan.add_argument("--query", required=True)
    plan.add_argument("--output", required=True)
    plan.set_defaults(func=command_plan)

    database_route = sub.add_parser(
        "database-route",
        help="recommend an access mode for an academic database target",
    )
    database_route.add_argument("--target", required=True)
    database_route.add_argument("--output", required=True)
    database_route.set_defaults(func=command_database_route)

    subagent_plan = sub.add_parser(
        "subagent-plan",
        help="generate parallel database-search subagent prompts",
    )
    subagent_plan.add_argument("--question", required=True)
    subagent_plan.add_argument("--targets", required=True)
    subagent_plan.add_argument("--output", required=True)
    subagent_plan.add_argument("--query-plan")
    subagent_plan.set_defaults(func=command_subagent_plan)
    pubmed = sub.add_parser("search-pubmed", help="search PubMed through NCBI E-utilities")
    pubmed.add_argument("--query")
    pubmed.add_argument("--query-json", help="JSON file containing a PubMed query string")
    pubmed.add_argument("--query-field", default="pubmed_query", help="field to read from --query-json")
    pubmed.add_argument("--limit", required=True, type=positive_int)
    pubmed.add_argument("--output", required=True)
    pubmed.add_argument("--api-key", help=argparse.SUPPRESS)
    pubmed.set_defaults(func=command_search_pubmed)

    arxiv = sub.add_parser("search-arxiv", help="search arXiv public API")
    arxiv.add_argument("--query", required=True)
    arxiv.add_argument("--limit", required=True, type=positive_int)
    arxiv.add_argument("--output", required=True)
    arxiv.set_defaults(func=command_search_arxiv)


    wos_import = sub.add_parser(
        "import-wos-export",
        help="normalize an official Web of Science CSV/TSV export",
    )
    wos_import.add_argument("--input", required=True, nargs="+", help="one or more official WoS CSV/TSV export batches")
    wos_import.add_argument("--query")
    wos_import.add_argument("--limit", required=True, type=positive_int)
    wos_import.add_argument("--output", required=True)
    wos_import.set_defaults(func=command_import_wos_export)

    merge = sub.add_parser("merge-rank", help="deduplicate and transparently rank records")
    merge.add_argument("--inputs", required=True, nargs="+")
    merge.add_argument("--query-plan")
    merge.add_argument("--keywords")
    merge.add_argument("--top-n", required=True, type=positive_int)
    merge.add_argument("--output", required=True)
    merge.add_argument("--csv")
    merge.add_argument(
        "--citation-weight",
        choices=["none", "log", "bucket"],
        default="none",
        help="citation scoring mode: none (default), log (log-scaled, cap 5), bucket (threshold-based)",
    )
    merge.set_defaults(func=command_merge_rank)

    journal_filter = sub.add_parser(
        "journal-filter-query",
        help="generate a PubMed ISSN query from a journal metrics CSV",
    )
    journal_filter.add_argument("--journal-metrics", required=True)
    journal_filter.add_argument("--cas-zones", nargs="+")
    journal_filter.add_argument("--jcr-zones", nargs="+")
    journal_filter.add_argument("--if-min", type=float)
    journal_filter.add_argument("--if-max", type=float)
    journal_filter.add_argument("--mesh-terms", nargs="+", help="MeSH terms to add as filter clause")
    journal_filter.add_argument("--output", required=True)
    journal_filter.add_argument("--markdown")
    journal_filter.set_defaults(func=command_journal_filter_query)

    compose_pubmed = sub.add_parser(
        "compose-pubmed-query",
        help="combine a core PubMed query with an ISSN/MeSH filter JSON",
    )
    compose_pubmed.add_argument("--core-query", required=True)
    compose_pubmed.add_argument("--filter-json", required=True)
    compose_pubmed.add_argument(
        "--filter-field",
        default="pubmed_combined_query",
        help="filter JSON field to use; falls back to pubmed_issn_query when empty",
    )
    compose_pubmed.add_argument("--output", required=True)
    compose_pubmed.add_argument("--markdown")
    compose_pubmed.set_defaults(func=command_compose_pubmed_query)

    enrich = sub.add_parser(
        "enrich-journal-metrics",
        help="add journal IF/CAS/JCR metadata to ranked records by ISSN",
    )
    enrich.add_argument("--ranked-json", required=True)
    enrich.add_argument("--journal-metrics", required=True)
    enrich.add_argument("--cas-zones", nargs="+")
    enrich.add_argument("--jcr-zones", nargs="+")
    enrich.add_argument("--if-min", type=float)
    enrich.add_argument("--if-max", type=float)
    enrich.add_argument(
        "--filter-to-matches",
        action="store_true",
        help="keep only records whose ISSN matches the selected journal metrics",
    )
    enrich.add_argument("--output", required=True)
    enrich.add_argument("--csv")
    enrich.set_defaults(func=command_enrich_journal_metrics)

    enrich_easyscholar = sub.add_parser(
        "enrich-easyscholar",
        help="enrich ranked records with easyscholar.cc journal rank data by journal name",
    )
    enrich_easyscholar.add_argument("--ranked-json", required=True)
    enrich_easyscholar.add_argument("--output", required=True)
    enrich_easyscholar.add_argument(
        "--selection-json",
        help="optional schema 1.0 evidence_ids selection; only selected journal records are queried",
    )
    enrich_easyscholar.add_argument(
        "--easyscholar-api-key",
        help=argparse.SUPPRESS,
    )
    enrich_easyscholar.add_argument(
        "--cache",
        help="path to easyscholar cache JSON (default: the platform-private frank-ai4s cache directory)",
    )
    enrich_easyscholar.add_argument(
        "--min-interval",
        type=float,
        default=1.0,
        help="seconds between easyscholar API calls (default: 1.0)",
    )
    enrich_easyscholar.add_argument("--csv")
    enrich_easyscholar.set_defaults(func=command_enrich_easyscholar)

    enrich_cite = sub.add_parser(
        "enrich-citations",
        help="enrich ranked records with point-in-time citation counts",
    )
    enrich_cite.add_argument("--ranked-json", required=True)
    enrich_cite.add_argument("--output", required=True)
    enrich_cite.add_argument(
        "--provider",
        choices=["auto", "semantic-scholar", "crossref"],
        metavar="{auto,crossref}",
        default="auto",
    )
    enrich_cite.add_argument("--s2-api-key", help=argparse.SUPPRESS)
    enrich_cite.add_argument("--cache", help="path to citation cache JSON for reuse across runs")
    enrich_cite.add_argument("--csv")
    enrich_cite.set_defaults(func=command_enrich_citations)

    extract_conc = sub.add_parser(
        "extract-conclusions",
        help="extract core conclusions from paper abstracts (scaffold/apply two-step)",
    )
    extract_conc.add_argument("--ranked-json", required=True)
    extract_conc.add_argument("--top-n", type=positive_int, default=20)
    extract_conc.add_argument("--mode", required=True, choices=["scaffold", "apply"])
    extract_conc.add_argument("--scaffold", help="filled scaffold JSON (required for apply mode)")
    extract_conc.add_argument("--output", required=True)
    extract_conc.add_argument("--csv")
    extract_conc.set_defaults(func=command_extract_conclusions)

    expand_q = sub.add_parser(
        "expand-query",
        help="expand query plan terms with LLM-assisted synonyms and MeSH vocabulary (scaffold/apply)",
    )
    expand_q.add_argument("--query-plan", required=True)
    expand_q.add_argument("--mode", required=True, choices=["scaffold", "apply"])
    expand_q.add_argument("--scaffold", help="filled scaffold JSON (required for apply mode)")
    expand_q.add_argument("--output", required=True)
    expand_q.set_defaults(func=command_expand_query)

    report = sub.add_parser("render-report", help="render a Markdown evidence report")
    report.add_argument("--ranked-json", required=True)
    report.add_argument("--question", required=True)
    report.add_argument("--top-n", required=True, type=positive_int)
    report.add_argument("--output", required=True)
    report.set_defaults(func=command_render_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except RateLimitError as exc:
        print(f"Rate limit error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI should surface actionable errors.
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
