"""
Tests for the Magnum W Controller JSON-RPC client.

The controller is faked with an in-memory device whose property values follow
the same addressing scheme the real client expects, so these tests exercise the
client's request building and response parsing end to end.
"""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest

from custom_components.magnum_w_controller.api import (
    MagnumApiError,
    MagnumClient,
    Zone,
)

# Raw property values keyed by (object_id, property_id), matching the addressing
# documented in api.py. One control unit, two active zones (1: manual heat,
# 2: cooling).
DEVICE_STATE: dict[tuple[int, int], Any] = {
    (0, 4): 1,  # number of control units
    (0, 5): "Test Magnum",  # system name
    (9990, 5): "1.1.186",  # firmware version
    (9991, 5): "201109-0850",  # application build stamp
    (1, 5): "CU One",  # CU 0 name
    (108, 4): 3,  # CU 0 link quality
    (100, 4): 0b00000011,  # CU 0 active-zone mask -> zones 1 and 2
    # Zone 1 (r=1, base=0)
    (200, 4): 205,  # room temp 20.5
    (205, 4): 210,  # effective setpoint 21.0
    (203, 4): 2,  # mode: manual heat
    (204, 4): 1,  # calling for heat
    (201, 4): 3,  # link quality
    (202, 4): 4,  # battery
    (201, 3): 50,  # min temp 5.0
    (202, 3): 350,  # max temp 35.0
    (9, 5): "Living Room",  # name
    # Zone 2 (r=2, base=100)
    (300, 4): 240,  # room temp 24.0
    (305, 4): 220,  # effective setpoint 22.0
    (303, 4): 7,  # mode: cooling
    (304, 4): 0,  # idle
    (301, 4): 2,  # link quality
    (302, 4): 2,  # battery
    (301, 3): 100,  # min temp 10.0
    (302, 3): 300,  # max temp 30.0
    (10, 5): "Bedroom",  # name
}


