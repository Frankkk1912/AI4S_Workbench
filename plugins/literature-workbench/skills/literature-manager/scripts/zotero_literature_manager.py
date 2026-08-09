#!/usr/bin/env python3
"""Zotero literature management helpers for evidence-first workflows."""

from __future__ import annotations

import argparse
import contextlib
import csv
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback.
    msvcrt = None


WEB_API_BASE = "https://api.zotero.org"
LOCAL_API_BASE = "http://localhost:23119/api"
DEFAULT_RATE_LIMIT_SECONDS = 1.0


class RateLimitError(RuntimeError):
    """Raised when Zotero asks the client to slow down."""


class ApiError(RuntimeError):
    """Raised when Zotero returns a non-retriable API error."""


@contextlib.contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    windows_lock = fcntl is None and msvcrt is not None
    mode = "a+b" if windows_lock else "a+"
    open_options = {} if windows_lock else {"encoding": "utf-8"}
    with path.open(mode, **open_options) as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif windows_lock:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            for _ in range(500):
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.02)
            else:
                raise RuntimeError(f"Timed out acquiring Windows rate-limit lock: {path}")
        try:
            yield handle
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif windows_lock:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def wait_for_rate_limit(lock_path: Path, interval_seconds: float) -> None:
    if interval_seconds <= 0:
        return
    with file_lock(lock_path) as handle:
        handle.seek(0)
        raw = handle.read().strip()
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", errors="replace")
        now = time.monotonic()
        if raw:
            try:
                elapsed = now - float(raw)
                delay = interval_seconds - elapsed
            except ValueError:
                delay = 0
            if delay > 0:
                time.sleep(delay)
        handle.seek(0)
        handle.truncate()
        value = str(time.monotonic())
        handle.write(value.encode("ascii") if "b" in handle.mode else value)
        handle.flush()


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str | Path, data: Any) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def normalize_base_url(base_url: str, local: bool) -> str:
    base = LOCAL_API_BASE if local else base_url
    return base.rstrip("/")


def library_prefix(library_type: str, library_id: str) -> str:
    prefix = "users" if library_type == "user" else "groups"
    return f"/{prefix}/{library_id}"


def api_key_from_env(env_name: str | None) -> str | None:
    if not env_name:
        return None
    return os.environ.get(env_name)


class ZoteroClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        rate_limit_seconds: float,
        rate_limit_state: Path,
        max_retries: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.rate_limit_seconds = rate_limit_seconds
        self.rate_limit_state = rate_limit_state
        self.max_retries = max_retries

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str | int] | None = None,
        payload: Any | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        url = self._url(path, query)
        body = None
        headers = {
            "Zotero-API-Version": "3",
            "Accept": "application/json",
            "User-Agent": "Frank-AI4S-literature-manager/1.0",
        }
        if self.api_key:
            headers["Zotero-API-Key"] = self.api_key
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)

        attempt = 0
        while True:
            wait_for_rate_limit(self.rate_limit_state, self.rate_limit_seconds)
            request = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    response_headers = dict(response.headers.items())
                    raw = response.read().decode("utf-8")
                    self._respect_backoff(url, response_headers)
                    if not raw:
                        return None, response_headers
                    return json.loads(raw), response_headers
            except urllib.error.HTTPError as exc:
                response_body = exc.read().decode("utf-8", errors="replace")
                retry_after = exc.headers.get("Retry-After")
                if exc.code == 429:
                    delay = self._retry_delay(attempt, retry_after)
                    if attempt >= self.max_retries:
                        raise RateLimitError(
                            f"Zotero API rate limit hit for {url}; Retry-After={retry_after or 'not provided'}"
                        ) from exc
                    print(f"Zotero API 429 for {url}; retrying in {delay:.1f}s", file=sys.stderr)
                    time.sleep(delay)
                    attempt += 1
                    continue
                if exc.code in {500, 502, 503, 504} and attempt < self.max_retries:
                    delay = self._retry_delay(attempt, retry_after)
                    print(f"Zotero API {exc.code} for {url}; retrying in {delay:.1f}s", file=sys.stderr)
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise ApiError(f"Zotero API {exc.code} for {url}: {response_body}") from exc
            except urllib.error.URLError as exc:
                if attempt < self.max_retries:
                    delay = 2**attempt
                    print(f"Zotero API connection error for {url}; retrying in {delay:.1f}s", file=sys.stderr)
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise ApiError(f"Zotero API connection error for {url}: {exc}") from exc

    def _url(self, path: str, query: dict[str, str | int] | None) -> str:
        path_part = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{path_part}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        return url

    @staticmethod
    def _retry_delay(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return float(2**attempt)

    @staticmethod
    def _respect_backoff(url: str, headers: dict[str, str]) -> None:
        backoff = headers.get("Backoff")
        if not backoff:
            return
        try:
            delay = max(float(backoff), 0.0)
        except ValueError:
            return
        print(f"Zotero API Backoff for {url}; waiting {delay:.1f}s", file=sys.stderr)
        time.sleep(delay)


def item_data(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data")
    if isinstance(data, dict):
        return data
    return item


def clean_doi(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return text.strip(" .")


def clean_pmid(value: Any) -> str:
    text = str(value or "").strip()
    match = re.search(r"\d+", text)
    return match.group(0) if match else ""


def clean_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def extract_year(value: Any) -> str:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return match.group(0) if match else ""


def evidence_records(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [record for record in raw if isinstance(record, dict)]
    if isinstance(raw, dict):
        for key in ("records", "ranked_records", "items", "results", "evidence"):
            value = raw.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
    raise ValueError("Evidence JSON must be a list or contain records/ranked_records/items/results/evidence")


def zotero_records(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [record for record in raw if isinstance(record, dict)]
    if isinstance(raw, dict):
        for key in ("items", "records", "zotero_items"):
            value = raw.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
    raise ValueError("Zotero JSON must be a list or contain items/records/zotero_items")


def field(record: dict[str, Any], *names: str) -> Any:
    data = item_data(record)
    for name in names:
        if name in record and record[name]:
            return record[name]
        if name in data and data[name]:
            return data[name]
    extra = data.get("extra") or record.get("extra") or ""
    for name in names:
        pattern = re.compile(rf"^{re.escape(name)}\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
        match = pattern.search(str(extra))
        if match:
            return match.group(1).strip()
    return ""


def record_identity(record: dict[str, Any]) -> dict[str, str]:
    return {
        "doi": clean_doi(field(record, "doi", "DOI")),
        "pmid": clean_pmid(field(record, "pmid", "PMID", "pubmed_id")),
        "title": clean_title(field(record, "title")),
        "year": extract_year(field(record, "year", "date", "publicationDate")),
    }


def item_key(record: dict[str, Any]) -> str:
    data = item_data(record)
    return str(data.get("key") or record.get("key") or "")


def title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def best_match(evidence: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    evidence_id = record_identity(evidence)
    best: dict[str, Any] | None = None
    for candidate in candidates:
        zotero_id = record_identity(candidate)
        reasons: list[str] = []
        score = 0.0
        if evidence_id["doi"] and evidence_id["doi"] == zotero_id["doi"]:
            score += 1.0
            reasons.append("doi")
        if evidence_id["pmid"] and evidence_id["pmid"] == zotero_id["pmid"]:
            score += 1.0
            reasons.append("pmid")
        sim = title_similarity(evidence_id["title"], zotero_id["title"])
        if sim >= 0.92 and (not evidence_id["year"] or not zotero_id["year"] or evidence_id["year"] == zotero_id["year"]):
            score += 0.7
            reasons.append(f"title-year:{sim:.2f}")
        elif sim >= 0.86:
            score += 0.4
            reasons.append(f"title-fuzzy:{sim:.2f}")
        if not reasons:
            continue
        match = {
            "score": round(score, 3),
            "reasons": reasons,
            "zotero_key": item_key(candidate),
            "zotero_item": item_data(candidate),
            "evidence_identity": evidence_id,
            "zotero_identity": zotero_id,
        }
        if best is None or match["score"] > best["score"]:
            best = match
    return best


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Project must contain at least one letter or number")
    return slug


def stable_evidence_id(record: dict[str, Any]) -> str:
    identity = record_identity(record)
    if identity["doi"]:
        computed = f"doi:{identity['doi']}"
    elif identity["pmid"]:
        computed = f"pmid:{identity['pmid']}"
    else:
        source = slugify(str(record.get("source") or "source"))
        source_id = str(record.get("id") or record.get("source_id") or "").strip()
        if source_id:
            computed = f"source:{source}:{source_id}"
        elif identity["title"]:
            digest = hashlib.sha256(identity["title"].encode("utf-8")).hexdigest()
            computed = f"title-sha256:{digest}"
        else:
            raise ValueError("Evidence record has no DOI, PMID, source ID, or usable title")
    supplied = str(record.get("evidence_id") or "").strip()
    if supplied and supplied != computed:
        raise ValueError(f"Evidence ID mismatch: supplied {supplied!r}, computed {computed!r}")
    return computed


def load_selection(args: argparse.Namespace) -> list[str]:
    if args.selection_json:
        raw = load_json(args.selection_json)
        if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
            raise ValueError("Selection JSON must be an object with schema_version 1.0")
        values = raw.get("evidence_ids")
    else:
        values = args.select_id
    if not isinstance(values, list) or not values:
        raise ValueError("Selection must contain at least one evidence ID")
    selected = [str(value).strip() for value in values if str(value).strip()]
    if len(selected) != len(values):
        raise ValueError("Selection contains an empty evidence ID")
    if len(set(selected)) != len(selected):
        raise ValueError("Selection contains duplicate evidence IDs")
    return selected


PRIORITY_TAG_PREFIX = "AI4S:Priority:"
PRIORITY_REVIEW_DEPTHS = {"metadata", "abstract", "mixed", "full-text"}


def priority_tags(values: Any) -> list[str]:
    tags: list[str] = []
    for entry in values if isinstance(values, list) else []:
        tag = str(entry.get("tag") if isinstance(entry, dict) else entry or "")
        if re.fullmatch(r"AI4S:Priority:[1-3]", tag) and tag not in tags:
            tags.append(tag)
    return tags


def load_priority_recommendations(
    path: str | None,
    *,
    project_slug: str,
    evidence_ids: set[str],
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
    if not path:
        return None, {}
    raw_bytes = Path(path).read_bytes()
    raw = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ValueError("Priority recommendations must be an object with schema_version 1.0")
    if raw.get("artifact_type") != "literature-priority-recommendations":
        raise ValueError("Priority recommendations have an unsupported artifact_type")
    scope = slugify(str(raw.get("scope") or ""))
    if scope != project_slug:
        raise ValueError(f"Priority recommendation scope {scope!r} does not match project {project_slug!r}")
    review_depth = str(raw.get("review_depth") or "")
    if review_depth not in PRIORITY_REVIEW_DEPTHS:
        raise ValueError("Priority review_depth must be metadata, abstract, mixed, or full-text")
    if raw.get("default_for_selected") != 1:
        raise ValueError("Priority default_for_selected must be 1")
    values = raw.get("recommendations")
    if not isinstance(values, dict):
        raise ValueError("Priority recommendations must contain a recommendations object")
    recommendations: dict[str, dict[str, Any]] = {}
    for evidence_id, value in values.items():
        evidence_id = str(evidence_id).strip()
        if evidence_id not in evidence_ids:
            raise ValueError(f"Priority recommendations contain unknown evidence ID: {evidence_id}")
        if not isinstance(value, dict) or value.get("priority") not in {2, 3}:
            raise ValueError(f"Priority recommendation {evidence_id} must use priority 2 or 3")
        reasons = value.get("reason_codes")
        if not isinstance(reasons, list) or not reasons:
            raise ValueError(f"Priority recommendation {evidence_id} needs reason_codes")
        normalized_reasons = []
        for reason in reasons:
            reason = str(reason).strip()
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", reason):
                raise ValueError(f"Priority reason code must be lower-kebab-case: {reason!r}")
            if reason not in normalized_reasons:
                normalized_reasons.append(reason)
        recommendations[evidence_id] = {
            "level": int(value["priority"]),
            "reason_codes": sorted(normalized_reasons),
        }
    metadata = {
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "scope": scope,
        "review_depth": review_depth,
        "default_for_selected": 1,
    }
    return metadata, recommendations


def normalize_creator(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict):
        first = str(value.get("firstName") or value.get("first_name") or "").strip()
        last = str(value.get("lastName") or value.get("last_name") or "").strip()
        name = str(value.get("name") or "").strip()
        creator_type = str(value.get("creatorType") or value.get("creator_type") or "author").strip()
        if last:
            result = {"creatorType": creator_type, "lastName": last}
            if first:
                result["firstName"] = first
            return result
        if name:
            return {"creatorType": creator_type, "name": name}
        return None
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None
    if "," in text:
        last, first = (part.strip() for part in text.split(",", 1))
        if last:
            result = {"creatorType": "author", "lastName": last}
            if first:
                result["firstName"] = first
            return result
    return {"creatorType": "author", "name": text}


def normalize_creators(record: dict[str, Any]) -> list[dict[str, str]]:
    raw = record.get("creators") or record.get("authors") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(";") if part.strip()]
    if not isinstance(raw, list):
        return []
    return [creator for value in raw if (creator := normalize_creator(value))]


def infer_item_type(record: dict[str, Any]) -> str | None:
    explicit = str(record.get("itemType") or record.get("item_type") or "").strip()
    if explicit in {"journalArticle", "preprint"}:
        return explicit
    source = str(record.get("source") or "").lower()
    article_types = " ".join(str(value) for value in (record.get("article_types") or [])).lower()
    journal = str(record.get("journal") or record.get("publicationTitle") or "").strip()
    if source == "arxiv" or "preprint" in article_types:
        return "preprint"
    if source in {"pubmed", "wos", "web-of-science", "webofscience"} or journal:
        return "journalArticle"
    return None


ARTICLE_TYPE_TAG_PREFIX = "AI4S:ArticleType:"

# PubMed Publication Types and common Web of Science Document Types are
# normalized only for presentation/filtering. They must not replace Zotero's
# broad, citation-oriented itemType (for example, a PubMed Letter remains a
# Zotero journalArticle rather than personal-correspondence itemType=letter).
ARTICLE_TYPE_ALIASES = {
    "article": "Article",
    "journal article": "Article",
    "journalarticle": "Article",
    "review": "Review",
    "review article": "Review",
    "systematic review": "Systematic Review",
    "systematicreview": "Systematic Review",
    "meta analysis": "Meta-Analysis",
    "metaanalysis": "Meta-Analysis",
    "clinical study": "Clinical Study",
    "clinical trial": "Clinical Trial",
    "clinicaltrial": "Clinical Trial",
    "clinical trial phase i": "Clinical Trial, Phase I",
    "clinical trial phase ii": "Clinical Trial, Phase II",
    "clinical trial phase iii": "Clinical Trial, Phase III",
    "clinical trial phase iv": "Clinical Trial, Phase IV",
    "randomized controlled trial": "Randomized Controlled Trial",
    "controlled clinical trial": "Controlled Clinical Trial",
    "pragmatic clinical trial": "Pragmatic Clinical Trial",
    "adaptive clinical trial": "Adaptive Clinical Trial",
    "observational study": "Observational Study",
    "multicenter study": "Multicenter Study",
    "comparative study": "Comparative Study",
    "evaluation study": "Evaluation Study",
    "validation study": "Validation Study",
    "case reports": "Case Report",
    "case report": "Case Report",
    "casereport": "Case Report",
    "guideline": "Guideline",
    "practice guideline": "Practice Guideline",
    "consensus statement": "Consensus Statement",
    "editorial": "Editorial",
    "editorial material": "Editorial",
    "letter": "Letter",
    "comment": "Comment",
    "news": "News",
    "preprint": "Preprint",
    "conference proceedings": "Conference Paper",
    "proceedings paper": "Conference Paper",
    "meeting abstract": "Meeting Abstract",
    "published erratum": "Correction",
    "correction": "Correction",
    "retraction notice": "Retraction Notice",
    "retracted publication": "Retracted Publication",
    "expression of concern": "Expression of Concern",
}

ARTICLE_TYPE_ORDER = {
    label: index
    for index, label in enumerate(
        [
            "Systematic Review", "Meta-Analysis", "Review",
            "Randomized Controlled Trial", "Controlled Clinical Trial",
            "Pragmatic Clinical Trial", "Adaptive Clinical Trial",
            "Clinical Trial, Phase IV", "Clinical Trial, Phase III",
            "Clinical Trial, Phase II", "Clinical Trial, Phase I",
            "Clinical Trial", "Clinical Study", "Observational Study",
            "Multicenter Study", "Comparative Study", "Evaluation Study",
            "Validation Study", "Case Report", "Guideline",
            "Practice Guideline", "Consensus Statement", "Editorial",
            "Letter", "Comment", "Meeting Abstract", "Conference Paper",
            "Correction", "Retraction Notice", "Retracted Publication",
            "Expression of Concern", "Preprint", "Article", "News",
        ]
    )
}


def normalize_article_type_key(value: Any) -> str:
    text = re.sub(r"[\u2010-\u2015_-]+", " ", str(value or "").strip().casefold())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_article_types(record: dict[str, Any]) -> list[str]:
    raw = record.get("article_types") or record.get("publication_types") or []
    if isinstance(raw, str):
        raw = [part for part in re.split(r"\s*;\s*", raw) if part]
    if not isinstance(raw, list):
        return []
    normalized: list[str] = []
    for value in raw:
        original = re.sub(r"\s+", " ", str(value or "")).strip()
        if not original:
            continue
        key = normalize_article_type_key(original)
        label = ARTICLE_TYPE_ALIASES.get(key)
        if label is None:
            # Preserve a safe, bounded projection of source vocabularies that
            # are not yet in the controlled mapping; the raw evidence remains
            # the lossless source of truth.
            label = original[:80]
        if label not in normalized:
            normalized.append(label)
    if "Systematic Review" in normalized and "Review" in normalized:
        normalized.remove("Review")
    if "Preprint" in normalized and "Article" in normalized:
        normalized.remove("Article")
    if len(normalized) > 1 and "Article" in normalized:
        normalized.remove("Article")
    return sorted(normalized, key=lambda label: (ARTICLE_TYPE_ORDER.get(label, 999), label.casefold()))


def article_type_tags(record: dict[str, Any]) -> list[str]:
    return [f"{ARTICLE_TYPE_TAG_PREFIX}{label}" for label in normalize_article_types(record)]


def normalize_zotero_item(record: dict[str, Any], tags: list[str]) -> tuple[dict[str, Any] | None, list[str]]:
    title = re.sub(r"\s+", " ", str(field(record, "title") or "")).strip()
    item_type = infer_item_type(record)
    reasons: list[str] = []
    if not title:
        reasons.append("missing-title")
    if not item_type:
        reasons.append("unsupported-item-type")
    if reasons:
        return None, reasons

    identity = record_identity(record)
    item: dict[str, Any] = {
        "itemType": item_type,
        "title": title,
        "creators": normalize_creators(record),
        "tags": [{"tag": tag} for tag in sorted(set([*tags, *article_type_tags(record)]))],
    }
    publication_container = record.get("journal") or record.get("publicationTitle")
    optional = {
        "abstractNote": record.get("abstract") or record.get("abstractNote"),
        "date": record.get("date") or record.get("year"),
        "DOI": identity["doi"],
        "url": record.get("url"),
    }
    # Zotero's preprint item type does not accept publicationTitle. Preserve
    # the source server in its schema-supported repository field instead.
    if item_type == "preprint":
        optional["repository"] = record.get("repository") or publication_container
    else:
        optional["publicationTitle"] = publication_container
    for name, value in optional.items():
        if value not in (None, "", []):
            item[name] = str(value).strip()
    if identity["pmid"]:
        item["extra"] = f"PMID: {identity['pmid']}"
    return item, []


def compact_candidate(candidate: dict[str, Any], reason_codes: list[str]) -> dict[str, Any]:
    identity = record_identity(candidate)
    data = item_data(candidate)
    return {
        "zotero_key": item_key(candidate),
        "zotero_version": data.get("version") or candidate.get("version"),
        "title": str(field(candidate, "title") or ""),
        "year": identity["year"] or None,
        "doi": identity["doi"] or None,
        "pmid": identity["pmid"] or None,
        "reason_codes": sorted(set(reason_codes)),
    }


def classify_match(record: dict[str, Any], candidates: list[dict[str, Any]], *, truncated: bool) -> tuple[str, list[str], Any]:
    if truncated:
        return "check", ["candidate-limit-exceeded"], {"candidates": []}
    identity = record_identity(record)
    doi_matches = [candidate for candidate in candidates if identity["doi"] and record_identity(candidate)["doi"] == identity["doi"]]
    pmid_matches = [candidate for candidate in candidates if identity["pmid"] and record_identity(candidate)["pmid"] == identity["pmid"]]
    exact_by_key: dict[str, tuple[dict[str, Any], set[str]]] = {}
    for kind, matches in (("doi", doi_matches), ("pmid", pmid_matches)):
        for candidate in matches:
            key = item_key(candidate) or f"candidate:{id(candidate)}"
            stored = exact_by_key.setdefault(key, (candidate, set()))
            stored[1].add(kind)
    doi_keys = {item_key(candidate) for candidate in doi_matches}
    pmid_keys = {item_key(candidate) for candidate in pmid_matches}
    if doi_keys and pmid_keys and doi_keys.isdisjoint(pmid_keys):
        compact = [compact_candidate(candidate, list(kinds)) for candidate, kinds in exact_by_key.values()]
        return "check", ["identifier-conflict"], {"candidates": compact}
    if len(exact_by_key) == 1:
        candidate, kinds = next(iter(exact_by_key.values()))
        data = item_data(candidate)
        kind = "doi+pmid" if len(kinds) == 2 else next(iter(kinds))
        return (
            "reuse",
            [f"unique-{kind}-match"],
            {
                "zotero_key": item_key(candidate),
                "zotero_version": data.get("version") or candidate.get("version"),
                "match_kind": kind,
                "matched_identity": identity["doi"] if "doi" in kinds else identity["pmid"],
            },
        )
    if len(exact_by_key) > 1:
        compact = [compact_candidate(candidate, list(kinds)) for candidate, kinds in exact_by_key.values()]
        return "check", ["multiple-identifier-matches"], {"candidates": compact}

    fuzzy = []
    for candidate in candidates:
        sim = title_similarity(identity["title"], record_identity(candidate)["title"])
        if sim >= 0.86:
            fuzzy.append(compact_candidate(candidate, [f"title-similarity:{sim:.2f}"]))
    if fuzzy:
        return "check", ["title-only-candidate"], {"candidates": fuzzy}
    return "create", ["no-library-match"], None


def candidate_for_match(candidates: list[dict[str, Any]], match: Any) -> dict[str, Any] | None:
    key = str((match or {}).get("zotero_key") or "") if isinstance(match, dict) else ""
    return next((candidate for candidate in candidates if item_key(candidate) == key), None)


def add_item_tag(item: dict[str, Any], tag: str) -> None:
    tags = item.setdefault("tags", [])
    if not any(isinstance(entry, dict) and entry.get("tag") == tag for entry in tags):
        tags.append({"tag": tag})
        tags.sort(key=lambda entry: str((entry or {}).get("tag", "")))


def fetch_local_candidates(
    records: list[tuple[str, dict[str, Any]]],
    *,
    library_type: str,
    library_id: str,
    candidate_limit: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, bool], int | None]:
    client = ZoteroClient(
        base_url=LOCAL_API_BASE,
        api_key=None,
        rate_limit_seconds=0.0,
        rate_limit_state=Path(tempfile.gettempdir()) / "zotero_literature_manager_local.lock",
        max_retries=0,
    )
    prefix = library_prefix(library_type, library_id)
    candidate_map: dict[str, list[dict[str, Any]]] = {}
    truncated_map: dict[str, bool] = {}
    library_version: int | None = None
    for evidence_id, record in records:
        identity = record_identity(record)
        query_text = identity["doi"] or identity["pmid"] or str(field(record, "title") or "")
        data, headers = client.request(
            "GET",
            f"{prefix}/items",
            query={
                "format": "json",
                "include": "data",
                "q": query_text,
                "qmode": "everything",
                "limit": candidate_limit,
                "start": 0,
            },
        )
        items = data if isinstance(data, list) else []
        total = int(headers.get("Total-Results", len(items)) or len(items))
        candidate_map[evidence_id] = items
        truncated_map[evidence_id] = total > candidate_limit
        header_version = headers.get("Last-Modified-Version")
        if header_version and str(header_version).isdigit():
            library_version = max(library_version or 0, int(header_version))
    return candidate_map, truncated_map, library_version


def canonical_plan_hash(plan: dict[str, Any]) -> str:
    actions = []
    for source_action in sorted(plan["actions"], key=lambda action: action["evidence_id"]):
        action = json.loads(json.dumps(source_action, ensure_ascii=False))
        action["reason_codes"] = sorted(set(action.get("reason_codes", [])))
        item = action.get("item")
        if isinstance(item, dict) and isinstance(item.get("tags"), list):
            item["tags"] = sorted(item["tags"], key=lambda entry: str((entry or {}).get("tag", "")))
        actions.append(action)
    payload = {
        "schema_version": plan["schema_version"],
        "plan_type": plan["plan_type"],
        "project": plan["project"],
        "target": {**plan["target"], "tags": sorted(set(plan["target"]["tags"]))},
        "matching": {
            "mode": plan["matching"]["mode"],
            "unchecked_create": plan["matching"]["unchecked_create"],
        },
        "actions": actions,
    }
    if isinstance(plan.get("priority"), dict):
        payload["priority"] = plan["priority"]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


METRICS_PREFIX = "AI4S-Metrics:"
METRICS_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def canonical_metrics_plan_hash(plan: dict[str, Any]) -> str:
    payload = {
        "schema_version": plan["schema_version"],
        "plan_type": plan["plan_type"],
        "target": plan["target"],
        "metrics": plan["metrics"],
        "actions": sorted(plan["actions"], key=lambda action: action["item_key"]),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def canonical_citation_plan_hash(plan: dict[str, Any]) -> str:
    payload = {
        "schema_version": plan["schema_version"],
        "plan_type": plan["plan_type"],
        "target": plan["target"],
        "citation_source": plan["citation_source"],
        "actions": sorted(plan["actions"], key=lambda action: action["item_key"]),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def command_plan_citation_refresh(args: argparse.Namespace) -> None:
    raw = Path(args.citation_records).read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    citations_by_doi: dict[str, dict[str, Any]] = {}
    citations_by_pmid: dict[str, dict[str, Any]] = {}
    for record in evidence_records(json.loads(raw.decode("utf-8"))):
        citation = record.get("citation")
        if not isinstance(citation, dict) or citation.get("provider") != "semantic-scholar":
            continue
        count = citation.get("citation_count")
        if not isinstance(count, int) or count < 0:
            continue
        retrieved_at = str(citation.get("retrieved_at") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", retrieved_at):
            continue
        snapshot = {"citation_count": count, "provider": "semantic-scholar", "retrieved_at": retrieved_at, "source_sha256": source_sha256}
        identity = record_identity(record)
        if identity["doi"]:
            citations_by_doi[identity["doi"]] = snapshot
        if identity["pmid"]:
            citations_by_pmid[identity["pmid"]] = snapshot
    actions: list[dict[str, Any]] = []
    for record in zotero_records(load_json(args.zotero_items)):
        data = item_data(record)
        identity = record_identity(record)
        key = item_key(record)
        version = data.get("version") or record.get("version")
        citation = citations_by_doi.get(identity["doi"]) or citations_by_pmid.get(identity["pmid"])
        base = {"item_key": key, "expected_version": int(version) if str(version or "").isdigit() else None, "title": str(data.get("title") or "")}
        if not key or base["expected_version"] is None:
            actions.append({**base, "decision": "skip", "reason_codes": ["missing-item-key-or-version"], "citation": None})
        elif not citation:
            actions.append({**base, "decision": "skip", "reason_codes": ["no-semantic-scholar-citation-match"], "citation": None})
        else:
            actions.append({**base, "decision": "update", "reason_codes": ["unique-doi-or-pmid-citation-match"], "citation": citation})
    actions.sort(key=lambda action: action["item_key"] or "~")
    plan = {
        "schema_version": "1.0", "plan_type": "zotero-citations",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "plan_hash": "",
        "target": {"library_type": args.library_type, "library_id": int(args.library_id)},
        "citation_source": {"provider": "semantic-scholar", "source_sha256": source_sha256},
        "actions": actions,
        "summary": {"selected": len(actions), "update": sum(action["decision"] == "update" for action in actions), "skip": sum(action["decision"] == "skip" for action in actions)},
    }
    plan["plan_hash"] = canonical_citation_plan_hash(plan)
    write_json(args.output, plan)
    print(f"Success! Zotero citation refresh plan written to: {args.output}")


def normalize_issn(value: Any) -> str:
    text = re.sub(r"[^0-9Xx]", "", str(value or "")).upper()
    return text if len(text) == 8 else ""


def item_issns(record: dict[str, Any]) -> list[str]:
    data = item_data(record)
    values = [data.get("ISSN"), data.get("issn"), data.get("eISSN"), data.get("eissn")]
    found: set[str] = set()
    for value in values:
        for candidate in re.split(r"[;,/\s]+", str(value or "")):
            normalized = normalize_issn(candidate)
            if normalized:
                found.add(normalized)
    return sorted(found)


def normalize_journal_name(value: Any) -> str:
    """Return a strict, punctuation-insensitive journal-name key."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def item_journal_names(record: dict[str, Any]) -> list[str]:
    """Return distinct normalized publication-title and abbreviation keys."""
    data = item_data(record)
    values = [
        data.get("publicationTitle"), data.get("journal"),
        data.get("journalAbbreviation"), data.get("abbreviation"),
    ]
    return sorted({normalized for value in values if (normalized := normalize_journal_name(value))})


def metric_column(row: dict[str, str], *names: str) -> str:
    index = {re.sub(r"[^a-z0-9]", "", key.lower()): value for key, value in row.items() if key}
    for name in names:
        value = index.get(re.sub(r"[^a-z0-9]", "", name.lower()))
        if value is not None:
            return str(value).strip()
    return ""


EASYSCHOLAR_JCR_DATASETS = (
    "jcr",
    "jcr分区",
    "jcr期刊分区",
    "jcrquartile",
)
EASYSCHOLAR_CAS_DATASETS = (
    "中科院分区",
    "中科院大类分区",
    "中科院sci期刊分区",
    "中科院",
    "cas分区",
    "cas",
)
EASYSCHOLAR_OFFICIAL_IF_FIELDS = (
    "sciif",
    "if",
    "impact_factor",
    "impactFactor",
)
EASYSCHOLAR_OFFICIAL_IF5_FIELDS = ("sciif5", "if5", "impact_factor_5y", "impactFactor5")
EASYSCHOLAR_OFFICIAL_JCR_FIELDS = ("sci", "ssci", "scie", "esci")
EASYSCHOLAR_OFFICIAL_CAS_FIELDS = ("sciUp", "sciBase")


def _easyscholar_key(value: Any) -> str:
    """Return a stable comparison key for easyscholar field and dataset names."""
    return re.sub(r"[\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)


def _easyscholar_number(value: Any) -> int | float | None:
    """Parse one finite, non-negative metric number without treating bool as IF."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    else:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).strip())
        if not match:
            return None
        try:
            parsed = float(match.group(0))
        except ValueError:
            return None
    if parsed < 0 or not parsed < float("inf"):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _normalize_jcr_zone(value: Any) -> str | None:
    text = re.sub(r"[\s_-]+", "", str(value or "").upper())
    match = re.fullmatch(r"(?:JCR)?Q([1-4])(?:区)?", text)
    return f"Q{match.group(1)}" if match else None


def _normalize_cas_zone(value: Any) -> str | None:
    text = re.sub(r"[\s_-]+", "", str(value or ""))
    match = re.fullmatch(r"(?:CAS|中科院)?([1-4])区", text, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}区"
    chinese_zone = {"一区": "1区", "二区": "2区", "三区": "3区", "四区": "4区"}
    if text in chinese_zone:
        return chinese_zone[text]
    # EasyScholar's real officialRank payload uses values such as
    # "生物学1区" and "综合性期刊3区" in sciUp/sciBase. Only accept a
    # single trailing major-category zone; never infer from sciUpSmall,
    # which may contain multiple subject-category zones.
    match = re.fullmatch(r".+?([1-4])区[。.]?", text)
    return f"{match.group(1)}区" if match else None


def _official_rank_buckets(easyscholar: dict[str, Any]) -> list[dict[str, Any]]:
    official_rank = easyscholar.get("official_rank")
    if not isinstance(official_rank, dict):
        return []
    return [
        bucket
        for bucket_name in ("all", "select")
        if isinstance((bucket := official_rank.get(bucket_name)), dict)
    ]


def _official_rank_value(buckets: list[dict[str, Any]], field_names: tuple[str, ...]) -> Any:
    for bucket in buckets:
        values = {_easyscholar_key(key): value for key, value in bucket.items()}
        for field_name in field_names:
            key = _easyscholar_key(field_name)
            if key in values:
                return values[key]
    return None


def _easyscholar_publication_metrics(
    easyscholar: dict[str, Any],
    buckets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map a small, audited allowlist of categorical journal descriptors."""
    metrics: list[dict[str, Any]] = []
    cas_major = re.sub(r"[。.]$", "", str(_official_rank_value(buckets, ("sciUp",)) or "").strip())
    if re.fullmatch(r".+[1-4]区", cas_major):
        metrics.append({"code": "cas_major", "value": cas_major})
    if str(_official_rank_value(buckets, ("sciUpTop",)) or "").strip():
        metrics.append({"code": "cas_top", "value": True})
    esi = str(_official_rank_value(buckets, ("esi",)) or "").strip()
    if esi:
        metrics.append({"code": "esi_category", "value": esi})
    indexing = str(_official_rank_value(buckets, ("eii",)) or "").strip().upper()
    if indexing == "EI":
        metrics.append({"code": "indexing", "value": "EI"})
    return metrics


def _custom_rank_zone(
    easyscholar: dict[str, Any],
    dataset_names: tuple[str, ...],
    normalizer: Any,
) -> str | None:
    custom_rank = easyscholar.get("custom_rank")
    if not isinstance(custom_rank, list):
        return None
    entries = [entry for entry in custom_rank if isinstance(entry, dict)]
    for dataset_name in dataset_names:
        expected = _easyscholar_key(dataset_name)
        for entry in entries:
            if _easyscholar_key(entry.get("dataset")) != expected:
                continue
            zone = normalizer(entry.get("rank"))
            if zone is not None:
                return zone
    return None


def easyscholar_record_to_metric(
    record: dict[str, Any],
    *,
    source_label: str,
    source_sha256: str,
) -> dict[str, Any] | None:
    """Conservatively map easyscholar ranks to the metrics add-on fields."""
    easyscholar = record.get("easyscholar")
    if not isinstance(easyscholar, dict):
        easyscholar = {}
    journal_metrics = record.get("journal_metrics")
    if not isinstance(journal_metrics, dict):
        journal_metrics = {}
    buckets = _official_rank_buckets(easyscholar)

    impact_factor = None
    for bucket in buckets:
        value = _official_rank_value([bucket], EASYSCHOLAR_OFFICIAL_IF_FIELDS)
        if value is not None:
            impact_factor = _easyscholar_number(value)
        if impact_factor is not None:
            break
    if impact_factor is None:
        impact_factor = _easyscholar_number(journal_metrics.get("impact_factor"))

    impact_factor_5y = None
    for bucket in buckets:
        value = _official_rank_value([bucket], EASYSCHOLAR_OFFICIAL_IF5_FIELDS)
        if value is not None:
            impact_factor_5y = _easyscholar_number(value)
        if impact_factor_5y is not None:
            break
    if impact_factor_5y is None:
        impact_factor_5y = _easyscholar_number(journal_metrics.get("impact_factor_5y"))

    jcr_zone = _custom_rank_zone(easyscholar, EASYSCHOLAR_JCR_DATASETS, _normalize_jcr_zone)
    if jcr_zone is None:
        for bucket in buckets:
            for field_name in EASYSCHOLAR_OFFICIAL_JCR_FIELDS:
                candidate = _official_rank_value([bucket], (field_name,))
                if (jcr_zone := _normalize_jcr_zone(candidate)) is not None:
                    break
            if jcr_zone is not None:
                break
    if jcr_zone is None:
        jcr_zone = _normalize_jcr_zone(journal_metrics.get("jcr_zone"))

    cas_zone = _custom_rank_zone(easyscholar, EASYSCHOLAR_CAS_DATASETS, _normalize_cas_zone)
    if cas_zone is None:
        for bucket in buckets:
            candidate = _official_rank_value([bucket], EASYSCHOLAR_OFFICIAL_CAS_FIELDS)
            if (cas_zone := _normalize_cas_zone(candidate)) is not None:
                break
    if cas_zone is None:
        cas_zone = _normalize_cas_zone(journal_metrics.get("cas_zone"))

    publication_metrics = _easyscholar_publication_metrics(easyscholar, buckets)
    fetched_at = str(easyscholar.get("fetched_at") or "")
    retrieved_match = re.match(r"^(\d{4}-\d{2}-\d{2})", fetched_at)

    if impact_factor is None and impact_factor_5y is None and jcr_zone is None and cas_zone is None and not publication_metrics:
        return None
    metric: dict[str, Any] = {
        "source_label": source_label,
        "source_sha256": source_sha256,
    }
    if impact_factor is not None:
        metric["impact_factor"] = impact_factor
    if impact_factor_5y is not None:
        metric["impact_factor_5y"] = impact_factor_5y
    if jcr_zone is not None:
        metric["jcr_zone"] = jcr_zone
    if cas_zone is not None:
        metric["cas_zone"] = cas_zone
    if publication_metrics:
        metric["publication_metrics"] = publication_metrics
    if retrieved_match:
        metric["retrieved_at"] = retrieved_match.group(1)
    return metric


def load_journal_metrics(path: str | Path) -> tuple[dict[str, dict[str, Any]], set[str], dict[str, set[str]], str]:
    raw = Path(path).read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    rows = csv.DictReader(raw.decode("utf-8-sig").splitlines())
    by_issn: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    by_journal_name: dict[str, set[str]] = {}
    for row in rows:
        issn = normalize_issn(metric_column(row, "ISSN", "eISSN", "e-ISSN"))
        if not issn:
            continue
        try:
            impact_factor = float(metric_column(row, "Impact Factor", "IF", "impact_factor"))
        except ValueError:
            continue
        if impact_factor < 0 or not impact_factor < float("inf"):
            continue
        # Match JSON's cross-runtime numeric representation: JavaScript emits
        # 18 rather than 18.0, and the plan hash must be portable to the MCP.
        if impact_factor.is_integer():
            impact_factor = int(impact_factor)
        metric: dict[str, Any] = {"impact_factor": impact_factor}
        jcr = metric_column(row, "JCR-zone", "JCR", "JCR Zone")
        cas = metric_column(row, "CAS-zone", "CAS", "CAS Zone")
        if jcr:
            metric["jcr_zone"] = jcr
        if cas:
            metric["cas_zone"] = cas
        if issn in by_issn and by_issn[issn] != metric:
            ambiguous.add(issn)
        else:
            by_issn[issn] = metric
        for journal_name in (
            metric_column(row, "Journal", "Journal Title", "publicationTitle"),
            metric_column(row, "Abbreviation", "Journal Abbreviation", "ISO Abbreviation"),
        ):
            normalized_name = normalize_journal_name(journal_name)
            if normalized_name:
                by_journal_name.setdefault(normalized_name, set()).add(issn)
    return by_issn, ambiguous, by_journal_name, source_sha256


def command_plan_metrics_backfill(args: argparse.Namespace) -> None:
    year = str(args.metrics_year)
    if not METRICS_YEAR_RE.fullmatch(year):
        raise ValueError("--metrics-year must use YYYY between 1900 and 2099")
    source_label = str(args.source_label).strip()
    if not source_label:
        raise ValueError("--source-label must not be empty")
    metrics_by_issn, ambiguous_issns, metrics_by_journal_name, source_sha256 = load_journal_metrics(args.journal_metrics)
    actions: list[dict[str, Any]] = []
    for record in zotero_records(load_json(args.zotero_items)):
        data = item_data(record)
        key = item_key(record)
        version = data.get("version") or record.get("version")
        issns = item_issns(record)
        journal_names = item_journal_names(record)
        base = {
            "item_key": key,
            "expected_version": int(version) if str(version or "").isdigit() else None,
            "title": str(data.get("title") or ""),
            "issns": issns,
        }
        if not key or base["expected_version"] is None:
            actions.append({**base, "decision": "skip", "reason_codes": ["missing-item-key-or-version"], "metric": None})
            continue
        matches = sorted({issn for issn in issns if issn in metrics_by_issn and issn not in ambiguous_issns})
        if any(issn in ambiguous_issns for issn in issns):
            actions.append({**base, "decision": "skip", "reason_codes": ["ambiguous-metrics-issn"], "metric": None})
        elif len(matches) == 1:
            metric = {**metrics_by_issn[matches[0]], "source_label": source_label, "source_sha256": source_sha256}
            actions.append({**base, "decision": "update", "reason_codes": ["unique-issn-match"], "metric": metric})
        elif len(matches) > 1:
            actions.append({**base, "decision": "skip", "reason_codes": ["multiple-metrics-issn-matches"], "metric": None})
        else:
            journal_match_issns = sorted({
                issn
                for journal_name in journal_names
                for issn in metrics_by_journal_name.get(journal_name, set())
                if issn in metrics_by_issn and issn not in ambiguous_issns
            })
            if len(journal_match_issns) == 1:
                metric = {**metrics_by_issn[journal_match_issns[0]], "source_label": source_label, "source_sha256": source_sha256}
                actions.append({**base, "decision": "update", "reason_codes": ["unique-journal-name-match"], "metric": metric})
            elif len(journal_match_issns) > 1:
                actions.append({**base, "decision": "skip", "reason_codes": ["ambiguous-journal-name-match"], "metric": None})
            elif not issns:
                actions.append({**base, "decision": "skip", "reason_codes": ["missing-issn-and-no-unique-journal-match"], "metric": None})
            else:
                actions.append({**base, "decision": "skip", "reason_codes": ["no-unique-metrics-match"], "metric": None})
    actions.sort(key=lambda action: action["item_key"] or "~")
    plan = {
        "schema_version": "1.0",
        "plan_type": "zotero-metrics",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan_hash": "",
        "target": {"library_type": args.library_type, "library_id": int(args.library_id)},
        "metrics": {"metrics_year": int(year), "source_label": source_label, "source_sha256": source_sha256},
        "actions": actions,
        "summary": {
            "selected": len(actions),
            "update": sum(action["decision"] == "update" for action in actions),
            "skip": sum(action["decision"] == "skip" for action in actions),
        },
    }
    plan["plan_hash"] = canonical_metrics_plan_hash(plan)
    write_json(args.output, plan)
    print(f"Success! Zotero metrics plan written to: {args.output}")


def command_plan_easyscholar_metrics_backfill(args: argparse.Namespace) -> None:
    """Plan EasyScholar metric updates by conservatively matching ranked records."""
    year = str(args.metrics_year)
    if not METRICS_YEAR_RE.fullmatch(year):
        raise ValueError("--metrics-year must use YYYY between 1900 and 2099")
    source_label = str(args.source_label).strip()
    if not source_label:
        raise ValueError("--source-label must not be empty")
    raw = Path(args.ranked).read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    ranked = evidence_records(json.loads(raw.decode("utf-8")))
    zotero = zotero_records(load_json(args.zotero_items))
    by_doi: dict[str, list[int]] = {}; by_pmid: dict[str, list[int]] = {}
    for idx, record in enumerate(zotero):
        ident = record_identity(record)
        if ident["doi"]: by_doi.setdefault(ident["doi"], []).append(idx)
        if ident["pmid"]: by_pmid.setdefault(ident["pmid"], []).append(idx)
    ranked_by_id: dict[tuple[str, str], list[int]] = {}
    for idx, record in enumerate(ranked):
        ident = record_identity(record)
        for kind in ("doi", "pmid"):
            if ident[kind]: ranked_by_id.setdefault((kind, ident[kind]), []).append(idx)
    actions: list[dict[str, Any]] = []; seen_keys: set[str] = set()
    for zidx, record in enumerate(zotero):
        data = item_data(record); key = item_key(record)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        version = data.get("version") or record.get("version")
        base = {"item_key": key, "expected_version": int(version) if str(version or "").isdigit() else None,
                "title": str(data.get("title") or ""), "issns": item_issns(record)}
        if base["expected_version"] is None:
            actions.append({**base, "decision": "skip", "reason_codes": ["missing-item-key-or-version"], "metric": None}); continue
        zi = record_identity(record); candidates: set[int] = set(); reasons: list[str] = []
        conflicts = False
        for kind, value, mapping in (("doi", zi["doi"], by_doi), ("pmid", zi["pmid"], by_pmid)):
            if not value: continue
            matches = mapping.get(value, [])
            if len(matches) != 1 or len(ranked_by_id.get((kind, value), [])) != 1:
                conflicts = True
            else:
                candidates.update(ranked_by_id[(kind, value)]); reasons.append("unique-" + kind + "-match")
        if conflicts or len(candidates) > 1:
            actions.append({**base, "decision": "skip", "reason_codes": ["identifier-conflict-or-duplicate"], "metric": None}); continue
        if not candidates and not (zi["doi"] or zi["pmid"]):
            title_year = (zi["title"], zi["year"])
            matches = [i for i, rr in enumerate(ranked) if record_identity(rr)["title"] == title_year[0] and record_identity(rr)["year"] == title_year[1] and title_year[0] and title_year[1]]
            if len(matches) != 1:
                actions.append({**base, "decision": "skip", "reason_codes": ["no-unique-ranked-match"], "metric": None}); continue
            candidates = {matches[0]}; reasons.append("unique-title-year-match")
        metric = easyscholar_record_to_metric(ranked[next(iter(candidates))], source_label=source_label, source_sha256=source_sha256)
        if metric is None:
            actions.append({**base, "decision": "skip", "reason_codes": ["no-easyscholar-metric"], "metric": None})
        else:
            actions.append({**base, "decision": "update", "reason_codes": reasons, "metric": metric})
    actions.sort(key=lambda action: action["item_key"])
    raw_remove_years = [str(value) for value in getattr(args, "remove_metrics_year", [])]
    invalid_remove_years = [value for value in raw_remove_years if not METRICS_YEAR_RE.fullmatch(value) or value == year]
    if invalid_remove_years:
        raise ValueError("--remove-metrics-year must use a different valid YYYY value")
    remove_years = sorted({int(value) for value in raw_remove_years})
    plan = {"schema_version": "1.0", "plan_type": "zotero-metrics", "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "plan_hash": "", "target": {"library_type": args.library_type, "library_id": int(args.library_id)}, "metrics": {"metrics_year": int(year), "remove_years": remove_years, "source_label": source_label, "source_sha256": source_sha256}, "actions": actions, "summary": {"selected": len(actions), "update": sum(a["decision"] == "update" for a in actions), "skip": sum(a["decision"] == "skip" for a in actions)}}
    plan["plan_hash"] = canonical_metrics_plan_hash(plan)
    write_json(args.output, plan)
    print(f"Success! Zotero EasyScholar metrics plan written to: {args.output}")


def ris_lines(action: dict[str, Any]) -> list[str]:
    item = action.get("item") or {}
    item_type = item.get("itemType")
    lines = [f"TY  - {'JOUR' if item_type == 'journalArticle' else 'UNPB'}"]
    mapping = (
        ("TI", item.get("title")),
        ("PY", item.get("date")),
        ("JO", item.get("publicationTitle")),
        ("DO", item.get("DOI")),
        ("UR", item.get("url")),
        ("AB", item.get("abstractNote")),
    )
    for code, value in mapping:
        if value:
            clean = re.sub(r"\s+", " ", str(value)).strip()
            lines.append(f"{code}  - {clean}")
    for creator in item.get("creators", []):
        if creator.get("name"):
            name = creator["name"]
        else:
            name = ", ".join(part for part in (creator.get("lastName"), creator.get("firstName")) if part)
        if name:
            clean_name = re.sub(r"\s+", " ", str(name)).strip()
            lines.append(f"AU  - {clean_name}")
    pmid = clean_pmid(item.get("extra"))
    if pmid:
        lines.extend(["DB  - PubMed", f"AN  - {pmid}"])
    for tag in item.get("tags", []):
        if isinstance(tag, dict) and tag.get("tag"):
            lines.append(f"KW  - {tag['tag']}")
    lines.append("ER  -")
    return lines


def write_ris(path: str | Path, actions: list[dict[str, Any]]) -> None:
    blocks = ["\n".join(ris_lines(action)) for action in actions if action.get("decision") == "create"]
    with Path(path).open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\n".join(blocks))
        if blocks:
            handle.write("\n")


def merge_metrics_extra(extra: Any, record: dict[str, Any], *, year: int, source_label: str, source_sha256: str) -> str | None:
    metric = easyscholar_record_to_metric(record, source_label=source_label, source_sha256=source_sha256)
    if metric is None:
        return str(extra or "")
    text = str(extra or "")
    payload: dict[str, Any] = {"schema_version": 2, "by_year": {}}
    retained: list[str] = []
    for line in text.splitlines():
        if line.startswith(METRICS_PREFIX):
            try:
                candidate = json.loads(line[len(METRICS_PREFIX):].strip())
                if isinstance(candidate, dict) and candidate.get("schema_version") == 2 and isinstance(candidate.get("by_year"), dict):
                    payload = candidate
            except json.JSONDecodeError:
                # Replace malformed managed blocks with the new valid block;
                # retaining one would make the add-on reject duplicate blocks.
                pass
        else:
            retained.append(line)
    payload.setdefault("by_year", {})[str(year)] = metric
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "\n".join([*retained, f"{METRICS_PREFIX} {encoded}"]).strip()


def command_plan_import(args: argparse.Namespace) -> None:
    if args.candidate_limit <= 0:
        raise ValueError("--candidate-limit must be a positive integer")
    raw_bytes = Path(args.evidence).read_bytes()
    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    raw_records = evidence_records(json.loads(raw_bytes.decode("utf-8")))
    indexed: dict[str, dict[str, Any]] = {}
    for record in raw_records:
        evidence_id = stable_evidence_id(record)
        if evidence_id in indexed:
            raise ValueError(f"Evidence input contains duplicate stable ID: {evidence_id}")
        indexed[evidence_id] = record
    selected_ids = load_selection(args)
    unknown = [evidence_id for evidence_id in selected_ids if evidence_id not in indexed]
    if unknown:
        raise ValueError(f"Selection contains unknown evidence IDs: {', '.join(unknown)}")
    selected = [(evidence_id, indexed[evidence_id]) for evidence_id in selected_ids]

    project_slug = slugify(args.project)
    priority_metadata, priority_by_id = load_priority_recommendations(
        getattr(args, "priority_recommendations", None),
        project_slug=project_slug,
        evidence_ids=set(indexed),
    )
    try:
        parsed_search_date = date.fromisoformat(args.search_date)
    except ValueError as exc:
        raise ValueError("--search-date must use YYYY-MM-DD") from exc
    metrics_year = parsed_search_date.year - 1
    configured_metrics_year = getattr(args, "metrics_year", None)
    if configured_metrics_year is not None and int(configured_metrics_year) != metrics_year:
        raise ValueError(f"--metrics-year must match the derived display year {metrics_year} for search date {args.search_date}")
    tags = sorted(
        set(
            [
                f"project:{project_slug}",
                f"import-run:{project_slug}-{args.search_date.replace('-', '')}",
                *(tag for tag in args.tag if str(tag).strip()),
            ]
        )
    )

    candidate_map: dict[str, list[dict[str, Any]]]
    truncated_map: dict[str, bool]
    source_version: int | None = None
    unchecked = False
    if args.zotero_items:
        snapshot = load_json(args.zotero_items)
        snapshot_items = zotero_records(snapshot)
        source_version_raw = snapshot.get("last_modified_version") if isinstance(snapshot, dict) else None
        source_version = int(source_version_raw) if str(source_version_raw or "").isdigit() else None
        truncated = len(snapshot_items) > args.candidate_limit
        candidates = snapshot_items[: args.candidate_limit]
        candidate_map = {evidence_id: candidates for evidence_id, _record in selected}
        truncated_map = {evidence_id: truncated for evidence_id, _record in selected}
        matching_mode = "snapshot"
    else:
        try:
            candidate_map, truncated_map, source_version = fetch_local_candidates(
                selected,
                library_type=args.library_type,
                library_id=args.library_id,
                candidate_limit=args.candidate_limit,
            )
            matching_mode = "local-api"
        except ApiError:
            if not args.allow_unchecked_create:
                raise
            candidate_map = {evidence_id: [] for evidence_id, _record in selected}
            truncated_map = {evidence_id: False for evidence_id, _record in selected}
            matching_mode = "unchecked"
            unchecked = True

    actions: list[dict[str, Any]] = []
    seen_selected: set[str] = set()
    for evidence_id, record in selected:
        item, metadata_reasons = normalize_zotero_item(record, tags)
        if evidence_id in seen_selected:
            decision, reasons, match = "skip", ["duplicate-selection-record"], None
        elif metadata_reasons:
            decision, reasons, match = "check", metadata_reasons, None
        else:
            decision, reasons, match = classify_match(
                record,
                candidate_map[evidence_id],
                truncated=truncated_map[evidence_id],
            )
            if unchecked and decision == "create":
                reasons = ["unchecked-library-create"]
        priority_recommendation = None
        if priority_metadata is not None:
            explicit = priority_by_id.get(evidence_id)
            priority_recommendation = {
                "level": explicit["level"] if explicit else priority_metadata["default_for_selected"],
                "reason_codes": explicit["reason_codes"] if explicit else ["selected-default"],
                "tag_decision": "not-actionable",
            }
            if decision in {"create", "reuse"} and item is not None:
                existing_priority = []
                if decision == "reuse":
                    candidate = candidate_for_match(candidate_map[evidence_id], match)
                    existing_priority = priority_tags(item_data(candidate or {}).get("tags", []))
                if existing_priority:
                    priority_recommendation["tag_decision"] = "preserve-existing"
                    priority_recommendation["existing_tags"] = existing_priority
                else:
                    priority_recommendation["tag_decision"] = "add"
                    add_item_tag(item, f"{PRIORITY_TAG_PREFIX}{priority_recommendation['level']}")
        if decision in {"create", "reuse"} and item is not None and item.get("itemType") != "preprint" and isinstance(record.get("easyscholar"), dict) and record["easyscholar"]:
            label = getattr(args, "metrics_source_label", None) or "easyscholar-latest"
            metric = easyscholar_record_to_metric(record, source_label=label, source_sha256=source_sha256)
            if metric is not None:
                item["extra"] = merge_metrics_extra(item.get("extra"), record, year=metrics_year, source_label=label, source_sha256=source_sha256)
                if metric.get("jcr_zone"):
                    add_item_tag(item, f"JCR:{metric['jcr_zone']}")
                if metric.get("cas_zone"):
                    add_item_tag(item, f"CAS:{metric['cas_zone']}")
        seen_selected.add(evidence_id)
        source_database = str(record.get("source") or "").strip() or None
        source_record_id = str(record.get("id") or record.get("source_id") or "").strip() or None
        rank_raw = record.get("rank")
        display_rank = int(rank_raw) if str(rank_raw or "").isdigit() and int(rank_raw) > 0 else None
        action = {
            "evidence_id": evidence_id,
            "display_rank": display_rank,
            "decision": decision,
            "reason_codes": sorted(set(reasons)),
            "source": {"database": source_database, "record_id": source_record_id},
            "item": item,
            "match": match,
        }
        if priority_recommendation is not None:
            action["priority_recommendation"] = priority_recommendation
        actions.append(action)
    actions.sort(key=lambda action: action["evidence_id"])
    counts = {decision: sum(action["decision"] == decision for action in actions) for decision in ("create", "reuse", "check", "skip")}
    plan = {
        "schema_version": "1.0",
        "plan_type": "zotero-import",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan_hash": "",
        "project": {"slug": project_slug, "search_date": args.search_date},
        "target": {
            "library_type": args.library_type,
            "library_id": int(args.library_id),
            "collection_name": args.collection_name.strip(),
            "tags": tags,
        },
        "matching": {
            "mode": matching_mode,
            "source_library_version": source_version,
            "candidate_limit": args.candidate_limit,
            "unchecked_create": unchecked,
        },
        "actions": actions,
        "summary": {"selected": len(actions), **counts},
    }
    if priority_metadata is not None:
        plan["priority"] = priority_metadata
    if not plan["target"]["collection_name"]:
        raise ValueError("--collection-name must not be empty")
    plan["plan_hash"] = canonical_plan_hash(plan)
    write_json(args.output, plan)
    if args.ris_output:
        write_ris(args.ris_output, actions)
    ris_message = f"; RIS: {args.ris_output}" if args.ris_output else ""
    print(
        f"Success! Zotero import plan written to: {args.output} "
        f"({plan['plan_hash'][:19]}, create={counts['create']}, reuse={counts['reuse']}, "
        f"check={counts['check']}, skip={counts['skip']}){ris_message}"
    )


def evidence_level(record: dict[str, Any]) -> str:
    for name in ("evidence_level", "evidenceLevel", "level"):
        value = record.get(name)
        if value:
            return str(value)
    score = record.get("score") or record.get("rank_score")
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return "unspecified"
    if numeric >= 80:
        return "high"
    if numeric >= 50:
        return "moderate"
    return "screen"


def command_fetch_items(args: argparse.Namespace) -> None:
    base_url = normalize_base_url(args.base_url, args.local)
    client = ZoteroClient(
        base_url=base_url,
        api_key=None if args.local else api_key_from_env(args.api_key_env),
        rate_limit_seconds=0.0 if args.local else args.rate_limit_seconds,
        rate_limit_state=Path(args.rate_limit_state),
        max_retries=args.max_retries,
    )
    path = f"{library_prefix(args.library_type, args.library_id)}/items"
    if args.collection_key:
        path = f"{library_prefix(args.library_type, args.library_id)}/collections/{args.collection_key}/items"
    records: list[dict[str, Any]] = []
    start = 0
    page_size = min(args.page_size, args.limit)
    headers: dict[str, str] = {}
    while len(records) < args.limit:
        query: dict[str, str | int] = {
            "format": "json",
            "include": "data",
            "limit": min(page_size, args.limit - len(records)),
            "start": start,
        }
        if args.query:
            query["q"] = args.query
            query["qmode"] = args.qmode
        if args.tag:
            query["tag"] = args.tag
        if args.since is not None:
            query["since"] = args.since
        data, headers = client.request("GET", path, query=query)
        if not isinstance(data, list) or not data:
            break
        records.extend(data)
        start += len(data)
        total = int(headers.get("Total-Results", len(records)) or len(records))
        if len(records) >= total:
            break
    output = {
        "source": "zotero-local-api" if args.local else "zotero-web-api",
        "base_url": base_url,
        "library_type": args.library_type,
        "library_id": args.library_id,
        "collection_key": args.collection_key,
        "query": args.query,
        "tag": args.tag,
        "limit": args.limit,
        "count": len(records),
        "last_modified_version": headers.get("Last-Modified-Version"),
        "items": records,
    }
    write_json(args.output, output)
    print(f"Success! Zotero items written to: {args.output}")


def command_match_evidence(args: argparse.Namespace) -> None:
    evidence = evidence_records(load_json(args.evidence))
    candidates = zotero_records(load_json(args.zotero_items))
    matches = []
    unmatched = []
    for index, record in enumerate(evidence):
        match = best_match(record, candidates)
        entry = {
            "evidence_index": index,
            "evidence_id": record.get("id") or record.get("pmid") or record.get("doi") or record.get("title"),
            "evidence_title": field(record, "title"),
            "evidence": record,
            "match": match,
            "status": "matched" if match and match["score"] >= args.min_score else "unmatched",
        }
        if entry["status"] == "matched":
            matches.append(entry)
        else:
            entry["match"] = match
            unmatched.append(entry)
    output = {
        "min_score": args.min_score,
        "counts": {
            "evidence": len(evidence),
            "zotero_items": len(candidates),
            "matched": len(matches),
            "unmatched": len(unmatched),
        },
        "matches": matches,
        "unmatched": unmatched,
    }
    write_json(args.output, output)
    print(f"Success! Zotero match report written to: {args.output}")


def command_dedupe_library(args: argparse.Namespace) -> None:
    records = zotero_records(load_json(args.zotero_items))
    clusters: list[dict[str, Any]] = []
    used: set[int] = set()
    identities = [record_identity(record) for record in records]

    for index, record in enumerate(records):
        if index in used:
            continue
        identity = identities[index]
        members = []
        for other_index in range(index + 1, len(records)):
            if other_index in used:
                continue
            other_identity = identities[other_index]
            reasons = duplicate_reasons(identity, other_identity, args.min_title_score)
            if reasons:
                members.append((other_index, reasons))
        if not members:
            continue
        used.add(index)
        cluster_items = [
            {
                "record_index": index,
                "zotero_key": item_key(record),
                "title": field(record, "title"),
                "identity": identity,
                "reasons": ["cluster-seed"],
            }
        ]
        for member_index, reasons in members:
            used.add(member_index)
            member = records[member_index]
            cluster_items.append(
                {
                    "record_index": member_index,
                    "zotero_key": item_key(member),
                    "title": field(member, "title"),
                    "identity": identities[member_index],
                    "reasons": reasons,
                }
            )
        clusters.append({"cluster_id": len(clusters) + 1, "items": cluster_items})

    output = {
        "count": len(clusters),
        "min_title_score": args.min_title_score,
        "clusters": clusters,
        "policy": "review-before-merge; this script reports duplicates but does not modify Zotero records",
    }
    write_json(args.output, output)
    print(f"Success! Zotero duplicate report written to: {args.output}")


def duplicate_reasons(a: dict[str, str], b: dict[str, str], min_title_score: float) -> list[str]:
    reasons: list[str] = []
    if a["doi"] and a["doi"] == b["doi"]:
        reasons.append("doi")
    if a["pmid"] and a["pmid"] == b["pmid"]:
        reasons.append("pmid")
    sim = title_similarity(a["title"], b["title"])
    if sim >= min_title_score and (not a["year"] or not b["year"] or a["year"] == b["year"]):
        reasons.append(f"title-year:{sim:.2f}")
    return reasons


def command_plan_sync(args: argparse.Namespace) -> None:
    match_report = load_json(args.matches)
    date_tag = f"search-date:{args.search_date}"
    project_tag = f"project:{args.project}"
    base_tags = [project_tag, date_tag] + list(args.tag)
    actions = []
    for entry in match_report.get("matches", []):
        record = entry.get("evidence", {})
        match = entry.get("match") or {}
        zotero_key = match.get("zotero_key")
        if not zotero_key:
            continue
        tags = base_tags + [f"evidence-level:{evidence_level(record)}", *article_type_tags(record)]
        action = {
            "action": "update-existing-item",
            "zotero_key": zotero_key,
            "evidence_index": entry.get("evidence_index"),
            "title": entry.get("evidence_title"),
            "add_to_collection_key": args.collection_key,
            "collection_name": args.collection_name,
            "add_tags": sorted(set(tags)),
            "note": {
                "title": f"{args.project} evidence note",
                "body": build_note(record, entry),
            },
        }
        actions.append(action)
    output = {
        "project": args.project,
        "search_date": args.search_date,
        "collection_name": args.collection_name,
        "collection_key": args.collection_key,
        "unmatched_policy": "check-before-import",
        "actions": actions,
        "unmatched": match_report.get("unmatched", []),
    }
    write_json(args.output, output)
    print(f"Success! Zotero sync plan written to: {args.output}")


def build_note(record: dict[str, Any], entry: dict[str, Any]) -> str:
    parts = [
        "# Evidence handoff",
        f"- Evidence index: {entry.get('evidence_index')}",
        f"- Match reasons: {', '.join((entry.get('match') or {}).get('reasons', []))}",
        f"- Evidence level: {evidence_level(record)}",
    ]
    for label, key in (
        ("DOI", "doi"),
        ("PMID", "pmid"),
        ("Source", "source"),
        ("Score", "score"),
        ("URL", "url"),
    ):
        value = record.get(key)
        if value:
            parts.append(f"- {label}: {value}")
    conclusion = record.get("conclusion") or record.get("key_finding") or record.get("abstract")
    if conclusion:
        parts.extend(["", "## Evidence summary", str(conclusion)])
    return "\n".join(parts)


def command_apply_sync(args: argparse.Namespace) -> None:
    plan = load_json(args.sync_plan)
    actions = plan.get("actions", [])
    if args.dry_run:
        write_json(args.output, {"dry_run": True, "planned_actions": actions})
        print(f"Success! Dry-run sync summary written to: {args.output}")
        return
    if args.local:
        raise ApiError("Zotero Local API is read-only; use the Zotero Web API for writes")

    base_url = normalize_base_url(args.base_url, args.local)
    api_key = None if args.local else api_key_from_env(args.api_key_env)
    if not args.local and not api_key:
        raise ApiError(f"Missing Zotero API key in environment variable {args.api_key_env}")
    client = ZoteroClient(
        base_url=base_url,
        api_key=api_key,
        rate_limit_seconds=0.0 if args.local else args.rate_limit_seconds,
        rate_limit_state=Path(args.rate_limit_state),
        max_retries=args.max_retries,
    )
    prefix = library_prefix(args.library_type, args.library_id)
    applied = []
    for action in actions:
        key = action["zotero_key"]
        current, _ = client.request("GET", f"{prefix}/items/{key}", query={"format": "json", "include": "data"})
        current_data = item_data(current)
        tags = merge_tags(current_data.get("tags", []), action.get("add_tags", []))
        collections = merge_collections(current_data.get("collections", []), action.get("add_to_collection_key"))
        patch = {
            "version": current_data.get("version"),
            "tags": tags,
            "collections": collections,
        }
        result, headers = client.request("PATCH", f"{prefix}/items/{key}", payload=patch)
        applied.append({"zotero_key": key, "result": result, "last_modified_version": headers.get("Last-Modified-Version")})
    write_json(args.output, {"dry_run": False, "applied": applied})
    print(f"Success! Zotero sync result written to: {args.output}")


def merge_tags(existing: list[Any], additions: list[str]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for tag in existing:
        if isinstance(tag, dict) and tag.get("tag"):
            merged[str(tag["tag"])] = tag
        elif isinstance(tag, str):
            merged[tag] = {"tag": tag}
    for tag in additions:
        if tag:
            merged.setdefault(tag, {"tag": tag})
    return list(merged.values())


def merge_collections(existing: list[Any], addition: str | None) -> list[str]:
    values = [str(value) for value in existing if value]
    if addition and addition not in values:
        values.append(addition)
    return values


def add_common_api_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--library-type", choices=["user", "group"], required=True)
    parser.add_argument("--library-id", required=True)
    parser.add_argument("--base-url", default=WEB_API_BASE)
    parser.add_argument("--local", action="store_true", help="Use Zotero local API at localhost:23119")
    parser.add_argument("--api-key-env", default="ZOTERO_API_KEY")
    parser.add_argument("--rate-limit-seconds", type=float, default=DEFAULT_RATE_LIMIT_SECONDS)
    parser.add_argument(
        "--rate-limit-state",
        default=str(Path(tempfile.gettempdir()) / "zotero_literature_manager_rate_limit.lock"),
    )
    parser.add_argument("--max-retries", type=int, default=3)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Zotero handoffs for literature evidence workflows.")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch-items", help="Fetch Zotero library or collection items to JSON.")
    add_common_api_args(fetch)
    fetch.add_argument("--limit", type=int, required=True, help="Maximum records to retrieve.")
    fetch.add_argument("--page-size", type=int, default=100)
    fetch.add_argument("--collection-key")
    fetch.add_argument("--query")
    fetch.add_argument("--qmode", default="titleCreatorYear", choices=["titleCreatorYear", "everything"])
    fetch.add_argument("--tag")
    fetch.add_argument("--since", type=int)
    fetch.add_argument("--output", required=True)
    fetch.set_defaults(func=command_fetch_items)

    match = sub.add_parser("match-evidence", help="Match ranked evidence JSON against exported Zotero items.")
    match.add_argument("--evidence", required=True)
    match.add_argument("--zotero-items", required=True)
    match.add_argument("--min-score", type=float, required=True)
    match.add_argument("--output", required=True)
    match.set_defaults(func=command_match_evidence)

    dedupe = sub.add_parser("dedupe-library", help="Report likely duplicate Zotero items without modifying them.")
    dedupe.add_argument("--zotero-items", required=True)
    dedupe.add_argument("--min-title-score", type=float, required=True)
    dedupe.add_argument("--output", required=True)
    dedupe.set_defaults(func=command_dedupe_library)

    plan = sub.add_parser("plan-sync", help="Create a dry-run Zotero collection/tag/note sync plan.")
    plan.add_argument("--matches", required=True)
    plan.add_argument("--project", required=True)
    plan.add_argument("--search-date", required=True)
    plan.add_argument("--collection-name", required=True)
    plan.add_argument("--collection-key")
    plan.add_argument("--tag", action="append", default=[])
    plan.add_argument("--output", required=True)
    plan.set_defaults(func=command_plan_sync)

    plan_import = sub.add_parser(
        "plan-import",
        help="Create a reviewable Zotero import plan from selected ranked evidence.",
    )
    plan_import.add_argument("--evidence", required=True)
    selection = plan_import.add_mutually_exclusive_group(required=True)
    selection.add_argument("--select-id", action="append")
    selection.add_argument("--selection-json")
    plan_import.add_argument("--project", required=True)
    plan_import.add_argument("--search-date", required=True)
    plan_import.add_argument("--collection-name", required=True)
    plan_import.add_argument("--library-type", choices=["user", "group"], required=True)
    plan_import.add_argument("--library-id", required=True)
    plan_import.add_argument("--candidate-limit", type=int, required=True)
    plan_import.add_argument("--tag", action="append", default=[])
    plan_import.add_argument("--zotero-items", help="Offline Zotero item snapshot; otherwise use Local API.")
    plan_import.add_argument("--allow-unchecked-create", action="store_true")
    plan_import.add_argument("--ris-output")
    plan_import.add_argument("--metrics-year", type=int, help="Deprecated compatibility check; must equal search-date year minus one.")
    plan_import.add_argument("--metrics-source-label", help="Optional metrics provenance label (defaults to easyscholar-latest).")
    plan_import.add_argument("--priority-recommendations", help="Optional report-stage priority_recommendations.json sidecar.")
    plan_import.add_argument("--output", required=True)
    plan_import.set_defaults(func=command_plan_import)

    metrics = sub.add_parser("plan-metrics-backfill", help="Create a reviewed, no-write IF/JCR/CAS metrics patch plan.")
    metrics.add_argument("--zotero-items", required=True, help="Zotero item export/snapshot with item key, version, and ISSN.")
    metrics.add_argument("--journal-metrics", required=True, help="Reviewed metrics CSV; it is hashed into the plan.")
    metrics.add_argument("--metrics-year", required=True, type=int)
    metrics.add_argument("--source-label", required=True)
    metrics.add_argument("--library-type", choices=["user", "group"], required=True)
    metrics.add_argument("--library-id", required=True)
    metrics.add_argument("--output", required=True)
    metrics.set_defaults(func=command_plan_metrics_backfill)

    easymetrics = sub.add_parser("plan-easyscholar-metrics-backfill", help="Create a Zotero metrics plan from ranked EasyScholar records.")
    easymetrics.add_argument("--ranked", "--ranked-json", dest="ranked", required=True, help="Ranked/EasyScholar JSON (raw bytes are hashed).")
    easymetrics.add_argument("--zotero-items", required=True)
    easymetrics.add_argument("--metrics-year", required=True)
    easymetrics.add_argument("--remove-metrics-year", action="append", default=[], help="Optional incorrect/historical metric year to remove during apply; repeatable.")
    easymetrics.add_argument("--source-label", required=True)
    easymetrics.add_argument("--library-type", choices=["user", "group"], required=True)
    easymetrics.add_argument("--library-id", required=True)
    easymetrics.add_argument("--output", required=True)
    easymetrics.set_defaults(func=command_plan_easyscholar_metrics_backfill)

    citations = sub.add_parser("plan-citation-refresh", help="Create a reviewed citation snapshot plan from compatible evidence.")
    citations.add_argument("--zotero-items", required=True)
    citations.add_argument("--citation-records", required=True, help="literature-research JSON enriched with compatible citation snapshots.")
    citations.add_argument("--library-type", choices=["user", "group"], required=True)
    citations.add_argument("--library-id", required=True)
    citations.add_argument("--output", required=True)
    citations.set_defaults(func=command_plan_citation_refresh)

    apply = sub.add_parser("apply-sync", help="Apply an approved sync plan to existing Zotero items.")
    add_common_api_args(apply)
    apply.add_argument("--sync-plan", required=True)
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--output", required=True)
    apply.set_defaults(func=command_apply_sync)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except (ApiError, RateLimitError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
