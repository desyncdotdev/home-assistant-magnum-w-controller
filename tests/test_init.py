"""Tests for setting up and unloading the Magnum W Controller integration."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.magnum_w_controller.api import MagnumApiError
from custom_components.magnum_w_controller.const import DOMAIN


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entry loads, creates entities for every zone and CU, then unloads."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    # 2 climate + 2 zones * 3 sensors + 1 CU * 1 sensor = 9
    assert len(entities) == 9

    # The Ethernet-connected CU 0 carries the controller's version string.
    dev_reg = dr.async_get(hass)
    cu0 = dev_reg.async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_cu_0"), entry.entry_id
    )
    assert cu0 is not None
    assert cu0.sw_version == "firmware 1.1.186 / app 201109-0850"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_on_connection_error(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A controller that cannot be reached puts the entry into retry."""
    entry = config_entry
    with patch(
        "custom_components.magnum_w_controller.api.MagnumClient.async_update",
        side_effect=MagnumApiError("boom"),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