class _FakeResponse:
    """Minimal stand-in for an aiohttp response used as an async context manager."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_: object) -> None:
        return

    def raise_for_status(self) -> None:
        return

    async def json(self, content_type: str | None = None) -> Any:
        return self._payload


class FakeSession:
    """Fake aiohttp session that answers Magnum JSON-RPC read/write calls."""

    def __init__(self, state: dict[tuple[int, int], Any]) -> None:
        self._state = state
        self.last_write: dict | None = None

    def post(self, url: str, *, json: dict, **_: Any) -> _FakeResponse:
        method = json["method"]
        objects = json["params"]["objects"]
        if method == "read":
            return _FakeResponse(self._build_read(objects))
        if method == "write":
            self.last_write = json
            return _FakeResponse({"jsonrpc": "2.0", "id": json["id"], "result": "ok"})
        msg = f"unexpected method {method}"
        raise AssertionError(msg)

    def _build_read(self, objects: list[dict]) -> dict:
        out = []
        for obj in objects:
            obj_id = int(obj["id"])
            props = {}
            for prop_id in obj["properties"]:
                key = (obj_id, int(prop_id))
                if key in self._state:
                    props[prop_id] = {"v": self._state[key]}
            out.append({"i": str(obj_id), "p": props})
        return {"jsonrpc": "2.0", "id": 1, "result": {"objects": out}}


def make_client(session: FakeSession | None = None) -> MagnumClient:
    """Build a client backed by a fake session."""
    return MagnumClient("1.2.3.4", session or FakeSession(DEVICE_STATE))  # type: ignore[arg-type]


def make_zone(zone_id: int, mode: int) -> Zone:
    """Build a zone in the given raw zone mode."""
    return Zone(
        zone_id=zone_id,
        cu_index=0,
        name=f"Zone {zone_id}",
        room_temp=20.0,
        setpoint=21.0,
        mode=mode,
        is_active=True,
        link_quality=3,
        battery=4,
        min_temp=5.0,
        max_temp=35.0,
    )


async def test_async_get_system_name() -> None:
    """The system name is read from object 0 / property 5."""
    client = make_client()
    assert await client.async_get_system_name() == "Test Magnum"


async def test_async_get_versions() -> None:
    """Firmware and app build are read from objects 9990 / 9991 / property 5."""
    client = make_client()
    assert await client.async_get_versions() == ("1.1.186", "201109-0850")


async def test_async_get_versions_missing() -> None:
    """Absent version objects yield None rather than raising."""
    client = make_client(FakeSession({(0, 4): 0, (0, 5): "Test Magnum"}))
    assert await client.async_get_versions() == (None, None)


async def test_async_update_full_snapshot() -> None:
    """A full update parses control units and zones with scaled values."""
    client = make_client()
    data = await client.async_update()

    assert data.firmware_version == "1.1.186"
    assert data.app_version == "201109-0850"
    assert data.sw_version == "firmware 1.1.186 / app 201109-0850"
    assert len(data.control_units) == 1
    cu = data.control_units[0]
    assert cu.name == "CU One"
    assert cu.is_ethernet_gateway is True
    assert cu.link_quality_pct == 100

    assert len(data.zones) == 2
    living, bedroom = data.zones

    assert living.name == "Living Room"
    assert living.room_temp == 20.5
    assert living.setpoint == 21.0
    assert living.is_active is True
    assert living.is_cooling is False
    assert living.battery_pct == 100
    assert living.link_quality_pct == 100
    assert living.min_temp == 5.0
    assert living.max_temp == 35.0

    assert bedroom.name == "Bedroom"
    assert bedroom.room_temp == 24.0
    assert bedroom.is_cooling is True
    assert bedroom.is_active is False
    assert bedroom.battery_pct == 50
    assert bedroom.link_quality_pct == 75


async def test_set_setpoint_manual_heat_writes_manual_object() -> None:
    """A manual-heat zone writes the manual setpoint object (200 + base)."""
    session = FakeSession(DEVICE_STATE)
    client = make_client(session)

    await client.async_set_zone_setpoint(make_zone(1, mode=2), 22.5)

    assert session.last_write is not None
    written = session.last_write["params"]["objects"][0]
    assert written["id"] == "200"
    assert written["properties"]["3"]["value"] == 225


async def test_set_setpoint_cooling_writes_cooling_object() -> None:
    """A cooling zone writes the cooling setpoint object (203 + base)."""
    session = FakeSession(DEVICE_STATE)
    client = make_client(session)

    await client.async_set_zone_setpoint(make_zone(2, mode=7), 19.0)

    assert session.last_write is not None
    written = session.last_write["params"]["objects"][0]
    assert written["id"] == "303"  # 203 + 100 * (2 - 1)
    assert written["properties"]["3"]["value"] == 190


async def test_set_setpoint_schedule_mode_rejected() -> None:
    """Schedule-driven modes have no editable setpoint and raise."""
    client = make_client()
    zone = make_zone(1, mode=3)  # not manual (2) or cooling (7)

    with pytest.raises(MagnumApiError):
        await client.async_set_zone_setpoint(zone, 20.0)


async def test_controller_error_response_raises() -> None:
    """An error object in the response surfaces as MagnumApiError."""

    class ErrorSession(FakeSession):
        def post(self, url: str, *, json: dict, **_: Any) -> _FakeResponse:
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "error": "nope"})

    client = make_client(ErrorSession(DEVICE_STATE))
    with pytest.raises(MagnumApiError):
        await client.async_get_system_name()


async def test_connection_error_raises() -> None:
    """A transport-level error is wrapped in MagnumApiError."""

    class BrokenSession(FakeSession):
        def post(self, url: str, *, json: dict, **_: Any) -> _FakeResponse:
            msg = "boom"
            raise aiohttp.ClientError(msg)

    client = make_client(BrokenSession(DEVICE_STATE))
    with pytest.raises(MagnumApiError):
        await client.async_get_system_name()
