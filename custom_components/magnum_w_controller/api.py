"""
Async client for the Magnum W Controller's undocumented JSON-RPC API.

The controller (an AngularJS app served at ``http://<host>``) talks to a
JSON-RPC endpoint at ``POST /api``. Everything is addressed by an integer
object id + a property id. This module was reverse-engineered from the
controller's own JavaScript.

Addressing summary
------------------
* System object 0 / property 4 -> number of Control Units (CUs).
* System object 0 / property 5 -> system name.
* Object 9990 / property 5 -> firmware version (e.g. "1.1.186").
* Object 9991 / property 5 -> application build stamp (e.g. "201109-0850").
  Both belong to the LAN-connected CU 0 (see ``ETHERNET_CU_INDEX``).
* CU ``s`` (0-based): object ``100 + s`` / property 4 = 8-bit mask of active
  zones. A zone's global 1-based id is ``r = s * 8 + (bit + 1)``.
* CU objects use ``initialId + offset * s`` (offset 1):
    - name:         initialId 1,   property 5 (string)
    - link quality: initialId 108, property 4 (0..3)
* Zone objects use ``initialId + 100 * (r - 1)``:
    - room temp:           initialId 200, property 4, value /10
    - effective setpoint:  initialId 205, property 4, value /10
    - zone mode:           initialId 203, property 4 (7 == cooling, else heat)
    - zone is active:      initialId 204, property 4 (1 == calling for heat/cool)
    - link quality:        initialId 201, property 4 (0..3)
    - battery level:       initialId 202, property 4 (0..4)
    - setpoint min/max:    initialId 201/202, property 3, value /10
    - manual setpoint:     initialId 200, property 3, value /10  (heat mode 2)
    - cooling setpoint:    initialId 203, property 3, value /10  (cool mode 7)
    - name:                initialId 9,   property 5 (string)
"""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from .const import DEFAULT_NAME

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

MAX_ZONES_PER_CU = 8
COOLING_ZONE_MODE = 7
MANUAL_ZONE_MODE = 2

DEFAULT_MIN_TEMP = 5.0
DEFAULT_MAX_TEMP = 35.0

# The first control unit (cu_index 0) is the LAN-connected box that serves the
# web UI and owns the device MAC; the controller's version strings belong to it.
ETHERNET_CU_INDEX = 0

# Object ids holding the controller's version strings (property 5): the
# firmware revision (e.g. "1.1.186") and the application build stamp
# (e.g. "201109-0850").
FIRMWARE_OBJ = 9990
APP_OBJ = 9991


class MagnumApiError(Exception):
    """Raised when the controller cannot be reached or returns an error."""


def link_quality_pct(value: int | None) -> int | None:
    """Map the controller's 0..3 link-quality enum to a percentage."""
    return None if value is None else min(value, 3) * 25 + 25


def battery_pct(value: int | None) -> int | None:
    """Map the controller's 0..4 battery enum to a percentage."""
    return None if value is None else min(value, 4) * 25


@dataclass
class ControlUnit:
    """A wired master unit that the wireless thermostats report to."""

    cu_index: int  # 0-based control unit index
    name: str
    link_quality: int | None  # raw 0..3 enum

    @property
    def unique_key(self) -> str:
        """Stable per-entry key for this control unit."""
        return f"cu_{self.cu_index}"

    @property
    def is_ethernet_gateway(self) -> bool:
        """Whether this CU is the LAN-connected controller (serves the web UI)."""
        return self.cu_index == ETHERNET_CU_INDEX

    @property
    def link_quality_pct(self) -> int | None:
        """Link quality as a percentage."""
        return link_quality_pct(self.link_quality)


