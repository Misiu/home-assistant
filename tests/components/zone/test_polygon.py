"""Test zone polygon support with GeoJSON and Shapely."""

from typing import Any

import pytest

from homeassistant import setup
from homeassistant.components import zone
from homeassistant.components.zone import DOMAIN
from homeassistant.const import ATTR_ICON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry
from tests.typing import WebSocketGenerator


async def test_setup_polygon_zone_with_points(hass: HomeAssistant) -> None:
    """Test setting up a polygon zone with points."""
    info = {
        "name": "Test Polygon Zone",
        "latitude": 32.880837,
        "longitude": -117.237561,
        "zone_type": "polygon",
        "points": [
            [32.882630, -117.240536],
            [32.882747, -117.236276],
            [32.879077, -117.235812],
            [32.880573, -117.241177],
        ],
        "passive": True,
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    assert len(hass.states.async_entity_ids("zone")) == 2  # home + test zone
    state = hass.states.get("zone.test_polygon_zone")
    assert info["name"] == state.name
    assert info["latitude"] == state.attributes["latitude"]
    assert info["longitude"] == state.attributes["longitude"]
    assert info["passive"] == state.attributes["passive"]
    assert info["zone_type"] == state.attributes["zone_type"]
    assert info["points"] == state.attributes["points"]
    # Check that GeoJSON geometry is generated
    assert "geometry" in state.attributes
    assert state.attributes["geometry"]["type"] == "Polygon"


async def test_in_zone_polygon_inside(hass: HomeAssistant) -> None:
    """Test point inside polygon zone."""
    latitude = 32.880600
    longitude = -117.237561
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Polygon Zone",
                    "latitude": latitude,
                    "longitude": longitude,
                    "zone_type": "polygon",
                    "points": [
                        [32.882630, -117.240536],
                        [32.882747, -117.236276],
                        [32.879077, -117.235812],
                        [32.880573, -117.241177],
                    ],
                    "passive": True,
                }
            ]
        },
    )

    assert zone.in_zone(hass.states.get("zone.polygon_zone"), latitude, longitude)


async def test_in_zone_polygon_outside(hass: HomeAssistant) -> None:
    """Test point outside polygon zone."""
    latitude = 31.880600  # Far outside
    longitude = -117.237561
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Polygon Zone",
                    "latitude": 32.880600,
                    "longitude": longitude,
                    "zone_type": "polygon",
                    "points": [
                        [32.882630, -117.240536],
                        [32.882747, -117.236276],
                        [32.879077, -117.235812],
                        [32.880573, -117.241177],
                    ],
                    "passive": True,
                }
            ]
        },
    )

    assert not zone.in_zone(hass.states.get("zone.polygon_zone"), latitude, longitude)


async def test_active_zone_polygon(hass: HomeAssistant) -> None:
    """Test finding active polygon zone."""
    latitude = 32.880600
    longitude = -117.237561
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Polygon Zone",
                    "latitude": latitude,
                    "longitude": longitude,
                    "zone_type": "polygon",
                    "points": [
                        [32.882630, -117.240536],
                        [32.882747, -117.236276],
                        [32.879077, -117.235812],
                        [32.880573, -117.241177],
                    ],
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
        "zone_type": "circle",
        "radius": 250,
        "passive": False,
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    state = hass.states.get("zone.circle_zone")
    assert state.attributes["zone_type"] == "circle"
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
    assert state.attributes["zone_type"] == "circle"


async def test_ws_create_polygon_zone(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test creating polygon zone via WebSocket."""
    assert await setup.async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 6,
            "type": f"{DOMAIN}/create",
            "name": "WS Polygon Zone",
            "latitude": 32.88,
            "longitude": -117.24,
            "passive": True,
            "zone_type": "polygon",
            "points": [[32.88, -117.24], [32.89, -117.24], [32.89, -117.23], [32.88, -117.23]],
        }
    )
    resp = await client.receive_json()
    assert resp["success"]

    state = hass.states.get("zone.ws_polygon_zone")
    assert state.attributes["zone_type"] == "polygon"
    assert state.attributes["points"] == [
        [32.88, -117.24],
        [32.89, -117.24],
        [32.89, -117.23],
        [32.88, -117.23],
    ]
    assert "geometry" in state.attributes


async def test_import_polygon_config_entry(hass: HomeAssistant) -> None:
    """Test importing polygon zone from config entry."""
    entry = MockConfigEntry(
        domain="zone",
        data={
            "name": "Imported Polygon",
            "latitude": 32.88,
            "longitude": -117.24,
            "zone_type": "polygon",
            "points": [[32.88, -117.24], [32.89, -117.24], [32.89, -117.23]],
            "passive": False,
            "icon": "mdi:polygon",
        },
    )
    entry.add_to_hass(hass)
    assert await setup.async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    state = hass.states.get("zone.imported_polygon")
    assert state is not None
    assert state.attributes[zone.ATTR_TYPE] == "polygon"
    assert state.attributes[zone.ATTR_POINTS] == [
        [32.88, -117.24],
        [32.89, -117.24],
        [32.89, -117.23],
    ]
    assert state.attributes[ATTR_ICON] == "mdi:polygon"


async def test_polygon_boundary_behavior(hass: HomeAssistant) -> None:
    """Test that points on polygon boundary are considered inside."""
    # Simple square polygon
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Square Zone",
                    "latitude": 0.5,
                    "longitude": 0.5,
                    "zone_type": "polygon",
                    "points": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                }
            ]
        },
    )

    zone_state = hass.states.get("zone.square_zone")

    # Point on edge should be inside (covers() includes boundary)
    assert zone.in_zone(zone_state, 0.5, 0.0)  # Bottom edge
    assert zone.in_zone(zone_state, 0.0, 0.5)  # Left edge

    # Point at corner should be inside
    assert zone.in_zone(zone_state, 0.0, 0.0)  # Bottom-left corner

    # Point clearly inside
    assert zone.in_zone(zone_state, 0.5, 0.5)  # Center

    # Point clearly outside
    assert not zone.in_zone(zone_state, 2.0, 2.0)


async def test_coordinate_order_geojson(hass: HomeAssistant) -> None:
    """Test that coordinate order is correctly handled (lat/lon -> lon/lat)."""
    # Points in [lat, lon] format (HA convention)
    points = [[48.8566, 2.3522], [48.8576, 2.3522], [48.8576, 2.3532], [48.8566, 2.3532]]

    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Paris Zone",
                    "latitude": 48.8571,
                    "longitude": 2.3527,
                    "zone_type": "polygon",
                    "points": points,
                }
            ]
        },
    )

    zone_state = hass.states.get("zone.paris_zone")
    geom = zone_state.attributes["geometry"]

    # GeoJSON coordinates should be [lon, lat]
    first_coord = geom["coordinates"][0][0]
    assert first_coord == [2.3522, 48.8566]  # [lon, lat]

    # Point in center should be inside
    assert zone.in_zone(zone_state, 48.8571, 2.3527)


async def test_invalid_polygon_points_logged(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that invalid polygon points are logged."""
    # Only 2 points - invalid polygon
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Invalid Zone",
                    "latitude": 0.0,
                    "longitude": 0.0,
                    "zone_type": "polygon",
                    "points": [[0.0, 0.0], [1.0, 1.0]],  # Only 2 points
                }
            ]
        },
    )

    # Should log error about invalid polygon
    assert "Invalid polygon points" in caplog.text or "at least 3 points" in caplog.text
