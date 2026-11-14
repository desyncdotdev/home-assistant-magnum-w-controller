"""Tests for moving HACS installs from date-based to semantic versions."""

from __future__ import annotations

import pytest
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.magnum_w_controller.const import DOMAIN
from custom_components.magnum_w_controller.version_migration import (
    HACS_REPOSITORY_ID,
    ISSUE_ID,
    async_setup_version_migration,
    is_date_based,
)


@pytest.fixture
def hacs_entity_id(hass: HomeAssistant) -> str:
    """Register HACS's update entity for this repository, as HACS does."""
    return (
        er.async_get(hass)
        .async_get_or_create(
            "update",
            "hacs",
            HACS_REPOSITORY_ID,
            suggested_object_id="magnum_w_controller_update",
        )
        .entity_id
    )


def _set_latest(hass: HomeAssistant, entity_id: str, latest: str) -> None:
    hass.states.async_set(
        entity_id,
        "off",
        {"installed_version": "2026.12.0", "latest_version": latest},
    )


def _issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2026.8.2", True),
        ("2026.12.0", True),
        ("v2026.12.0", True),
        ("1.0.0", False),
        ("v1.2.3", False),
        ("0.9.0", False),
        ("", False),
        ("main", False),
    ],
)
def test_is_date_based(version: str, expected: bool) -> None:  # noqa: FBT001
    assert is_date_based(version) is expected


async def test_no_issue_while_hacs_offers_a_date_based_version(
    hass: HomeAssistant, hacs_entity_id: str
) -> None:
    _set_latest(hass, hacs_entity_id, "2026.12.0")
    async_setup_version_migration(hass, "2026.12.0")
    await hass.async_block_till_done()

    assert _issue(hass) is None


async def test_issue_when_hacs_finds_a_semantic_version(
    hass: HomeAssistant, hacs_entity_id: str
) -> None:
    """HACS learns of 1.0.0 while Home Assistant runs."""
    _set_latest(hass, hacs_entity_id, "2026.12.0")
    async_setup_version_migration(hass, "2026.12.0")
    await hass.async_block_till_done()

    _set_latest(hass, hacs_entity_id, "1.0.0")
    await hass.async_block_till_done()

    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_placeholders == {"version": "1.0.0"}
    assert issue.data == {"entity_id": hacs_entity_id, "version": "1.0.0"}


async def test_issue_when_hacs_sets_up_after_the_integration(
    hass: HomeAssistant, hacs_entity_id: str
) -> None:
    """The entity is registered from an earlier run, but has no state yet."""
    async_setup_version_migration(hass, "2026.12.0")
    await hass.async_block_till_done()
    assert _issue(hass) is None

    _set_latest(hass, hacs_entity_id, "1.0.1")
    await hass.async_block_till_done()

    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_placeholders == {"version": "1.0.1"}


async def test_no_issue_on_a_semantic_version(
    hass: HomeAssistant, hacs_entity_id: str
) -> None:
    _set_latest(hass, hacs_entity_id, "1.1.0")
    async_setup_version_migration(hass, "1.0.0")
    await hass.async_block_till_done()

    assert _issue(hass) is None


async def test_no_issue_without_hacs(hass: HomeAssistant) -> None:
    async_setup_version_migration(hass, "2026.12.0")
    await hass.async_block_till_done()

    assert _issue(hass) is None


async def test_setup_checks_the_installed_version(
    hass: HomeAssistant, hacs_entity_id: str, init_integration
) -> None:
    """The manifest in the repository still has a date-based version."""
    _set_latest(hass, hacs_entity_id, "1.0.0")
    await hass.async_block_till_done()

    assert _issue(hass) is not None


async def _start_fix_flow(hass: HomeAssistant, hacs_entity_id: str) -> dict:
    """Raise the issue, from the date-based version in the manifest, and fix it."""
    assert await async_setup_component(hass, "repairs", {})
    _set_latest(hass, hacs_entity_id, "1.0.0")
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    manager = repairs_flow_manager(hass)
    assert manager is not None
    result = await manager.async_init(DOMAIN, data={"issue_id": ISSUE_ID})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"version": "1.0.0"}
    return result


async def test_fix_installs_the_semantic_version(
    hass: HomeAssistant, hacs_entity_id: str
) -> None:
    calls = async_mock_service(hass, "update", "install")
    result = await _start_fix_flow(hass, hacs_entity_id)

    result = await repairs_flow_manager(hass).async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(calls) == 1
    assert calls[0].data == {"entity_id": hacs_entity_id, "version": "1.0.0"}
    assert _issue(hass) is None


async def test_fix_aborts_when_hacs_fails(
    hass: HomeAssistant, hacs_entity_id: str
) -> None:
    async_mock_service(
        hass, "update", "install", raise_exception=HomeAssistantError("offline")
    )
    result = await _start_fix_flow(hass, hacs_entity_id)

    result = await repairs_flow_manager(hass).async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "install_failed"
    assert _issue(hass) is not None
