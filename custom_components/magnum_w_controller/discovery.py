"""
Active UDP discovery for Magnum W controllers.

The protocol was reverse-engineered from Ouman's *MAGNUM Control Center*
Android app (``fi.ouman.networkdiscovery``) and verified against a live
controller:

* Probe: ``{"jsonrpc": "2.0", "id": n, "method": "whois", "params": ""}`` sent
  as UTF-8 to the link-local all-hosts group ``224.0.0.1``, port 1324.
* Reply: a JSON-RPC response whose ``result`` object carries the inventory. A
  live controller returns ``devicename``, ``ipaddress``, ``macaddress``,
  ``netmask``, ``serialnumber``, ``swversion`` and ``supplier``. The app's own
  model declares fields a real controller omits (``devicetype``, ``gateway``,
  ``accessip``, ``applicationversion``), so all fields are optional.
* The controller replies to the multicast group rather than to the sender's
  ephemeral port, so the probe must be sent from a socket that is itself bound
  to port 1324 and joined to the group.
* Sent with TTL 1, so discovery only reaches controllers on the same segment as
  Home Assistant. A controller behind a router must be added by host. It does
  not answer a unicast probe.
* Replies may be NUL-padded to the sender's buffer size.

Only devices whose ``supplier`` contains "magnum" are reported (a live
controller reports ``Magnum C&F``). The protocol spans Ouman's whole product
range, and this mirrors the vendor app's own filtering.

Discovery is the only way, short of a DHCP event, for a user-initiated flow to
learn the controller's MAC address: the HTTP API does not expose it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import struct
from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, Any

from homeassistant.components import network
from homeassistant.helpers.device_registry import format_mac

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DISCOVERY_GROUP = "224.0.0.1"
DISCOVERY_PORT = 1324
SUPPLIER_MATCH = "magnum"
DEFAULT_NAME = "Magnum W Controller"

DEFAULT_DISCOVERY_TIMEOUT = 5.0

# UDP is lossy, so the probe is repeated once inside the listen window.
_RETRY_DELAY = 1.0

# What a controller with no serial number programmed reports.
_EMPTY_SERIAL = "0"

_ANY_ADDRESS = "0.0.0.0"  # noqa: S104


@dataclass(frozen=True)
class DiscoveredController:
    """A controller that answered a ``whois`` probe."""

    host: str
    mac: str
    name: str
    serial_number: str | None
    sw_version: str | None


def build_probe(request_id: int = 1) -> bytes:
    """Return the ``whois`` request datagram."""
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": "whois", "params": ""}
    ).encode()


def _clean(value: object) -> str | None:
    """Return a stripped string, or None if absent or empty."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _load_result(raw: bytes) -> dict[str, Any] | None:
    """Return a datagram's JSON-RPC ``result`` object, if it has one."""
    text = raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    return result if isinstance(result, dict) else None


def parse_reply(raw: bytes) -> DiscoveredController | None:
    """
    Parse one datagram into a controller, or None if it is not one of ours.

    Rejects our own looped-back probe, malformed JSON, and replies from
    non-Magnum Ouman hardware.
    """
    result = _load_result(raw)
    if result is None:
        return None

    supplier = _clean(result.get("supplier")) or ""
    host = _clean(result.get("ipaddress"))
    mac = _clean(result.get("macaddress"))
    if SUPPLIER_MATCH not in supplier.casefold() or not host or not mac:
        return None

    serial = _clean(result.get("serialnumber"))
    return DiscoveredController(
        host=host,
        mac=format_mac(mac),
        name=_clean(result.get("devicename")) or DEFAULT_NAME,
        serial_number=None if serial == _EMPTY_SERIAL else serial,
        sw_version=_clean(result.get("swversion")),
    )


class _WhoisProtocol(asyncio.DatagramProtocol):
    """Collects raw replies to a ``whois`` probe."""

    def __init__(self, stop_host: str | None = None) -> None:
        """Initialise an empty reply buffer, watching for ``stop_host``."""
        self.replies: list[bytes] = []
        self.done = asyncio.Event()
        self._stop_host = stop_host

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        """Buffer an incoming datagram."""
        _LOGGER.debug("whois reply from %s: %s", addr[0], data[:256])
        self.replies.append(data)
        if self._stop_host is not None:
            controller = parse_reply(data)
            if controller is not None and controller.host == self._stop_host:
                self.done.set()

    def error_received(self, exc: Exception) -> None:
        """Log a transport error without aborting discovery."""
        _LOGGER.debug("whois socket error: %s", exc)


