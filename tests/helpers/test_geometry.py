"""Test geometry helper functions."""

from __future__ import annotations

import json

import pytest

from homeassistant.helpers import geometry


def test_hash_geometry() -> None:
    """Test geometry hashing for cache invalidation."""
    geojson1 = {
        "type": "Polygon",
        "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [1.0, 2.0]]],
    }
    geojson2 = {
        "type": "Polygon",
        "coordinates": [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [1.0, 2.0]]],
    }
    geojson3 = {
        "type": "Polygon",
        "coordinates": [[[1.0, 2.0], [3.0, 4.0], [7.0, 8.0], [1.0, 2.0]]],
    }

    hash1 = geometry._hash_geometry(geojson1)
    hash2 = geometry._hash_geometry(geojson2)
    hash3 = geometry._hash_geometry(geojson3)

    assert hash1 == hash2  # Same geometry should have same hash
    assert hash1 != hash3  # Different geometry should have different hash


def test_build_geometry_from_geojson() -> None:
    """Test building Shapely geometry from GeoJSON."""
    geojson = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }

    geom = geometry.build_geometry_from_geojson(geojson)
    assert geom.is_valid
    assert geom.geom_type == "Polygon"


def test_build_geometry_invalid_geojson() -> None:
    """Test building geometry from invalid GeoJSON raises error."""
    invalid_geojson = {"type": "InvalidType", "coordinates": []}

    with pytest.raises(ValueError, match="Invalid GeoJSON geometry"):
        geometry.build_geometry_from_geojson(invalid_geojson)


def test_prepare_and_cache_geometry() -> None:
    """Test preparing and caching geometries."""
    geometry.clear_all_caches()

    geojson = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }

    entity_id = "zone.test"
    prepared1 = geometry.prepare_and_cache_geometry(entity_id, geojson)
    prepared2 = geometry.prepare_and_cache_geometry(entity_id, geojson)

    # Should return the same cached instance
    assert prepared1 is prepared2


def test_cache_invalidation_on_geometry_change() -> None:
    """Test that cache is invalidated when geometry changes."""
    geometry.clear_all_caches()

    geojson1 = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }
    geojson2 = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]],
    }

    entity_id = "zone.test"
    prepared1 = geometry.prepare_and_cache_geometry(entity_id, geojson1)
    prepared2 = geometry.prepare_and_cache_geometry(entity_id, geojson2)

    # Different geometry should create new prepared geometry
    assert prepared1 is not prepared2


def test_invalidate_cache() -> None:
    """Test explicit cache invalidation."""
    geometry.clear_all_caches()

    geojson = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }

    entity_id = "zone.test"
    geometry.prepare_and_cache_geometry(entity_id, geojson)
    geometry.invalidate_cache(entity_id)

    # Cache should be empty for this zone
    assert not any(key[0] == entity_id for key in geometry._GEOMETRY_CACHE)


def test_contains_point_inside() -> None:
    """Test point containment check for point inside polygon."""
    geometry.clear_all_caches()

    # Square polygon from (0,0) to (1,1)
    # GeoJSON coordinates are [lon, lat]
    geojson = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }

    entity_id = "zone.test"
    # Point at (0.5, 0.5) - center of square
    assert geometry.contains_point(entity_id, geojson, 0.5, 0.5)


def test_contains_point_outside() -> None:
    """Test point containment check for point outside polygon."""
    geometry.clear_all_caches()

    # Square polygon from (0,0) to (1,1)
    geojson = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }

    entity_id = "zone.test"
    # Point at (2.0, 2.0) - outside square
    assert not geometry.contains_point(entity_id, geojson, 2.0, 2.0)


def test_contains_point_on_boundary() -> None:
    """Test that covers() includes boundary points."""
    geometry.clear_all_caches()

    # Square polygon from (0,0) to (1,1)
    geojson = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }

    entity_id = "zone.test"
    # Point exactly on the edge
    assert geometry.contains_point(entity_id, geojson, 0.5, 0.0)
    # Point at corner
    assert geometry.contains_point(entity_id, geojson, 0.0, 0.0)


def test_points_to_geojson_polygon() -> None:
    """Test converting points to GeoJSON polygon."""
    # Input points are [lat, lon] (HA convention)
    points = [[48.8566, 2.3522], [48.8576, 2.3522], [48.8576, 2.3532], [48.8566, 2.3532]]

    geojson = geometry.points_to_geojson_polygon(points)

    assert geojson["type"] == "Polygon"
    # GeoJSON coordinates are [lon, lat]
    coords = geojson["coordinates"][0]
    assert coords[0] == [2.3522, 48.8566]  # First point: [lon, lat]
    assert coords[-1] == coords[0]  # Ring should be closed


def test_points_to_geojson_polygon_auto_close() -> None:
    """Test that polygon ring is automatically closed."""
    points = [[48.8566, 2.3522], [48.8576, 2.3522], [48.8576, 2.3532]]

    geojson = geometry.points_to_geojson_polygon(points)

    coords = geojson["coordinates"][0]
    # Should have 4 points (3 + 1 to close)
    assert len(coords) == 4
    assert coords[0] == coords[-1]


