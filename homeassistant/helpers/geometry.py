"""Geometry helpers for Home Assistant.

This module provides utilities for working with geometric shapes throughout
Home Assistant, particularly for geospatial operations using GeoJSON format
and the Shapely library.

Common use cases:
- Zone polygon containment checks
- Geographic area discovery for integrations
- Location-based automation triggers
- Geofencing operations

GeoJSON coordinate order: [longitude, latitude] (x, y)
Note: This differs from typical lat/lon order used elsewhere in Home Assistant.

Coordinate system: WGS84 (EPSG:4326)
Note: Coordinates are treated as planar for efficiency. For high-precision
geodesic calculations over large distances, consider using specialized libraries.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from typing import Any

from shapely import prepare
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry


# Cache for geometries (prepared in-place via shapely.prepare())
# Key: (identifier, geometry_hash)
# Value: BaseGeometry (prepared)
_GEOMETRY_CACHE: dict[tuple[str, str], BaseGeometry] = {}


def _hash_geometry(geojson: dict[str, Any]) -> str:
    """Create a stable hash of GeoJSON geometry for cache invalidation.

    Args:
        geojson: GeoJSON geometry dictionary

    Returns:
        SHA256 hash of normalized GeoJSON coordinates
    """
    # Use sorted JSON to ensure consistent hashing
    normalized = json.dumps(geojson, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


def build_geometry_from_geojson(geojson: dict[str, Any]) -> BaseGeometry:
    """Build a Shapely geometry from a GeoJSON geometry dictionary.

    GeoJSON coordinate order: [longitude, latitude] (x, y)

    Args:
        geojson: GeoJSON geometry dict, e.g.,
                 {"type": "Polygon", "coordinates": [[[lon, lat], ...]]}

    Returns:
        Shapely geometry object

    Raises:
        ValueError: If GeoJSON is invalid
    """
    try:
        return shape(geojson)
    except Exception as err:
        raise ValueError(f"Invalid GeoJSON geometry: {err}") from err


def prepare_and_cache_geometry(
    identifier: str, geojson: dict[str, Any]
) -> BaseGeometry:
    """Build and cache a prepared geometry for efficient containment checks.

    Prepared geometries are optimized for repeated spatial predicates like
    contains() and covers(). The cache is keyed by identifier and geometry content
    to automatically invalidate when the geometry changes.

    In Shapely 2.x, prepare() modifies the geometry in-place for optimization.

    This function is thread-safe for reads but should be called from the event
    loop for writes to avoid race conditions.

    Args:
        identifier: Unique identifier for caching (e.g., zone.home, integration_name, device_id)
        geojson: GeoJSON geometry dictionary

    Returns:
        Prepared BaseGeometry for efficient spatial operations
    """
    geom_hash = _hash_geometry(geojson)
    cache_key = (identifier, geom_hash)

    # Check if we have a cached prepared geometry
    if cache_key not in _GEOMETRY_CACHE:
        # Build the geometry from GeoJSON
        geom = build_geometry_from_geojson(geojson)
        # Prepare it for efficient spatial operations (in-place in Shapely 2.x)
        prepare(geom)
        # Cache it
        _GEOMETRY_CACHE[cache_key] = geom

        # Clean up old cache entries for this identifier (different geometry)
        _invalidate_cache(identifier, exclude_key=cache_key)

    return _GEOMETRY_CACHE[cache_key]


def _invalidate_cache(identifier: str, exclude_key: tuple[str, str] | None = None) -> None:
    """Remove old cached geometries for an identifier.

    Args:
        identifier: Identifier to invalidate
        exclude_key: Cache key to keep (the new geometry)
    """
    keys_to_remove = [
        key for key in _GEOMETRY_CACHE if key[0] == identifier and key != exclude_key
    ]
    for key in keys_to_remove:
        del _GEOMETRY_CACHE[key]


def invalidate_cache(identifier: str) -> None:
    """Invalidate all cached geometries for an identifier.

    Call this when a zone/integration/feature is deleted or its geometry type changes.

    Args:
        identifier: Identifier to invalidate (e.g., zone.home, integration_name, device_id)
    """
    _invalidate_cache(identifier)


def contains_point(
    identifier: str, geojson: dict[str, Any], longitude: float, latitude: float
) -> bool:
    """Check if a point is inside a geometry using cached prepared geometry.

    Uses the covers() predicate which includes boundary points, reducing
    flapping when a device is near geometry edges.

    GeoJSON coordinate order: [longitude, latitude] (x, y)
    Point coordinates must be provided as (longitude, latitude) to match.

    Args:
        identifier: Unique identifier for caching (e.g., zone.home, integration_name, device_id)
        geojson: GeoJSON geometry dictionary
        longitude: Point longitude (x coordinate)
        latitude: Point latitude (y coordinate)

    Returns:
        True if point is inside (or on boundary of) the geometry
    """
    prepared_geom = prepare_and_cache_geometry(identifier, geojson)
    point = Point(longitude, latitude)  # Shapely Point expects (x, y)
    return prepared_geom.covers(point)


def points_to_geojson_polygon(points: list[list[float]]) -> dict[str, Any]:
    """Convert a list of coordinate points to a GeoJSON Polygon.

    Handles coordinate order conversion:
    - Input points are assumed to be [latitude, longitude] (HA convention)
    - Output GeoJSON uses [longitude, latitude] (GeoJSON/Shapely convention)

    Ensures the polygon ring is closed (first point == last point).

    Args:
        points: List of [lat, lon] coordinate pairs

    Returns:
        GeoJSON Polygon geometry dictionary

    Raises:
        ValueError: If fewer than 3 points provided
    """
    if len(points) < 3:
        raise ValueError("Polygon must have at least 3 points")

    # Convert [lat, lon] to [lon, lat] for GeoJSON
    coords = [[lon, lat] for lat, lon in points]

    # Ensure ring is closed
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    return {"type": "Polygon", "coordinates": [coords]}


def point_to_geojson(latitude: float, longitude: float) -> dict[str, Any]:
    """Convert a lat/lon coordinate to a GeoJSON Point.

    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate

    Returns:
        GeoJSON Point geometry dictionary
    """
    return {"type": "Point", "coordinates": [longitude, latitude]}


def distance_between_points(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculate approximate distance between two points in meters.

    Uses Haversine formula for spherical distance calculation.
    Suitable for most Home Assistant use cases.

    For high-precision geodesic calculations, consider using
    homeassistant.util.location.distance() which uses Vincenty formula.

    Args:
        lat1: Latitude of first point
        lon1: Longitude of first point
        lat2: Latitude of second point
        lon2: Longitude of second point

    Returns:
        Distance in meters
    """
    from math import asin, cos, radians, sin, sqrt

    # Earth's radius in meters
    R = 6371000

    # Convert to radians
    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)

    # Haversine formula
    a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    c = 2 * asin(sqrt(a))

    return R * c


