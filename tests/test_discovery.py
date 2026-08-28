"""Tests for the Magnum W Controller whois discovery protocol."""

from __future__ import annotations

import json
import socket
import time
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.magnum_w_controller.discovery import (
    DiscoveredController,
    async_discover_device,
    async_discover_devices,
    build_probe,
    parse_reply,
)

_MOD = "custom_components.magnum_w_controller.discovery"

# Verbatim reply from a live MAGNUM W-Controller (firmware 1.1.186).
_LIVE_REPLY = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "devicename": "MAGNUM W-Controller",
            "serialnumber": "0",
            "swversion": "1.1.186",
            "ipaddress": "192.168.20.47",
            "macaddress": "00:22:A8:01:0C:5C",
            "netmask": "255.255.255.0",
            "supplier": "Magnum C&F",
        },
    }
).encode()


def _reply(**overrides) -> bytes:
    """Return the live reply with its result fields overridden."""
    payload = json.loads(_LIVE_REPLY)
    payload["result"].update(overrides)
    return json.dumps(payload).encode()


def test_build_probe_is_jsonrpc_whois():
    """The probe is the JSON-RPC whois request the vendor app sends."""
    assert json.loads(build_probe(7)) == {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "whois",
        "params": "",
    }


def test_parse_live_reply():
    """A real controller reply is parsed into a DiscoveredController."""
    controller = parse_reply(_LIVE_REPLY)
    assert controller == DiscoveredController(
        host="192.168.20.47",
        mac="00:22:a8:01:0c:5c",
        name="MAGNUM W-Controller",
        serial_number=None,  # a bare "0" carries no information
        sw_version="1.1.186",
    )


def test_parse_reply_tolerates_nul_padding():
    """Replies arrive NUL-padded to the sender's buffer size."""
    assert parse_reply(_LIVE_REPLY + b"\x00" * 4000) == parse_reply(_LIVE_REPLY)


def test_parse_reply_keeps_real_serial():
    """A programmed serial number is kept."""
    assert parse_reply(_reply(serialnumber="12345")).serial_number == "12345"


def test_parse_reply_tolerates_missing_optional_fields():
    """The vendor app declares fields a live controller omits."""
    controller = parse_reply(
        json.dumps(
            {
                "result": {
                    "ipaddress": "1.2.3.4",
                    "macaddress": "00:22:A8:00:00:01",
                    "supplier": "Magnum",
                }
            }
        ).encode()
    )
    assert controller.name == "Magnum W Controller"
    assert controller.serial_number is None
    assert controller.sw_version is None


def test_parse_reply_ignores_own_probe():
    """Our own multicast probe loops back and must not be treated as a device."""
    assert parse_reply(build_probe(1)) is None


@pytest.mark.parametrize(
    "supplier",
    ["Ouman", "", "Some Other Vendor"],
    ids=["other_ouman_device", "empty", "third_party"],
)
def test_parse_reply_filters_by_supplier(supplier):
    """The protocol spans Ouman's range; only Magnum hardware is ours."""
    assert parse_reply(_reply(supplier=supplier)) is None


@pytest.mark.parametrize(
    "missing",
    ["ipaddress", "macaddress"],
)
def test_parse_reply_requires_address_and_mac(missing):
    """A reply without an address or MAC cannot identify a controller."""
    assert parse_reply(_reply(**{missing: ""})) is None


@pytest.mark.parametrize(
    "raw",
    [b"", b"\x00", b"not json", b"[]", b'{"result": "ok"}', b'{"error": {}}'],
    ids=["empty", "nul", "garbage", "list", "result_not_object", "error_response"],
)
def test_parse_reply_rejects_malformed(raw):
    """Malformed or non-reply datagrams are ignored rather than raising."""
    assert parse_reply(raw) is None


@pytest.mark.parametrize(
    ("host", "expected"),
    [("192.168.20.47", "192.168.20.47"), ("10.0.0.1", None)],
    ids=["match", "no_match"],
)
async def test_async_discover_device_filters_by_host(
    hass: HomeAssistant, host, expected
):
    """A host lookup returns only the controller reporting that address."""
    with patch(
        f"{_MOD}.async_discover_devices",
        return_value=[parse_reply(_LIVE_REPLY)],
    ) as mock_discover:
        found = await async_discover_device(hass, host)

    assert (found.host if found else None) == expected
    # The single-host lookup asks the scan to end as soon as the host answers.
    assert mock_discover.call_args.kwargs["stop_host"] == host


def _loopback_socket() -> socket.socket:
    """A stand-in for the multicast socket, bound to an ephemeral loopback port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    return sock


async def test_async_discover_devices_collects_and_dedupes(
    hass: HomeAssistant, socket_enabled: None
):
    """Datagrams arriving on the socket are parsed and deduplicated by MAC."""
    sock = _loopback_socket()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with (
            patch(f"{_MOD}._create_socket", return_value=sock),
            patch(f"{_MOD}._send_probe"),
            patch(f"{_MOD}.network.async_get_enabled_source_ips", return_value=[]),
        ):
            task = hass.async_create_task(
                async_discover_devices(hass, scan_timeout=0.2)
            )
            sender.sendto(_LIVE_REPLY, sock.getsockname())
            sender.sendto(_LIVE_REPLY, sock.getsockname())
            sender.sendto(build_probe(1), sock.getsockname())  # our own loopback
            found = await task
    finally:
        sender.close()

    assert found == [parse_reply(_LIVE_REPLY)]


async def test_async_discover_devices_stops_early_for_stop_host(
    hass: HomeAssistant, socket_enabled: None
):
    """A scan for a specific host ends as soon as that host answers."""
    sock = _loopback_socket()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with (
            patch(f"{_MOD}._create_socket", return_value=sock),
            patch(f"{_MOD}._send_probe"),
            patch(f"{_MOD}.network.async_get_enabled_source_ips", return_value=[]),
        ):
            start = time.monotonic()
            task = hass.async_create_task(
                async_discover_devices(hass, scan_timeout=30, stop_host="192.168.20.47")
            )
            sender.sendto(_LIVE_REPLY, sock.getsockname())
            found = await task
    finally:
        sender.close()

    assert time.monotonic() - start < 5
    assert found == [parse_reply(_LIVE_REPLY)]
