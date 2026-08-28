"""
Config flow for the Magnum W Controller integration.

Supports three entry points:

* Automatic **DHCP discovery** — primarily by the controller's MAC OUI
  (``0022A8*``, Ouman Oy), with the DHCP hostname ``Magnum_W-Controller`` as a
  secondary matcher (see ``manifest.json``). The OUI is what makes discovery
  fire reliably: Home Assistant's always-on network scan learns hostnames via
  reverse DNS, and the controller's hostname contains an underscore — illegal
  in DNS — so it rarely arrives in matchable form, whereas the MAC is always
  present from ARP. The MAC then doubles as a stable ``unique_id`` so the config
  entry survives IP changes. Per Home Assistant's discovery rules, the discovery
  step performs no network I/O and never finishes the flow — the controller is
  only contacted once the user confirms.
* **Active ``whois`` discovery** — when the user starts the flow, the local
  segment is probed with the same UDP multicast request the vendor's Android
  app uses (see ``discovery.py``). Controllers that answer are offered as a
  pick list. Their reply carries the MAC address, which the HTTP API does not
  expose, so these entries get the same stable ``unique_id`` as DHCP ones.
* Manual setup — the user types the host. If that host also answered the
  ``whois`` probe its MAC is used as the ``unique_id``; otherwise (a controller
  on another segment, or a hostname rather than the reported address) the host
  itself is the ``unique_id``.

A controller keyed by its host is adopted and re-keyed to the MAC when that
same controller is later seen via DHCP, so every path converges on one stable
identity instead of creating a duplicate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .api import MagnumApiError, MagnumClient
from .const import CONF_HOST, DOMAIN
from .discovery import async_discover_device, async_discover_devices

if TYPE_CHECKING:
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

    from .discovery import DiscoveredController

# An empty host sends the user to the discovery pick list.
STEP_USER_SCHEMA = vol.Schema({vol.Optional(CONF_HOST, default=""): str})


class MagnumConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Magnum W Controller."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow's discovery state."""
        self._host: str | None = None
        self._system_name: str | None = None
        self._discovered_devices: dict[str, DiscoveredController] = {}

    @property
    def host(self) -> str | None:
        """Host of the controller this flow is configuring."""
        return self._host

    def is_matching(self, other_flow: Self) -> bool:
        """Return True if another in-progress flow targets the same controller."""
        return other_flow.host == self._host

    async def _async_get_system_name(self, host: str) -> str:
        """Connect to the controller and return its system name."""
        session = async_get_clientsession(self.hass)
        client = MagnumClient(host, session)
        return await client.async_get_system_name()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup, falling back to discovery for an empty host."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input.get(CONF_HOST, "").strip()
            if not self._host:
                return await self.async_step_pick_device()

            self._async_abort_entries_match({CONF_HOST: self._host})
            # A whois reply is the only source of the MAC for a typed host, and
            # it is silent for a controller on another segment or for a
            # hostname rather than the address the controller reports. Those
            # entries key on the host and converge on the MAC once DHCP sees
            # the controller (see async_step_dhcp).
            discovered = await async_discover_device(self.hass, self._host)
            await self.async_set_unique_id(
                discovered.mac if discovered else self._host, raise_on_progress=False
            )
            self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
            try:
                system_name = await self._async_get_system_name(self._host)
            except MagnumApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=system_name, data={CONF_HOST: self._host}
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the controllers that answered a whois probe."""
        if user_input is not None:
            mac = user_input[CONF_DEVICE]
            controller = self._discovered_devices[mac]
            self._host = controller.host
            await self.async_set_unique_id(mac, raise_on_progress=False)
            self._abort_if_unique_id_configured(updates={CONF_HOST: controller.host})
            try:
                system_name = await self._async_get_system_name(controller.host)
            except MagnumApiError:
                return self.async_abort(reason="cannot_connect")
            return self.async_create_entry(
                title=system_name, data={CONF_HOST: controller.host}
            )

        self._discovered_devices = {
            controller.mac: controller
            for controller in await async_discover_devices(self.hass)
        }
        configured_ids = self._async_current_ids(include_ignore=False)
        configured_hosts = {
            entry.data[CONF_HOST]
            for entry in self._async_current_entries(include_ignore=False)
        }
        choices = {
            mac: f"{controller.name} ({controller.host})"
            for mac, controller in self._discovered_devices.items()
            if mac not in configured_ids and controller.host not in configured_hosts
        }
        if not choices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): vol.In(choices)}),
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """
        Handle discovery via DHCP.

        No network I/O happens here: the controller is contacted only after the
        user confirms, in ``async_step_discovery_confirm``.
        """
        self._host = discovery_info.ip

        # The MAC is the stable id; update the stored host if the IP changed.
        unique_id = format_mac(discovery_info.macaddress)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})

        # A controller added by host is keyed by it. Adopt that entry so it
        # picks up the stable MAC unique_id instead of creating a duplicate.
        for entry in self._async_current_entries():
            if entry.data.get(CONF_HOST) == discovery_info.ip:
                self.hass.config_entries.async_update_entry(entry, unique_id=unique_id)
                return self.async_abort(reason="already_configured")

        self.context["title_placeholders"] = {"name": discovery_info.ip}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered controller, contacting it only on confirmation."""
        assert self._host is not None  # noqa: S101
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._system_name = await self._async_get_system_name(self._host)
            except MagnumApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=self._system_name or "Magnum W Controller",
                    data={CONF_HOST: self._host},
                )

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"host": self._host},
            errors=errors,
        )
