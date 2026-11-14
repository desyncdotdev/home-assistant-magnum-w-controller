"""Repairs for the Magnum W Controller integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.components.update import ATTR_VERSION, SERVICE_INSTALL
from homeassistant.components.update import DOMAIN as UPDATE_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import HomeAssistantError

from .version_migration import ISSUE_ID

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class SemanticVersioningRepairFlow(RepairsFlow):
    """Install the first semantic version with HACS (version_migration.py)."""

    def __init__(self, entity_id: str, version: str) -> None:
        """Remember HACS's update entity and the version it offers."""
        self._entity_id = entity_id
        self._version = version

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> RepairsFlowResult:
        """Start with the confirmation; the input here is the issue, not the user's."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Install the version once the user confirms."""
        placeholders = {"version": self._version}
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders=placeholders,
            )

        try:
            await self.hass.services.async_call(
                UPDATE_DOMAIN,
                SERVICE_INSTALL,
                {ATTR_ENTITY_ID: self._entity_id, ATTR_VERSION: self._version},
                blocking=True,
            )
        except HomeAssistantError:
            return self.async_abort(
                reason="install_failed", description_placeholders=placeholders
            )
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create the flow that fixes an issue."""
    if issue_id != ISSUE_ID or not data:
        msg = f"No fix for issue {issue_id}"
        raise ValueError(msg)
    return SemanticVersioningRepairFlow(data["entity_id"], data["version"])
