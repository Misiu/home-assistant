"""Test zone polygon support with GeoJSON and Shapely."""

from typing import Any

import pytest

from homeassistant import setup
from homeassistant.components import zone
from homeassistant.components.zone import DOMAIN
from homeassistant.components.zone.const import TYPE_CIRCLE, TYPE_POLYGON
from homeassistant.const import ATTR_ICON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry
from tests.typing import WebSocketGenerator


def create_polygon_geojson(points: list[list[float]]) -> dict[str, Any]:
    """Create a GeoJSON polygon from lat/lon points."""
    # Convert [lat, lon] to [lon, lat] for GeoJSON
    coords = [[lon, lat] for lat, lon in points]
    # Ensure ring is closed
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


async def test_setup_polygon_zone(hass: HomeAssistant) -> None:
    """Test setting up a polygon zone with GeoJSON geometry."""
    points = [
        [32.882630, -117.240536],
        [32.882747, -117.236276],
        [32.879077, -117.235812],
        [32.880573, -117.241177],
    ]
    geojson = create_polygon_geojson(points)
    
    info = {
        "name": "Test Polygon Zone",
        "latitude": 32.880837,
        "longitude": -117.237561,
        "zone_type": TYPE_POLYGON,
        "geometry": geojson,
        "passive": True,
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    assert len(hass.states.async_entity_ids("zone")) == 2  # home + test zone
    state = hass.states.get("zone.test_polygon_zone")
    assert state is not None
    assert info["name"] == state.name
    assert info["latitude"] == state.attributes["latitude"]
    assert info["longitude"] == state.attributes["longitude"]
    assert info["passive"] == state.attributes["passive"]
    assert state.attributes["zone_type"] == TYPE_POLYGON
    # Verify GeoJSON geometry is stored
    assert "geometry" in state.attributes
    assert state.attributes["geometry"]["type"] == "Polygon"
    assert state.attributes["geometry"] == geojson


async def test_in_zone_polygon_inside(hass: HomeAssistant) -> None:
    """Test point inside polygon zone."""
    latitude = 32.880600
    longitude = -117.237561
    
    points = [
        [32.882630, -117.240536],
        [32.882747, -117.236276],
        [32.879077, -117.235812],
        [32.880573, -117.241177],
    ]
    geojson = create_polygon_geojson(points)
    
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Polygon Zone",
                    "latitude": latitude,
                    "longitude": longitude,
                    "zone_type": TYPE_POLYGON,
                    "geometry": geojson,
                    "passive": False,
                }
            ]
        },
    )

    zone_state = hass.states.get("zone.polygon_zone")
    assert zone_state is not None
    assert zone.in_zone(zone_state, latitude, longitude)


async def test_in_zone_polygon_outside(hass: HomeAssistant) -> None:
    """Test point outside polygon zone."""
    latitude = 31.880600  # Far outside
    longitude = -117.237561
    
    points = [
        [32.882630, -117.240536],
        [32.882747, -117.236276],
        [32.879077, -117.235812],
        [32.880573, -117.241177],
    ]
    geojson = create_polygon_geojson(points)
    
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Polygon Zone",
                    "latitude": 32.880600,
                    "longitude": longitude,
                    "zone_type": TYPE_POLYGON,
                    "geometry": geojson,
                    "passive": False,
                }
            ]
        },
    )

    zone_state = hass.states.get("zone.polygon_zone")
    assert zone_state is not None
    assert not zone.in_zone(zone_state, latitude, longitude)


async def test_active_zone_polygon(hass: HomeAssistant) -> None:
    """Test finding active polygon zone."""
    latitude = 32.880600
    longitude = -117.237561
    
    points = [
        [32.882630, -117.240536],
        [32.882747, -117.236276],
        [32.879077, -117.235812],
        [32.880573, -117.241177],
    ]
    geojson = create_polygon_geojson(points)
    
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Polygon Zone",
                    "latitude": latitude,
                    "longitude": longitude,
                    "zone_type": TYPE_POLYGON,
                    "geometry": geojson,
                }
            ]
        },
    )

    active = zone.async_active_zone(hass, latitude, longitude)
    assert active is not None
    assert active.entity_id == "zone.polygon_zone"


