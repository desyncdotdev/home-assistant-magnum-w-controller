"""Tests for the Magnum W Controller sensor platform."""

from __future__ import annotations

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.magnum_w_controller.const import DOMAIN


def _state(
    hass: HomeAssistant, entry: MockConfigEntry, unique_suffix: str
) -> str | None:
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        SENSOR_DOMAIN, DOMAIN, f"{entry.entry_id}_{unique_suffix}"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state


async def test_zone_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Temperature, battery and signal sensors expose the mapped values."""
    assert _state(hass, init_integration, "zone_1_temperature") == "20.5"
    assert _state(hass, init_integration, "zone_1_battery") == "100"
    assert _state(hass, init_integration, "zone_1_signal") == "100"

    assert _state(hass, init_integration, "zone_2_battery") == "50"
    assert _state(hass, init_integration, "zone_2_signal") == "75"


async def test_control_unit_sensor(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The control unit exposes a signal-strength sensor."""
    assert _state(hass, init_integration, "cu_0_signal") == "100"
