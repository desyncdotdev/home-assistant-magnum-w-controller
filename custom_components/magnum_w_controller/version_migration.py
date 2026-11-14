"""
Move HACS installs from date-based version numbers to semantic versioning.

Releases up to 2026.12.0 were numbered after their date, later ones start again
at 1.0.0. HACS only offers a release as an update when its version is higher
than the installed one, so it never offers 1.0.0 to an install of 2026.12.0.
HACS's update entity installs any version it is asked for, though: while this
integration runs a date-based version and HACS knows of a semantic one, a
Repairs issue offers to install it (repairs.py). Releases from 1.0.0 on run a
semantic version, so they never raise the issue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.update import ATTR_LATEST_VERSION
from homeassistant.components.update import DOMAIN as UPDATE_DOMAIN
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# HACS gives its update entity for a repository the repository's GitHub ID as
# its unique ID; this is desyncdotdev/home-assistant-magnum-w-controller.
HACS_DOMAIN = "hacs"
HACS_REPOSITORY_ID = "1253571671"

ISSUE_ID = "semantic_versioning"

# The year in a date-based version; no semantic version gets this far.
_FIRST_DATE_BASED_MAJOR = 2000


def is_date_based(version: str) -> bool:
    """Return whether a version is numbered after its date, like 2026.12.0."""
    major = version.removeprefix("v").split(".", 1)[0]
    return major.isdigit() and int(major) >= _FIRST_DATE_BASED_MAJOR


@callback
def async_setup_version_migration(hass: HomeAssistant, version: str | None) -> None:
    """Raise the Repairs issue while HACS offers no way from this version to 1.x."""
    if version is None or not is_date_based(version):
        return

    entity_id = er.async_get(hass).async_get_entity_id(
        UPDATE_DOMAIN, HACS_DOMAIN, HACS_REPOSITORY_ID
    )
    if entity_id is None:
        # Not installed with HACS, which leaves updating to the user.
        return

    @callback
    def _async_check(_event: Event[EventStateChangedData] | None = None) -> None:
        state = hass.states.get(entity_id)
        latest = state.attributes.get(ATTR_LATEST_VERSION) if state else None
        if not isinstance(latest, str) or is_date_based(latest):
            return
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_ID,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_ID,
            translation_placeholders={"version": latest},
            data={"entity_id": entity_id, "version": latest},
        )

    # HACS may set its entity up after this integration, and checks GitHub for
    # new releases while Home Assistant runs, so watch it from now on.
    async_track_state_change_event(hass, entity_id, _async_check)
    _async_check()
