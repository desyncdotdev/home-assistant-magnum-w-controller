<p align="center">
  <img alt="banner" src="https://github.com/user-attachments/assets/4b538294-7d78-44b5-95bc-615dfb83bed9" />

</p>

# Magnum W Controller

[![CI](https://github.com/desyncdotdev/home-assistant-magnum-w-controller/actions/workflows/ci.yml/badge.svg)](https://github.com/desyncdotdev/home-assistant-magnum-w-controller/actions/workflows/ci.yml)

Home Assistant custom integration for the **Magnum W Controller**, the hub for
Magnum wireless underfloor-heating thermostats.

It talks to the controller's local JSON-RPC API, discovers every control unit
and heating zone, and exposes them to Home Assistant.

## Support

If you find this integration useful, you can support my work:

[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-desyncdotdev-EA4AAA?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/desyncdotdev)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-desyncdotdev-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/desyncdotdev)

## Features

- **Automatic DHCP discovery** of the controller.
- **Network scan** when adding it by hand, using the same UDP `whois` probe the
  official MAGNUM Control Center app uses (with manual host entry as a
  fallback).
- A **`climate` entity per zone** — current temperature, target temperature,
  heating/cooling action, and per-zone min/max limits.
- **Diagnostic sensors** — battery level and signal strength per thermostat,
  signal strength per control unit, plus a temperature sensor per zone.
- A device per control unit, with each thermostat linked to its control unit in
  the device registry.

## Installation

### HACS (recommended)

1. Add this repository to HACS as a custom repository (category: *Integration*).
2. Search for **Magnum W Controller** and install it.
3. Restart Home Assistant.

### Version numbers

Releases up to 2026.12.0 were numbered after their date; from 1.0.0 on they
follow [semantic versioning](https://semver.org). HACS takes 1.0.0 for an older
version than 2026.12.0, so 2026.12.0 shows a Repairs issue (**Settings →
Repairs**) that downloads 1.0.0 with HACS. On an older release, open
**Magnum W Controller** in HACS, choose **Redownload** and select the latest
version. After that, HACS offers new releases as usual.

### Manual

1. Copy `custom_components/magnum_w_controller` into your Home Assistant `config/custom_components` directory.
2. Restart Home Assistant.

## Configuration

The integration is configured entirely from the UI.

- If the controller is on your network, Home Assistant will usually **discover
  it automatically** via DHCP — accept the discovery prompt.
- Otherwise go to **Settings → Devices & Services → Add Integration** and
  search for **Magnum W Controller**. Leave the host field **empty** to scan
  the network for controllers and pick one from the list, or enter an IP
  address or hostname directly.

Network scanning uses a link-local UDP multicast probe, so it only finds
controllers on the same network segment as Home Assistant. A controller behind
a router has to be added by IP address.

## Development

This integration is based on the
[integration_blueprint](https://github.com/ludeeus/integration_blueprint)
template and ships with a VS Code dev container that runs a standalone Home
Assistant instance pre-configured with this integration.

[mise](https://mise.jdx.dev) installs Python and uv, and runs the tasks in
`mise.toml` in a virtualenv in `.venv`:

```bash
mise run install  # install the development dependencies
mise run test     # run the tests
mise run lint     # lint and check formatting
mise run format   # fix lint issues and format
scripts/develop   # start Home Assistant with this integration loaded
```

### Tests

Tests use
[`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component).

```bash
mise run test
```

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).
