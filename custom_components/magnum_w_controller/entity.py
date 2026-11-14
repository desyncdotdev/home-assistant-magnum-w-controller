"""Shared device-registry helpers and entity base for Magnum W entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import MagnumCoordinator

if TYPE_CHECKING:
    from .api import ControlUnit, Zone


def control_unit_device_info(
    entry_id: str, unit: ControlUnit, sw_version: str | None = None
) -> DeviceInfo:
    """
    Device entry for a control unit.

    The LAN-connected CU (the box serving the web UI) carries the controller's
    firmware/app version in ``sw_version``; other CUs leave it unset.
    """
    info = DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_{unit.unique_key}")},
        name=unit.name,
        manufacturer=MANUFACTURER,
        model="Magnum W Control Unit",
    )
    if unit.is_ethernet_gateway and sw_version:
        info["sw_version"] = sw_version
    return info


def zone_device_info(entry_id: str, zone: Zone) -> DeviceInfo:
    """Device entry for a thermostat/zone, linked to its control unit."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_{zone.unique_key}")},
        name=zone.name,
        manufacturer=MANUFACTURER,
        model="Magnum W Thermostat",
        via_device=(DOMAIN, f"{entry_id}_cu_{zone.cu_index}"),
    )


class MagnumZoneEntity(CoordinatorEntity[MagnumCoordinator]):
    """Base for entities that belong to a single thermostat/zone."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: MagnumCoordinator, entry_id: str, zone: Zone
    ) -> None:
        """Attach the entity to the device of ``zone``."""
        super().__init__(coordinator)
        self._zone_id = zone.zone_id
        self._attr_device_info = zone_device_info(entry_id, zone)

    @property
    def _zone(self) -> Zone | None:
        """The zone in the latest snapshot, or None once it has disappeared."""
        for zone in self.coordinator.data.zones:
            if zone.zone_id == self._zone_id:
                return zone
        return None

    @property
    def available(self) -> bool:
        """Whether the zone is still present in the latest snapshot."""
        return super().available and self._zone is not None