@dataclass
class Zone:
    """A single thermostat / heating zone."""

    zone_id: int  # global 1-based zone id
    cu_index: int  # 0-based control unit index
    name: str
    room_temp: float | None  # degrees C
    setpoint: float | None  # degrees C (effective target for active mode)
    mode: int  # raw zoneMode value
    is_active: bool  # currently calling for heat/cool
    link_quality: int | None  # raw 0..3 enum
    battery: int | None  # raw 0..4 enum
    min_temp: float | None
    max_temp: float | None

    @property
    def unique_key(self) -> str:
        """Stable per-entry key for this zone."""
        return f"zone_{self.zone_id}"

    @property
    def is_cooling(self) -> bool:
        """Whether the zone is currently in cooling mode."""
        return self.mode == COOLING_ZONE_MODE

    @property
    def link_quality_pct(self) -> int | None:
        """Link quality as a percentage."""
        return link_quality_pct(self.link_quality)

    @property
    def battery_pct(self) -> int | None:
        """Battery level as a percentage."""
        return battery_pct(self.battery)


@dataclass
class MagnumData:
    """Snapshot of the whole controller returned by a single refresh."""

    firmware_version: str | None
    app_version: str | None
    control_units: list[ControlUnit]
    zones: list[Zone]

    @property
    def sw_version(self) -> str | None:
        """Combined firmware/app version string for the controller's device."""
        parts: list[str] = []
        if self.firmware_version:
            parts.append(f"firmware {self.firmware_version}")
        if self.app_version:
            parts.append(f"app {self.app_version}")
        return " / ".join(parts) or None


