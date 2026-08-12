<p align="center">
  <img alt="banner" src="https://github.com/user-attachments/assets/4b538294-7d78-44b5-95bc-615dfb83bed9" />

</p>

# Magnum W Controller

[![Validate](https://github.com/desync-dev/home-assistant-magnum-w-controller/actions/workflows/validate.yml/badge.svg)](https://github.com/desync-dev/home-assistant-magnum-w-controller/actions/workflows/validate.yml)
[![Lint](https://github.com/desync-dev/home-assistant-magnum-w-controller/actions/workflows/lint.yml/badge.svg)](https://github.com/desync-dev/home-assistant-magnum-w-controller/actions/workflows/lint.yml)

Home Assistant custom integration for the **Magnum W Controller**, the hub for
Magnum wireless underfloor-heating thermostats.

It talks to the controller's local JSON-RPC API, discovers every control unit
and heating zone, and exposes them to Home Assistant.

## Support

If you find this integration useful, you can support my work:

[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-desyncdotdev-EA4AAA?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/desyncdotdev)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-desyncdotdev-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/desyncdotdev)

## Features

- **Automatic DHCP discovery** of the controller (with manual host entry as a
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

### Manual

1. Copy `custom_components/magnum_w_controller` into your Home Assistant `config/custom_components` directory.
2. Restart Home Assistant.

## Configuration

The integration is configured entirely from the UI.

- If the controller is on your network, Home Assistant will usually **discover
  it automatically** via DHCP — accept the discovery prompt.
- Otherwise go to **Settings → Devices & Services → Add Integration**, search
  for **Magnum W Controller**, and enter its IP address or hostname.

## Development

This integration is based on the
[integration_blueprint](https://github.com/ludeeus/integration_blueprint)
template and ships with a VS Code dev container that runs a standalone Home
Assistant instance pre-configured with this integration.

```bash
scripts/setup     # install dependencies
scripts/develop   # start Home Assistant with this integration loaded
scripts/lint      # format and lint with ruff
```

### Tests

Tests use
[`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component).

```bash
pip install -r requirements.txt
pytest
```

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).
