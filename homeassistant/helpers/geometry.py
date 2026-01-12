"""Geometry helpers for zone polygon support.

This module provides utilities for working with geometric shapes in zones,
particularly for polygon zones using GeoJSON format and Shapely library.

GeoJSON coordinate order: [longitude, latitude] (x, y)
Note: This differs from typical lat/lon order used elsewhere in Home Assistant.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from typing import Any

from shapely import prepare
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.prepared import PreparedGeometry


# Cache for prepared geometries
# Key: (zone_id, geometry_hash)
# Value: PreparedGeometry
_GEOMETRY_CACHE: dict[tuple[str, str], PreparedGeometry] = {}


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
    zone_id: str, geojson: dict[str, Any]
) -> PreparedGeometry:
    """Build and cache a prepared geometry for efficient containment checks.

    Prepared geometries are optimized for repeated spatial predicates like
    contains() and covers(). The cache is keyed by zone_id and geometry content
    to automatically invalidate when the geometry changes.

    Thread-safety: Reads are safe, but concurrent updates should be avoided.
    In practice, zone updates happen on the event loop, so this is safe.

    Args:
        zone_id: Unique zone identifier
        geojson: GeoJSON geometry dictionary

    Returns:
        PreparedGeometry for efficient spatial operations
    """
    geom_hash = _hash_geometry(geojson)
    cache_key = (zone_id, geom_hash)

    # Check if we have a cached prepared geometry
    if cache_key not in _GEOMETRY_CACHE:
        # Build the geometry from GeoJSON
        geom = build_geometry_from_geojson(geojson)
        # Prepare it for efficient spatial operations
        prepared = prepare(geom)
        # Cache it
        _GEOMETRY_CACHE[cache_key] = prepared

        # Clean up old cache entries for this zone_id (different geometry)
        _invalidate_zone_cache(zone_id, exclude_key=cache_key)

    return _GEOMETRY_CACHE[cache_key]


def _invalidate_zone_cache(zone_id: str, exclude_key: tuple[str, str] | None = None) -> None:
    """Remove old cached geometries for a zone.

    Args:
        zone_id: Zone identifier to invalidate
        exclude_key: Cache key to keep (the new geometry)
    """
    keys_to_remove = [
        key for key in _GEOMETRY_CACHE if key[0] == zone_id and key != exclude_key
    ]
    for key in keys_to_remove:
        del _GEOMETRY_CACHE[key]


def invalidate_cache(zone_id: str) -> None:
    """Invalidate all cached geometries for a zone.

    Call this when a zone is deleted or its geometry type changes
    (e.g., circle <-> polygon).

    Args:
        zone_id: Zone identifier to invalidate
    """
    _invalidate_zone_cache(zone_id)


def contains_point(
    zone_id: str, geojson: dict[str, Any], longitude: float, latitude: float
) -> bool:
    """Check if a point is inside the polygon using cached prepared geometry.

    Uses the covers() predicate which includes boundary points, reducing
    flapping when a device is near zone edges.

    GeoJSON coordinate order: [longitude, latitude] (x, y)
    Point coordinates must be provided as (longitude, latitude) to match.

    Args:
        zone_id: Zone identifier for caching
        geojson: GeoJSON geometry dictionary
        longitude: Point longitude (x coordinate)
        latitude: Point latitude (y coordinate)

    Returns:
        True if point is inside (or on boundary of) the polygon
    """
    prepared_geom = prepare_and_cache_geometry(zone_id, geojson)
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
    prepared = prepare(geom)
    return prepared.covers(point)


def clear_all_caches() -> None:
    """Clear all geometry caches.

    Useful for testing or when Home Assistant restarts.
    """
    _GEOMETRY_CACHE.clear()
    _cached_point_check.cache_clear()