def create_circle_polygon(
    latitude: float, longitude: float, radius_meters: float, num_points: int = 32
) -> dict[str, Any]:
    """Create a GeoJSON Polygon approximating a circle.

    Useful for converting circular zones to polygon format for uniform handling.

    Args:
        latitude: Center latitude
        longitude: Center longitude
        radius_meters: Radius in meters
        num_points: Number of points to approximate the circle (default: 32)

    Returns:
        GeoJSON Polygon geometry dictionary approximating a circle
    """
    from math import cos, radians, sin

    # Approximate degrees per meter at this latitude
    # 1 degree latitude ≈ 111,320 meters
    # 1 degree longitude ≈ 111,320 * cos(latitude) meters
    lat_offset = radius_meters / 111320
    lon_offset = radius_meters / (111320 * abs(cos(radians(latitude))))

    points = []
    for i in range(num_points):
        angle = 2 * 3.14159265359 * i / num_points
        lat = latitude + lat_offset * sin(angle)
        lon = longitude + lon_offset * cos(angle)
        points.append([lon, lat])

    # Close the ring
    points.append(points[0])

    return {"type": "Polygon", "coordinates": [points]}


def geometry_contains_geometry(
    outer_geojson: dict[str, Any], inner_geojson: dict[str, Any]
) -> bool:
    """Check if one geometry completely contains another geometry.

    Useful for checking if a point/area is within another area.

    Args:
        outer_geojson: GeoJSON geometry that should contain the other
        inner_geojson: GeoJSON geometry to check if contained

    Returns:
        True if outer geometry contains inner geometry
    """
    outer_geom = build_geometry_from_geojson(outer_geojson)
    inner_geom = build_geometry_from_geojson(inner_geojson)
    return outer_geom.contains(inner_geom)


def geometries_intersect(
    geojson1: dict[str, Any], geojson2: dict[str, Any]
) -> bool:
    """Check if two geometries intersect.

    Useful for proximity detection and overlap checking.

    Args:
        geojson1: First GeoJSON geometry
        geojson2: Second GeoJSON geometry

    Returns:
        True if geometries intersect
    """
    geom1 = build_geometry_from_geojson(geojson1)
    geom2 = build_geometry_from_geojson(geojson2)
    return geom1.intersects(geom2)


@lru_cache(maxsize=128)
def _cached_point_check(
    geojson_str: str, longitude: float, latitude: float
) -> bool:
    """LRU cached point-in-polygon check for frequently checked locations.

    This provides an additional layer of caching for specific point checks,
    useful when the same coordinates are checked repeatedly.

    Args:
        geojson_str: JSON string of GeoJSON geometry
        longitude: Point longitude
        latitude: Point latitude

    Returns:
        True if point is inside the polygon
    """
    geojson = json.loads(geojson_str)
    geom = build_geometry_from_geojson(geojson)
    point = Point(longitude, latitude)
    # Prepare the geometry for faster checks
    prepare(geom)
    return geom.covers(point)


def clear_all_caches() -> None:
    """Clear all geometry caches.

    Useful for testing or when Home Assistant restarts.
    """
    _GEOMETRY_CACHE.clear()
    _cached_point_check.cache_clear()
