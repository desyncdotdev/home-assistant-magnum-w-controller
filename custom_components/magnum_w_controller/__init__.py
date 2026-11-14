"""The Magnum W Controller integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import MagnumClient
from .const import CONF_HOST, DOMAIN
from .coordinator import MagnumCoordinator
from .entity import control_unit_device_info
from .version_migration import async_setup_version_migration

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    from .coordinator import MagnumConfigEntry

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up the parts of the integration that do not belong to an entry."""
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version) if integration.version else None
    async_setup_version_migration(hass, version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MagnumConfigEntry) -> bool:
    """Set up Magnum W Controller from a config entry."""
    session = async_get_clientsession(hass)
    client = MagnumClient(entry.data[CONF_HOST], session)

    coordinator = MagnumCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Register the control unit devices up front so the zone devices, which
    # reference them via ``via_device``, never point at a not-yet-created
    # device while the platforms are being set up.
    device_registry = dr.async_get(hass)
    for unit in coordinator.data.control_units:
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **control_unit_device_info(
                entry.entry_id, unit, coordinator.data.sw_version
            ),
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MagnumConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
