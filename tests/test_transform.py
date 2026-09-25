"""Unit tests for feature slimming. No network access."""

import json
from pathlib import Path

from pipeline.transform import slim_collection, slim_feature

FIXTURES = Path(__file__).parent / "fixtures"


def load_sample():
    return json.loads((FIXTURES / "upstream_sample.geojson").read_text())["features"]


def test_slim_feature_keeps_only_map_fields():
    feature = next(f for f in load_sample() if f["id"] == "b-hotel")
    slim = slim_feature(feature)
    assert slim == {
        "type": "Feature",
        "id": "b-hotel",
        "geometry": {"type": "Point", "coordinates": [139.76731, 35.68096]},
        "properties": {
            "name": "Example Hotel Tokyo Station",
            "brand": "Example",
            "address": "1-9-1 Marunouchi, Chiyoda-ku, Tokyo",
            "country": "JP",
            "website": "https://example.com/tokyo",
        },
    }


def test_address_is_assembled_when_no_full_address():
    feature = next(f for f in load_sample() if f["id"] == "a-hotel")
    slim = slim_feature(feature)
    assert slim["properties"]["address"] == "22, Buckingham Gate, London, SW1E 6LB"


def test_feature_without_location_is_dropped():
    feature = next(f for f in load_sample() if f["id"] == "no-location")
    assert slim_feature(feature) is None


def test_polygon_is_represented_by_its_centroid():
    feature = next(f for f in load_sample() if f["id"] == "polygon-hotel")
    slim = slim_feature(feature)
    assert slim["geometry"] == {"type": "Point", "coordinates": [10.1, 50.1]}


def test_empty_properties_are_omitted():
    slim = slim_feature(
        {
            "type": "Feature",
            "id": "x",
            "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
            "properties": {"name": "  ", "brand": None},
        }
    )
    assert slim["properties"] == {}


def test_slim_collection_drops_unusable_features_and_sorts_by_id():
    slimmed = slim_collection(load_sample())
    assert [f["id"] for f in slimmed] == ["a-hotel", "b-hotel", "polygon-hotel"]


def test_out_of_range_coordinates_are_dropped():
    feature = {
        "type": "Feature",
        "id": "bad",
        "geometry": {"type": "Point", "coordinates": [999.0, 99.0]},
        "properties": {},
    }
    assert slim_feature(feature) is None
