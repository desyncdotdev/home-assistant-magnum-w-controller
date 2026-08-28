"""Common fixtures for the Magnum W Controller tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.magnum_w_controller.api import (
    ControlUnit,
    MagnumData,
    Zone,
)
from custom_components.magnum_w_controller.const import CONF_HOST, DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable loading of the custom integration in every test."""
    return


@pytest.fixture(autouse=True)
def mock_discovery() -> Generator[None]:
    """
    Keep the whois probe off the network.

    Patched at the use sites, not in ``discovery``: the config flow binds these
    names at import time. Tests that exercise discovery re-patch the same
    targets.
    """
    with (
        patch(
            "custom_components.magnum_w_controller.config_flow.async_discover_devices",
            return_value=[],
        ),
        patch(
            "custom_components.magnum_w_controller.config_flow.async_discover_device",
            return_value=None,
        ),
    ):
        yield


@pytest.fixture
def sample_data() -> MagnumData:
    """A representative controller snapshot: one CU, one heating + one cooling zone."""
    return MagnumData(
        system_name="Test Magnum",
        firmware_version="1.1.186",
        app_version="201109-0850",
        control_units=[
            ControlUnit(cu_index=0, name="CU One", link_quality=3),
        ],
        zones=[
            Zone(
                zone_id=1,
                cu_index=0,
                name="Living Room",
                room_temp=20.5,
                setpoint=21.0,
                mode=2,  # manual heat
                is_active=True,
                link_quality=3,
                battery=4,
                min_temp=5.0,
                max_temp=35.0,
            ),
            Zone(
                zone_id=2,
                cu_index=0,
                name="Bedroom",
                room_temp=24.0,
                setpoint=22.0,
                mode=7,  # cooling
                is_active=False,
                link_quality=2,
                battery=2,
                min_temp=10.0,
                max_temp=30.0,
            ),
        ],
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    sample_data: MagnumData,
) -> AsyncGenerator[MockConfigEntry]:
    """Set up the integration with a mocked controller and yield the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Magnum",
        data={CONF_HOST: "1.2.3.4"},
        unique_id="1.2.3.4",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.magnum_w_controller.api.MagnumClient.async_update",
        return_value=sample_data,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
