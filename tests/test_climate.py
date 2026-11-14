"""Tests for the Magnum W Controller climate platform."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_TEMPERATURE,
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.magnum_w_controller.const import DOMAIN


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, zone_id: int) -> str:
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, f"{entry.entry_id}_zone_{zone_id}"
    )
    assert entity_id is not None
    return entity_id


async def test_heating_zone_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A manual-heat zone reports heat mode and its current/target temps."""
    state = hass.states.get(_entity_id(hass, init_integration, 1))
    assert state is not None
    assert state.state == "heat"
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 20.5
    assert state.attributes[ATTR_TEMPERATURE] == 21.0
    assert state.attributes[ATTR_HVAC_ACTION] == "heating"
    assert state.attributes[ATTR_MIN_TEMP] == 5.0
    assert state.attributes[ATTR_MAX_TEMP] == 35.0


async def test_cooling_zone_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """An idle cooling zone reports cool mode and an idle action."""
    state = hass.states.get(_entity_id(hass, init_integration, 2))
    assert state is not None
    assert state.state == "cool"
    assert state.attributes[ATTR_HVAC_ACTION] == "idle"


async def test_set_temperature(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Setting a target temperature forwards the new setpoint to the client."""
    entity_id = _entity_id(hass, init_integration, 1)

    with patch(
        "custom_components.magnum_w_controller.api.MagnumClient.async_set_zone_setpoint",
    ) as mock_set:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 22.5},
            blocking=True,
        )

    assert mock_set.call_count == 1
    zone, temperature = mock_set.call_args.args
    assert zone.zone_id == 1
    assert temperature == 22.5
