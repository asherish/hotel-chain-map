"""Feature slimming and the Ritz-Carlton de-duplication.

The upstream GeoJSON carries many properties we do not need. We keep only
what the map shows, represent every feature as a point, and emit output in
a deterministic order so unchanged data produces no diff.
"""

from __future__ import annotations

import logging
import math
from typing import Iterable

log = logging.getLogger(__name__)

# ~1m precision; enough for a hotel marker and keeps files small and stable.
COORD_DECIMALS = 5

ADDRESS_PARTS = ("addr:housenumber", "addr:street", "addr:city", "addr:state", "addr:postcode")


def slim_feature(feature: dict) -> dict | None:
    """Reduce one upstream feature to the fields the map needs.

    Returns None for features without a usable location.
    """
    point = _as_point(feature.get("geometry"))
    if point is None:
        return None
    lon, lat = point
    properties = feature.get("properties") or {}
    slim_props = {
        "name": _clean(properties.get("name")),
        "brand": _clean(properties.get("brand")),
        "address": _address(properties),
        "country": _clean(properties.get("addr:country")),
        "website": _clean(properties.get("website")),
    }
    return {
        "type": "Feature",
        "id": feature.get("id") or _clean(properties.get("ref")) or "",
        "geometry": {
            "type": "Point",
            "coordinates": [round(lon, COORD_DECIMALS), round(lat, COORD_DECIMALS)],
        },
        "properties": {key: value for key, value in slim_props.items() if value},
    }


def slim_collection(features: Iterable[dict]) -> list[dict]:
    """Slim all features, dropping unusable ones, sorted for stable diffs."""
    slimmed = [slim for feature in features if (slim := slim_feature(feature)) is not None]
    # Sort by id, then by coordinates so features with empty ids stay stable.
    slimmed.sort(key=lambda f: (f["id"], f["geometry"]["coordinates"]))
    return slimmed


def _address(properties: dict) -> str | None:
    """Prefer the source-provided full address, else assemble a rough one."""
    full = _clean(properties.get("addr:full"))
    if full:
        return full
    parts = [part for key in ADDRESS_PARTS if (part := _clean(properties.get(key)))]
    return ", ".join(parts) if parts else None


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _as_point(geometry) -> tuple[float, float] | None:
    """Return (lon, lat) for a geometry, using the vertex centroid for
    anything that is not already a point. Hotels are effectively points, so
    an exact polygon centroid is not worth the extra code."""
    if not geometry or not isinstance(geometry, dict):
        return None
    coordinates = geometry.get("coordinates")
    if coordinates is None:
        return None
    positions = list(_positions(coordinates))
    if not positions:
        return None
    lon = sum(p[0] for p in positions) / len(positions)
    lat = sum(p[1] for p in positions) / len(positions)
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return lon, lat


def _positions(coordinates) -> Iterable[tuple[float, float]]:
    """Yield every (lon, lat) pair from arbitrarily nested coordinates."""
    if (
        isinstance(coordinates, (list, tuple))
        and len(coordinates) >= 2
        and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in coordinates[:2])
    ):
        yield float(coordinates[0]), float(coordinates[1])
        return
    if isinstance(coordinates, (list, tuple)):
        for child in coordinates:
            yield from _positions(child)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters."""
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def drop_ritz_duplicates(
    ritz_features: list[dict],
    marriott_features: list[dict],
    *,
    brand_substring: str = "ritz",
    distance_m: float = 500.0,
) -> list[dict]:
    """Drop ritz_carlton features that duplicate marriott_hotels ones.

    The marriott_hotels spider also emits some Ritz-Carlton properties. A
    ritz_carlton feature is considered a duplicate when a marriott feature
    whose brand contains ``brand_substring`` (case-insensitive) lies within
    ``distance_m`` meters.
    """
    marriott_ritz = [
        feature["geometry"]["coordinates"]
        for feature in marriott_features
        if brand_substring in feature.get("properties", {}).get("brand", "").lower()
    ]
    kept = []
    for feature in ritz_features:
        lon, lat = feature["geometry"]["coordinates"]
        if any(haversine_m(lon, lat, mlon, mlat) <= distance_m for mlon, mlat in marriott_ritz):
            continue
        kept.append(feature)
    dropped = len(ritz_features) - len(kept)
    if dropped:
        log.info("ritz_carlton: dropped %d features duplicated by marriott_hotels", dropped)
    return kept