class MagnumClient:
    """Minimal async JSON-RPC client for the Magnum W Controller."""

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        """Initialize the client for a controller at ``host``."""
        self._url = f"http://{host}/api"
        self._session = session
        self._req_id = 0

    async def _call(self, method: str, objects: list[dict]) -> object:
        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": {"objects": objects},
        }
        try:
            async with self._session.post(
                self._url, json=payload, timeout=REQUEST_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as err:
            msg = f"Error talking to controller: {err}"
            raise MagnumApiError(msg) from err

        if not isinstance(data, dict) or "error" in data:
            msg = f"Controller returned error: {data!r}"
            raise MagnumApiError(msg)
        if "result" not in data:
            msg = f"Unexpected response: {data!r}"
            raise MagnumApiError(msg)
        # Reads return {"objects": [...]}; writes return the string "ok".
        return data["result"]

    @staticmethod
    def _obj(obj_id: int, prop_id: int) -> dict:
        return {"id": str(obj_id), "properties": {str(prop_id): {}}}

    async def _read_values(
        self, requests: list[tuple[int, int]]
    ) -> dict[tuple[int, int], object]:
        """Read (obj_id, prop_id) pairs in one batch; return a value lookup."""
        if not requests:
            return {}
        objects = [self._obj(o, p) for o, p in requests]
        result = await self._call("read", objects)
        if not isinstance(result, dict) or "objects" not in result:
            msg = f"Unexpected read response: {result!r}"
            raise MagnumApiError(msg)
        values: dict[tuple[int, int], object] = {}
        for item in result["objects"]:
            obj_id = int(item["i"])
            for prop_id, prop in item.get("p", {}).items():
                if "v" in prop:
                    values[(obj_id, int(prop_id))] = prop["v"]
        return values

    async def async_get_system_name(self) -> str:
        """Read the controller's configured system name."""
        values = await self._read_values([(0, 5)])
        return str(values.get((0, 5)) or DEFAULT_NAME)

    async def async_get_versions(self) -> tuple[str | None, str | None]:
        """Read the controller's firmware and application version strings."""
        values = await self._read_values([(FIRMWARE_OBJ, 5), (APP_OBJ, 5)])
        firmware = values.get((FIRMWARE_OBJ, 5))
        app = values.get((APP_OBJ, 5))
        return (
            str(firmware) if firmware is not None else None,
            str(app) if app is not None else None,
        )

    async def _async_number_of_cus(self) -> int:
        values = await self._read_values([(0, 4)])
        return int(values.get((0, 4), 0))

    async def async_get_control_units(self, num_cu: int) -> list[ControlUnit]:
        """Read all control units and their link quality."""
        requests: list[tuple[int, int]] = []
        for s in range(num_cu):
            requests.append((1 + s, 5))  # name
            requests.append((108 + s, 4))  # link quality
        values = await self._read_values(requests)

        units: list[ControlUnit] = []
        for s in range(num_cu):
            name = values.get((1 + s, 5)) or f"CU {s + 1}"
            link = values.get((108 + s, 4))
            units.append(
                ControlUnit(
                    cu_index=s,
                    name=str(name),
                    link_quality=int(link) if link is not None else None,
                )
            )
        return units

    async def _async_active_zone_ids(self, num_cu: int) -> list[tuple[int, int]]:
        """Return (cu_index, global_zone_id) for every active zone."""
        masks = await self._read_values([(100 + s, 4) for s in range(num_cu)])
        return [
            (s, s * MAX_ZONES_PER_CU + (bit + 1))
            for s in range(num_cu)
            for bit in range(MAX_ZONES_PER_CU)
            if int(masks.get((100 + s, 4), 0)) & (1 << bit)
        ]

    async def async_get_zones(self, num_cu: int) -> list[Zone]:
        """Read every active zone and its current state."""
        active = await self._async_active_zone_ids(num_cu)

        requests: list[tuple[int, int]] = []
        for _, r in active:
            base = 100 * (r - 1)
            requests.append((200 + base, 4))  # room temp
            requests.append((205 + base, 4))  # effective setpoint
            requests.append((203 + base, 4))  # zone mode
            requests.append((204 + base, 4))  # zone is active
            requests.append((201 + base, 4))  # link quality
            requests.append((202 + base, 4))  # battery level
            requests.append((201 + base, 3))  # setpoint min
            requests.append((202 + base, 3))  # setpoint max
            requests.append((9 + (r - 1), 5))  # name
        values = await self._read_values(requests)

        def temp(key: tuple[int, int]) -> float | None:
            raw = values.get(key)
            return raw / 10 if raw is not None else None

        zones: list[Zone] = []
        for cu_index, r in active:
            base = 100 * (r - 1)
            mode = values.get((203 + base, 4))
            link = values.get((201 + base, 4))
            batt = values.get((202 + base, 4))
            name = values.get((9 + (r - 1), 5)) or f"Zone {r}"
            zones.append(
                Zone(
                    zone_id=r,
                    cu_index=cu_index,
                    name=str(name),
                    room_temp=temp((200 + base, 4)),
                    setpoint=temp((205 + base, 4)),
                    mode=int(mode) if mode is not None else -1,
                    is_active=bool(values.get((204 + base, 4))),
                    link_quality=int(link) if link is not None else None,
                    battery=int(batt) if batt is not None else None,
                    min_temp=temp((201 + base, 3)),
                    max_temp=temp((202 + base, 3)),
                )
            )
        return zones

    async def async_update(self) -> MagnumData:
        """Fetch a full snapshot of the controller."""
        num_cu = await self._async_number_of_cus()
        firmware_version, app_version = await self.async_get_versions()
        return MagnumData(
            firmware_version=firmware_version,
            app_version=app_version,
            control_units=await self.async_get_control_units(num_cu),
            zones=await self.async_get_zones(num_cu),
        )

    async def async_set_zone_setpoint(self, zone: Zone, temp_c: float) -> None:
        """
        Write a new target temperature for ``zone``.

        The object written depends on the zone's current mode: cooling mode
        writes the cooling setpoint, manual heating writes the manual setpoint.
        Schedule-driven modes (week program / holiday / setback) have no single
        editable setpoint, so they are rejected.
        """
        base = 100 * (zone.zone_id - 1)
        if zone.mode == COOLING_ZONE_MODE:
            obj_id = 203 + base
        elif zone.mode == MANUAL_ZONE_MODE:
            obj_id = 200 + base
        else:
            msg = (
                f"Zone '{zone.name}' is in a schedule-driven mode ({zone.mode}); "
                "its target temperature cannot be set directly."
            )
            raise MagnumApiError(msg)

        value = round(temp_c * 10)
        objects = [{"id": str(obj_id), "properties": {"3": {"value": value}}}]
        result = await self._call("write", objects)
        # A successful write is acknowledged with the string "ok".
        if result != "ok":
            msg = f"Write was not acknowledged: {result!r}"
            raise MagnumApiError(msg)
