#!/usr/bin/env python3
"""Verify the fde-case-study's quoted numbers against their sources.

The case study (README.md) quotes a metrics table for the eleven FDE
portfolio projects P1-P11. Those quotes live in machine-readable form in
claims.json. This harness checks every claim against the sibling build
directory it came from:

* coverage   -- claims.json must cover exactly the eleven expected
                project slugs, in programme order;
* test count -- `python3 -m pytest tests/ --collect-only -q` is run in
                the sibling directory and the collected count must equal
                the claimed test_count;
* headlines  -- each headline value must appear verbatim in the sibling
                project's README.md (or in a results file shipped in that
                project), after whitespace normalisation so that line
                wrapping in the source Markdown cannot hide a match.

Any mismatch is reported as a FAIL line and the process exits 1. The
harness never edits the sibling projects; it only reads them and runs
their test collectors.

Usage:
    python3 verify_case_study.py [--claims claims.json]
                                  [--build-root ~/workspace/build]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

EXPECTED_SLUGS = [
    "fde-multitenant-saas",   # P1
    "fde-enterprise-sso",     # P2
    "fde-connector-pack",     # P3
    "fde-secure-rag",         # P4
    "fde-health-dashboard",   # P5
    "fde-webhook-engine",     # P6
    "fde-oneclick-deploy",    # P7
    "fde-pii-redaction",      # P8
    "fde-incident-response",  # P9
    "fde-usage-billing",      # P10
    "fde-onboarding",         # P11
]

_COLLECTED_RE = re.compile(r"(\d+)\s+tests?\s+collected")


def _normalise(text: str) -> str:
    """Collapse every whitespace run to a single space."""
    return " ".join(text.split())


def load_claims(claims_path: Path) -> dict:
    with claims_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def collect_test_count(project_dir: Path, timeout: int = 120) -> int:
    """Return how many tests pytest collects in *project_dir*.

    Raises RuntimeError with the collector output when collection fails,
    so a broken sibling suite fails the verification loudly instead of
    being mistaken for a count of zero.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = proc.stdout + proc.stderr
    match = None
    for match in _COLLECTED_RE.finditer(output):
        pass  # keep the last summary line's count
    if proc.returncode != 0 or match is None:
        raise RuntimeError(
            f"pytest --collect-only failed in {project_dir} "
            f"(exit {proc.returncode}):\n{output.strip()[-2000:]}"
        )
    return int(match.group(1))


def source_corpus(project_dir: Path) -> str:
    """Whitespace-normalised text of the project's README + results files."""
    texts: list[str] = []
    readme = project_dir / "README.md"
    if readme.is_file():
        texts.append(readme.read_text(encoding="utf-8", errors="replace"))
    for candidate in sorted(project_dir.rglob("*")):
        if not candidate.is_file():
            continue
        rel = candidate.relative_to(project_dir)
        if "result" in rel.name.lower() and candidate.suffix.lower() in {
            ".md",
            ".json",
            ".txt",
        }:
            texts.append(candidate.read_text(encoding="utf-8", errors="replace"))
    return _normalise("\n".join(texts))


def verify_project(claim: dict, build_root: Path) -> list[str]:
    """Check one project's claims. Returns a list of failure messages."""
    slug = claim.get("slug", "<missing slug>")
    failures: list[str] = []
    project_dir = build_root / slug
    if not project_dir.is_dir():
        return [f"{slug}: sibling build directory not found: {project_dir}"]
    if not (project_dir / "README.md").is_file():
        failures.append(f"{slug}: README.md missing in {project_dir}")

    claimed_count = claim.get("test_count")
    if not isinstance(claimed_count, int) or claimed_count <= 0:
        failures.append(f"{slug}: claims.json test_count is not a positive int: {claimed_count!r}")
    else:
        try:
            actual_count = collect_test_count(project_dir)
        except Exception as exc:  # collector failure is a verification failure
            failures.append(f"{slug}: could not collect tests: {exc}")
        else:
            if actual_count != claimed_count:
                failures.append(
                    f"{slug}: test count mismatch -- claims.json says "
                    f"{claimed_count}, pytest collects {actual_count}"
                )

    headlines = claim.get("headlines")
    if not headlines:
        failures.append(f"{slug}: claims.json lists no headline claims")
    else:
        corpus = source_corpus(project_dir)
        for headline in headlines:
            value = headline.get("value", "")
            if _normalise(value) not in corpus:
                failures.append(
                    f"{slug}: headline value not found in source README/results: "
                    f"{value!r} ({headline.get('label', 'unlabelled claim')})"
                )
    return failures


def verify_claims(claims: dict, build_root: Path) -> list[str]:
    """Check coverage plus every project. Returns all failure messages."""
    failures: list[str] = []
    projects = claims.get("projects")
    if not isinstance(projects, list):
        return ["claims.json: 'projects' must be a list"]
    slugs = [p.get("slug") for p in projects]
    if slugs != EXPECTED_SLUGS:
        failures.append(
            "claims.json: project coverage/order mismatch -- expected "
            f"{EXPECTED_SLUGS}, found {slugs}"
        )
    for claim in projects:
        failures.extend(verify_project(claim, build_root))
    return failures


def verify_all(claims_path: Path, build_root: Path) -> list[str]:
    return verify_claims(load_claims(claims_path), build_root)


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--claims",
        type=Path,
        default=here / "claims.json",
        help="path to claims.json (default: alongside this script)",
    )
    parser.add_argument(
        "--build-root",
        type=Path,
        default=here.parent,
        help="directory holding the sibling fde-* builds "
        "(default: the parent of this project, i.e. ~/workspace/build)",
    )
    args = parser.parse_args(argv)

    claims = load_claims(args.claims)
    failures = verify_claims(claims, args.build_root)

    failed_slugs = set()
    for failure in failures:
        for slug in EXPECTED_SLUGS:
            if failure.startswith(slug) or slug in failure:
                failed_slugs.add(slug)
    total_tests = 0
    for claim in claims.get("projects", []):
        slug = claim.get("slug")
        count = claim.get("test_count")
        if isinstance(count, int):
            total_tests += count
        status = "FAIL" if slug in failed_slugs else "PASS"
        print(
            f"[{status}] {claim.get('id', '?')} {slug}: "
            f"test_count={count}, headlines={len(claim.get('headlines', []))}"
        )
    print(f"Total claimed tests across P1-P11: {total_tests}")
    if failures:
        print(f"\nVERIFICATION FAILED -- {len(failures)} problem(s):", file=sys.stderr)
        for failure in failures:
            print(f"  FAIL: {failure}", file=sys.stderr)
        return 1
    print("\nAll case-study claims verified against their sources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
