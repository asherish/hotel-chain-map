"""Entry point: update site/data from the latest healthy All the Places runs.

Run with ``uv run python -m pipeline``. The pipeline never overwrites good
data with a degraded snapshot: when no acceptable run exists for a spider,
the previously published file is kept and marked as stale in meta.json.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import requests

from . import fetch
from .select_runs import RunInfo, run_info_from_history, select_run, spider_output_url
from .transform import drop_ritz_duplicates, slim_collection

log = logging.getLogger("pipeline")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "site" / "data"


class StatsProvider:
    """Lazily fetches and caches per-run stats (one small JSON per run)."""

    def __init__(self, session: requests.Session):
        self._session = session
        self._cache: dict[str, dict[str, int]] = {}

    def get_features(self, run: RunInfo, spider: str) -> int:
        if run.run_id not in self._cache:
            stats = fetch.get_json(run.stats_url, self._session)
            self._cache[run.run_id] = {
                row["spider"]: row.get("features", 0) for row in stats.get("results", [])
            }
        return self._cache[run.run_id].get(spider, 0)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    selection_cfg = config["run_selection"]
    session = requests.Session()

    log.info("Fetching run history from %s", config["history_url"])
    history = fetch.get_json(config["history_url"], session)
    runs = [info for entry in history if (info := run_info_from_history(entry)) is not None]
    # Keep only what run selection can ever look at.
    window = selection_cfg["candidate_runs"] + selection_cfg["median_lookback_limit"]
    runs = runs[-window:]
    if not runs:
        log.error("No runs with stats metadata found in history")
        return 1
    log.info("Considering %d runs, newest %s", len(runs), runs[-1].run_id)

    stats = StatsProvider(session)
    previous_meta = _load_previous_meta()

    features_by_spider: dict[str, list[dict]] = {}
    meta_spiders: dict[str, dict] = {}
    for spider, spider_cfg in config["spiders"].items():
        selection = select_run(
            spider,
            runs,
            stats.get_features,
            candidate_runs=selection_cfg["candidate_runs"],
            median_window=selection_cfg["median_window"],
            median_lookback_limit=selection_cfg["median_lookback_limit"],
            min_fraction_of_median=selection_cfg["min_fraction_of_median"],
        )
        chain = spider_cfg["chain"]
        if selection is None:
            features, entry = _keep_previous(spider, chain, previous_meta)
        else:
            source_url = spider_output_url(selection.run, spider)
            log.info("%s: downloading %s", spider, source_url)
            collection = fetch.get_json(source_url, session)
            raw_features = collection.get("features", [])
            features = slim_collection(raw_features)
            log.info("%s: %d features kept of %d", spider, len(features), len(raw_features))
            entry = {
                "chain": chain,
                "run_id": selection.run.run_id,
                "run_start_time": selection.run.start_time,
                "source_url": source_url,
                "feature_count_raw": len(raw_features),
                "feature_count": len(features),
                "stale": False,
            }
        features_by_spider[spider] = features
        meta_spiders[spider] = entry

    _apply_ritz_dedup(config, features_by_spider, meta_spiders)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for spider, entry in meta_spiders.items():
        path = DATA_DIR / f"{spider}.geojson"
        if entry["stale"] and path.exists():
            # Never rewrite a kept file; its content is last week's good data.
            continue
        _write_feature_collection(path, features_by_spider[spider])

    meta = {
        "attribution": config["attribution"],
        "chains": {
            chain: {
                "color": chain_cfg["color"],
                "spiders": sorted(
                    spider for spider, cfg in config["spiders"].items() if cfg["chain"] == chain
                ),
            }
            for chain, chain_cfg in config["chains"].items()
        },
        "spiders": meta_spiders,
    }
    meta_path = DATA_DIR / "meta.json"
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    log.info("Wrote %s", meta_path)
    return 0


def _keep_previous(spider: str, chain: str, previous_meta: dict) -> tuple[list[dict], dict]:
    """Fall back to the previously published data for a spider, if any."""
    previous_entry = previous_meta.get("spiders", {}).get(spider)
    path = DATA_DIR / f"{spider}.geojson"
    if path.exists() and previous_entry and not previous_entry.get("no_data"):
        log.warning("%s: keeping previously published data (run %s)",
                    spider, previous_entry.get("run_id"))
        entry = dict(previous_entry)
        entry["chain"] = chain
        entry["stale"] = True
        # The kept file is not re-read; return an empty list as a placeholder
        # (the file itself is left untouched on disk).
        return [], entry
    log.warning("%s: no acceptable run and no previously published data", spider)
    return [], {
        "chain": chain,
        "stale": False,
        "no_data": True,
        "note": "No healthy recent run of this spider; see the All the Places issue tracker.",
    }


def _apply_ritz_dedup(config: dict, features_by_spider: dict, meta_spiders: dict) -> None:
    """Drop freshly fetched ritz_carlton features that duplicate Marriott ones.

    A stale ritz file was already de-duplicated when it was first published,
    so only a fresh ritz snapshot needs processing. If the Marriott data is
    stale this week, de-duplicate against the kept file on disk.
    """
    dedup_cfg = config["ritz_dedup"]
    ritz_spider = dedup_cfg["ritz_spider"]
    marriott_spider = dedup_cfg["marriott_spider"]
    ritz_entry = meta_spiders.get(ritz_spider)
    if ritz_entry is None or ritz_entry["stale"] or ritz_entry.get("no_data"):
        return
    marriott_entry = meta_spiders.get(marriott_spider, {})
    if marriott_entry.get("stale"):
        marriott_features = _read_feature_collection(DATA_DIR / f"{marriott_spider}.geojson")
    else:
        marriott_features = features_by_spider.get(marriott_spider, [])
    before = len(features_by_spider[ritz_spider])
    features_by_spider[ritz_spider] = drop_ritz_duplicates(
        features_by_spider[ritz_spider],
        marriott_features,
        brand_substring=dedup_cfg["brand_substring"],
        distance_m=dedup_cfg["distance_m"],
    )
    ritz_entry["feature_count"] = len(features_by_spider[ritz_spider])
    ritz_entry["ritz_duplicates_dropped"] = before - len(features_by_spider[ritz_spider])


def _load_previous_meta() -> dict:
    path = DATA_DIR / "meta.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _read_feature_collection(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("features", [])


def _write_feature_collection(path: Path, features: list[dict]) -> None:
    """One feature per line: small diffs when only a few hotels change."""
    with path.open("w", encoding="utf-8") as handle:
        handle.write('{"type":"FeatureCollection","features":[\n')
        for index, feature in enumerate(features):
            trailing = "," if index < len(features) - 1 else ""
            handle.write(json.dumps(feature, ensure_ascii=False, separators=(",", ":")) + trailing + "\n")
        handle.write("]}\n")
    log.info("Wrote %s (%d features)", path, len(features))


if __name__ == "__main__":
    sys.exit(main())
