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


def clear_all_caches() -> None:
    """Clear all geometry caches.

    Useful for testing or when memory needs to be freed.
    """
    _GEOMETRY_CACHE.clear()
