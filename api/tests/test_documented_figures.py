"""Check that numbers quoted in prose still match the shipped data.

Three separate rounds of review found the same defect: a comment or README paragraph that
described a computation accurately when it was written, and kept describing it after the
computation moved. The README data table, the co-occurrence lifts in `sites.py`, and the cell
counts in `sites.py` and `extract.py` all went stale that way, the last of them within an hour
of the change that invalidated them.

This project argues its case in narrated comments, which is a deliberate choice but means the
narration is load-bearing. These tests make the load-bearing figures fail loudly instead of
quietly becoming false.

Deliberately not exhaustive. It pins the counts that describe the shipped extract, which are
the ones that move whenever the pipeline is re-run.
"""

import re
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
CELLS = ROOT / "data" / "cells.parquet"


@pytest.fixture(scope="module")
def counts():
    con = duckdb.connect()
    total = con.execute(f"SELECT count(*) FROM '{CELLS}'").fetchone()[0]
    eligible = con.execute(
        f"SELECT count(*) FROM '{CELLS}' WHERE storefront_count >= 10").fetchone()[0]
    unlabelled = con.execute(
        f"SELECT count(*) FROM '{CELLS}' WHERE neighborhood IS NULL").fetchone()[0]
    return {"total": total, "eligible": eligible, "unlabelled": unlabelled}


def quoted(path: Path, pattern: str) -> list[tuple[int, ...]]:
    """Every group of integers matching `pattern` in a file, commas stripped."""
    text = path.read_text()
    return [tuple(int(g.replace(",", "")) for g in m.groups())
            for m in re.finditer(pattern, text)]


def test_eligible_cell_count_in_sites_matches_the_data(counts):
    """`MIN_STOREFRONTS` is documented with how many cells clear it."""
    found = quoted(ROOT / "api/src/overture_api/sites.py",
                   r"([\d,]+) of ([\d,]+) cells clear it")
    assert found, "the sentence documenting MIN_STOREFRONTS has changed shape"
    for eligible, total in found:
        assert (eligible, total) == (counts["eligible"], counts["total"])


def test_unlabelled_cell_counts_match_the_data(counts):
    """Both the extractor and the README quote how many cells end up without a label."""
    pattern = r"([\d,]+) unlabelled cells of ([\d,]+)|([\d,]+) of ([\d,]+) unlabelled"
    for path in (ROOT / "data-pipeline/extract.py", ROOT / "README.md"):
        text = path.read_text()
        hits = re.findall(pattern, text)
        assert hits, f"{path.name} no longer states an unlabelled-cell count"
        for a, b, c, d in hits:
            unl, tot = (a or c), (b or d)
            assert int(unl.replace(",", "")) == counts["unlabelled"], path.name
            assert int(tot.replace(",", "")) == counts["total"], path.name


def test_readme_place_count_matches_the_extract():
    """The headline dataset size appears in several README sentences."""
    con = duckdb.connect()
    places = con.execute(
        f"SELECT count(*) FROM '{ROOT / 'data' / 'places.parquet'}'").fetchone()[0]
    text = (ROOT / "README.md").read_text()
    assert f"{places:,}" in text, f"README no longer quotes the real place count {places:,}"
