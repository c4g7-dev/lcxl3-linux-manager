#!/usr/bin/env bash
# install-shutdown-service.sh — Install the LCXL3 LED-off shutdown service.
#
# Run once with sudo after cloning the repo:
#   sudo ./scripts/install-shutdown-service.sh
#
# To uninstall:
#   sudo systemctl disable --now lcxl3-leds-off.service
#   sudo rm /etc/systemd/system/lcxl3-leds-off.service
#   sudo rm /opt/lcxl3-linux-manager/scripts/lcxl3-leds-off.sh
#   sudo systemctl daemon-reload

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="/opt/lcxl3-linux-manager"

echo "==> Installing LCXL3 LED shutdown service"

# Copy the shutdown script
install -Dm755 "$REPO_DIR/scripts/lcxl3-leds-off.sh" \
    "$INSTALL_DIR/scripts/lcxl3-leds-off.sh"

# Install the systemd unit
install -Dm644 "$REPO_DIR/scripts/lcxl3-leds-off.service" \
    /etc/systemd/system/lcxl3-leds-off.service

systemctl daemon-reload
systemctl enable lcxl3-leds-off.service

echo "==> Done. LEDs will turn off on shutdown/reboot."
echo "    Test now with: sudo systemctl start lcxl3-leds-off.service"
