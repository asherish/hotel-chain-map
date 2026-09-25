"""Unit tests for per-spider run selection. No network access."""

import json
from pathlib import Path

from pipeline.select_runs import RunInfo, run_info_from_history, select_run, spider_output_url

FIXTURES = Path(__file__).parent / "fixtures"

DEFAULTS = {
    "candidate_runs": 8,
    "median_window": 8,
    "median_lookback_limit": 52,
    "min_fraction_of_median": 0.7,
}


def make_runs(counts):
    """Build runs (oldest to newest) and a get_features fn from a count list."""
    runs = [
        RunInfo(f"run-{i:03d}", f"start-{i:03d}", f"https://x/{i}/stats", f"https://x/{i}")
        for i in range(len(counts))
    ]
    by_id = {run.run_id: count for run, count in zip(runs, counts)}

    def get_features(run, spider):
        return by_id[run.run_id]

    return runs, get_features


def select(counts, **overrides):
    runs, get_features = make_runs(counts)
    return select_run("spider", runs, get_features, **{**DEFAULTS, **overrides})


def test_newest_healthy_run_is_selected():
    result = select([1000] * 10)
    assert result is not None
    assert result.run.run_id == "run-009"
    assert result.features == 1000
    assert result.reference_median == 1000


def test_degraded_newest_run_is_skipped_for_older_healthy_one():
    result = select([1000] * 9 + [300])
    assert result is not None
    assert result.run.run_id == "run-008"


def test_no_acceptable_run_returns_none():
    # Healthy history, then every recent candidate is degraded or empty.
    assert select([1000] * 10 + [0, 0, 100, 0, 0, 200, 0, 0]) is None


def test_all_zero_returns_none():
    assert select([0] * 10) is None


def test_recovery_at_normal_level_is_accepted():
    # Outage (zeros) then a comeback in line with pre-outage history.
    result = select([195, 195, 195, 0, 0, 0, 0, 0, 0, 0, 201])
    assert result is not None
    assert result.run.run_id == "run-010"
    assert result.reference_median == 195


def test_degraded_recovery_does_not_validate_itself():
    # After an outage the only non-zero count in the candidate window is the
    # candidate itself; the reference median must come from older runs, so a
    # weak comeback is rejected.
    assert select([1000, 1000, 1000, 0, 0, 0, 0, 0, 0, 0, 300]) is None


def test_bootstrap_without_history_is_accepted():
    # A brand-new spider has no non-zero history at all: accept, with a
    # warning, so it can publish its first data.
    result = select([0, 0, 50])
    assert result is not None
    assert result.run.run_id == "run-002"
    assert result.reference_median is None


def test_history_beyond_lookback_limit_is_ignored():
    # The healthy history is too far in the past to serve as a reference.
    counts = [1000, 1000] + [0] * 60 + [50]
    result = select(counts)
    assert result is not None
    assert result.reference_median is None


def test_median_uses_only_last_window_of_nonzero_counts():
    # With a 3-value window the reference median is 1000 and 400 is rejected;
    # a wider window lets the old tiny counts drag the median down enough for
    # the same candidate to pass. Only the newest run is a candidate here.
    counts = [10, 10, 10, 1000, 1000, 1000, 400]
    assert select(counts, candidate_runs=1, median_window=3) is None
    result = select(counts, candidate_runs=1, median_window=8)
    assert result is not None
    assert result.run.run_id == "run-006"


def test_run_info_from_history_skips_runs_without_metadata():
    entries = json.loads((FIXTURES / "history_sample.json").read_text())
    runs = [info for entry in entries if (info := run_info_from_history(entry)) is not None]
    assert [run.run_id for run in runs] == ["2026-09-12-13-32-21", "2026-09-19-13-32-18"]
    assert runs[1].output_base == "https://example.com/runs/2026-09-19-13-32-18"
    assert (
        spider_output_url(runs[1], "hyatt")
        == "https://example.com/runs/2026-09-19-13-32-18/output/hyatt.geojson"
    )
