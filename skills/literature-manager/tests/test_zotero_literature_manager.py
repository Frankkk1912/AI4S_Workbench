#!/usr/bin/env python3
"""Unit tests for the evidence-to-Zotero import handoff."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import zotero_literature_manager as zlm  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeMsvcrt:
    LK_NBLCK = 1
    LK_UNLCK = 2

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def locking(self, _fd: int, mode: int, size: int) -> None:
        self.calls.append((mode, size))


class TestCrossPlatformRateLimitLock(unittest.TestCase):
    def test_windows_lock_uses_msvcrt_and_binary_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeMsvcrt()
            path = Path(directory) / "rate.lock"
            with (
                patch.object(zlm, "fcntl", None),
                patch.object(zlm, "msvcrt", fake),
                patch.object(zlm.time, "monotonic", side_effect=[10.0, 10.0]),
            ):
                zlm.wait_for_rate_limit(path, 0.0)
                zlm.wait_for_rate_limit(path, 1.0)
            self.assertIn((fake.LK_NBLCK, 1), fake.calls)
            self.assertIn((fake.LK_UNLCK, 1), fake.calls)
            self.assertTrue(path.read_text(encoding="ascii"))


def plan_args(tmp: Path, snapshot: str = "zotero_items_unique_sample.json") -> argparse.Namespace:
    return argparse.Namespace(
        evidence=str(FIXTURES / "evidence_sample.json"),
        selection_json=str(FIXTURES / "selection_sample.json"),
        select_id=None,
        project="gpld1-cvd",
        search_date="2026-07-12",
        collection_name="GPLD1 cardiovascular disease",
        library_type="user",
        library_id="19552201",
        candidate_limit=50,
        tag=[],
        zotero_items=str(FIXTURES / snapshot) if snapshot else None,
        allow_unchecked_create=False,
        ris_output=str(tmp / "selected.ris"),
        output=str(tmp / "zotero_import_plan.json"),
        metrics_year=None,
        metrics_source_label=None,
        priority_recommendations=None,
    )


class TestEvidenceIdentity(unittest.TestCase):
    def test_priority(self) -> None:
        self.assertEqual(
            zlm.stable_evidence_id({"doi": "https://doi.org/10.1/ABC", "pmid": "123"}),
            "doi:10.1/abc",
        )
        self.assertEqual(zlm.stable_evidence_id({"pmid": "PMID: 123"}), "pmid:123")
        self.assertEqual(
            zlm.stable_evidence_id({"source": "PubMed", "id": "42"}),
            "source:pubmed:42",
        )
        self.assertRegex(zlm.stable_evidence_id({"title": "A Study"}), r"^title-sha256:[0-9a-f]{64}$")
        self.assertRegex(zlm.stable_evidence_id({"title": "心血管疾病研究"}), r"^title-sha256:[0-9a-f]{64}$")

    def test_changed_supplied_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "mismatch"):
            zlm.stable_evidence_id({"doi": "10.1/a", "evidence_id": "doi:10.1/b"})

    def test_creator_normalization_does_not_guess_unstructured_order(self) -> None:
        self.assertEqual(zlm.normalize_creator("Smith J"), {"creatorType": "author", "name": "Smith J"})
        self.assertEqual(
            zlm.normalize_creator("Smith, Jane"),
            {"creatorType": "author", "lastName": "Smith", "firstName": "Jane"},
        )

    def test_preprint_uses_repository_not_publication_title(self) -> None:
        item, reasons = zlm.normalize_zotero_item(
            {
                "source": "pubmed",
                "article_types": ["Journal Article", "Preprint"],
                "title": "A preprint about sorting nexins",
                "journal": "bioRxiv : the preprint server for biology",
                "year": 2026,
                "doi": "10.1101/2026.01.01.123456",
            },
            [],
        )
        self.assertEqual(reasons, [])
        self.assertIsNotNone(item)
        self.assertEqual(item["itemType"], "preprint")
        self.assertEqual(item["repository"], "bioRxiv : the preprint server for biology")
        self.assertNotIn("publicationTitle", item)

    def test_article_types_are_normalized_without_changing_zotero_item_type(self) -> None:
        item, reasons = zlm.normalize_zotero_item(
            {
                "source": "pubmed",
                "article_types": ["Journal Article", "Review", "Systematic Review", "Meta-Analysis", "Letter"],
                "title": "A systematic review published as a journal letter",
                "journal": "Example Journal",
            },
            ["project:test"],
        )
        self.assertEqual(reasons, [])
        self.assertEqual(item["itemType"], "journalArticle")
        self.assertEqual(
            [entry["tag"] for entry in item["tags"]],
            [
                "AI4S:ArticleType:Letter",
                "AI4S:ArticleType:Meta-Analysis",
                "AI4S:ArticleType:Systematic Review",
                "project:test",
            ],
        )

    def test_article_type_normalization_handles_pubmed_phases_wos_and_unknown_values(self) -> None:
        self.assertEqual(
            zlm.normalize_article_types(
                {
                    "article_types": [
                        "Journal Article",
                        "Clinical Trial, Phase III",
                        "Editorial Material",
                        "Novel Source Vocabulary",
                    ]
                }
            ),
            ["Clinical Trial, Phase III", "Editorial", "Novel Source Vocabulary"],
        )


class TestImportPlanning(unittest.TestCase):
    def test_metrics_extra_payload_preserves_pmid_and_source_hash(self) -> None:
        raw = b'{"records":[]}'
        digest = __import__('hashlib').sha256(raw).hexdigest()
        extra = zlm.merge_metrics_extra("PMID: 42", {"easyscholar": {"official_rank": {"all": {"if": 0}}}}, year=2026, source_label="easyscholar-2026", source_sha256=digest)
        self.assertIn("PMID: 42", extra)
        self.assertIn('"2026"', extra)
        self.assertIn(digest, extra)

    def test_metrics_disabled_returns_extra_unchanged(self) -> None:
        self.assertEqual(zlm.merge_metrics_extra("PMID: 42", {}, year=2026, source_label="x", source_sha256="0"*64), "PMID: 42")

    def test_new_import_defaults_metrics_to_search_year_minus_one_for_create_and_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            evidence = zlm.load_json(FIXTURES / "evidence_sample.json")
            for record in evidence["records"]:
                record["easyscholar"] = {
                    "official_rank": {"all": {"sciif": "5.8", "sciif5": "6.3", "sci": "Q1", "sciUp": "生物学1区"}},
                    "fetched_at": "2026-07-17T00:00:00Z",
                }
            evidence_path = tmp / "evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            args = plan_args(tmp)
            args.evidence = str(evidence_path)
            zlm.command_plan_import(args)
            plan = zlm.load_json(args.output)
            for action in plan["actions"]:
                self.assertIn('"2025"', action["item"]["extra"])
                self.assertNotIn('"2026"', action["item"]["extra"])
                self.assertIn({"tag": "JCR:Q1"}, action["item"]["tags"])
                self.assertIn({"tag": "CAS:1区"}, action["item"]["tags"])
            reuse = next(action for action in plan["actions"] if action["decision"] == "reuse")
            self.assertIn("AI4S-Metrics:", reuse["item"]["extra"])

    def test_new_import_rejects_wrong_configured_metrics_year(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(Path(directory))
            args.metrics_year = 2026
            with self.assertRaisesRegex(ValueError, "derived display year 2025"):
                zlm.command_plan_import(args)

    def test_unique_fixture_produces_one_reuse_and_one_create(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(Path(directory))
            zlm.command_plan_import(args)
            plan = zlm.load_json(args.output)
            self.assertEqual(plan["summary"], {"selected": 2, "create": 1, "reuse": 1, "check": 0, "skip": 0})
            self.assertRegex(plan["plan_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(plan["target"]["tags"], ["import-run:gpld1-cvd-20260712", "project:gpld1-cvd"])
            for action in plan["actions"]:
                self.assertIn({"tag": "AI4S:ArticleType:Article"}, action["item"]["tags"])

    def test_generated_plan_matches_shared_golden_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(Path(directory))
            zlm.command_plan_import(args)
            actual = zlm.load_json(args.output)
            expected = zlm.load_json(FIXTURES / "import_plan_expected.json")
            actual["created_at"] = expected["created_at"]
            self.assertEqual(actual, expected)

    def test_ambiguous_duplicate_fixture_marks_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(Path(directory), "zotero_items_sample.json")
            zlm.command_plan_import(args)
            plan = zlm.load_json(args.output)
            first = next(action for action in plan["actions"] if action["evidence_id"].endswith("example.1"))
            self.assertEqual(first["decision"], "check")
            self.assertIn("multiple-identifier-matches", first["reason_codes"])
            self.assertEqual(len(first["match"]["candidates"]), 2)

    def test_unknown_selection_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            selection = tmp / "selection.json"
            selection.write_text('{"schema_version":"1.0","evidence_ids":["doi:missing"]}', encoding="utf-8")
            args = plan_args(tmp)
            args.selection_json = str(selection)
            with self.assertRaisesRegex(ValueError, "unknown evidence"):
                zlm.command_plan_import(args)

    def test_ris_contains_only_create_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(Path(directory))
            zlm.command_plan_import(args)
            ris = Path(args.ris_output).read_text(encoding="utf-8")
            self.assertIn("DO  - 10.1000/example.2", ris)
            self.assertNotIn("10.1000/example.1", ris)
            self.assertEqual(ris.count("ER  -"), 1)

    def test_unavailable_local_api_requires_explicit_unchecked_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(Path(directory), snapshot="")
            with patch.object(zlm, "fetch_local_candidates", side_effect=zlm.ApiError("offline")):
                with self.assertRaisesRegex(zlm.ApiError, "offline"):
                    zlm.command_plan_import(args)
                args.allow_unchecked_create = True
                zlm.command_plan_import(args)
            plan = zlm.load_json(args.output)
            self.assertEqual(plan["matching"]["mode"], "unchecked")
            self.assertTrue(plan["matching"]["unchecked_create"])

    def test_plan_sync_backfills_article_type_tags_for_matched_existing_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            matches = tmp / "matches.json"
            output = tmp / "sync.json"
            matches.write_text(json.dumps({"matches": [{
                "evidence_index": 0,
                "evidence_title": "Review paper",
                "evidence": {"article_types": ["JournalArticle", "SystematicReview", "MetaAnalysis"]},
                "match": {"zotero_key": "ITEM0001", "reasons": ["doi"]},
            }], "unmatched": []}), encoding="utf-8")
            args = argparse.Namespace(
                matches=str(matches), project="test", search_date="2026-07-16",
                collection_name="Test", collection_key="COLL0001", tag=[], output=str(output),
            )
            zlm.command_plan_sync(args)
            action = zlm.load_json(output)["actions"][0]
            self.assertIn("AI4S:ArticleType:Systematic Review", action["add_tags"])
            self.assertIn("AI4S:ArticleType:Meta-Analysis", action["add_tags"])
            self.assertNotIn("AI4S:ArticleType:Article", action["add_tags"])

    def test_priority_sidecar_adds_explicit_and_default_tags_to_hashed_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            sidecar = tmp / "priority_recommendations.json"
            sidecar.write_text(json.dumps({
                "schema_version": "1.0",
                "artifact_type": "literature-priority-recommendations",
                "scope": "gpld1-cvd",
                "review_depth": "abstract",
                "default_for_selected": 1,
                "recommendations": {
                    "doi:10.1000/example.1": {
                        "priority": 3,
                        "reason_codes": ["direct-question-match", "core-conclusion"],
                    }
                },
            }), encoding="utf-8")
            args = plan_args(tmp)
            args.priority_recommendations = str(sidecar)
            zlm.command_plan_import(args)
            plan = zlm.load_json(args.output)
            self.assertEqual(plan["priority"]["scope"], "gpld1-cvd")
            self.assertRegex(plan["priority"]["source_sha256"], r"^[0-9a-f]{64}$")
            explicit = next(action for action in plan["actions"] if action["evidence_id"].endswith("example.1"))
            defaulted = next(action for action in plan["actions"] if action["evidence_id"].endswith("example.2"))
            self.assertIn({"tag": "AI4S:Priority:3"}, explicit["item"]["tags"])
            self.assertEqual(explicit["priority_recommendation"], {
                "level": 3,
                "reason_codes": ["core-conclusion", "direct-question-match"],
                "tag_decision": "add",
            })
            self.assertIn({"tag": "AI4S:Priority:1"}, defaulted["item"]["tags"])
            self.assertEqual(defaulted["priority_recommendation"]["reason_codes"], ["selected-default"])

    def test_existing_user_priority_is_preserved_for_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            snapshot = zlm.load_json(FIXTURES / "zotero_items_unique_sample.json")
            snapshot["items"][0]["tags"].append({"tag": "AI4S:Priority:2"})
            snapshot_path = tmp / "items.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            sidecar = tmp / "priority.json"
            sidecar.write_text(json.dumps({
                "schema_version": "1.0", "artifact_type": "literature-priority-recommendations",
                "scope": "gpld1-cvd", "review_depth": "abstract", "default_for_selected": 1,
                "recommendations": {"doi:10.1000/example.1": {"priority": 3, "reason_codes": ["core-conclusion"]}},
            }), encoding="utf-8")
            args = plan_args(tmp)
            args.zotero_items = str(snapshot_path)
            args.priority_recommendations = str(sidecar)
            zlm.command_plan_import(args)
            action = next(a for a in zlm.load_json(args.output)["actions"] if a["decision"] == "reuse")
            self.assertNotIn({"tag": "AI4S:Priority:3"}, action["item"]["tags"])
            self.assertEqual(action["priority_recommendation"]["tag_decision"], "preserve-existing")
            self.assertEqual(action["priority_recommendation"]["existing_tags"], ["AI4S:Priority:2"])

    def test_priority_sidecar_rejects_wrong_scope_and_unknown_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            sidecar = tmp / "priority.json"
            sidecar.write_text(json.dumps({
                "schema_version": "1.0", "artifact_type": "literature-priority-recommendations",
                "scope": "another-project", "review_depth": "abstract", "default_for_selected": 1,
                "recommendations": {"doi:missing": {"priority": 3, "reason_codes": ["core-conclusion"]}},
            }), encoding="utf-8")
            args = plan_args(tmp)
            args.priority_recommendations = str(sidecar)
            with self.assertRaisesRegex(ValueError, "does not match project"):
                zlm.command_plan_import(args)


class TestPlanHash(unittest.TestCase):
    def test_timestamp_version_and_order_do_not_change_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(Path(directory))
            zlm.command_plan_import(args)
            plan = zlm.load_json(args.output)
            changed = copy.deepcopy(plan)
            changed["created_at"] = "2030-01-01T00:00:00Z"
            changed["matching"]["source_library_version"] = 999
            changed["actions"].reverse()
            self.assertEqual(zlm.canonical_plan_hash(plan), zlm.canonical_plan_hash(changed))

    def test_write_intent_change_changes_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(Path(directory))
            zlm.command_plan_import(args)
            plan = zlm.load_json(args.output)
            changed = copy.deepcopy(plan)
            changed["target"]["collection_name"] = "Another collection"
            self.assertNotEqual(zlm.canonical_plan_hash(plan), zlm.canonical_plan_hash(changed))


class TestMetricsPlanning(unittest.TestCase):
    def test_easyscholar_backfill_matches_doi_and_skips_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            ranked = tmp / "ranked.json"; snapshot = tmp / "items.json"; output = tmp / "out.json"
            ranked.write_text(json.dumps({"records": [{"doi": "10.1/x", "title": "Good", "year": 2026,
                "easyscholar": {"official_rank": {"all": {"if": 4.2}}}}]}), encoding="utf-8")
            snapshot.write_text(json.dumps({"items": [{"key": "ABCD1234", "version": 2,
                "data": {"title": "Good", "DOI": "10.1/x"}}, {"key": "MISS1234", "version": 1,
                "data": {"title": "Missing", "DOI": "10.1/no"}}]}), encoding="utf-8")
            args = argparse.Namespace(ranked=str(ranked), zotero_items=str(snapshot), metrics_year="2025",
                remove_metrics_year=["2026"], source_label="easyscholar-2025", library_type="user", library_id="1", output=str(output))
            zlm.command_plan_easyscholar_metrics_backfill(args)
            plan = zlm.load_json(output)
            self.assertEqual([a["decision"] for a in plan["actions"]], ["update", "skip"])
            self.assertEqual(plan["actions"][0]["metric"]["impact_factor"], 4.2)
            self.assertEqual(plan["metrics"]["metrics_year"], 2025)
            self.assertEqual(plan["metrics"]["remove_years"], [2026])
            self.assertRegex(plan["metrics"]["source_sha256"], r"^[0-9a-f]{64}$")

    def test_unique_issn_generates_update_and_ambiguous_or_missing_records_skip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            snapshot = tmp / "items.json"
            csv_file = tmp / "metrics.csv"
            output = tmp / "metrics-plan.json"
            snapshot.write_text(json.dumps({"items": [
                {"key": "GOOD0001", "version": 7, "data": {"title": "Good", "ISSN": "1234-5678"}},
                {"key": "MISS0001", "version": 8, "data": {"title": "Missing"}},
                {"key": "AMB00001", "version": 9, "data": {"title": "Ambiguous", "ISSN": "9999-0000"}},
            ]}), encoding="utf-8")
            csv_file.write_text(
                "Journal,Impact Factor,JCR-zone,CAS-zone,ISSN\n"
                "Good Journal,12.4,Q1,1区,1234-5678\n"
                "Duplicate A,3,Q2,2区,9999-0000\n"
                "Duplicate B,4,Q1,1区,9999-0000\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                zotero_items=str(snapshot), journal_metrics=str(csv_file), metrics_year=2026,
                source_label="reviewed-2026", library_type="user", library_id="1", output=str(output),
            )
            zlm.command_plan_metrics_backfill(args)
            plan = zlm.load_json(output)
            self.assertEqual(plan["summary"], {"selected": 3, "update": 1, "skip": 2})
            good = next(action for action in plan["actions"] if action["item_key"] == "GOOD0001")
            self.assertEqual(good["metric"]["impact_factor"], 12.4)
            self.assertEqual(good["metric"]["jcr_zone"], "Q1")
            self.assertEqual(good["metric"]["cas_zone"], "1区")
            self.assertRegex(plan["plan_hash"], r"^sha256:[0-9a-f]{64}$")

    def test_unique_journal_name_or_abbreviation_fallback_is_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            snapshot = tmp / "items.json"
            csv_file = tmp / "metrics.csv"
            output = tmp / "metrics-plan.json"
            snapshot.write_text(json.dumps({"items": [
                {"key": "TITLE001", "version": 1, "data": {"title": "By title", "publicationTitle": "The Good Journal"}},
                {"key": "ABBR0001", "version": 2, "data": {"title": "By abbreviation", "journalAbbreviation": "Good J."}},
                {"key": "AMBIG001", "version": 3, "data": {"title": "Ambiguous", "publicationTitle": "Shared Journal"}},
            ]}), encoding="utf-8")
            csv_file.write_text(
                "Journal,Abbreviation,Impact Factor,JCR-zone,ISSN\n"
                "The Good Journal,Good J.,9.1,Q1,1111-1111\n"
                "Shared Journal,Shared J.,2.0,Q3,2222-2222\n"
                "Shared Journal,Shared Journal,3.0,Q2,3333-3333\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                zotero_items=str(snapshot), journal_metrics=str(csv_file), metrics_year=2026,
                source_label="reviewed-2026", library_type="user", library_id="1", output=str(output),
            )
            zlm.command_plan_metrics_backfill(args)
            plan = zlm.load_json(output)
            self.assertEqual(plan["summary"], {"selected": 3, "update": 2, "skip": 1})
            for key in ("TITLE001", "ABBR0001"):
                action = next(action for action in plan["actions"] if action["item_key"] == key)
                self.assertEqual(action["reason_codes"], ["unique-journal-name-match"])
                self.assertEqual(action["metric"]["impact_factor"], 9.1)
            ambiguous = next(action for action in plan["actions"] if action["item_key"] == "AMBIG001")
            self.assertEqual(ambiguous["reason_codes"], ["ambiguous-journal-name-match"])


class TestEasyscholarMetricMapping(unittest.TestCase):
    def test_maps_real_easyscholar_official_rank_fields(self) -> None:
        metric = zlm.easyscholar_record_to_metric(
            {
                "easyscholar": {
                    "official_rank": {
                        "all": {
                            "sciif": "5.8",
                            "sciif5": "6.3",
                            "sci": "Q1",
                            "sciBase": "生物2区",
                            "sciUp": "生物学1区",
                            "sciUpSmall": "生物学1区。",
                            "sciUpTop": "生物学TOP",
                            "esi": "生物与生化",
                            "eii": "EI",
                        }
                    },
                    "fetched_at": "2026-07-16T06:30:00+00:00",
                }
            },
            source_label="easyscholar-live",
            source_sha256="abc123",
        )
        self.assertEqual(metric, {
            "impact_factor": 5.8,
            "impact_factor_5y": 6.3,
            "jcr_zone": "Q1",
            "cas_zone": "1区",
            "publication_metrics": [
                {"code": "cas_major", "value": "生物学1区"},
                {"code": "cas_top", "value": True},
                {"code": "esi_category", "value": "生物与生化"},
                {"code": "indexing", "value": "EI"},
            ],
            "retrieved_at": "2026-07-16",
            "source_label": "easyscholar-live",
            "source_sha256": "abc123",
        })

    def test_maps_real_esci_and_uses_sciup_before_scibase(self) -> None:
        metric = zlm.easyscholar_record_to_metric(
            {
                "easyscholar": {
                    "official_rank": {
                        "all": {
                            "sciif": "2.6",
                            "esci": "Q2",
                            "sciBase": "生物3区",
                            "sciUp": "生物学4区",
                        }
                    }
                }
            },
            source_label="easyscholar-live",
            source_sha256="def456",
        )
        self.assertEqual(metric["impact_factor"], 2.6)
        self.assertEqual(metric["jcr_zone"], "Q2")
        self.assertEqual(metric["cas_zone"], "4区")
        self.assertEqual(metric["publication_metrics"], [{"code": "cas_major", "value": "生物学4区"}])

    def test_maps_plan_example_from_nested_official_and_custom_ranks(self) -> None:
        record = {
            "easyscholar": {
                "official_rank": {"all": {"sci": "Q2", "if": "49.96"}, "select": {"impactFactor": "48"}},
                "custom_rank": [
                    {"dataset": "中科院分区", "rank": "1区"},
                    {"dataset": "JCR", "rank": "Q1"},
                ],
            }
        }
        metric = zlm.easyscholar_record_to_metric(
            record, source_label="easyscholar-2026", source_sha256="abc123"
        )
        self.assertEqual(metric, {
            "impact_factor": 49.96,
            "jcr_zone": "Q1",
            "cas_zone": "1区",
            "source_label": "easyscholar-2026",
            "source_sha256": "abc123",
        })

    def test_malformed_official_sci_zone_is_not_reinterpreted_as_cas(self) -> None:
        metric = zlm.easyscholar_record_to_metric(
            {"easyscholar": {"official_rank": {"all": {"sci": "1区"}}}},
            source_label="easyscholar-2026",
            source_sha256="abc123",
        )
        self.assertIsNone(metric)

    def test_journal_metrics_are_field_level_fallbacks(self) -> None:
        metric = zlm.easyscholar_record_to_metric(
            {
                "easyscholar": {
                    "official_rank": {"select": {"impact_factor": "7.5", "ssci": "not ranked"}},
                    "custom_rank": "dirty-value",
                },
                "journal_metrics": {"impact_factor": 6.2, "jcr_zone": "Q3", "cas_zone": "2区"},
            },
            source_label="combined-2026",
            source_sha256="def456",
        )
        self.assertEqual(metric["impact_factor"], 7.5)
        self.assertEqual(metric["jcr_zone"], "Q3")
        self.assertEqual(metric["cas_zone"], "2区")

    def test_zero_impact_factor_is_a_valid_metric(self) -> None:
        metric = zlm.easyscholar_record_to_metric(
            {"easyscholar": {"official_rank": {"all": {"if": 0}}}},
            source_label="easyscholar-2026",
            source_sha256="zero",
        )
        self.assertEqual(metric["impact_factor"], 0)

    def test_returns_none_when_only_provenance_would_remain(self) -> None:
        self.assertIsNone(zlm.easyscholar_record_to_metric(
            {
                "easyscholar": {
                    "official_rank": {"all": {"sci": "1类", "if": "unknown"}},
                    "custom_rank": [None, "bad", {"dataset": "JCR", "rank": "Q5"}],
                },
                "journal_metrics": {"jcr_zone": "unknown"},
            },
            source_label="easyscholar-2026",
            source_sha256="empty",
        ))


class TestCitationPlanning(unittest.TestCase):
    def test_semantic_scholar_citations_make_a_manual_refresh_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            snapshot = tmp / "items.json"
            records = tmp / "citations.json"
            output = tmp / "citation-plan.json"
            snapshot.write_text(json.dumps({"items": [{"key": "CITE0001", "version": 4, "data": {"title": "Paper", "DOI": "10.1000/example"}}]}), encoding="utf-8")
            records.write_text(json.dumps({"records": [{"doi": "10.1000/example", "citation": {"citation_count": 128, "provider": "semantic-scholar", "retrieved_at": "2026-07-13"}}]}), encoding="utf-8")
            args = argparse.Namespace(zotero_items=str(snapshot), citation_records=str(records), library_type="user", library_id="1", output=str(output))
            zlm.command_plan_citation_refresh(args)
            plan = zlm.load_json(output)
            self.assertEqual(plan["summary"], {"selected": 1, "update": 1, "skip": 0})
            self.assertEqual(plan["actions"][0]["citation"]["citation_count"], 128)
            self.assertEqual(plan["citation_source"]["provider"], "semantic-scholar")


class TestLocalWriteGuard(unittest.TestCase):
    def test_apply_sync_rejects_local_write_before_client_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            sync_plan = tmp / "sync.json"
            sync_plan.write_text(json.dumps({"actions": []}), encoding="utf-8")
            args = argparse.Namespace(
                sync_plan=str(sync_plan),
                dry_run=False,
                output=str(tmp / "out.json"),
                local=True,
                base_url=zlm.WEB_API_BASE,
                api_key_env="ZOTERO_API_KEY",
                rate_limit_seconds=1.0,
                rate_limit_state=str(tmp / "rate.lock"),
                max_retries=0,
                library_type="user",
                library_id="1",
            )
            with patch.object(zlm, "ZoteroClient") as client:
                with self.assertRaisesRegex(zlm.ApiError, "read-only"):
                    zlm.command_apply_sync(args)
                client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