async def test_circle_zone_still_works(hass: HomeAssistant) -> None:
    """Test that circular zones still work correctly."""
    info = {
        "name": "Circle Zone",
        "latitude": 32.880837,
        "longitude": -117.237561,
        "zone_type": TYPE_CIRCLE,
        "radius": 250,
        "passive": False,
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    state = hass.states.get("zone.circle_zone")
    assert state is not None
    assert state.attributes["zone_type"] == TYPE_CIRCLE
    assert state.attributes["radius"] == 250

    # Test in_zone for circle
    assert zone.in_zone(state, 32.880837, -117.237561)
    assert not zone.in_zone(state, 32.9, -117.3)  # Outside


async def test_default_circle_zone(hass: HomeAssistant) -> None:
    """Test that zones default to circle type."""
    info = {
        "name": "Default Zone",
        "latitude": 32.880837,
        "longitude": -117.237561,
        "radius": 100,
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    state = hass.states.get("zone.default_zone")
    assert state is not None
    assert state.attributes["zone_type"] == TYPE_CIRCLE


async def test_polygon_boundary_behavior(hass: HomeAssistant) -> None:
    """Test that points on polygon boundary are considered inside."""
    # Simple square polygon
    points = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    geojson = create_polygon_geojson(points)
    
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Square Zone",
                    "latitude": 0.5,
                    "longitude": 0.5,
                    "zone_type": TYPE_POLYGON,
                    "geometry": geojson,
                }
            ]
        },
    )

    zone_state = hass.states.get("zone.square_zone")
    assert zone_state is not None

    # Point on edge should be inside (covers() includes boundary)
    assert zone.in_zone(zone_state, 0.5, 0.0)  # Bottom edge
    assert zone.in_zone(zone_state, 0.0, 0.5)  # Left edge

    # Point at corner should be inside
    assert zone.in_zone(zone_state, 0.0, 0.0)  # Bottom-left corner

    # Point clearly inside
    assert zone.in_zone(zone_state, 0.5, 0.5)  # Center

    # Point clearly outside
    assert not zone.in_zone(zone_state, 2.0, 2.0)


async def test_polygon_zone_missing_geometry(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test polygon zone without geometry attribute logs warning."""
    # Create a polygon zone but don't provide geometry
    # This shouldn't normally happen but we should handle it gracefully
    info = {
        "name": "Invalid Polygon",
        "latitude": 32.880837,
        "longitude": -117.237561,
        "zone_type": TYPE_POLYGON,
        # Missing geometry!
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    zone_state = hass.states.get("zone.invalid_polygon")
    assert zone_state is not None
    
    # Trying to check if point is in zone should log warning and return False
    result = zone.in_zone(zone_state, 32.880837, -117.237561)
    assert not result
    assert "missing geometry attribute" in caplog.text.lower()


async def test_ws_create_polygon_zone(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test creating polygon zone via WebSocket."""
    assert await setup.async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)

    points = [[32.88, -117.24], [32.89, -117.24], [32.89, -117.23], [32.88, -117.23]]
    geojson = create_polygon_geojson(points)

    await client.send_json(
        {
            "id": 6,
            "type": f"{DOMAIN}/create",
            "name": "WS Polygon Zone",
            "latitude": 32.88,
            "longitude": -117.24,
            "passive": True,
            "zone_type": TYPE_POLYGON,
            "geometry": geojson,
        }
    )
    resp = await client.receive_json()
    assert resp["success"]

    state = hass.states.get("zone.ws_polygon_zone")
    assert state is not None
    assert state.attributes["zone_type"] == TYPE_POLYGON
    assert state.attributes["geometry"] == geojson


async def test_two_zone_types_coexist(hass: HomeAssistant) -> None:
    """Test that circle and polygon zones can coexist."""
    points = [[32.88, -117.24], [32.89, -117.24], [32.89, -117.23], [32.88, -117.23]]
    geojson = create_polygon_geojson(points)
    
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Circle Zone",
                    "latitude": 32.880837,
                    "longitude": -117.237561,
                    "zone_type": TYPE_CIRCLE,
                    "radius": 250,
                },
                {
                    "name": "Polygon Zone",
                    "latitude": 32.88,
                    "longitude": -117.24,
                    "zone_type": TYPE_POLYGON,
                    "geometry": geojson,
                },
            ]
        },
    )

    # Should have 3 zones: home + circle + polygon
    assert len(hass.states.async_entity_ids("zone")) == 3

    circle_zone = hass.states.get("zone.circle_zone")
    polygon_zone = hass.states.get("zone.polygon_zone")

    assert circle_zone is not None
    assert polygon_zone is not None
    assert circle_zone.attributes["zone_type"] == TYPE_CIRCLE
    assert polygon_zone.attributes["zone_type"] == TYPE_POLYGON

    # Test both zone types work
    assert zone.in_zone(circle_zone, 32.880837, -117.237561)
    assert zone.in_zone(polygon_zone, 32.885, -117.235)