def _create_socket() -> socket.socket:
    """Return a socket bound to the discovery port, ready to join the group."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with contextlib.suppress(AttributeError, OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.bind((_ANY_ADDRESS, DISCOVERY_PORT))
    except OSError:
        sock.close()
        raise
    return sock


def _join_group(sock: socket.socket, source_ip: str) -> bool:
    """Join the discovery group on one interface, returning True on success."""
    mreq = struct.pack(
        "4s4s", socket.inet_aton(DISCOVERY_GROUP), socket.inet_aton(source_ip)
    )
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError as err:
        _LOGGER.debug("Could not join %s on %s: %s", DISCOVERY_GROUP, source_ip, err)
        return False
    return True


async def _async_source_ips(hass: HomeAssistant) -> list[str]:
    """
    Return the IPv4 addresses to probe from.

    A multicast datagram leaves through a single interface, so a multi-homed
    Home Assistant has to probe from each enabled address in turn.
    """
    try:
        source_ips = await network.async_get_enabled_source_ips(hass)
    except (OSError, RuntimeError) as err:  # pragma: no cover
        _LOGGER.debug("Could not enumerate source IPs: %s", err)
        return [_ANY_ADDRESS]

    addresses = [
        str(ip)
        for ip in source_ips
        if isinstance(ip, IPv4Address) and not ip.is_loopback and not ip.is_unspecified
    ]
    return addresses or [_ANY_ADDRESS]


def _send_probe(
    transport: asyncio.DatagramTransport,
    sock: socket.socket,
    source_ips: list[str],
    request_id: int,
) -> None:
    """Send one probe out of every candidate interface."""
    probe = build_probe(request_id)
    for source_ip in source_ips:
        with contextlib.suppress(OSError):
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(source_ip),
            )
        # The transport owns the socket (and made it non-blocking), so sends
        # must go through it; send errors surface in error_received.
        transport.sendto(probe, (DISCOVERY_GROUP, DISCOVERY_PORT))


async def _async_wait_for_replies(protocol: _WhoisProtocol, window: float) -> bool:
    """Listen for ``window`` seconds; True if the watched host answered early."""
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(window):
            await protocol.done.wait()
        return True
    return False


async def async_discover_devices(
    hass: HomeAssistant,
    scan_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    stop_host: str | None = None,
) -> list[DiscoveredController]:
    """
    Probe the local network and return the controllers that answered.

    Best-effort: never raises, and an empty list just means the user has to
    enter a host by hand. When ``stop_host`` is given, the scan ends as soon
    as that address answers instead of waiting out the timeout.
    """
    try:
        sock = _create_socket()
    except OSError as err:
        _LOGGER.debug("Could not open discovery socket: %s", err)
        return []

    source_ips = await _async_source_ips(hass)
    if not any(_join_group(sock, ip) for ip in source_ips) and not _join_group(
        sock, _ANY_ADDRESS
    ):
        _LOGGER.debug("Could not join %s on any interface", DISCOVERY_GROUP)

    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: _WhoisProtocol(stop_host), sock=sock
    )
    try:
        _send_probe(transport, sock, source_ips, 1)
        answered = await _async_wait_for_replies(
            protocol, min(_RETRY_DELAY, scan_timeout)
        )
        if not answered and scan_timeout > _RETRY_DELAY:
            _send_probe(transport, sock, source_ips, 2)
            await _async_wait_for_replies(protocol, scan_timeout - _RETRY_DELAY)
    finally:
        transport.close()

    found: dict[str, DiscoveredController] = {}
    for raw in protocol.replies:
        controller = parse_reply(raw)
        if controller is not None:
            found.setdefault(controller.mac, controller)

    _LOGGER.debug("Discovered %d controller(s)", len(found))
    return list(found.values())


async def async_discover_device(
    hass: HomeAssistant, host: str, scan_timeout: float = DEFAULT_DISCOVERY_TIMEOUT
) -> DiscoveredController | None:
    """
    Return the discovered controller at ``host``, if it answers.

    Used to recover the MAC address of a controller entered by hand, so the
    scan returns as soon as that host answers rather than waiting out the
    timeout. Returns None when the controller is on another segment, or when
    ``host`` is a name rather than the address the controller reports.
    """
    for controller in await async_discover_devices(hass, scan_timeout, stop_host=host):
        if controller.host == host:
            return controller
    return None