def test_points_to_geojson_polygon_too_few_points() -> None:
    """Test that too few points raises error."""
    points = [[48.8566, 2.3522], [48.8576, 2.3522]]

    with pytest.raises(ValueError, match="at least 3 points"):
        geometry.points_to_geojson_polygon(points)


def test_coordinate_order_consistency() -> None:
    """Test that coordinate order is consistent throughout."""
    geometry.clear_all_caches()

    # Create a polygon using points (lat/lon order)
    # Paris area coordinates
    points = [
        [48.8566, 2.3522],  # lat, lon
        [48.8576, 2.3522],
        [48.8576, 2.3532],
        [48.8566, 2.3532],
    ]

    geojson = geometry.points_to_geojson_polygon(points)

    # Point inside: center of the polygon (lat=48.8571, lon=2.3527)
    entity_id = "zone.test"
    assert geometry.contains_point(entity_id, geojson, 2.3527, 48.8571)  # lon, lat

    # Point outside
    assert not geometry.contains_point(entity_id, geojson, 2.36, 48.86)  # lon, lat


def test_real_world_coordinates() -> None:
    """Test with real-world coordinates similar to PR test case."""
    geometry.clear_all_caches()

    # From the PR test case
    points = [
        [32.882630, -117.240536],
        [32.882747, -117.236276],
        [32.879077, -117.235812],
        [32.880573, -117.241177],
    ]

    geojson = geometry.points_to_geojson_polygon(points)

    entity_id = "zone.test"
    # Point that should be inside (from PR test)
    latitude = 32.880600
    longitude = -117.237561
    assert geometry.contains_point(entity_id, geojson, longitude, latitude)

    # Point that should be outside (from PR test)
    latitude_outside = 31.880600
    assert not geometry.contains_point(entity_id, geojson, longitude, latitude_outside)


def test_clear_all_caches() -> None:
    """Test clearing all caches."""
    geojson = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }

    entity_id = "zone.test"
    geometry.prepare_and_cache_geometry(entity_id, geojson)

    assert len(geometry._GEOMETRY_CACHE) > 0

    geometry.clear_all_caches()

    assert len(geometry._GEOMETRY_CACHE) == 0


def test_point_to_geojson() -> None:
    """Test converting a point to GeoJSON."""
    geojson = geometry.point_to_geojson(48.8566, 2.3522)
    
    assert geojson["type"] == "Point"
    assert geojson["coordinates"] == [2.3522, 48.8566]  # [lon, lat]


def test_distance_between_points() -> None:
    """Test distance calculation between two points."""
    # Paris to Paris (same point)
    dist = geometry.distance_between_points(48.8566, 2.3522, 48.8566, 2.3522)
    assert dist < 1  # Should be essentially 0
    
    # Paris to coordinates ~1km away
    dist = geometry.distance_between_points(48.8566, 2.3522, 48.8566, 2.3622)
    assert 700 < dist < 900  # Approximately 800 meters


def test_create_circle_polygon() -> None:
    """Test creating a circle approximation as polygon."""
    geojson = geometry.create_circle_polygon(48.8566, 2.3522, 100, num_points=8)
    
    assert geojson["type"] == "Polygon"
    # Should have 9 points (8 + 1 to close)
    assert len(geojson["coordinates"][0]) == 9
    # First and last should be the same (closed ring)
    assert geojson["coordinates"][0][0] == geojson["coordinates"][0][-1]


def test_geometry_contains_geometry() -> None:
    """Test checking if one geometry contains another."""
    # Large polygon
    outer = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]
    }
    
    # Small polygon inside
    inner = {
        "type": "Polygon",
        "coordinates": [[[2.0, 2.0], [4.0, 2.0], [4.0, 4.0], [2.0, 4.0], [2.0, 2.0]]]
    }
    
    # Polygon outside
    outside = {
        "type": "Polygon",
        "coordinates": [[[20.0, 20.0], [25.0, 20.0], [25.0, 25.0], [20.0, 25.0], [20.0, 20.0]]]
    }
    
    assert geometry.geometry_contains_geometry(outer, inner)
    assert not geometry.geometry_contains_geometry(outer, outside)


def test_geometries_intersect() -> None:
    """Test checking if two geometries intersect."""
    geom1 = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0], [0.0, 0.0]]]
    }
    
    # Overlapping polygon
    geom2 = {
        "type": "Polygon",
        "coordinates": [[[3.0, 3.0], [7.0, 3.0], [7.0, 7.0], [3.0, 7.0], [3.0, 3.0]]]
    }
    
    # Non-overlapping polygon
    geom3 = {
        "type": "Polygon",
        "coordinates": [[[10.0, 10.0], [15.0, 10.0], [15.0, 15.0], [10.0, 15.0], [10.0, 10.0]]]
    }
    
    assert geometry.geometries_intersect(geom1, geom2)
    assert not geometry.geometries_intersect(geom1, geom3)
