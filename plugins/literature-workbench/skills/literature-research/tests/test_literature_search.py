#!/usr/bin/env python3
"""Unit tests for literature_search.py — stdlib unittest, no network calls."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Make the script importable
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import literature_search as ls  # type: ignore[reportMissingImports]  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestChineseOrInt(unittest.TestCase):
    def test_digit_string(self) -> None:
        self.assertEqual(ls.chinese_or_int("5"), 5)

    def test_simple_chinese(self) -> None:
        self.assertEqual(ls.chinese_or_int("三"), 3)

    def test_ten(self) -> None:
        self.assertEqual(ls.chinese_or_int("十"), 10)

    def test_twelve(self) -> None:
        self.assertEqual(ls.chinese_or_int("十二"), 12)

    def test_thirty(self) -> None:
        self.assertEqual(ls.chinese_or_int("三十"), 30)

    def test_twenty_three(self) -> None:
        self.assertEqual(ls.chinese_or_int("二十三"), 23)

    def test_unknown(self) -> None:
        self.assertIsNone(ls.chinese_or_int("零"))


class TestDetectYearRange(unittest.TestCase):
    def test_english_past_years(self) -> None:
        with patch.object(ls, "_current_year", return_value=2026):
            result = ls.detect_year_range("past 5 years")
            self.assertEqual(result, {"start_year": 2022, "end_year": 2026})

    def test_chinese_year_range(self) -> None:
        with patch.object(ls, "_current_year", return_value=2026):
            result = ls.detect_year_range("过去五年")
            self.assertEqual(result, {"start_year": 2022, "end_year": 2026})

    def test_chinese_near_years(self) -> None:
        with patch.object(ls, "_current_year", return_value=2026):
            result = ls.detect_year_range("近三年")
            self.assertEqual(result, {"start_year": 2024, "end_year": 2026})

    def test_explicit_range(self) -> None:
        result = ls.detect_year_range("2019-2024")
        self.assertEqual(result, {"start_year": 2019, "end_year": 2024})

    def test_no_range(self) -> None:
        self.assertIsNone(ls.detect_year_range("GPLD1 cardiovascular disease"))


class TestExtractCandidateTerms(unittest.TestCase):
    def test_ascii_terms(self) -> None:
        result = ls.extract_candidate_terms("GPLD1 in cardiovascular disease")
        self.assertIn("GPLD1", result)
        self.assertNotIn("in", result)  # stopword

    def test_cjk_terms(self) -> None:
        result = ls.extract_candidate_terms("检索GPLD1在心血管疾病中的作用")
        self.assertIn("GPLD1", result)
        # CJK extraction captures continuous runs (no dictionary segmentation)
        self.assertIn("检索", result)
        self.assertIn("在心血管疾病中的作用", result)

    def test_mixed_terms(self) -> None:
        result = ls.extract_candidate_terms("过去五年GPLD1在心肌病和心衰中的作用")
        self.assertIn("GPLD1", result)
        # CJK runs are captured as continuous chunks; expand-query handles domain splitting
        self.assertTrue(any("心肌病" in term for term in result))

    def test_no_duplicates(self) -> None:
        result = ls.extract_candidate_terms("GPLD1 GPLD1")
        self.assertEqual(result.count("GPLD1"), 1)


class TestNormalizeISSN(unittest.TestCase):
    def test_eight_digit(self) -> None:
        self.assertEqual(ls.normalize_issn("12345679"), "1234-5679")

    def test_already_dashed(self) -> None:
        self.assertEqual(ls.normalize_issn("1234-5679"), "1234-5679")

    def test_with_x(self) -> None:
        self.assertEqual(ls.normalize_issn("1234567x"), "1234-567X")

    def test_short(self) -> None:
        self.assertEqual(ls.normalize_issn("123"), "123")


class TestParsePubMedXML(unittest.TestCase):
    def setUp(self) -> None:
        xml_path = FIXTURES / "pubmed_sample.xml"
        self.records = ls.parse_pubmed_xml(xml_path.read_text(encoding="utf-8"))

    def test_record_count(self) -> None:
        self.assertEqual(len(self.records), 2)

    def test_first_record_fields(self) -> None:
        rec = self.records[0]
        self.assertEqual(rec["id"], "12345678")
        self.assertIn("GPLD1", rec["title"])
        self.assertEqual(rec["year"], 2023)
        self.assertEqual(rec["doi"], "10.1234/jcr.2023.001")
        self.assertIn("1234-5679", rec["issns"])
        self.assertIn("GPLD1 protein, human", rec["mesh_terms"])
        self.assertIn("Heart Failure", rec["mesh_terms"])

    def test_second_record_review(self) -> None:
        rec = self.records[1]
        self.assertIn("Review", rec["article_types"])


class TestParseArxivXML(unittest.TestCase):
    def setUp(self) -> None:
        xml_path = FIXTURES / "arxiv_sample.xml"
        self.records = ls.parse_arxiv_xml(xml_path.read_text(encoding="utf-8"))

    def test_record_count(self) -> None:
        self.assertEqual(len(self.records), 1)

    def test_record_fields(self) -> None:
        rec = self.records[0]
        self.assertEqual(rec["id"], "2301.01234v1")
        self.assertIn("GPLD1", rec["title"])
        self.assertEqual(rec["year"], 2023)
        self.assertEqual(rec["source"], "arxiv")
        self.assertIn("preprint", rec["article_types"])


class TestNormalizeWosExportRecord(unittest.TestCase):
    def test_tsv_parsing(self) -> None:
        rows = ls.read_delimited_rows(FIXTURES / "wos_sample.tsv")
        self.assertEqual(len(rows), 1)
        record = ls.normalize_wos_export_record(rows[0])
        self.assertIn("GPLD1", record["title"])
        self.assertEqual(record["year"], 2024)
        self.assertEqual(record["doi"], "10.1161/CIRCRES.2024.001")
        self.assertIn("0009-7330", record["issns"])


class TestImportWosExportBatches(unittest.TestCase):
    def test_merges_batches_and_deduplicates_by_ut_then_doi(self) -> None:
        header = "Article Title\tUT (Unique WOS ID)\tDOI\tPublication Year\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "batch-0001.txt"
            second = root / "batch-0002.txt"
            output = root / "wos.json"
            first.write_text(
                header
                + "First paper\tWOS:0001\t10.1000/first\t2024\n"
                + "Second paper\t\t10.1000/second\t2023\n",
                encoding="utf-8",
            )
            second.write_text(
                header
                + "First paper duplicate\tWOS:0001\t10.1000/first\t2024\n"
                + "Second paper duplicate\t\t10.1000/second\t2023\n"
                + "Third paper\tWOS:0003\t10.1000/third\t2022\n",
                encoding="utf-8",
            )
            ls.command_import_wos_export(
                argparse.Namespace(input=[first, second], query="TS=(example)", limit=10, output=output)
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["duplicate_records_skipped"], 2)
        self.assertEqual([record["id"] for record in payload["records"]], ["WOS:0001", "", "WOS:0003"])
        self.assertEqual(len(payload["input_files"]), 2)


class TestDeduplicate(unittest.TestCase):
    def test_doi_dedup(self) -> None:
        records = [
            {"doi": "10.1/test", "title": "Test Paper", "source": "pubmed"},
            {"doi": "10.1/test", "title": "Test Paper", "source": "wos"},
        ]
        result = ls.deduplicate(records)
        self.assertEqual(len(result), 1)

    def test_title_dedup(self) -> None:
        records = [
            {"doi": "", "title": "A Study of GPLD1", "source": "pubmed"},
            {"doi": "", "title": "A Study of GPLD1", "source": "arxiv"},
        ]
        result = ls.deduplicate(records)
        self.assertEqual(len(result), 1)

    def test_different_papers(self) -> None:
        records = [
            {"doi": "10.1/a", "title": "Paper A", "source": "pubmed"},
            {"doi": "10.1/b", "title": "Paper B", "source": "wos"},
        ]
        result = ls.deduplicate(records)
        self.assertEqual(len(result), 2)


class TestScoreRecord(unittest.TestCase):
    def test_title_match(self) -> None:
        record = {"title": "GPLD1 in heart disease", "abstract": "", "mesh_terms": [], "doi": "", "article_types": [], "year": 2023}
        result = ls.score_record(record, ["GPLD1"])
        self.assertIn("title matches 'GPLD1'", result["score_reasons"])
        self.assertEqual(result["score"], 6.0 + 2.0)  # title + recency(5yr)

    def test_abstract_match(self) -> None:
        record = {"title": "Heart disease", "abstract": "GPLD1 expression is elevated", "mesh_terms": [], "doi": "", "article_types": [], "year": 2020}
        result = ls.score_record(record, ["GPLD1"])
        self.assertIn("abstract matches 'GPLD1'", result["score_reasons"])

    def test_mesh_match(self) -> None:
        record = {"title": "Study", "abstract": "Findings", "mesh_terms": ["GPLD1 protein, human"], "doi": "", "article_types": [], "year": 2020}
        result = ls.score_record(record, ["GPLD1"])
        self.assertIn("MeSH matches 'GPLD1'", result["score_reasons"])

    def test_review_bonus(self) -> None:
        record = {"title": "Review", "abstract": "", "mesh_terms": [], "doi": "10.1/r", "article_types": ["Review"], "year": 2023}
        result = ls.score_record(record, ["GPLD1"])
        self.assertIn("review article", result["score_reasons"])

    def test_citation_weight_none(self) -> None:
        record = {"title": "GPLD1 study", "abstract": "", "mesh_terms": [], "doi": "", "article_types": [], "year": 2023,
                  "citation": {"provider": "semantic-scholar", "citation_count": 100, "influential_citation_count": 10}}
        result = ls.score_record(record, ["GPLD1"], citation_weight="none")
        # Citation count should appear in reasons but NOT change score
        self.assertIn("citation count: 100 (not weighted)", result["score_reasons"])
        self.assertEqual(result["score"], 6.0 + 2.0)  # title + recency only

    def test_citation_weight_log(self) -> None:
        record = {"title": "GPLD1 study", "abstract": "", "mesh_terms": [], "doi": "", "article_types": [], "year": 2023,
                  "citation": {"provider": "semantic-scholar", "citation_count": 99, "influential_citation_count": 5}}
        result = ls.score_record(record, ["GPLD1"], citation_weight="log")
        import math
        expected_bonus = min(5.0, math.log10(99 + 1))
        self.assertAlmostEqual(result["score"], 6.0 + 2.0 + round(expected_bonus, 2), places=1)
        self.assertTrue(any("citation count log-scaled" in r for r in result["score_reasons"]))

    def test_citation_weight_bucket_high(self) -> None:
        record = {"title": "GPLD1 study", "abstract": "", "mesh_terms": [], "doi": "", "article_types": [], "year": 2023,
                  "citation": {"provider": "semantic-scholar", "citation_count": 100, "influential_citation_count": 15}}
        result = ls.score_record(record, ["GPLD1"], citation_weight="bucket")
        # influential >= 10 → +3, citations >= 50 → +2
        self.assertEqual(result["score"], 6.0 + 2.0 + 3.0 + 2.0)

    def test_citation_weight_bucket_medium(self) -> None:
        record = {"title": "GPLD1 study", "abstract": "", "mesh_terms": [], "doi": "", "article_types": [], "year": 2023,
                  "citation": {"provider": "semantic-scholar", "citation_count": 30, "influential_citation_count": 3}}
        result = ls.score_record(record, ["GPLD1"], citation_weight="bucket")
        # citations >= 10 → +1, no influential bonus
        self.assertEqual(result["score"], 6.0 + 2.0 + 1.0)

    def test_citation_weight_no_data(self) -> None:
        record = {"title": "GPLD1 study", "abstract": "", "mesh_terms": [], "doi": "", "article_types": [], "year": 2023}
        result = ls.score_record(record, ["GPLD1"], citation_weight="log")
        # Should not crash; should note unavailable
        self.assertTrue(any("unavailable" in r for r in result["score_reasons"]))


class TestMetricMatches(unittest.TestCase):
    def test_load_chinese_jcr_2025_columns(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
            tmp.write("全称,简称,Index类型,主要学科,影响因子,Q分区,ISSN,Rank\n")
            tmp.write("LANCET,LANCET,SCIE,\"MEDICINE, GENERAL & INTERNAL\",109.0,Q1,0140-6736,3\n")
            path = tmp.name
        try:
            metrics = ls.load_journal_metrics(path)
            self.assertEqual(metrics[0]["journal"], "LANCET")
            self.assertEqual(metrics[0]["jcr_zone"], "Q1")
            self.assertEqual(metrics[0]["impact_factor"], "109.0")
            self.assertTrue(ls.metric_matches(metrics[0], None, ["Q1"], 100.0, None))
            self.assertFalse(ls.metric_matches(metrics[0], None, ["Q2"], 100.0, None))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cas_zone_match(self) -> None:
        metric = {"cas_zone": "1区", "jcr_zone": "Q1", "impact_factor": "15.0"}
        self.assertTrue(ls.metric_matches(metric, ["1区"], None, None, None))

    def test_cas_zone_mismatch(self) -> None:
        metric = {"cas_zone": "2区", "jcr_zone": "Q1", "impact_factor": "5.0"}
        self.assertFalse(ls.metric_matches(metric, ["1区"], None, None, None))

    def test_if_range(self) -> None:
        metric = {"cas_zone": "", "jcr_zone": "", "impact_factor": "10.0"}
        self.assertTrue(ls.metric_matches(metric, None, None, 5.0, 15.0))
        self.assertFalse(ls.metric_matches(metric, None, None, 12.0, None))

    def test_no_if_excluded(self) -> None:
        metric = {"cas_zone": "", "jcr_zone": "", "impact_factor": ""}
        self.assertFalse(ls.metric_matches(metric, None, None, 1.0, None))


class TestCompactSpace(unittest.TestCase):
    def test_collapse(self) -> None:
        self.assertEqual(ls.compact_space("  hello   world  "), "hello world")

    def test_empty(self) -> None:
        self.assertEqual(ls.compact_space(""), "")

    def test_none(self) -> None:
        self.assertEqual(ls.compact_space(None), "")


class TestMergeRankEndToEnd(unittest.TestCase):
    """End-to-end merge-rank test using fixture JSON files (no HTTP)."""

    def test_merge_rank_from_fixtures(self) -> None:
        ranked_data = ls.load_json(FIXTURES / "ranked_sample.json")
        records = ranked_data["records"]
        terms = ranked_data["ranking_terms"]
        # Re-score and re-rank
        scored = [ls.score_record(dict(r), terms) for r in records]
        scored.sort(key=lambda r: r["score"], reverse=True)
        # Top record should have GPLD1 in title
        self.assertIn("GPLD1", scored[0]["title"])


class TestRenderReport(unittest.TestCase):
    """Snapshot test: report contains expected section headers."""

    def test_report_sections(self) -> None:
        ranked_data = ls.load_json(FIXTURES / "ranked_sample.json")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
            tmp_path = tmp.name
        try:
            args = type("Args", (), {
                "ranked_json": str(FIXTURES / "ranked_sample.json"),
                "question": "GPLD1 in cardiovascular disease",
                "top_n": 5,
                "output": tmp_path,
            })()
            ls.command_render_report(args)
            text = Path(tmp_path).read_text(encoding="utf-8")
            self.assertIn("检索问题", text)
            self.assertIn("检索策略", text)
            self.assertIn("证据概览", text)
            self.assertIn("排序文献表", text)
            self.assertIn("科学问题回答", text)
            self.assertIn("局限性", text)
            self.assertIn("参考文献", text)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestWriteCSVExtraFields(unittest.TestCase):
    """Test that write_csv supports extra_fields parameter."""

    def test_extra_fields(self) -> None:
        records = [
            {"rank": 1, "score": 10.0, "source": "pubmed", "year": 2023,
             "title": "Test", "journal": "J", "issns": [], "doi": "10.1/t",
             "url": "https://example.com", "score_reasons": ["test"],
             "custom_field": "hello"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
            tmp_path = tmp.name
        try:
            ls.write_csv(
                tmp_path, records,
                extra_fields=[("custom_field", lambda r: r.get("custom_field", ""))],
            )
            text = Path(tmp_path).read_text(encoding="utf-8")
            self.assertIn("custom_field", text)
            self.assertIn("hello", text)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestS2PaperId(unittest.TestCase):
    def test_doi_record(self) -> None:
        record = {"doi": "10.1234/test", "source": "pubmed", "id": "12345"}
        self.assertEqual(ls.s2_paper_id(record), "DOI:10.1234/test")

    def test_arxiv_record(self) -> None:
        record = {"doi": "", "source": "arxiv", "id": "2301.01234v1"}
        self.assertEqual(ls.s2_paper_id(record), "ARXIV:2301.01234v1")

    def test_pubmed_no_doi(self) -> None:
        record = {"doi": "", "source": "pubmed", "id": "99999"}
        self.assertEqual(ls.s2_paper_id(record), "PMID:99999")

    def test_wos_no_id(self) -> None:
        record = {"doi": "", "source": "wos", "id": ""}
        self.assertIsNone(ls.s2_paper_id(record))


class TestEnrichCitationsEndToEnd(unittest.TestCase):
    """Test enrich-citations with mocked API responses (no real HTTP)."""

    def test_enrich_with_s2_mock(self) -> None:
        ranked_data = ls.load_json(FIXTURES / "ranked_sample.json")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(ranked_data, tmp)
            input_path = tmp.name
        output_path = input_path + ".out.json"
        try:
            mock_s2_response = [
                {"citationCount": 50, "influentialCitationCount": 10, "referenceCount": 30,
                 "publicationTypes": ["JournalArticle"], "year": 2023,
                 "externalIds": {"DOI": "10.1234/jcr.2023.001"}},
                {"citationCount": 120, "influentialCitationCount": 25, "referenceCount": 45,
                 "publicationTypes": ["Review"], "year": 2022,
                 "externalIds": {"DOI": "10.1038/nm.2022.050"}},
                {"citationCount": 5, "influentialCitationCount": 0, "referenceCount": 15,
                 "publicationTypes": ["Preprint"], "year": 2023,
                 "externalIds": {"DOI": "10.1101/2023.01.01234"}},
            ]
            with patch.object(ls, "fetch_s2_batch", return_value={
                "DOI:10.1234/jcr.2023.001": mock_s2_response[0],
                "DOI:10.1038/nm.2022.050": mock_s2_response[1],
                "DOI:10.1101/2023.01.01234": mock_s2_response[2],
            }):
                args = type("Args", (), {
                    "ranked_json": input_path,
                    "output": output_path,
                    "provider": "semantic-scholar",
                    "s2_api_key": None,
                    "cache": None,
                    "csv": None,
                })()
                ls.command_enrich_citations(args)

            result = ls.load_json(output_path)
            records = result["records"]
            for rec in records:
                self.assertIsNotNone(rec.get("citation"))
                self.assertIn("citation_count", rec["citation"])
            self.assertEqual(result["citation_enrichment"]["s2_hits"], 3)
        finally:
            Path(input_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)


class TestExtractConclusions(unittest.TestCase):
    """Test extract-conclusions scaffold and apply modes."""

    def test_scaffold_mode(self) -> None:
        ranked_data = ls.load_json(FIXTURES / "ranked_sample.json")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(ranked_data, tmp)
            input_path = tmp.name
        output_path = input_path + ".scaffold.json"
        try:
            args = type("Args", (), {
                "ranked_json": input_path,
                "top_n": 5,
                "mode": "scaffold",
                "scaffold": None,
                "output": output_path,
                "csv": None,
            })()
            ls.command_extract_conclusions(args)
            scaffold = ls.load_json(output_path)
            self.assertEqual(scaffold["task"], "extract core conclusions")
            self.assertEqual(len(scaffold["items"]), 3)
            # All items should have null conclusion fields
            for item in scaffold["items"]:
                self.assertIsNone(item["core_conclusion"])
                self.assertIn("abstract", item)
        finally:
            Path(input_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)

    def test_apply_mode(self) -> None:
        ranked_data = ls.load_json(FIXTURES / "ranked_sample.json")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(ranked_data, tmp)
            input_path = tmp.name
        output_path = input_path + ".applied.json"
        # Create a filled scaffold
        scaffold_data = {
            "task": "extract core conclusions",
            "items": [
                {"rank": 1, "id": "12345678", "doi": "10.1234/jcr.2023.001",
                 "title": "GPLD1 regulates cardiac function",
                 "abstract": "...",
                 "core_conclusion": "GPLD1 is elevated in heart failure",
                 "method": "cohort", "confidence": "high"},
                {"rank": 2, "id": "2301.01234v1", "doi": "10.1101/2023.01.01234",
                 "title": "GPLD1 as a biomarker",
                 "abstract": "...",
                 "core_conclusion": "GPLD1 correlates with adverse cardiac events",
                 "method": "computational", "confidence": "medium"},
            ],
        }
        scaffold_path = input_path + ".filled.json"
        write_scaffold = lambda: Path(scaffold_path).write_text(json.dumps(scaffold_data), encoding="utf-8")
        try:
            write_scaffold()
            args = type("Args", (), {
                "ranked_json": input_path,
                "top_n": 5,
                "mode": "apply",
                "scaffold": scaffold_path,
                "output": output_path,
                "csv": None,
            })()
            ls.command_extract_conclusions(args)
            result = ls.load_json(output_path)
            records = result["records"]
            # First two should have conclusions
            rec1 = next(r for r in records if r.get("id") == "12345678")
            self.assertEqual(rec1["core_conclusion"], "GPLD1 is elevated in heart failure")
            self.assertEqual(rec1["method"], "cohort")
            self.assertEqual(rec1["confidence"], "high")
            self.assertEqual(rec1["conclusion_source"], "abstract-level")
            # Third should have no conclusion (not in scaffold)
            rec3 = next(r for r in records if r.get("id") == "87654321")
            self.assertIsNone(rec3.get("core_conclusion"))
        finally:
            Path(input_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)
            Path(scaffold_path).unlink(missing_ok=True)


class TestExpandQuery(unittest.TestCase):
    """Test expand-query scaffold and apply modes."""

    def test_scaffold_mode(self) -> None:
        plan = {
            "question": "检索过去五年GPLD1在心血管疾病中的作用",
            "core_terms": ["GPLD1"],
            "expanded_terms": [],
            "exclude_terms": [],
            "constraints": {"year_range": {"start_year": 2022, "end_year": 2026}},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(plan, tmp)
            plan_path = tmp.name
        output_path = plan_path + ".scaffold.json"
        try:
            args = type("Args", (), {
                "query_plan": plan_path,
                "mode": "scaffold",
                "scaffold": None,
                "output": output_path,
            })()
            ls.command_expand_query(args)
            scaffold = ls.load_json(output_path)
            self.assertEqual(scaffold["task"], "expand query terms")
            self.assertIn("GPLD1", scaffold["current_core_terms"])
            self.assertIn("expansion", scaffold)
            self.assertIn("instructions", scaffold)
        finally:
            Path(plan_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)

    def test_apply_mode(self) -> None:
        plan = {
            "question": "GPLD1 in cardiovascular disease",
            "core_terms": ["GPLD1"],
            "expanded_terms": [],
            "exclude_terms": [],
            "mesh_terms": [],
            "constraints": {"year_range": {"start_year": 2022, "end_year": 2026}},
            "pubmed_query": "(GPLD1)",
            "arxiv_query": "GPLD1",
            "wos_query": "TS=((GPLD1))",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(plan, tmp)
            plan_path = tmp.name
        output_path = plan_path + ".expanded.json"
        # Create filled scaffold
        scaffold_data = {
            "task": "expand query terms",
            "expansion": {
                "synonyms": ["Gpld1", "phosphatidylinositol-glycan-specific phospholipase D"],
                "mesh_terms": ["GPLD1 protein, human", "Cardiovascular Diseases"],
                "related_diseases": ["heart failure", "myocardial infarction", "cardiomyopathy"],
                "exclusions": ["mouse"],
                "organism": "human",
                "study_types": ["clinical trial", "cohort"],
            },
        }
        scaffold_path = plan_path + ".filled.json"
        try:
            Path(scaffold_path).write_text(json.dumps(scaffold_data), encoding="utf-8")
            args = type("Args", (), {
                "query_plan": plan_path,
                "mode": "apply",
                "scaffold": scaffold_path,
                "output": output_path,
            })()
            ls.command_expand_query(args)
            result = ls.load_json(output_path)
            # Check expanded terms
            self.assertIn("GPLD1", result["expanded_terms"])
            self.assertIn("heart failure", result["expanded_terms"])
            self.assertIn("cardiomyopathy", result["expanded_terms"])
            # Check exclusions
            self.assertIn("mouse", result["exclude_terms"])
            # Check MeSH terms
            self.assertIn("Cardiovascular Diseases", result["mesh_terms"])
            # Check audit fields
            self.assertEqual(result["expansion_source"], "llm-assisted")
            self.assertIn("expansion_applied_at", result)
            # Check queries were regenerated
            self.assertIn("phosphatidylinositol-glycan-specific phospholipase D", result["pubmed_query"])
            self.assertIn("mouse", result["pubmed_query"])  # should appear as NOT
            self.assertIn("human", result["pubmed_query"])  # organism constraint
        finally:
            Path(plan_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)
            Path(scaffold_path).unlink(missing_ok=True)


class TestBuildPubMedQuery(unittest.TestCase):
    def test_basic_terms(self) -> None:
        result = ls._build_pubmed_query(["GPLD1", "heart failure"])
        self.assertEqual(result, "(GPLD1) AND (heart failure)")

    def test_with_mesh(self) -> None:
        result = ls._build_pubmed_query(["GPLD1"], mesh_terms=["Cardiovascular Diseases"])
        self.assertIn('"Cardiovascular Diseases"[MeSH Terms]', result)

    def test_with_organism(self) -> None:
        result = ls._build_pubmed_query(["GPLD1"], organism="human")
        self.assertIn('"human"[Organism]', result)

    def test_with_year_range(self) -> None:
        result = ls._build_pubmed_query(["GPLD1"], constraints={"year_range": {"start_year": 2022, "end_year": 2026}})
        self.assertIn('"2022:2026"[dp]', result)

    def test_with_exclusions(self) -> None:
        result = ls._build_pubmed_query(["GPLD1"], exclude_terms=["mouse"])
        self.assertIn('NOT "mouse"', result)


class TestReportWithConclusions(unittest.TestCase):
    """Test that report includes conclusion column when available."""

    def test_report_with_conclusions(self) -> None:
        ranked_data = ls.load_json(FIXTURES / "ranked_sample.json")
        # Add conclusions to records
        for rec in ranked_data["records"]:
            rec["core_conclusion"] = "Test conclusion"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(ranked_data, tmp)
            input_path = tmp.name
        output_path = input_path + ".md"
        try:
            args = type("Args", (), {
                "ranked_json": input_path,
                "question": "GPLD1 cardiovascular",
                "top_n": 5,
                "output": output_path,
            })()
            ls.command_render_report(args)
            text = Path(output_path).read_text(encoding="utf-8")
            self.assertIn("核心结论", text)
            self.assertIn("Test conclusion", text)
        finally:
            Path(input_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)


class TestWorkflowPlanning(unittest.TestCase):
    def test_review_runs_pubmed_only_and_enriches_default_journal_metrics(self) -> None:
        record = {
            "source": "pubmed",
            "id": "1",
            "title": "GPLD1 evidence",
            "abstract": "Evidence abstract.",
            "authors": ["A Author"],
            "year": 2025,
            "doi": "10.1000/test",
            "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
            "issns": [],
            "article_types": [],
            "mesh_terms": [],
        }

        def fake_pubmed(args: object) -> None:
            ls.write_json(args.output, {"source": "pubmed", "count": 1, "records": [record]})

        with tempfile.TemporaryDirectory() as output_dir, patch.object(
            ls, "command_search_pubmed", side_effect=fake_pubmed
        ), patch.object(ls, "command_search_arxiv") as arxiv, patch.object(
            ls, "command_enrich_citations"
        ) as citations, patch.object(ls, "command_enrich_journal_metrics") as metrics:
            args = type("Args", (), {
                "question": "GPLD1 cardiovascular disease",
                "pubmed_query": "GPLD1 AND cardiovascular",
                "limit": 20,
                "top_n": 10,
                "output": output_dir,
                "api_key": None,
                "arxiv": False,
                "wos_export": None,
                "citation_provider": None,
                "s2_api_key": None,
                "citation_cache": None,
                "journal_metrics": None,
                "cas_zones": None,
                "jcr_zones": None,
                "if_min": None,
                "if_max": None,
                "filter_journals": False,
                "easyscholar": False,
                "easyscholar_api_key": None,
                "easyscholar_cache": None,
                "easyscholar_min_interval": 1.0,
            })()
            ls.command_review(args)
            self.assertEqual(
                {path.name for path in Path(output_dir).iterdir()},
                {"search_plan.json", "ranked_all.json", "ranked_all.csv", "report.md"},
            )
            plan = ls.load_json(Path(output_dir) / "search_plan.json")
            self.assertEqual(plan["pubmed_query"], "GPLD1 AND cardiovascular")
            self.assertEqual(plan["source_routing"]["enabled"], ["pubmed"])
            self.assertEqual(plan["limits"], {"per_source_retrieval": 20, "ranked_top_n": 10})
            source_summary = ls.load_json(Path(output_dir) / "ranked_all.json")["sources"][0]
            self.assertNotIn("path", source_summary)
            self.assertFalse(source_summary["intermediate_retained"])
            arxiv.assert_not_called()
            citations.assert_not_called()
            metrics.assert_called_once()
            self.assertTrue(plan["conditional_enrichment"]["journal_metrics_enabled"])
            self.assertEqual(plan["conditional_enrichment"]["journal_metrics_source"], "bundled-jcr-2025")

    def test_review_enables_optional_sources_and_enrichments_only_when_requested(self) -> None:
        def fake_source(source: str):
            def write(args: object) -> None:
                ls.write_json(args.output, {"source": source, "count": 0, "records": []})
            return write

        def pass_through(args: object) -> None:
            if args.ranked_json != args.output:
                ls.write_json(args.output, ls.load_json(args.ranked_json))

        with tempfile.TemporaryDirectory() as output_dir, tempfile.NamedTemporaryFile(
            suffix=".csv"
        ) as wos, tempfile.NamedTemporaryFile(suffix=".csv") as metrics_file, patch.object(
            ls, "command_search_pubmed", side_effect=fake_source("pubmed")
        ), patch.object(ls, "command_search_arxiv", side_effect=fake_source("arxiv")) as arxiv, patch.object(
            ls, "command_import_wos_export", side_effect=fake_source("wos")
        ) as wos_import, patch.object(
            ls, "command_enrich_citations", side_effect=pass_through
        ) as citations, patch.object(
            ls, "command_enrich_journal_metrics", side_effect=pass_through
        ) as journal_metrics:
            args = type("Args", (), {
                "question": "AI biology",
                "pubmed_query": None,
                "limit": 5,
                "top_n": 5,
                "output": output_dir,
                "api_key": None,
                "arxiv": True,
                "wos_export": wos.name,
                "citation_provider": "crossref",
                "s2_api_key": None,
                "citation_cache": None,
                "journal_metrics": metrics_file.name,
                "cas_zones": None,
                "jcr_zones": ["Q1"],
                "if_min": None,
                "if_max": None,
                "filter_journals": True,
                "easyscholar": False,
                "easyscholar_api_key": None,
                "easyscholar_cache": None,
                "easyscholar_min_interval": 1.0,
            })()
            ls.command_review(args)
            arxiv.assert_called_once()
            wos_import.assert_called_once()
            citations.assert_called_once()
            journal_metrics.assert_called_once()
            plan = ls.load_json(Path(output_dir) / "search_plan.json")
            self.assertEqual(
                plan["source_routing"]["enabled"],
                ["pubmed", "arxiv", "web-of-science-official-export"],
            )
            self.assertEqual(plan["conditional_enrichment"]["citation_provider"], "crossref")
            self.assertTrue(plan["journal_filters"]["filter_to_matches"])

    def test_review_rejects_journal_filters_when_default_metrics_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            output_dir = Path(parent) / "review"
            args = type("Args", (), {
                "question": "GPLD1",
                "pubmed_query": "GPLD1",
                "limit": 5,
                "top_n": 5,
                "output": str(output_dir),
                "api_key": None,
                "arxiv": False,
                "wos_export": None,
                "citation_provider": None,
                "s2_api_key": None,
                "citation_cache": None,
                "journal_metrics": None,
                "no_journal_metrics": True,
                "cas_zones": None,
                "jcr_zones": ["Q1"],
                "if_min": None,
                "if_max": None,
                "filter_journals": False,
                "easyscholar": False,
                "easyscholar_api_key": None,
                "easyscholar_cache": None,
                "easyscholar_min_interval": 1.0,
            })()
            with self.assertRaises(ValueError):
                ls.command_review(args)
            self.assertFalse(output_dir.exists())

    def test_review_runs_easyscholar_when_requested(self) -> None:
        record = {
            "source": "pubmed",
            "id": "1",
            "title": "GPLD1 evidence",
            "abstract": "Evidence abstract.",
            "authors": ["A Author"],
            "year": 2025,
            "doi": "10.1000/test",
            "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
            "issns": [],
            "article_types": [],
            "mesh_terms": [],
        }

        def fake_pubmed(args: object) -> None:
            ls.write_json(args.output, {"source": "pubmed", "count": 1, "records": [record]})

        with tempfile.TemporaryDirectory() as output_dir, patch.object(
            ls, "command_search_pubmed", side_effect=fake_pubmed
        ), patch.object(ls, "command_enrich_journal_metrics") as metrics, patch.object(
            ls, "command_enrich_easyscholar"
        ) as easyscholar:
            args = type("Args", (), {
                "question": "GPLD1 cardiovascular disease",
                "pubmed_query": "GPLD1 AND cardiovascular",
                "limit": 20,
                "top_n": 10,
                "output": output_dir,
                "api_key": None,
                "arxiv": False,
                "wos_export": None,
                "citation_provider": None,
                "s2_api_key": None,
                "citation_cache": None,
                "journal_metrics": None,
                "cas_zones": None,
                "jcr_zones": None,
                "if_min": None,
                "if_max": None,
                "filter_journals": False,
                "easyscholar": True,
                "easyscholar_api_key": "test-key",
                "easyscholar_cache": None,
                "easyscholar_min_interval": 1.0,
            })()
            ls.command_review(args)
            metrics.assert_called_once()
            easyscholar.assert_called_once()
            plan = ls.load_json(Path(output_dir) / "search_plan.json")
            self.assertTrue(plan["conditional_enrichment"]["easyscholar_enabled"])
            self.assertTrue(plan["conditional_enrichment"]["easyscholar_api_key_configured"])

    def test_review_parser_defaults_to_bundled_metrics_and_allows_opt_out(self) -> None:
        parser = ls.build_parser()
        args = parser.parse_args([
            "review", "--question", "SNX", "--limit", "5", "--top-n", "5", "--output", "out",
        ])
        self.assertIsNone(args.journal_metrics)
        self.assertFalse(args.no_journal_metrics)
        self.assertFalse(args.easyscholar)
        self.assertIsNone(args.easyscholar_api_key)
        self.assertIsNone(args.easyscholar_cache)
        self.assertEqual(args.easyscholar_min_interval, 1.0)
        self.assertEqual(str(ls.DEFAULT_JOURNAL_METRICS), str(ls.DEFAULT_JOURNAL_METRICS))

    def test_workflow_plan_pubmed_arxiv_uses_script_steps(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            output_path = tmp.name
        try:
            args = type("Args", (), {
                "question": "GPLD1 in cardiovascular disease",
                "targets": "PubMed arXiv",
                "limit": 25,
                "top_n": 10,
                "journal_metrics": None,
                "cas_zones": None,
                "jcr_zones": None,
                "if_min": None,
                "if_max": None,
                "citation_weight": "none",
                "output": output_path,
            })()
            ls.command_workflow_plan(args)
            result = ls.load_json(output_path)
            step_ids = [step["id"] for step in result["steps"]]
            self.assertIn("search_pubmed", step_ids)
            self.assertIn("search_arxiv", step_ids)
            self.assertIn("merge_rank", step_ids)
            output_dir = Path(output_path).parent
            arxiv_step = next(step for step in result["steps"] if step["id"] == "search_arxiv")
            self.assertEqual(arxiv_step["writes"], [str(output_dir / "arxiv_raw.json")])
            self.assertIn(str(output_dir / "arxiv_raw.json"), result["file_policy"]["allowed_default_outputs"])
            self.assertIn("Do not create subagents for XML parsing", result["subagent_policy"])
            self.assertTrue(all(step.get("owner") != "subagent" for step in result["steps"]))
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_workflow_plan_enriches_ranked_json_before_inspection_and_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "workflow.json"
            args = ls.build_parser().parse_args([
                "workflow-plan",
                "--question", "GPLD1 cardiovascular disease",
                "--targets", "PubMed arXiv",
                "--limit", "10",
                "--top-n", "5",
                "--easyscholar",
                "--easyscholar-api-key", "must-not-enter-plan",
                "--easyscholar-cache", "easyscholar-cache.json",
                "--easyscholar-min-interval", "2.5",
                "--output", str(output_path),
            ])
            ls.command_workflow_plan(args)
            result = ls.load_json(output_path)
            step_ids = [step["id"] for step in result["steps"]]
            self.assertLess(step_ids.index("merge_rank"), step_ids.index("enrich_easyscholar"))
            self.assertLess(step_ids.index("enrich_easyscholar"), step_ids.index("inspect_ranked_evidence"))
            self.assertLess(step_ids.index("inspect_ranked_evidence"), step_ids.index("render_report"))
            enrich = next(step for step in result["steps"] if step["id"] == "enrich_easyscholar")
            ranked_json = str(Path(tmpdir) / "ranked_all.json")
            self.assertEqual(enrich["reads"], [ranked_json])
            self.assertEqual(enrich["writes"], [ranked_json])
            self.assertIn("easyscholar-cache.json", enrich["argv"])
            self.assertIn("2.5", enrich["argv"])
            serialized = json.dumps(result)
            self.assertNotIn("must-not-enter-plan", serialized)
            self.assertNotIn("--easyscholar-api-key", serialized)

    def test_pubmed_review_enriches_before_filter_and_filter_preserves_easyscholar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "pubmed-workflow.json"
            args = ls.build_parser().parse_args([
                "pubmed-review-workflow",
                "--question", "GPLD1 cardiovascular disease",
                "--core-query", "GPLD1 AND cardiovascular",
                "--limit", "10",
                "--top-n", "5",
                "--journal-metrics", "journal_metrics.csv",
                "--jcr-zones", "Q1",
                "--easyscholar",
                "--easyscholar-api-key", "must-not-enter-plan",
                "--easyscholar-cache", "easyscholar-cache.json",
                "--easyscholar-min-interval", "3.0",
                "--output", str(output_path),
            ])
            ls.command_pubmed_review_workflow(args)
            result = ls.load_json(output_path)
            step_ids = [step["id"] for step in result["steps"]]
            self.assertLess(step_ids.index("merge_rank"), step_ids.index("enrich_easyscholar"))
            self.assertLess(step_ids.index("enrich_easyscholar"), step_ids.index("local_journal_quality_filter"))
            self.assertLess(step_ids.index("local_journal_quality_filter"), step_ids.index("inspect_ranked_evidence"))
            local_filter = next(step for step in result["steps"] if step["id"] == "local_journal_quality_filter")
            ranked_json = str(Path(tmpdir) / "ranked_all.json")
            ranked_arg_index = local_filter["argv"].index("--ranked-json")
            self.assertEqual(local_filter["argv"][ranked_arg_index + 1], ranked_json)
            self.assertNotIn("must-not-enter-plan", json.dumps(result))

            ranked_path = Path(tmpdir) / "already-enriched.json"
            metrics_path = Path(tmpdir) / "metrics.csv"
            filtered_path = Path(tmpdir) / "filtered.json"
            ls.write_json(ranked_path, {"records": [{
                "title": "Matched",
                "issns": ["1234-5678"],
                "score": 1.0,
                "score_reasons": [],
                "easyscholar": {"official_rank": {"all": {"sci": "Q1"}}},
            }]})
            metrics_path.write_text(
                "Journal,Impact Factor,JCR-zone,ISSN,Rank\nGood Journal,7.2,Q1,1234-5678,1\n",
                encoding="utf-8",
            )
            filter_args = type("Args", (), {
                "ranked_json": str(ranked_path),
                "journal_metrics": str(metrics_path),
                "cas_zones": None,
                "jcr_zones": ["Q1"],
                "if_min": None,
                "if_max": None,
                "filter_to_matches": True,
                "output": str(filtered_path),
                "csv": None,
            })()
            ls.command_enrich_journal_metrics(filter_args)
            self.assertIn("easyscholar", ls.load_json(filtered_path)["records"][0])

    def test_workflow_plan_forwards_easyscholar_options_to_pubmed_subplan_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "workflow.json"
            parser = ls.build_parser()
            args = parser.parse_args([
                "workflow-plan",
                "--question", "GPLD1",
                "--targets", "PubMed",
                "--limit", "10",
                "--journal-metrics", "journal_metrics.csv",
                "--easyscholar",
                "--easyscholar-api-key", "must-not-enter-plan",
                "--easyscholar-cache", "easyscholar-cache.json",
                "--easyscholar-min-interval", "4.5",
                "--output", str(output_path),
            ])
            ls.command_workflow_plan(args)
            result = ls.load_json(output_path)
            subplan = next(step for step in result["steps"] if step["id"] == "pubmed_review_subplan")
            self.assertIn("--easyscholar", subplan["argv"])
            self.assertIn("--easyscholar-cache", subplan["argv"])
            self.assertIn("easyscholar-cache.json", subplan["argv"])
            self.assertIn("--easyscholar-min-interval", subplan["argv"])
            self.assertIn("4.5", subplan["argv"])
            serialized = json.dumps(result)
            self.assertNotIn("must-not-enter-plan", serialized)
            self.assertNotIn("--easyscholar-api-key", serialized)
            pubmed_args = parser.parse_args([
                "pubmed-review-workflow",
                "--question", "GPLD1",
                "--core-query", "GPLD1",
                "--limit", "10",
                "--output", str(Path(tmpdir) / "pubmed.json"),
            ])
            self.assertEqual(pubmed_args.easyscholar_min_interval, 1.0)

    def test_workflow_plan_rejects_quality_filters_without_metrics(self) -> None:
        args = type("Args", (), {
            "question": "GPLD1",
            "targets": "PubMed",
            "limit": 25,
            "top_n": 10,
            "journal_metrics": None,
            "cas_zones": ["1区"],
            "jcr_zones": None,
            "if_min": None,
            "if_max": None,
            "citation_weight": "none",
            "output": "unused.json",
        })()
        with self.assertRaises(ValueError):
            ls.command_workflow_plan(args)

    def test_pubmed_review_workflow_with_journal_filter(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            output_path = tmp.name
        try:
            args = type("Args", (), {
                "question": "GPLD1 cardiovascular",
                "core_query": "(GPLD1) AND (cardiovascular disease)",
                "limit": 50,
                "top_n": 20,
                "journal_metrics": "journal_metrics.csv",
                "cas_zones": ["1区", "2区"],
                "jcr_zones": ["Q1"],
                "if_min": 5.0,
                "if_max": None,
                "citation_weight": "none",
                "output": output_path,
            })()
            ls.command_pubmed_review_workflow(args)
            result = ls.load_json(output_path)
            step_ids = [step["id"] for step in result["steps"]]
            self.assertNotIn("journal_filter_audit", step_ids)
            self.assertNotIn("review_journal_filter", step_ids)
            self.assertIn("local_journal_quality_filter", step_ids)
            self.assertIn("finalize_report_in_place", step_ids)
            self.assertNotIn("compose_second_pass_query", step_ids)
            self.assertNotIn("pubmed_second_pass_search", step_ids)
            create_plan = next(step for step in result["steps"] if step["id"] == "create_query_plan")
            core_search = next(step for step in result["steps"] if step["id"] == "pubmed_core_search")
            merge_rank = next(step for step in result["steps"] if step["id"] == "merge_rank")
            local_filter = next(step for step in result["steps"] if step["id"] == "local_journal_quality_filter")
            output_dir = Path(output_path).parent
            self.assertEqual(create_plan["writes"], [str(output_dir / "search_plan.json")])
            self.assertEqual(core_search["writes"], [str(output_dir / "pubmed_raw.json")])
            self.assertEqual(merge_rank["writes"], [str(output_dir / "ranked_all.json"), str(output_dir / "ranked_all.csv")])
            self.assertEqual(local_filter["writes"], [str(output_dir / "filtered_q1_if_gt5.json"), str(output_dir / "filtered_q1_if_gt5.csv")])
            self.assertIn("--filter-to-matches", local_filter["argv"])
            self.assertIn("--jcr-zones", local_filter["argv"])
            self.assertIn("--if-min", local_filter["argv"])
            self.assertTrue(result["journal_quality_filter_enabled"])
            render_report = next(step for step in result["steps"] if step["id"] == "render_report")
            finalize_report = next(step for step in result["steps"] if step["id"] == "finalize_report_in_place")
            self.assertEqual(render_report["writes"], [str(output_dir / "report.md")])
            self.assertIn("report.md is the only default Markdown report", " ".join(render_report["notes"]))
            self.assertIn(str(output_dir / "report.md"), finalize_report["requires"])
            self.assertIn("canonical Markdown deliverable is report.md", result["agent_policy"])
            self.assertIn(str(output_dir / "filtered_q1_if_gt5.json"), result["file_policy"]["allowed_default_outputs"])
            forbidden = " ".join(result["file_policy"]["forbidden_default_outputs"])
            self.assertIn("filter_q1_if.py", forbidden)
            self.assertIn("*_metrics.json", forbidden)
            self.assertIn("<target>_*_records.json", forbidden)
            self.assertIn("ad hoc helper scripts", result["file_policy"]["policy"])
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_workflow_plan_with_journal_filter_uses_pubmed_review_workflow_name(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            output_path = tmp.name
        try:
            args = type("Args", (), {
                "question": "GPLD1",
                "targets": "PubMed",
                "limit": 25,
                "top_n": 10,
                "journal_metrics": "journal_metrics.csv",
                "cas_zones": None,
                "jcr_zones": ["Q1"],
                "if_min": 5.0,
                "if_max": None,
                "citation_weight": "none",
                "output": output_path,
            })()
            ls.command_workflow_plan(args)
            result = ls.load_json(output_path)
            output_dir = Path(output_path).parent
            subplan = next(step for step in result["steps"] if step["id"] == "pubmed_review_subplan")
            self.assertEqual(subplan["writes"], [str(output_dir / "pubmed_review_workflow.json")])
            self.assertIn(str(output_dir / "pubmed_review_workflow.json"), result["file_policy"]["allowed_default_outputs"])
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_enrich_journal_metrics_can_filter_to_quality_matches(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as ranked:
            json.dump(
                {
                    "records": [
                        {"title": "Q1 match", "issns": ["1234-5678"], "score": 2.0, "score_reasons": []},
                        {"title": "Low IF", "issns": ["2222-2222"], "score": 3.0, "score_reasons": []},
                        {"title": "No metrics", "issns": ["9999-9999"], "score": 4.0, "score_reasons": []},
                    ]
                },
                ranked,
            )
            ranked_path = ranked.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as metrics:
            metrics.write("Journal,Impact Factor,JCR-zone,ISSN,Rank\n")
            metrics.write("Good Journal,7.2,Q1,1234-5678,1\n")
            metrics.write("Low Journal,2.1,Q1,2222-2222,2\n")
            metrics_path = metrics.name
        output_path = ranked_path + ".enriched.json"
        try:
            args = type("Args", (), {
                "ranked_json": ranked_path,
                "journal_metrics": metrics_path,
                "cas_zones": None,
                "jcr_zones": ["Q1"],
                "if_min": 5.0,
                "if_max": None,
                "filter_to_matches": True,
                "output": output_path,
                "csv": None,
            })()
            ls.command_enrich_journal_metrics(args)
            result = ls.load_json(output_path)
            self.assertEqual([record["title"] for record in result["records"]], ["Q1 match"])
            self.assertEqual(result["records"][0]["journal_metrics"]["impact_factor"], "7.2")
            self.assertTrue(result["journal_metrics_filter"]["filter_to_matches"])
            self.assertEqual(result["journal_metrics_filter"]["matched_metric_journals"], 1)
        finally:
            Path(ranked_path).unlink(missing_ok=True)
            Path(metrics_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)

    def test_compose_pubmed_query_falls_back_to_issn_query(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump({"pubmed_combined_query": "", "pubmed_issn_query": '("1234-5678"[ISSN])'}, tmp)
            filter_path = tmp.name
        output_path = filter_path + ".query.json"
        try:
            args = type("Args", (), {
                "core_query": "(GPLD1)",
                "filter_json": filter_path,
                "filter_field": "pubmed_combined_query",
                "output": output_path,
                "markdown": None,
            })()
            ls.command_compose_pubmed_query(args)
            result = ls.load_json(output_path)
            self.assertEqual(result["pubmed_query"], '((GPLD1)) AND (("1234-5678"[ISSN]))')
        finally:
            Path(filter_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)

    def test_resolve_pubmed_query_from_json(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump({"pubmed_query": "(GPLD1)"}, tmp)
            query_path = tmp.name
        try:
            args = type("Args", (), {"query": None, "query_json": query_path, "query_field": "pubmed_query"})()
            self.assertEqual(ls.resolve_pubmed_query(args), "(GPLD1)")
        finally:
            Path(query_path).unlink(missing_ok=True)


class TestNormalizeJournalName(unittest.TestCase):
    def test_strips_leading_articles(self) -> None:
        self.assertEqual(ls.normalize_journal_name("The Lancet"), "lancet")
        self.assertEqual(ls.normalize_journal_name("Journal of the American College of Cardiology"), "american college of cardiology")
        self.assertEqual(ls.normalize_journal_name("Annals of Internal Medicine"), "internal medicine")

    def test_removes_punctuation(self) -> None:
        self.assertEqual(ls.normalize_journal_name("Nature Medicine (London)"), "nature medicine london")
        self.assertEqual(ls.normalize_journal_name("Cell, 2023"), "cell 2023")

    def test_preserves_cjk(self) -> None:
        self.assertEqual(ls.normalize_journal_name("中华医学杂志"), "中华医学杂志")


class TestParseEasyscholarCustomRank(unittest.TestCase):
    def test_parses_rank_strings(self) -> None:
        custom_rank = {
            "rankInfo": [
                {"uuid": "1614986460329492480", "abbName": "DUFE", "oneRankText": "TOP", "twoRankText": "A", "threeRankText": "B"},
            ],
            "rank": ["1614986460329492480&&&3"],
        }
        result = ls.parse_easyscholar_custom_rank(custom_rank)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["dataset"], "DUFE")
        self.assertEqual(result[0]["rank"], "B")
        self.assertEqual(result[0]["rank_index"], 3)

    def test_wraps_single_dict(self) -> None:
        custom_rank = {
            "rankInfo": {"uuid": "abc", "abbName": "X", "oneRankText": "A"},
            "rank": "abc&&&1",
        }
        result = ls.parse_easyscholar_custom_rank(custom_rank)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rank"], "A")

    def test_returns_empty_for_none(self) -> None:
        self.assertEqual(ls.parse_easyscholar_custom_rank(None), [])


class TestParseEasyscholarOfficialRank(unittest.TestCase):
    def test_extracts_non_empty_fields(self) -> None:
        official_rank = {
            "all": {"sci": "1区", "ssci": "", "swufe": "A"},
            "select": {"cufe": "AA"},
        }
        result = ls.parse_easyscholar_official_rank(official_rank)
        self.assertEqual(result["all"]["sci"], "1区")
        self.assertNotIn("ssci", result["all"])
        self.assertEqual(result["select"]["cufe"], "AA")

    def test_returns_empty_for_none(self) -> None:
        self.assertEqual(ls.parse_easyscholar_official_rank(None), {})


class TestEasyscholarCache(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            cache = {"version": 1, "created_at": "2026-07-14", "entries": {"lancet": {"publication_name": "Lancet"}}}
            ls.save_easyscholar_cache(path, cache)
            loaded = ls.load_easyscholar_cache(path)
            self.assertEqual(loaded["entries"]["lancet"]["publication_name"], "Lancet")

    def test_missing_cache_returns_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.json"
            loaded = ls.load_easyscholar_cache(path)
            self.assertEqual(loaded["version"], 1)
            self.assertEqual(loaded["entries"], {})


class TestGetEasyscholarApiKey(unittest.TestCase):
    def test_arg_takes_precedence(self) -> None:
        args = type("Args", (), {"easyscholar_api_key": "arg-key"})()
        with patch.dict(os.environ, {"EASYSCHOLAR_SECRET_KEY": "env-key"}):
            self.assertEqual(ls.get_easyscholar_api_key(args), "arg-key")

    def test_env_fallback(self) -> None:
        args = type("Args", (), {"easyscholar_api_key": None})()
        with patch.dict(os.environ, {"EASYSCHOLAR_SECRET_KEY": "env-key"}):
            self.assertEqual(ls.get_easyscholar_api_key(args), "env-key")

    def test_config_fallback(self) -> None:
        args = type("Args", (), {"easyscholar_api_key": None})()
        with patch.object(ls, "load_config", return_value={"easyscholar_secret_key": "config-key"}):
            self.assertEqual(ls.get_easyscholar_api_key(args), "config-key")


class TestConfigSetKeys(unittest.TestCase):
    """Test config --set-* options write keys without exposing them."""

    def test_set_easyscholar_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "academic-research.json"
            with patch.object(ls, "CONFIG_PATH", config_path):
                args = type("Args", (), {
                    "init": False,
                    "show": False,
                    "set_pubmed_api_key": None,
                    "set_s2_api_key": None,
                    "set_easyscholar_key": "my-secret-key",
                })()
                ls.command_config(args)
                config = ls.load_config(config_path)
                self.assertEqual(config["easyscholar_secret_key"], "my-secret-key")

    def test_set_key_overwrites_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "academic-research.json"
            ls.write_json(config_path, {"easyscholar_secret_key": "old-key", "pubmed_api_key": "pubmed-old"})
            with patch.object(ls, "CONFIG_PATH", config_path):
                args = type("Args", (), {
                    "init": False,
                    "show": False,
                    "set_pubmed_api_key": "pubmed-new",
                    "set_s2_api_key": None,
                    "set_easyscholar_key": None,
                })()
                ls.command_config(args)
                config = ls.load_config(config_path)
                self.assertEqual(config["pubmed_api_key"], "pubmed-new")
                self.assertEqual(config["easyscholar_secret_key"], "old-key")

    def test_empty_key_deletes_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "academic-research.json"
            ls.write_json(config_path, {"easyscholar_secret_key": "old-key"})
            with patch.object(ls, "CONFIG_PATH", config_path):
                args = type("Args", (), {
                    "init": False,
                    "show": False,
                    "set_pubmed_api_key": None,
                    "set_s2_api_key": None,
                    "set_easyscholar_key": "",
                })()
                ls.command_config(args)
                config = ls.load_config(config_path)
                self.assertNotIn("easyscholar_secret_key", config)


class TestPlatformPrivatePaths(unittest.TestCase):
    def test_windows_paths_use_local_app_data(self) -> None:
        home = Path("C:/Users/Alice")
        env = {"LOCALAPPDATA": "C:/Users/Alice/AppData/Local"}
        self.assertEqual(
            ls.default_config_path("win32", env, home),
            Path("C:/Users/Alice/AppData/Local/frank-ai4s/academic-research.json"),
        )
        self.assertEqual(
            ls.default_easyscholar_cache_path("win32", env, home),
            Path("C:/Users/Alice/AppData/Local/frank-ai4s/cache/easyscholar_journal_ranks.json"),
        )

    def test_windows_paths_fall_back_to_home(self) -> None:
        home = Path("C:/Users/Alice")
        self.assertEqual(
            ls.default_config_path("win32", {}, home),
            home / "AppData" / "Local" / "frank-ai4s" / "academic-research.json",
        )

    def test_posix_paths_remain_backward_compatible(self) -> None:
        home = Path("/home/alice")
        self.assertEqual(
            ls.default_config_path("linux", {}, home),
            home / ".config" / "frank-ai4s" / "academic-research.json",
        )


class TestEnrichEasyscholarEndToEnd(unittest.TestCase):
    """Test enrich-easyscholar with mocked API responses (no real HTTP)."""

    def test_enrich_attaches_rank_data(self) -> None:
        ranked_data = {
            "records": [
                {"source": "pubmed", "id": "1", "title": "T1", "journal": "Nature Medicine", "year": 2023, "score": 5.0, "score_reasons": []},
                {"source": "pubmed", "id": "2", "title": "T2", "journal": "Unknown Journal", "year": 2023, "score": 4.0, "score_reasons": []},
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "ranked.json"
            output_path = Path(tmpdir) / "out.json"
            cache_path = Path(tmpdir) / "cache.json"
            ls.write_json(input_path, ranked_data)

            def fake_fetch(publication_name: str, api_key: str | None, min_interval: float = 1.0) -> dict[str, Any] | None:
                if publication_name == "Nature Medicine":
                    return {
                        "publication_name": "Nature Medicine",
                        "official_rank": {"all": {"sci": "1区"}, "select": {}},
                        "custom_rank": [],
                        "fetched_at": "2026-07-14T10:00:00",
                    }
                return None

            with patch.object(ls, "fetch_easyscholar_rank", side_effect=fake_fetch):
                args = type("Args", (), {
                    "ranked_json": str(input_path),
                    "output": str(output_path),
                    "easyscholar_api_key": "test-key",
                    "cache": str(cache_path),
                    "min_interval": 1.0,
                    "csv": None,
                })()
                ls.command_enrich_easyscholar(args)

            result = ls.load_json(output_path)
            records = result["records"]
            self.assertIn("easyscholar", records[0])
            self.assertEqual(records[0]["easyscholar"]["official_rank"]["all"]["sci"], "1区")
            self.assertNotIn("easyscholar", records[1])
            self.assertEqual(result["easyscholar_enrichment"]["matched"], 1)
            self.assertEqual(result["easyscholar_enrichment"]["unmatched"], 1)
            self.assertEqual(result["easyscholar_enrichment"]["api_calls"], 2)

            # Cache should contain the successful lookup.
            cache = ls.load_easyscholar_cache(cache_path)
            self.assertIn("nature medicine", cache["entries"])

    def test_enrich_uses_cache(self) -> None:
        ranked_data = {
            "records": [
                {"source": "pubmed", "id": "1", "title": "T1", "journal": "Nature Medicine", "year": 2023, "score": 5.0, "score_reasons": []},
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "ranked.json"
            output_path = Path(tmpdir) / "out.json"
            cache_path = Path(tmpdir) / "cache.json"
            ls.write_json(input_path, ranked_data)
            ls.save_easyscholar_cache(
                cache_path,
                {
                    "version": 1,
                    "created_at": "2026-07-14",
                    "entries": {
                        "nature medicine": {
                            "publication_name": "Nature Medicine",
                            "official_rank": {"all": {"sci": "1区"}},
                            "custom_rank": [],
                            "fetched_at": "2026-07-14T09:00:00",
                        }
                    },
                },
            )

            with patch.object(ls, "fetch_easyscholar_rank") as mock_fetch:
                args = type("Args", (), {
                    "ranked_json": str(input_path),
                    "output": str(output_path),
                    "easyscholar_api_key": "test-key",
                    "cache": str(cache_path),
                    "min_interval": 1.0,
                    "csv": None,
                })()
                ls.command_enrich_easyscholar(args)
                mock_fetch.assert_not_called()

            result = ls.load_json(output_path)
            self.assertEqual(result["easyscholar_enrichment"]["cache_hits"], 1)
            self.assertEqual(result["easyscholar_enrichment"]["api_calls"], 0)
            self.assertEqual(result["records"][0]["easyscholar"]["official_rank"]["all"]["sci"], "1区")

    def test_selection_queries_only_selected_journals_and_skips_preprints(self) -> None:
        ranked_data = {"records": [
            {"source": "pubmed", "id": "1", "doi": "10.1/selected", "title": "Selected", "journal": "Selected Journal", "article_types": ["Journal Article"]},
            {"source": "pubmed", "id": "2", "doi": "10.1/unselected", "title": "Unselected", "journal": "Unselected Journal", "article_types": ["Journal Article"]},
            {"source": "arxiv", "id": "3", "doi": "10.1/preprint", "title": "Preprint", "journal": "bioRxiv", "article_types": ["Preprint"]},
        ]}
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "ranked.json"
            selection_path = Path(tmpdir) / "selection.json"
            output_path = Path(tmpdir) / "out.json"
            ls.write_json(input_path, ranked_data)
            ls.write_json(selection_path, {"schema_version": "1.0", "evidence_ids": ["doi:10.1/selected", "doi:10.1/preprint"]})
            with patch.object(ls, "fetch_easyscholar_rank", return_value={
                "publication_name": "Selected Journal", "official_rank": {"all": {"sciif": "5.2"}},
                "custom_rank": [], "fetched_at": "2026-07-17T00:00:00Z",
            }) as fetch:
                ls.command_enrich_easyscholar(type("Args", (), {
                    "ranked_json": str(input_path), "selection_json": str(selection_path),
                    "output": str(output_path), "easyscholar_api_key": "test-key",
                    "cache": str(Path(tmpdir) / "cache.json"), "min_interval": 1.0, "csv": None,
                })())
            fetch.assert_called_once_with("Selected Journal", "test-key", min_interval=1.0)
            result = ls.load_json(output_path)
            self.assertIn("easyscholar", result["records"][0])
            self.assertNotIn("easyscholar", result["records"][1])
            self.assertNotIn("easyscholar", result["records"][2])
            self.assertEqual(result["easyscholar_enrichment"]["selected"], 2)
            self.assertEqual(result["easyscholar_enrichment"]["preprints_skipped"], 1)
            self.assertEqual(result["easyscholar_enrichment"]["journal_records"], 1)


class TestEnrichEasyscholarErrorHandling(unittest.TestCase):
    def test_api_error_does_not_crash(self) -> None:
        ranked_data = {
            "records": [
                {"source": "pubmed", "id": "1", "title": "T1", "journal": "Nature Medicine", "year": 2023, "score": 5.0, "score_reasons": []},
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "ranked.json"
            output_path = Path(tmpdir) / "out.json"
            cache_path = Path(tmpdir) / "cache.json"
            ls.write_json(input_path, ranked_data)

            with patch.object(ls, "fetch_easyscholar_rank", return_value=None):
                args = type("Args", (), {
                    "ranked_json": str(input_path),
                    "output": str(output_path),
                    "easyscholar_api_key": "test-key",
                    "cache": str(cache_path),
                    "min_interval": 1.0,
                    "csv": None,
                })()
                ls.command_enrich_easyscholar(args)

            result = ls.load_json(output_path)
            self.assertEqual(result["easyscholar_enrichment"]["matched"], 0)
            self.assertEqual(result["easyscholar_enrichment"]["unmatched"], 1)
            self.assertNotIn("easyscholar", result["records"][0])

    def test_missing_api_key_reports_unavailable_and_preserves_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "ranked.json"
            output_path = Path(tmpdir) / "out.json"
            ls.write_json(input_path, {"records": [{"source": "pubmed", "id": "1", "title": "T1", "journal": "Nature Medicine"}]})
            args = type("Args", (), {
                "ranked_json": str(input_path), "output": str(output_path),
                "easyscholar_api_key": None, "cache": None, "min_interval": 1.0, "csv": None,
            })()
            with patch.object(ls, "get_easyscholar_api_key", return_value=None):
                ls.command_enrich_easyscholar(args)
            result = ls.load_json(output_path)
            self.assertEqual(result["easyscholar_enrichment"]["status"], "unavailable")
            self.assertEqual(result["easyscholar_enrichment"]["reason"], "api-key-not-configured")
            self.assertNotIn("easyscholar", result["records"][0])


class TestSecretRedaction(unittest.TestCase):
    def test_sanitize_url_removes_pubmed_and_easyscholar_keys(self) -> None:
        sanitized = ls.sanitize_url(
            "https://example.test/api?publicationName=Nature&secretKey=easy-secret&api_key=pubmed-secret"
        )
        self.assertIn("publicationName=Nature", sanitized)
        self.assertNotIn("easy-secret", sanitized)
        self.assertNotIn("pubmed-secret", sanitized)
        self.assertNotIn("secretKey", sanitized)
        self.assertNotIn("api_key", sanitized)

    def test_default_help_hides_credential_arguments_and_hidden_provider(self) -> None:
        parser = ls.build_parser()
        subparsers = next(
            action for action in parser._actions if hasattr(action, "choices") and action.choices
        )
        for command in ("config", "review", "enrich-citations", "enrich-easyscholar"):
            help_text = subparsers.choices[command].format_help()
            self.assertNotIn("Semantic Scholar", help_text)
            self.assertNotIn("semantic-scholar", help_text)
            self.assertNotIn("--set-pubmed-api-key", help_text)
            self.assertNotIn("--set-easyscholar-key", help_text)
            self.assertNotIn("--s2-api-key", help_text)
            self.assertNotIn("--api-key", help_text)
            self.assertNotIn("--easyscholar-api-key", help_text)


if __name__ == "__main__":
    unittest.main()
