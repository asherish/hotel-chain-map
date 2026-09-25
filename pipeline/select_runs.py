"""Per-spider run selection.

Each spider independently gets the newest "acceptable" run. A candidate run
is acceptable when its feature count is at least ``min_fraction_of_median``
of a reference median, where the reference is the median of the last
``median_window`` non-zero feature counts from runs *older than the
candidate* (scanning back at most ``median_lookback_limit`` runs). Using
only history older than the candidate prevents a degraded run from
validating itself after an outage, when it would otherwise be the only
non-zero sample in the window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import median
from typing import Callable, Sequence

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunInfo:
    """The minimum we need to know about one All the Places run."""

    run_id: str
    start_time: str
    stats_url: str
    # Base URL of the run's files, e.g. ".../runs/<run_id>". Derived from the
    # run's output_url so we follow wherever upstream actually hosts the data.
    output_base: str


@dataclass(frozen=True)
class Selection:
    run: RunInfo
    features: int
    reference_median: float | None


def spider_output_url(run: RunInfo, spider: str) -> str:
    return f"{run.output_base}/output/{spider}.geojson"


def run_info_from_history(entry: dict) -> RunInfo | None:
    """Build a RunInfo from one history.json entry, or None if it predates
    the metadata fields we rely on (old runs only carry run_id/start_time)."""
    if not entry.get("stats_url") or not entry.get("output_url"):
        return None
    # output_url looks like ".../runs/<run_id>/output.zip"; its parent
    # directory is the base for all per-run files, including the per-spider
    # GeoJSON at "<base>/output/<spider>.geojson" (verified against the
    # redirect target of /runs/latest/output/<spider>.geojson).
    output_base = entry["output_url"].rsplit("/", 1)[0]
    return RunInfo(entry["run_id"], entry.get("start_time", ""), entry["stats_url"], output_base)


def select_run(
    spider: str,
    runs: Sequence[RunInfo],
    get_features: Callable[[RunInfo, str], int],
    *,
    candidate_runs: int,
    median_window: int,
    median_lookback_limit: int,
    min_fraction_of_median: float,
) -> Selection | None:
    """Pick the newest acceptable run for one spider.

    ``runs`` must be ordered oldest to newest. ``get_features`` returns the
    spider's feature count for a run (it is expected to cache/fetch lazily,
    so we only touch the stats files we actually need).
    Returns None when no recent run is acceptable; callers must then keep
    the previously published data rather than overwrite it.
    """
    candidates = list(runs[-candidate_runs:])
    for index in range(len(runs) - 1, len(runs) - 1 - len(candidates), -1):
        run = runs[index]
        features = get_features(run, spider)
        if features <= 0:
            log.info("%s: run %s has no features, skipping", spider, run.run_id)
            continue
        reference = _reference_median(
            spider, runs, index, get_features, median_window, median_lookback_limit
        )
        if reference is None:
            # No non-zero history within the lookback window. Accept so that
            # brand-new spiders can bootstrap, but say so loudly.
            log.warning(
                "%s: run %s (%d features) accepted without a reference median "
                "(no non-zero history in the last %d runs)",
                spider, run.run_id, features, median_lookback_limit,
            )
            return Selection(run, features, None)
        if features >= min_fraction_of_median * reference:
            log.info(
                "%s: selected run %s (%d features, median of previous non-zero runs %.0f)",
                spider, run.run_id, features, reference,
            )
            return Selection(run, features, reference)
        log.warning(
            "%s: run %s rejected (%d features is below %.0f%% of median %.0f)",
            spider, run.run_id, features, min_fraction_of_median * 100, reference,
        )
    log.warning("%s: no acceptable run among the last %d runs", spider, len(candidates))
    return None


def _reference_median(
    spider: str,
    runs: Sequence[RunInfo],
    candidate_index: int,
    get_features: Callable[[RunInfo, str], int],
    median_window: int,
    median_lookback_limit: int,
) -> float | None:
    """Median of the last ``median_window`` non-zero counts before the candidate."""
    non_zero: list[int] = []
    oldest = max(0, candidate_index - median_lookback_limit)
    for index in range(candidate_index - 1, oldest - 1, -1):
        features = get_features(runs[index], spider)
        if features > 0:
            non_zero.append(features)
            if len(non_zero) >= median_window:
                break
    if not non_zero:
        return None
    return float(median(non_zero))
