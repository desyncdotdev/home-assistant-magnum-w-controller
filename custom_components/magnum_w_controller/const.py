"""Constants for the Magnum W Controller integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "magnum_w_controller"

# Shown when the controller does not report a name of its own.
DEFAULT_NAME: Final = "Magnum W Controller"

# The controller is polled over the LAN; 60s keeps it responsive without
# hammering the (modest) embedded web server.
DEFAULT_SCAN_INTERVAL: Final = 60

# Manufacturer string used for the HA device registry.
MANUFACTURER: Final = "Magnum"
