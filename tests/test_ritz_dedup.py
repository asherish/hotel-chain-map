"""Unit tests for the Ritz-Carlton de-duplication. No network access."""

from pipeline.transform import drop_ritz_duplicates, haversine_m


def point(feature_id, lon, lat, brand=None):
    properties = {"brand": brand} if brand else {}
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }


# Roughly 0.001 degrees of latitude is 111 m.
def test_ritz_near_marriott_ritz_is_dropped():
    ritz = [point("r1", 139.7, 35.6)]
    marriott = [point("m1", 139.7, 35.601, brand="The Ritz-Carlton")]
    assert drop_ritz_duplicates(ritz, marriott) == []


def test_ritz_far_from_marriott_ritz_is_kept():
    ritz = [point("r1", 139.7, 35.6)]
    marriott = [point("m1", 139.7, 35.65, brand="The Ritz-Carlton")]
    assert drop_ritz_duplicates(ritz, marriott) == ritz


def test_nearby_non_ritz_marriott_does_not_drop():
    ritz = [point("r1", 139.7, 35.6)]
    marriott = [point("m1", 139.7, 35.601, brand="Courtyard")]
    assert drop_ritz_duplicates(ritz, marriott) == ritz


def test_brand_match_is_case_insensitive():
    ritz = [point("r1", 139.7, 35.6)]
    marriott = [point("m1", 139.7, 35.601, brand="THE RITZ-CARLTON")]
    assert drop_ritz_duplicates(ritz, marriott) == []


def test_haversine_known_distance():
    # One degree of latitude is about 111.2 km.
    assert abs(haversine_m(0.0, 0.0, 0.0, 1.0) - 111_195) < 200
