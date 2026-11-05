"""Tests for the fde-case-study verification harness.

The harness (../verify_case_study.py) checks claims.json against the
eleven sibling FDE builds. These tests pin three behaviours:

1. claims.json covers exactly the eleven programme projects;
2. every claim in claims.json verifies against its real source;
3. a corrupted claim fails loudly (negative tests on temp copies --
   the real claims.json and the sibling builds are never modified).
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
BUILD_ROOT = PROJECT_DIR.parent
CLAIMS_PATH = PROJECT_DIR / "claims.json"

_spec = importlib.util.spec_from_file_location(
    "verify_case_study", PROJECT_DIR / "verify_case_study.py"
)
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)


@pytest.fixture(scope="module")
def claims() -> dict:
    return harness.load_claims(CLAIMS_PATH)


def test_claims_cover_all_eleven_projects(claims):
    projects = claims["projects"]
    assert len(projects) == 11
    assert [p["slug"] for p in projects] == harness.EXPECTED_SLUGS
    assert [p["id"] for p in projects] == [f"P{i}" for i in range(1, 12)]
    for project in projects:
        assert project["repo"] == f"https://github.com/habib-analyst/{project['slug']}"
        assert isinstance(project["test_count"], int) and project["test_count"] > 0
        assert project["headlines"], f"{project['slug']} has no headline claims"
        for headline in project["headlines"]:
            assert headline["value"], f"{project['slug']} has an empty headline value"
            assert headline["label"], f"{project['slug']} has an unlabelled headline"


def test_every_claim_verifies_against_sibling_builds(claims):
    failures = harness.verify_claims(claims, BUILD_ROOT)
    assert failures == [], "unverified claims:\n" + "\n".join(failures)


def _single_project_failures(claims, slug, build_root=BUILD_ROOT):
    claim = next(p for p in claims["projects"] if p["slug"] == slug)
    return harness.verify_project(claim, build_root)


def test_corrupted_headline_value_fails(claims, tmp_path):
    corrupted = copy.deepcopy(claims)
    target = next(p for p in corrupted["projects"] if p["slug"] == "fde-secure-rag")
    target["headlines"][0]["value"] = "9.9999 -- a figure no source contains"
    bad_path = tmp_path / "claims.json"
    bad_path.write_text(json.dumps(corrupted), encoding="utf-8")

    failures = _single_project_failures(
        harness.load_claims(bad_path), "fde-secure-rag"
    )
    assert failures, "a corrupted headline value must fail verification"
    assert any("headline value not found" in f for f in failures)


def test_corrupted_test_count_fails(claims, tmp_path):
    corrupted = copy.deepcopy(claims)
    target = next(p for p in corrupted["projects"] if p["slug"] == "fde-onboarding")
    target["test_count"] += 1
    bad_path = tmp_path / "claims.json"
    bad_path.write_text(json.dumps(corrupted), encoding="utf-8")

    failures = _single_project_failures(
        harness.load_claims(bad_path), "fde-onboarding"
    )
    assert failures, "a corrupted test count must fail verification"
    assert any("test count mismatch" in f for f in failures)


def test_missing_sibling_directory_fails_loudly(claims, tmp_path):
    failures = _single_project_failures(claims, "fde-webhook-engine", build_root=tmp_path)
    assert failures, "a missing sibling build must fail verification"
    assert any("not found" in f for f in failures)
